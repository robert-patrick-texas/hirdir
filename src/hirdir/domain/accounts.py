"""Accounts: users, user groups, role grants, access codes, tokens and signing in."""

import re
from collections import defaultdict
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth import codes, tokens
from hirdir.auth.roles import Role, highest
from hirdir.auth.throttle import Throttle
from hirdir.db import dialect
from hirdir.db.models import (
    Contact,
    Operator,
    RoleGrant,
    ServiceToken,
    User,
    UserGroup,
    UserGroupMember,
)
from hirdir.domain import audit, colours, contacts, operators, product, records, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import (
    Conflict,
    Existing,
    Invalid,
    NoRole,
    NotFound,
    SignInDelayed,
    SignInRefused,
)
from hirdir.domain.records import AnySelect, Arrange
from hirdir.domain.records import touch as _touch

USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
LAST_USED_GRANULARITY_SECONDS = 60
# Which users of a list are kept by `contact` and by `operator`: all of them, those that
# are one, or those that are not (P-280).
WHICH = ("any", "some", "none")
# A user's notes are as long as a contact's may be (P-281).
MAX_NOTES = 10_000
# Which accounts a list of users holds: those that are not retired, the retired with
# the rest, or the retired alone (P-296).
RETIRED = ("no", "yes", "only")
# What an account that holds no role is told, and what a person made or brought back
# with none is refused with (P-299).
NO_ROLE = "this account holds no role, and so cannot sign in: an Admin gives it one"
NO_ROLE_MADE = "a person is made with a role: an account with no role does not sign in"
NO_ROLE_BACK = "a person is brought back with a role: an account with no role does not sign in"
GIVE_A_ROLE = "give a role, or a group that grants one"


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
        select(User).where(
            User.disabled.is_(False),
            User.is_service_account.is_(False),
            User.record_status != "retired",
        )
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


@contextmanager
def _ending_with_the_last_role(db: Session, who: Callable[[], Sequence[User]]) -> Generator[None]:
    """End every session of each of the users that the change takes the last role from
    (P-299): an account with no role has no session, and a role given again later brings
    no old one back. The change is audited by its own event, and this adds nothing to it.
    The roles are read for all the users at once, before and after, however many a group
    holds. The writer's place is taken before anything is read, the users `who` gives
    among it: of two such changes at the same moment, an own grant and a group's revoked
    together, the second waits and then sees the first, so that one of them finds the
    last role gone and ends the sessions. It is entered before `_keeping_an_admin`, so
    that the count of Admins is read in the writer's place too.
    """
    dialect.hold_other_writers(db)
    users = who()
    before = roles_of(db, users)
    held = [user for user in users if before[user.hid] is not None]
    yield
    db.flush()
    after = roles_of(db, held)
    for user in held:
        if after[user.hid] is None:
            _end_sessions(user)


@contextmanager
def _ending_with_the_first_role(db: Session, who: Callable[[], Sequence[User]]) -> Generator[None]:
    """End every session of each of the users that the change gives a role to where it
    held none (P-299). No session is given to an account with no role, but one that an
    earlier release gave, as 0.9.14 did to an account brought back, is refused and not
    ended: it would answer again once a role is given. So whatever gives the first role,
    a grant to the user or to a group of its, or its being put in a group that grants
    one, ends what sessions it had first, as `_ending_with_the_last_role` does for the
    last role, in the writer's place in the same way.
    """
    dialect.hold_other_writers(db)
    users = who()
    before = roles_of(db, users)
    roleless = [user for user in users if before[user.hid] is None]
    yield
    db.flush()
    after = roles_of(db, roleless)
    for user in roleless:
        if after[user.hid] is not None:
            _end_sessions(user)


def _members(db: Session, group_hid: str) -> list[User]:
    """Return the users in a group, by its HID."""
    return list(
        db.scalars(
            select(User)
            .join(UserGroupMember, UserGroupMember.user_hid == User.hid)
            .where(UserGroupMember.group_hid == group_hid)
        )
    )


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


def _behind_an_operator() -> ColumnElement[bool]:
    """Say whether the contact of a user, the `Contact` the list joins, stands behind an
    operator that is not retired: a retired contact stands behind none, as nobody is
    behind its labels, by the rule each of the three lists follows (P-280)."""
    return and_(
        ~operators.nobody_behind(Contact),
        exists().where(
            Operator.contact_hid == User.contact_hid, Operator.record_status != "retired"
        ),
    )


