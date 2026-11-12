"""Turning records into the shapes the API returns."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.api import schemas
from hirdir.db.models import AuditEvent, RoleGrant, User, UserGroup
from hirdir.domain import accounts


def user_out(db: Session, user: User) -> schemas.UserOut:
    """Return user with the role and groups they hold right now."""
    role = accounts.effective_role(db, user)
    return schemas.UserOut(
        hid=user.hid,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_service_account=user.is_service_account,
        disabled=user.disabled,
        role=role.value if role else None,
        groups=[schemas.GroupRef(hid=g.hid, name=g.name) for g in accounts.groups_of(db, user)],
        last_sign_in_at=user.last_sign_in_at,
        row_version=user.row_version,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _group_fields(db: Session, group: UserGroup, member_count: int) -> dict:
    roles = db.scalars(select(RoleGrant.role).where(RoleGrant.group_hid == group.hid))
    return {
        "hid": group.hid,
        "name": group.name,
        "description": group.description,
        "member_count": member_count,
        "roles": sorted(roles),
        "row_version": group.row_version,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def group_out(db: Session, group: UserGroup) -> schemas.GroupOut:
    """Return group with its size and the roles granted to it."""
    return schemas.GroupOut(**_group_fields(db, group, len(group.memberships)))


def group_detail(db: Session, group: UserGroup) -> schemas.GroupDetail:
    """Return group with its members."""
    members = accounts.members_of(db, group)
    return schemas.GroupDetail(
        **_group_fields(db, group, len(members)),
        members=[user_out(db, member) for member in members],
    )


def grant_out(db: Session, grant: RoleGrant) -> schemas.GrantOut:
    """Return grant with the name of the user or group it is made to."""
    if grant.user_hid:
        user = db.get(User, grant.user_hid)
        name = user.username if user else ""
    else:
        group = db.get(UserGroup, grant.group_hid)
        name = group.name if group else ""
    return schemas.GrantOut(
        hid=grant.hid,
        role=grant.role,
        user_hid=grant.user_hid,
        group_hid=grant.group_hid,
        target_name=name,
        created_at=grant.created_at,
    )


def audit_out(db: Session, event: AuditEvent) -> schemas.AuditEventOut:
    """Return event with the username of whoever caused it."""
    actor = db.get(User, event.actor_hid) if event.actor_hid else None
    return schemas.AuditEventOut(
        hid=event.hid,
        at=event.at,
        actor_hid=event.actor_hid,
        actor_name=actor.username if actor else None,
        via=event.via,
        request_id=event.request_id,
        action=event.action,
        record_type=event.record_type,
        record_hid=event.record_hid,
        changes=event.changes,
    )
