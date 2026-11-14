"""Accounts: users, user groups, role grants, access codes, tokens and signing in."""

import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth import codes, tokens
from hirdir.auth.roles import Role, highest
from hirdir.auth.throttle import Throttle
from hirdir.db.models import RoleGrant, ServiceToken, User, UserGroup, UserGroupMember
from hirdir.domain import audit
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import (
    Conflict,
    Invalid,
    NotFound,
    SignInDelayed,
    SignInRefused,
)
from hirdir.domain.records import Arrange
from hirdir.domain.records import touch as _touch

USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
LAST_USED_GRANULARITY_SECONDS = 60


class NotSignedIn(Exception):
    """The request carries no token, or one that is not accepted."""


@dataclass(frozen=True)
class Principal:
    """Who a request comes from, and the role they hold right now."""

    user: User
    role: Role | None
    kind: str  # "session" or "service"


def _key(text: str) -> str:
    return text.strip().casefold()


# --- roles -------------------------------------------------------------------------


def effective_role(db: Session, user: User) -> Role | None:
    """Return the highest role granted to user directly or through a group."""
    group_hids = select(UserGroupMember.group_hid).where(UserGroupMember.user_hid == user.hid)
    roles = db.scalars(
        select(RoleGrant.role).where(
            or_(RoleGrant.user_hid == user.hid, RoleGrant.group_hid.in_(group_hids))
        )
    )
    return highest(roles)


def _admin_count(db: Session) -> int:
    """Count the people (not service accounts) who can sign in and hold Admin."""
    people = db.scalars(
        select(User).where(User.disabled.is_(False), User.is_service_account.is_(False))
    )
    return sum(1 for user in people if effective_role(db, user) is Role.ADMIN)


@contextmanager
def _keeping_an_admin(db: Session) -> Generator[None]:
    """Refuse a change that would leave an installation with no Admin who can sign in."""
    before = _admin_count(db)
    yield
    db.flush()
    if before > 0 and _admin_count(db) == 0:
        raise Conflict("this would leave no Admin who can sign in")


# --- users -------------------------------------------------------------------------


def get_user(db: Session, hid: str) -> User:
    """Return the user with hid."""
    user = db.get(User, hid)
    if user is None:
        raise NotFound(f"there is no user {hid}")
    return user


def find_user(db: Session, username: str) -> User | None:
    """Return the user with username, compared without regard to case."""
    return db.scalar(select(User).where(User.username_key == _key(username)))