def retired_or_not(query: AnySelect, retired: str) -> AnySelect:
    """Narrow a statement of users to those that are not retired, `no`, or to the
    retired alone, `only`; `yes` keeps them all (P-296)."""
    if retired not in RETIRED:
        raise Invalid("retired is not acceptable", {"retired": "no, yes or only"})
    if retired == "no":
        return query.where(User.record_status != "retired")
    if retired == "only":
        return query.where(User.record_status == "retired")
    return query


def _narrowed(query: AnySelect, contact: str, operator: str) -> AnySelect:
    """Narrow a list of users, which joins their contacts, to those that are, or are not,
    a contact and an operator.

    `some` keeps the users that are one, `none` those that are not, and `any` all of
    them. A contact that is retired is as none. A service account is no person and is in
    neither `none`, so that `any` is `some`, `none` and the service accounts (P-280). A
    retired account is in no gap: neither `none` holds it, whatever is asked of the
    retired (P-296).
    """
    for name, value in (("contact", contact), ("operator", operator)):
        if value not in WHICH:
            raise Invalid(f"{name} is not acceptable", {name: "any, some or none"})
    person = and_(User.is_service_account.is_(False), User.record_status != "retired")
    if contact == "some":
        query = query.where(~operators.nobody_behind(Contact))
    elif contact == "none":
        query = query.where(person, operators.nobody_behind(Contact))
    if operator == "some":
        query = query.where(_behind_an_operator())
    elif operator == "none":
        query = query.where(person, ~_behind_an_operator())
    return query


def list_users(
    db: Session,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    arrange: Arrange | None = None,
    *,
    contact: str = "any",
    operator: str = "any",
    retired: str = "no",
) -> tuple[list[User], int]:
    """Return one page of users, by username, and the total that match q.

    `arrange` sorts them as was asked for, and the username settles what that leaves tied.
    `contact` and `operator` keep those that are one, `some`, or the gaps, `none` (P-280).
    The retired accounts are left out unless `retired` asks for them, `yes`, or for them
    alone, `only` (P-296).
    """
    query = select(User).outerjoin(Contact, Contact.hid == User.contact_hid)
    query = retired_or_not(query, retired)
    if q:
        query = query.where(
            or_(
                dialect.contains_text(User.username.expression, q),
                dialect.contains_text(Contact.name.expression, q),
            )
        )
    query = _narrowed(query, contact, operator)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(query.order_by(User.username_key).limit(limit).offset(offset))
    return list(page), total


def contacts_of(db: Session, users: Sequence[User]) -> dict[str, Contact]:
    """Return the contact of each of the users that has one, by its HID."""
    hids = {user.contact_hid for user in users if user.contact_hid}
    if not hids:
        return {}
    return {one.hid: one for one in db.scalars(select(Contact).where(Contact.hid.in_(hids)))}


def roles_of(db: Session, users: Sequence[User]) -> dict[str, Role | None]:
    """Return the role in force of each of the users, by its HID, as `effective_role`
    gives it for one: the highest granted to the user or to a group it is in. Read in two
    statements for them all, however many they are."""
    hids = [user.hid for user in users]
    if not hids:
        return {}
    members: dict[str, list[str]] = defaultdict(list)
    for user_hid, group_hid in db.execute(
        select(UserGroupMember.user_hid, UserGroupMember.group_hid).where(
            UserGroupMember.user_hid.in_(hids)
        )
    ):
        members[group_hid].append(user_hid)
    granted: dict[str, list[str]] = {hid: [] for hid in hids}
    for role, user_hid, group_hid in db.execute(
        select(RoleGrant.role, RoleGrant.user_hid, RoleGrant.group_hid).where(
            or_(RoleGrant.user_hid.in_(hids), RoleGrant.group_hid.in_(list(members)))
        )
    ):
        for hid in [user_hid] if user_hid else members.get(group_hid or "", []):
            granted[hid].append(role)
    return {hid: highest(roles) for hid, roles in granted.items()}


def groups_of_users(db: Session, users: Sequence[User]) -> dict[str, list[UserGroup]]:
    """Return the groups each of the users is in, by name, by the user's HID, read in one
    statement for them all."""
    found: dict[str, list[UserGroup]] = {user.hid: [] for user in users}
    if not found:
        return found
    for user_hid, group in db.execute(
        select(UserGroupMember.user_hid, UserGroup)
        .join(UserGroup, UserGroup.hid == UserGroupMember.group_hid)
        .where(UserGroupMember.user_hid.in_(list(found)))
        .order_by(UserGroup.name_key)
    ):
        found[user_hid].append(group)
    return found


def roles_of_groups(db: Session, groups: Sequence[UserGroup]) -> dict[str, list[str]]:
    """Return the roles granted to each of the groups, by name, read in one statement."""
    found: dict[str, list[str]] = {group.hid: [] for group in groups}
    if found:
        for group_hid, role in db.execute(
            select(RoleGrant.group_hid, RoleGrant.role).where(RoleGrant.group_hid.in_(list(found)))
        ):
            found[group_hid or ""].append(role)
    return {hid: sorted(roles) for hid, roles in found.items()}


def sizes_of(db: Session, groups: Sequence[UserGroup]) -> dict[str, int]:
    """Return how many users are in each of the groups, read in one statement."""
    found = {group.hid: 0 for group in groups}
    if found:
        for group_hid, count in db.execute(
            select(UserGroupMember.group_hid, func.count())
            .where(UserGroupMember.group_hid.in_(list(found)))
            .group_by(UserGroupMember.group_hid)
        ):
            found[group_hid] = count
    return found


def operators_of(db: Session, users: Sequence[User]) -> dict[str, list[Operator]]:
    """Return the operators each of the users works as, by the user's HID: those whose
    contact is the user's, retired ones among them, in the order of their labels, read
    in one query for them all. A user with no contact has none (P-280)."""
    behind = contacts.operators_of(db, [user.contact_hid for user in users if user.contact_hid])
    return {user.hid: list(behind.get(user.contact_hid or "", [])) for user in users}


def name_of(user: User, contact: Contact | None) -> str:
    """Return the name a user is shown by: its contact's, or its username."""
    return contact.name if contact is not None else user.username


def _checked_username(db: Session, username: str, user: User | None) -> str:
    username = username.strip()
    if not USERNAME.fullmatch(username):
        raise Invalid(
            "the username is not acceptable",
            {"username": "1 to 64 letters, digits, dots, hyphens or underscores"},
        )
    taken = find_user(db, username)
    if taken is not None and (user is None or taken.hid != user.hid):
        if is_retired(taken):
            # The name stays the retired account's, since the audit trail is read by
            # username: an Admin renames that account to free it (P-296).
            raise Conflict(
                f"the retired account {taken.username} has this username: rename that "
                "account to free the name, or bring it back",
                {"username": "a retired account has this username"},
                Existing("user", taken.hid, taken.username),
            )
        raise Conflict(
            f"there is already a user named {taken.username}",
            {"username": "another user has this username"},
            Existing("user", taken.hid, taken.username),
        )
    return username


def _checked_contact(db: Session, hid: str, user: User | None, service: bool) -> Contact:
    """Return the contact a user is to be, or refuse one it cannot be (P-172)."""
    if service:
        raise Invalid(
            "a service account is no person and has no contact",
            {"contact_hid": "a service account has no contact"},
        )
    # An account does not stand on a retired contact. That is checked by reading the
    # contact and kept by writing the user, so the writer's place is taken before the
    # look: a retirement of the contact at the same moment waits, and then finds the
    # user, or this finds the contact retired (P-297).
    dialect.hold_other_writers(db)
    contact = db.get(Contact, hid)
    if contact is None:
        raise Invalid("there is no such contact", {"contact_hid": f"there is no contact {hid}"})
    if contact.record_status == "retired":
        raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
    other = db.scalar(select(User).where(User.contact_hid == hid))
    if other is not None and (user is None or other.hid != user.hid):
        if is_retired(other):
            # The contact of a retired account is still that account's, so that it is
            # brought back as the person it was: it is taken off that account first.
            raise Conflict(
                f"{contact.name} is still the contact of the retired account "
                f"{other.username}: take it off that account first, or bring the account back",
                {"contact_hid": "this contact is a retired account's"},
                Existing("user", other.hid, other.username),
            )
        raise Conflict(
            f"{contact.name} is already the contact of the user {other.username}",
            {"contact_hid": "this contact is another user's"},
            Existing("user", other.hid, other.username),
        )
    return contact


def _told(db: Session, context: AuditContext, user: User, old: str | None, new: str | None) -> None:
    """Record on each contact that it is now, or is no longer, the person a user is.

    What a contact is, a user's or not, decides whether an operator it stands behind is
    internal or external, so its history says so, and a kept answer that shows it is no
    longer good once it changes (P-172).
    """
    if old is not None:
        audit.record(db, context, "update", "contact", old, [change("user_hid", user.hid, None)])
    if new is not None:
        audit.record(db, context, "update", "contact", new, [change("user_hid", None, user.hid)])


def _checked_notes(value: Any) -> str | None:
    """Return a user's notes, a blank as none, or refuse them (P-281)."""
    notes = records.clean(value)
    if notes is not None and len(notes) > MAX_NOTES:
        raise Invalid("the notes are too long", {"notes": f"at most {MAX_NOTES} characters"})
    return notes