def list_users(
    db: Session, q: str = "", limit: int = 100, offset: int = 0, arrange: Arrange | None = None
) -> tuple[list[User], int]:
    """Return one page of users, by username, and the total that match q.

    `arrange` sorts them as was asked for, and the username settles what that leaves tied.
    """
    query = select(User)
    if q:
        pattern = f"%{_key(q)}%"
        query = query.where(
            or_(User.username_key.like(pattern), func.lower(User.display_name).like(pattern))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(query.order_by(User.username_key).limit(limit).offset(offset))
    return list(page), total


def groups_of(db: Session, user: User) -> list[UserGroup]:
    """Return the groups user is in, by name."""
    return list(
        db.scalars(
            select(UserGroup)
            .join(UserGroupMember, UserGroupMember.group_hid == UserGroup.hid)
            .where(UserGroupMember.user_hid == user.hid)
            .order_by(UserGroup.name_key)
        )
    )


def create_user(
    db: Session,
    context: AuditContext,
    *,
    username: str,
    display_name: str = "",
    email: str = "",
    is_service_account: bool = False,
    access_code: str | None = None,
) -> tuple[User, str | None]:
    """Create a user. Return it with its access code, which is shown this once.

    A person gets the given access code, or a generated one. A service account gets
    none: it holds tokens instead.
    """
    username = username.strip()
    if not USERNAME.fullmatch(username):
        raise Invalid(
            "the username is not acceptable",
            {"username": "1 to 64 letters, digits, dots, hyphens or underscores"},
        )
    if find_user(db, username) is not None:
        raise Conflict(f"there is already a user named {username}")
    code = None
    if not is_service_account:
        code = _checked_code(access_code) if access_code is not None else codes.generate()
    user = User(
        username=username,
        username_key=_key(username),
        display_name=display_name.strip(),
        email=email.strip(),
        is_service_account=is_service_account,
        access_code_hash=codes.hash_code(code) if code else None,
        created_by=context.actor_hid,
        updated_by=context.actor_hid,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        context,
        "create",
        "user",
        user.hid,
        [
            change("username", None, user.username),
            change("is_service_account", None, user.is_service_account),
        ],
    )
    return user, code


def update_user(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> User:
    """Change display_name, email or disabled on a user."""
    user = get_user(db, hid)
    changes = []
    for name in ("display_name", "email", "disabled"):
        if name not in fields or fields[name] is None:
            continue
        new = fields[name].strip() if isinstance(fields[name], str) else fields[name]
        old = getattr(user, name)
        if new != old:
            changes.append(change(name, old, new))
    if not changes:
        if user.row_version != row_version:
            _touch(user, context, row_version)
        return user
    with _keeping_an_admin(db):
        _touch(user, context, row_version)
        for entry in changes:
            setattr(user, entry["field"], entry["new"])
        if user.disabled:
            _end_sessions(user)
    audit.record(db, context, "update", "user", user.hid, changes)
    return user


def _checked_code(code: str) -> str:
    if not code or code != code.strip():
        raise Invalid(
            "the access code is not acceptable",
            {"access_code": "must not be empty or begin or end with a space"},
        )
    return code


def _end_sessions(user: User) -> None:
    """Make every session token issued to user so far invalid."""
    user.tokens_valid_after = max(clock.now_ms(), user.tokens_valid_after + 1)


def set_access_code(
    db: Session, context: AuditContext, hid: str, access_code: str | None = None
) -> str:
    """Give a user a new access code, ending every session they have. Return the code."""
    user = get_user(db, hid)
    if user.is_service_account:
        raise Conflict("a service account has no access code; it holds tokens")
    code = _checked_code(access_code) if access_code is not None else codes.generate()
    _touch(user, context, None)
    user.access_code_hash = codes.hash_code(code)
    _end_sessions(user)
    audit.record(db, context, "set_access_code", "user", user.hid)
    return code


def sign_out_everywhere(db: Session, context: AuditContext, hid: str) -> None:
    """End every session of a user."""
    user = get_user(db, hid)
    _touch(user, context, None)
    _end_sessions(user)
    audit.record(db, context, "sign_out_everywhere", "user", user.hid)


# --- groups ------------------------------------------------------------------------


def get_group(db: Session, hid: str) -> UserGroup:
    """Return the user group with hid."""
    group = db.get(UserGroup, hid)
    if group is None:
        raise NotFound(f"there is no user group {hid}")
    return group


def list_groups(db: Session) -> list[UserGroup]:
    """Return every user group, by name."""
    return list(db.scalars(select(UserGroup).order_by(UserGroup.name_key)))


def members_of(db: Session, group: UserGroup) -> list[User]:
    """Return the users in group, by username."""
    return list(
        db.scalars(
            select(User)
            .join(UserGroupMember, UserGroupMember.user_hid == User.hid)
            .where(UserGroupMember.group_hid == group.hid)
            .order_by(User.username_key)
        )
    )


def _checked_group_name(db: Session, name: str, except_hid: str | None = None) -> str:
    name = name.strip()
    if not name or len(name) > 100:
        raise Invalid("the group name is not acceptable", {"name": "1 to 100 characters"})
    other = db.scalar(select(UserGroup).where(UserGroup.name_key == _key(name)))
    if other is not None and other.hid != except_hid:
        raise Conflict(f"there is already a group named {name}")
    return name


def create_group(
    db: Session, context: AuditContext, *, name: str, description: str = ""
) -> UserGroup:
    """Create a user group."""
    name = _checked_group_name(db, name)
    group = UserGroup(
        name=name,
        name_key=_key(name),
        description=description.strip(),
        created_by=context.actor_hid,
        updated_by=context.actor_hid,
    )
    db.add(group)
    db.flush()
    audit.record(db, context, "create", "user_group", group.hid, [change("name", None, name)])
    return group


def update_group(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> UserGroup:
    """Change the name or description of a user group."""
    group = get_group(db, hid)
    changes = []
    if fields.get("name") is not None:
        name = _checked_group_name(db, fields["name"], except_hid=hid)
        if name != group.name:
            changes.append(change("name", group.name, name))
    if fields.get("description") is not None and fields["description"].strip() != group.description:
        changes.append(change("description", group.description, fields["description"].strip()))
    _touch(group, context, row_version)
    for entry in changes:
        setattr(group, entry["field"], entry["new"])
    group.name_key = _key(group.name)
    if changes:
        audit.record(db, context, "update", "user_group", group.hid, changes)
    return group


def delete_group(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a user group, its memberships and the roles granted to it."""
    group = get_group(db, hid)
    with _keeping_an_admin(db):
        for grant in db.scalars(select(RoleGrant).where(RoleGrant.group_hid == hid)):
            db.delete(grant)
        db.delete(group)
    audit.record(db, context, "delete", "user_group", hid, [change("name", group.name, None)])


def add_member(db: Session, context: AuditContext, group_hid: str, user_hid: str) -> None:
    """Put a user in a group. Doing it twice changes nothing."""
    group, user = get_group(db, group_hid), get_user(db, user_hid)
    if db.get(UserGroupMember, (user.hid, group.hid)) is not None:
        return
    db.add(UserGroupMember(user_hid=user.hid, group_hid=group.hid))
    audit.record(
        db, context, "add_member", "user_group", group.hid, [change("user_hid", None, user.hid)]
    )


def remove_member(db: Session, context: AuditContext, group_hid: str, user_hid: str) -> None:
    """Take a user out of a group."""
    member = db.get(UserGroupMember, (user_hid, get_group(db, group_hid).hid))
    if member is None:
        raise NotFound("that user is not in that group")
    with _keeping_an_admin(db):
        db.delete(member)
    audit.record(
        db, context, "remove_member", "user_group", group_hid, [change("user_hid", user_hid, None)]
    )


# --- role grants -------------------------------------------------------------------


def list_grants(db: Session) -> list[RoleGrant]:
    """Return every role grant, oldest first."""
    return list(db.scalars(select(RoleGrant).order_by(RoleGrant.created_at, RoleGrant.hid)))


def grant_role(
    db: Session,
    context: AuditContext,
    *,
    role: str,
    user_hid: str | None = None,
    group_hid: str | None = None,
) -> RoleGrant:
    """Grant a role to one user or one group. Granting it twice returns the first grant."""
    if (user_hid is None) == (group_hid is None):
        raise Invalid(
            "a role is granted to a user or to a group",
            {"user_hid": "give exactly one of user_hid and group_hid"},
        )
    try:
        role = Role(role).value
    except ValueError:
        raise Invalid("there is no such role", {"role": "viewer, inventory or admin"}) from None
    if user_hid is not None:
        get_user(db, user_hid)
    else:
        get_group(db, group_hid or "")
    existing = db.scalar(
        select(RoleGrant).where(
            RoleGrant.role == role,
            RoleGrant.user_hid == user_hid if user_hid else RoleGrant.group_hid == group_hid,
        )
    )
    if existing is not None:
        return existing
    grant = RoleGrant(
        role=role, user_hid=user_hid, group_hid=group_hid, created_by=context.actor_hid
    )
    db.add(grant)
    db.flush()
    audit.record(
        db,
        context,
        "grant_role",
        "user" if user_hid else "user_group",
        user_hid or group_hid,
        [change("role", None, role)],
    )
    return grant


def revoke_grant(db: Session, context: AuditContext, hid: str) -> None:
    """Take back a role grant."""
    grant = db.get(RoleGrant, hid)
    if grant is None:
        raise NotFound(f"there is no role grant {hid}")
    with _keeping_an_admin(db):
        db.delete(grant)
    audit.record(
        db,
        context,
        "revoke_role",
        "user" if grant.user_hid else "user_group",
        grant.user_hid or grant.group_hid,
        [change("role", grant.role, None)],
    )


# --- service tokens ----------------------------------------------------------------


def list_service_tokens(db: Session, user_hid: str) -> list[ServiceToken]:
    """Return the tokens of a service account, newest first."""
    get_user(db, user_hid)
    return list(
        db.scalars(
            select(ServiceToken)
            .where(ServiceToken.user_hid == user_hid)
            .order_by(ServiceToken.created_at.desc())
        )
    )


def create_service_token(
    db: Session,
    context: AuditContext,
    user_hid: str,
    *,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[ServiceToken, str]:
    """Create a token for a service account. Return it with the secret, shown this once."""
    user = get_user(db, user_hid)
    if not user.is_service_account:
        raise Conflict("tokens belong to service accounts, not to people")
    name = name.strip()
    if not name or len(name) > 100:
        raise Invalid("the token name is not acceptable", {"name": "1 to 100 characters"})
    if expires_at is not None and expires_at <= clock.now():
        raise Invalid("the expiry is in the past", {"expires_at": "must be in the future"})
    secret, token_hash = tokens.new_service_token()
    token = ServiceToken(
        user_hid=user.hid,
        name=name,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by=context.actor_hid,
    )
    db.add(token)
    db.flush()
    audit.record(
        db, context, "create", "service_token", token.hid, [change("user_hid", None, user.hid)]
    )
    return token, secret


def revoke_service_token(db: Session, context: AuditContext, hid: str) -> ServiceToken:
    """Revoke one service token. Revoking it twice changes nothing."""
    token = db.get(ServiceToken, hid)
    if token is None:
        raise NotFound(f"there is no service token {hid}")
    if token.revoked_at is None:
        token.revoked_at = clock.now()
        audit.record(db, context, "revoke", "service_token", token.hid)
    return token


# --- signing in --------------------------------------------------------------------


def sign_in(
    db: Session,
    *,
    username: str,
    access_code: str,
    address: str,
    via: str,
    request_id: str,
    throttle: Throttle,
    signing_key: bytes,
    session_hours: int,
) -> tuple[User, str, datetime]:
    """Check a username and access code. Return the user, a session token and its expiry.

    Every outcome is an audit event, committed here so that a refusal is recorded too.
    """
    name_key = _key(username)
    keys = (f"user:{name_key}", f"addr:{address}")
    user = find_user(db, username)
    context = AuditContext(actor_hid=user.hid if user else None, via=via, request_id=request_id)
    attempted = [change("username", None, username.strip()[:64])]

    wait = throttle.retry_after(*keys)
    if wait > 0:
        audit.record(db, context, "sign_in_delayed", "user", user.hid if user else None, attempted)
        db.commit()
        raise SignInDelayed(wait)

    accepted = codes.verify(user.access_code_hash if user else None, access_code)
    if user is None or not accepted or user.disabled or user.is_service_account:
        throttle.failure(*keys)
        audit.record(db, context, "sign_in_failed", "user", user.hid if user else None, attempted)
        db.commit()
        raise SignInRefused("the username or access code was not accepted")

    throttle.success(*keys)
    issued_ms = max(clock.now_ms(), user.tokens_valid_after + 1)
    token, expires_at = tokens.issue_session(signing_key, user.hid, issued_ms, session_hours)
    user.last_sign_in_at = clock.now()
    audit.record(db, context, "sign_in", "user", user.hid)
    db.commit()
    return user, token, expires_at


def authenticate(db: Session, signing_key: bytes, token: str) -> Principal:
    """Return who a bearer token belongs to, or raise NotSignedIn."""
    if tokens.is_service_token(token):
        return _authenticate_service(db, token)
    try:
        claims = tokens.read_session(signing_key, token)
    except tokens.InvalidToken as error:
        raise NotSignedIn("the session is not valid or has expired") from error
    user = db.get(User, claims.user_hid)
    if user is None or user.disabled or claims.issued_ms <= user.tokens_valid_after:
        raise NotSignedIn("the session has been ended")
    return Principal(user=user, role=effective_role(db, user), kind="session")


def _authenticate_service(db: Session, token: str) -> Principal:
    record = db.scalar(
        select(ServiceToken).where(ServiceToken.token_hash == tokens.hash_service_token(token))
    )
    now = clock.now()
    if (
        record is None
        or record.revoked_at is not None
        or (record.expires_at is not None and record.expires_at <= now)
    ):
        raise NotSignedIn("the token is not valid")
    user = db.get(User, record.user_hid)
    if user is None or user.disabled or not user.is_service_account:
        raise NotSignedIn("the token is not valid")
    last = record.last_used_at
    if last is None or (now - last).total_seconds() > LAST_USED_GRANULARITY_SECONDS:
        record.last_used_at = now
    return Principal(user=user, role=effective_role(db, user), kind="service")