@dataclass(frozen=True)
class NewUser:
    """A user just made, with its access code, shown this once, and the operator made
    with it, where one was (P-283)."""

    user: User
    access_code: str | None
    operator: Operator | None


def _named_in(prefix: str, error: Invalid | Conflict) -> Invalid | Conflict:
    """Name the fields a refusal names as fields of a part of the request (P-283)."""
    error.fields = {f"{prefix}.{name}": text for name, text in error.fields.items()}
    return error


def _checked_groups(db: Session, hids: Sequence[str]) -> list[UserGroup]:
    """Return the groups a new user is put into, each once, or refuse one there is not."""
    found: dict[str, UserGroup] = {}
    for hid in hids:
        group = db.get(UserGroup, hid)
        if group is None:
            raise Invalid(
                "there is no such user group", {"group_hids": f"there is no user group {hid}"}
            )
        found[group.hid] = group
    return list(found.values())


def checked_role(role: str | None) -> str | None:
    if not role:
        return None
    try:
        return Role(role).value
    except ValueError:
        raise Invalid("there is no such role", {"role": "viewer, inventory or admin"}) from None


def onboard(
    db: Session,
    context: AuditContext,
    *,
    username: str,
    is_service_account: bool = False,
    access_code: str | None = None,
    contact_hid: str | None = None,
    contact: dict[str, Any] | None = None,
    role: str | None = None,
    group_hids: Sequence[str] = (),
    operator: dict[str, Any] | None = None,
    notes: str | None = None,
) -> NewUser:
    """Make what a new person needs, in the one change (P-282, P-283): the user, the
    contact it is, the operator it works as, the grant of its role and its memberships.

    Each part is audited as if it were made by itself, with the events that
    `POST /operators`, `POST /role-grants` and `PUT /user-groups/{hid}/members/{user_hid}`
    write. Where any part is refused, the error is raised before the caller's
    transaction is committed, and so nothing is made and no event is kept. A refusal
    names the field of the request it is for: `operator.label` for the label of the
    operator, `group_hids` for a group there is not. A person who would hold no role,
    neither `role` nor a group that grants one, is refused at `role`, since an account
    with none does not sign in; a service account may be made with none (P-299).

    `operator` holds `label`, `colour` and `description`, each optional. The label left
    out, or blank, is the username, and a username that is no acceptable label is
    refused and never altered; the colour left out is the next that no operator has,
    and given as blank or null is none. It needs a contact in the same request.
    """
    if operator is not None and (is_service_account or (contact is None and not contact_hid)):
        raise Invalid(
            "an operator is made of a person who is a contact",
            {
                "operator": "a service account works as no operator"
                if is_service_account
                else "give the contact, new or there, that stands behind the operator"
            },
        )
    granted = checked_role(role)
    groups = _checked_groups(db, group_hids)
    roleless = granted is None and not any(roles_of_groups(db, groups).values())
    user, code = create_user(
        db,
        context,
        username=username,
        is_service_account=is_service_account,
        access_code=access_code,
        contact_hid=contact_hid,
        contact=contact,
        notes=notes,
    )
    if granted is not None:
        grant_role(db, context, role=granted, user_hid=user.hid)
    for group in groups:
        add_member(db, context, group.hid, user.hid)
    made = None
    if operator is not None:
        fields = {
            "label": records.clean(operator.get("label")) or user.username,
            "description": operator.get("description"),
            "colour": operator["colour"]
            if "colour" in operator
            else colours.next_for_operators(db),
            "contact_hid": user.contact_hid,
            "record_status": "active",
        }
        try:
            made = operators.create_operator(db, context, fields)
        except (Invalid, Conflict) as error:
            raise _named_in("operator", error) from None
    if roleless and not is_service_account:
        # An account with no role does not sign in, so a person is made with one
        # (P-299). What is wrong with any other part is said first; nothing is kept,
        # since the caller's transaction is not committed.
        raise Invalid(NO_ROLE_MADE, {"role": GIVE_A_ROLE})
    return NewUser(user, code, made)


def create_user(
    db: Session,
    context: AuditContext,
    *,
    username: str,
    is_service_account: bool = False,
    access_code: str | None = None,
    contact_hid: str | None = None,
    contact: dict[str, Any] | None = None,
    notes: str | None = None,
) -> tuple[User, str | None]:
    """Create a user. Return it with its access code, which is shown this once.

    A person gets the given access code, or a generated one. A service account gets
    none: it holds tokens instead. The person is a contact: `contact_hid` names one,
    `contact` holds the fields of a new one, made in the same change, or neither is
    given and the user has none until an Admin gives it one (P-172). `onboard` makes
    with it its operator, its role and its groups (P-283).
    """
    username = _checked_username(db, username, None)
    notes = _checked_notes(notes)
    if contact_hid is not None and contact is not None:
        raise Invalid(
            "a user is given one contact",
            {"contact": "give contact_hid or contact, not both"},
        )
    if contact is not None and is_service_account:
        raise Invalid(
            "a service account is no person and has no contact",
            {"contact": "a service account has no contact"},
        )
    person = _checked_contact(db, contact_hid, None, is_service_account) if contact_hid else None
    code = None
    if not is_service_account:
        code = _checked_code(db, access_code) if access_code is not None else made_code(db)
    if contact is not None:
        try:
            person = contacts.create_contact(db, context, dict(contact))
        except (Invalid, Conflict) as error:
            # What is wrong is a field of the new contact, and is named so.
            raise _named_in("contact", error) from None
    user = User(
        username=username,
        username_key=_key(username),
        contact_hid=person.hid if person is not None else None,
        is_service_account=is_service_account,
        access_code_hash=codes.hash_code(code) if code else None,
        notes=notes,
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
            *([change("contact_hid", None, user.contact_hid)] if user.contact_hid else []),
            *([change("notes", None, user.notes)] if user.notes else []),
        ],
    )
    _told(db, context, user, None, user.contact_hid)
    return user, code


def update_user(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> User:
    """Change a user's username (P-173), its contact (P-172), its notes (P-281), or
    whether it is disabled.

    The name, the email and the numbers a user shows are its contact's, and are changed
    on the contact. A new username keeps the user's sessions and tokens: it is the same
    record, by its HID.
    """
    user = get_user(db, hid)
    if is_retired(user):
        # Of a retired account the username, the notes and its contact taken off are
        # all that is changed (P-296).
        if fields.get("disabled") is not None and fields["disabled"] != user.disabled:
            raise _retired(user, "disabled", "is neither disabled nor enabled")
        if (fields.get("contact_hid") or None) not in (None, user.contact_hid):
            raise _retired(user, "contact_hid", "is given no other contact")
    changes = []
    if fields.get("username") is not None:
        username = _checked_username(db, fields["username"], user)
        if username != user.username:
            changes.append(change("username", user.username, username))
            changes.append(change("username_key", user.username_key, _key(username)))
    if "contact_hid" in fields:
        new = fields["contact_hid"] or None
        if new is not None and new != user.contact_hid:
            _checked_contact(db, new, user, user.is_service_account)
        if new != user.contact_hid:
            changes.append(change("contact_hid", user.contact_hid, new))
    if fields.get("disabled") is not None and fields["disabled"] != user.disabled:
        changes.append(change("disabled", user.disabled, fields["disabled"]))
    if "notes" in fields:
        notes = _checked_notes(fields["notes"])
        if notes != user.notes:
            changes.append(change("notes", user.notes, notes))
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
    shown = [entry for entry in changes if entry["field"] != "username_key"]
    audit.record(db, context, "update", "user", user.hid, shown)
    for entry in shown:
        if entry["field"] == "contact_hid":
            _told(db, context, user, entry["old"], entry["new"])
    return user


def is_retired(user: User) -> bool:
    """Say whether an account is retired: that of somebody who has left (P-296)."""
    return user.record_status == "retired"


def _retired(user: User, field: str | None, what: str) -> Conflict:
    """Return the refusal of what a retired account is not given (P-296)."""
    text = f"the account {user.username} is retired and {what}: bring it back first"
    return Conflict(text, {field: "this account is retired"} if field else None)


def _told_of_its_account(
    db: Session, context: AuditContext, user: User, old: str, new: str
) -> None:
    """Record on the contact of a user that its account is retired, or is back.

    A retired account is no user, so the contact is no user's from then on, and an
    operator it stands behind is external and no longer internal: its history says so,
    as it says when the contact is given to a user (P-172), and a kept answer that shows
    it is no longer good (P-296).
    """
    if user.contact_hid is not None:
        entry = change("user_record_status", old, new)
        audit.record(db, context, "update", "contact", user.contact_hid, [entry])


def retire_user(db: Session, context: AuditContext, hid: str, row_version: int | None) -> User:
    """Retire the account of somebody who has left (P-296).

    Every session of the account ends and its access code is erased. It is taken out of
    each of its groups, each role granted to the account itself is revoked, and the
    tokens of a service account are revoked, each audited as it is when done by itself,
    and the account as `retire`. `disabled` stays what it was. Refused where it would
    leave no Admin who can sign in, and for an account that is retired already.
    """
    user = get_user(db, hid)
    if is_retired(user):
        raise Conflict(f"the account {user.username} is retired already")
    with _keeping_an_admin(db):
        _touch(user, context, row_version)
        groups = db.scalars(
            select(UserGroupMember.group_hid)
            .join(UserGroup, UserGroup.hid == UserGroupMember.group_hid)
            .where(UserGroupMember.user_hid == user.hid)
            .order_by(UserGroup.name_key)
        ).all()
        for group_hid in groups:
            remove_member(db, context, group_hid, user.hid)
        grants = db.scalars(
            select(RoleGrant.hid)
            .where(RoleGrant.user_hid == user.hid)
            .order_by(RoleGrant.created_at, RoleGrant.hid)
        ).all()
        for grant_hid in grants:
            revoke_grant(db, context, grant_hid)
        tokens_ = db.scalars(
            select(ServiceToken.hid)
            .where(ServiceToken.user_hid == user.hid, ServiceToken.revoked_at.is_(None))
            .order_by(ServiceToken.created_at, ServiceToken.hid)
        ).all()
        for token_hid in tokens_:
            revoke_service_token(db, context, token_hid)
        user.access_code_hash = None
        _end_sessions(user)
        user.record_status = "retired"
    audit.record(
        db, context, "retire", "user", user.hid, [change("record_status", "active", "retired")]
    )
    _told_of_its_account(db, context, user, "active", "retired")
    return user


def bring_back_user(
    db: Session, context: AuditContext, hid: str, row_version: int | None
) -> tuple[User, str | None]:
    """Bring a retired account back (P-296). Return it with its new access code, which is
    shown this once; a service account has none.

    It is active again and not disabled, with no role and no group: what it held was
    taken away when it was retired, and an Admin gives it anew, the role in the same
    change, which `hirdir.domain.people` sees to with that its contact is not retired
    (P-299).
    """
    user = get_user(db, hid)
    if not is_retired(user):
        raise Conflict(f"the account {user.username} is not retired")
    _touch(user, context, row_version)
    code = None if user.is_service_account else made_code(db)
    changes = [change("record_status", "retired", "active")]
    if user.disabled:
        changes.append(change("disabled", True, False))
    user.record_status = "active"
    user.disabled = False
    user.access_code_hash = codes.hash_code(code) if code else None
    _end_sessions(user)
    audit.record(db, context, "bring_back", "user", user.hid, changes)
    _told_of_its_account(db, context, user, "retired", "active")
    return user, code


def give_access_code(
    db: Session, context: AuditContext, hid: str, access_code: str | None = None
) -> str:
    """Give a user a new access code, as an Admin does for another. Return the code.
    A retired account is given none (P-296), which `set_access_code` sees to."""
    return set_access_code(db, context, hid, access_code)


def made_code(db: Session) -> str:
    """Return an access code made by the server: groups of four, as many as make it at
    least as long as the setting `access_code_min_length` asks (P-300). Wherever the
    server makes a code it is made here: for an empty box, at bring back, by
    `hirdir admin`, and for a form that asks for one, which stores nothing."""
    return codes.generate(settings.code_length(db))


def _checked_code(db: Session, code: str) -> str:
    """Return an access code that is typed, by an Admin or by the person whose it is, or
    refuse it: a blank one, one with a space at either end, and one shorter than the
    setting `access_code_min_length` says (P-295). A code the server makes is not
    brought here: `made_code` makes it long enough. A code that is held already is not
    looked at."""
    if not code or code != code.strip():
        raise Invalid(
            "the access code is not acceptable",
            {"access_code": "must not be empty or begin or end with a space"},
        )
    least = settings.code_length(db)
    if len(code) < least:
        # What a person reads at the box: the length, and not the name of the setting.
        length = f"at least {least} character{'' if least == 1 else 's'}"
        raise Invalid(f"the access code is too short: {length}", {"access_code": length})
    return code


def _end_sessions(user: User) -> None:
    """Make every session token issued to user so far invalid."""
    user.tokens_valid_after = max(clock.now_ms(), user.tokens_valid_after + 1)


def set_access_code(
    db: Session, context: AuditContext, hid: str, access_code: str | None = None
) -> str:
    """Give a user a new access code, ending every session they have. Return the code.

    A retired account is given none (P-296), by whichever way it is asked: the route of
    an Admin, and `hirdir admin`, which comes here with no route.
    """
    user = get_user(db, hid)
    if is_retired(user):
        raise _retired(user, None, "is given no access code")
    if user.is_service_account:
        raise Conflict("a service account has no access code; it holds tokens")
    code = _checked_code(db, access_code) if access_code is not None else made_code(db)
    _touch(user, context, None)
    user.access_code_hash = codes.hash_code(code)
    _end_sessions(user)
    audit.record(db, context, "set_access_code", "user", user.hid)
    return code


def change_access_code(
    db: Session,
    context: AuditContext,
    user: User,
    *,
    current: str,
    new: str,
    address: str,
    throttle: Throttle,
    signing_key: bytes,
    session_hours: int,
) -> tuple[str, datetime]:
    """Change the access code of a person who gives the one they have (P-295). Return a
    new session token for the session in hand, and when it ends.

    A wrong current code is counted by the throttle under the keys of a failed sign-in,
    the username and the address, so that a session left open is no way to try codes:
    a person delayed here is delayed at sign-in, and the other way round. While they
    are delayed no code is looked at. Both refusals are audit events, committed here so
    that they are kept though the request is refused, as `sign_in` keeps its own. The
    current code is looked at before the new one, which is refused where it is the
    current one (P-300) and then by `_checked_code`; neither refusal is an event, and
    neither ends a session. Accepted, every session of the person is ended, the one in
    hand too, which goes on with the token returned.
    """
    keys = (f"user:{user.username_key}", f"addr:{address}")
    wait = throttle.retry_after(*keys)
    if wait > 0:
        audit.record(db, context, "access_code_delayed", "user", user.hid)
        db.commit()
        raise SignInDelayed(wait)
    if not codes.verify(user.access_code_hash, current):
        throttle.failure(*keys)
        audit.record(db, context, "access_code_refused", "user", user.hid)
        db.commit()
        raise Invalid(
            "the current access code was not accepted",
            {"current_access_code": "this is not the access code you have"},
        )
    throttle.success(*keys)
    if codes.verify(user.access_code_hash, new):
        raise Invalid(
            "the new access code is the one you have now: choose another",
            {"access_code": "this is the access code you have now"},
        )
    code = _checked_code(db, new)
    _touch(user, context, None)
    user.access_code_hash = codes.hash_code(code)
    _end_sessions(user)
    issued_ms = max(clock.now_ms(), user.tokens_valid_after + 1)
    token, expires_at = tokens.issue_session(signing_key, user.hid, issued_ms, session_hours)
    audit.record(db, context, "set_access_code", "user", user.hid)
    return token, expires_at


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


def groups_named(db: Session, names: Sequence[str]) -> list[UserGroup]:
    """Return the user groups of names, each compared without regard to case, in the
    order given and each once, or refuse every name that no group has (P-304)."""
    found: list[UserGroup] = []
    missing: list[str] = []
    for name in names:
        group = db.scalar(select(UserGroup).where(UserGroup.name_key == _key(name)))
        if group is None:
            missing.append(name.strip())
        elif group not in found:
            found.append(group)
    if missing:
        listed = ", ".join(missing)
        raise Invalid(
            f"there is no user group named {listed}",
            {"group": "give the name of a group there is"},
        )
    return found


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


def _checked_group_name(db: Session, name: str, group: UserGroup | None = None) -> str:
    """Return the name a group is to have, or refuse it.

    It holds no semicolon, which separates the groups of a user in a file (P-288). A
    group that holds one already, from before, keeps its name until it is renamed.
    """
    name = name.strip()
    if not name or len(name) > 100:
        raise Invalid("the group name is not acceptable", {"name": "1 to 100 characters"})
    if ";" in name and (group is None or name != group.name):
        raise Invalid(
            "the group name is not acceptable",
            {"name": "must not hold a semicolon, which separates groups in a file"},
        )
    except_hid = group.hid if group is not None else None
    other = db.scalar(select(UserGroup).where(UserGroup.name_key == _key(name)))
    if other is not None and other.hid != except_hid:
        raise Conflict(
            f"there is already a group named {name}",
            {"name": "another group has this name"},
            Existing("user_group", other.hid, other.name),
        )
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
        name = _checked_group_name(db, fields["name"], group)
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
    """Remove a user group, its memberships and the roles granted to it. A member that
    it gave the last role to has every session ended (P-299)."""
    group = get_group(db, hid)
    with _ending_with_the_last_role(db, lambda: _members(db, hid)), _keeping_an_admin(db):
        for grant in db.scalars(select(RoleGrant).where(RoleGrant.group_hid == hid)):
            db.delete(grant)
        db.delete(group)
    audit.record(db, context, "delete", "user_group", hid, [change("name", group.name, None)])


def add_member(db: Session, context: AuditContext, group_hid: str, user_hid: str) -> None:
    """Put a user in a group. Doing it twice changes nothing. Where the group gives it
    its first role, every session it had ends (P-299)."""
    group, user = get_group(db, group_hid), get_user(db, user_hid)
    if is_retired(user):
        raise _retired(user, None, "is put in no group")
    if db.get(UserGroupMember, (user.hid, group.hid)) is not None:
        return
    with _ending_with_the_first_role(db, lambda: [user]):
        db.add(UserGroupMember(user_hid=user.hid, group_hid=group.hid))
    audit.record(
        db, context, "add_member", "user_group", group.hid, [change("user_hid", None, user.hid)]
    )


def remove_member(db: Session, context: AuditContext, group_hid: str, user_hid: str) -> None:
    """Take a user out of a group. Where the group gave it its last role, every session
    of the user ends (P-299)."""
    member = db.get(UserGroupMember, (user_hid, get_group(db, group_hid).hid))
    if member is None:
        raise NotFound("that user is not in that group")
    with _ending_with_the_last_role(db, lambda: [get_user(db, user_hid)]), _keeping_an_admin(db):
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
    """Grant a role to one user or one group. Granting it twice returns the first grant.
    Each user it gives the first role to, the user or a member of the group, has every
    session it had ended (P-299)."""
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
        user = get_user(db, user_hid)
        if is_retired(user):
            raise _retired(user, "user_hid", "is granted no role")
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

    def holders() -> list[User]:
        return [get_user(db, user_hid)] if user_hid else _members(db, group_hid or "")

    with _ending_with_the_first_role(db, holders):
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
    """Take back a role grant. Each user it took the last role from, the user it was
    granted to or a member of the group, has every session ended (P-299)."""
    grant = db.get(RoleGrant, hid)
    if grant is None:
        raise NotFound(f"there is no role grant {hid}")

    def holders() -> list[User]:
        if grant.user_hid:
            return [get_user(db, grant.user_hid)]
        return _members(db, grant.group_hid or "")

    with _ending_with_the_last_role(db, holders), _keeping_an_admin(db):
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
    if is_retired(user):
        raise _retired(user, None, "is given no token")
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
    An account whose code is right and which holds no role is refused with `NoRole`,
    which says whom to ask, once every other refusal is looked at (P-299).
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
    # A retired account is refused as an unknown one is, and in the same time: its
    # code is erased, so what is typed is checked against the hash that no code has.
    if user is None or not accepted or user.disabled or user.is_service_account or is_retired(user):
        throttle.failure(*keys)
        audit.record(db, context, "sign_in_failed", "user", user.hid if user else None, attempted)
        db.commit()
        raise SignInRefused("the username or access code was not accepted")

    throttle.success(*keys)
    if effective_role(db, user) is None:
        # The code is right, and the person is told so plainly, with whom to ask; the
        # throttle counts it a success, as it is no guess (P-299).
        audit.record(db, context, "sign_in_no_role", "user", user.hid, attempted)
        db.commit()
        raise NoRole(NO_ROLE, asdict(product.help_of(db)))
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
    if (
        user is None
        or user.disabled
        or is_retired(user)
        or claims.issued_ms <= user.tokens_valid_after
    ):
        raise NotSignedIn("the session has been ended")
    role = effective_role(db, user)
    if role is None:
        # An account with no role has no session, so a role lost while signed in takes
        # effect at the next request (P-299). It is said to a session that is live in
        # every other way alone: a token ended already tells nobody whether the account
        # holds a role.
        raise NotSignedIn("the session has been ended: this account holds no role")
    return Principal(user=user, role=role, kind="session")


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
    if user is None or user.disabled or is_retired(user) or not user.is_service_account:
        raise NotSignedIn("the token is not valid")
    role = effective_role(db, user)
    if role is None:
        raise NotSignedIn("the token is not accepted: its service account holds no role")
    last = record.last_used_at
    if last is None or (now - last).total_seconds() > LAST_USED_GRANULARITY_SECONDS:
        _used(db, record, now)
    return Principal(user=user, role=role, kind="service")


def _used(db: Session, record: ServiceToken, now: datetime) -> None:
    """Keep when a service token was last used, and store it at once (P-277).

    Left to be stored with the request, it would take the one writer's place at the
    request's first read and hold it until the request ends: a report or an export
    asked for with a token would hold up every save for as long as it took. Nothing
    else of the request is written yet, so storing it here stores nothing else. Where
    the writer's place cannot be had in time, the use is not kept, and the next
    request keeps it: a request that only reads is not refused for it.
    """
    record.last_used_at = now
    try:
        db.commit()
    except OperationalError:
        db.rollback()
