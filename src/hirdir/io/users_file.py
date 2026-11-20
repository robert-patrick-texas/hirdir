"""The users as a file, for an Admin (P-288).

A row to each user, by username, with what the Users list tells of it: the person it is,
the role in force, its groups and its operators, what kind of account it is and whether
it signs in. It holds no access code, no token and no hash of either, ever: none of them
is read here. No file makes or changes a user, so this file is written and never read.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth.roles import highest
from hirdir.db.models import Contact, Operator, RoleGrant, User, UserGroup, UserGroupMember
from hirdir.domain import audit, product, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.io import files

# The columns of the file, in order, and no other.
COLUMNS = (
    "username",
    "name",
    "email",
    "phone",
    "phone2",
    "role",
    "groups",
    "operators",
    "kind",
    "state",
    "last_sign_in_at",
    "notes",
)
# The audit trail names what was exported so.
RECORD = "user"
ACTION = "export"


@dataclass(frozen=True)
class UsersFile:
    """The file of the users, written, with its name and how many rows it holds."""

    name: str
    text: str
    rows: int


def _groups(db: Session) -> dict[str, list[str]]:
    """Return the names of the groups each user is in, by name, by the user's HID."""
    found: dict[str, list[str]] = defaultdict(list)
    for user_hid, name in db.execute(
        select(UserGroupMember.user_hid, UserGroup.name)
        .join(UserGroup, UserGroup.hid == UserGroupMember.group_hid)
        .order_by(UserGroup.name_key)
    ):
        found[user_hid].append(name)
    return found


def _roles(db: Session) -> dict[str, str]:
    """Return the role in force of each user that has one, by its HID: the highest granted
    to the user or to a group it is in."""
    granted: dict[str, list[str]] = defaultdict(list)
    members: dict[str, list[str]] = defaultdict(list)
    for user_hid, group_hid in db.execute(
        select(UserGroupMember.user_hid, UserGroupMember.group_hid)
    ):
        members[group_hid].append(user_hid)
    for role, user_hid, group_hid in db.execute(
        select(RoleGrant.role, RoleGrant.user_hid, RoleGrant.group_hid)
    ):
        for hid in [user_hid] if user_hid else members.get(group_hid or "", []):
            granted[hid].append(role)
    return {hid: str(highest(roles)) for hid, roles in granted.items() if roles}


def _operators(db: Session) -> dict[str, list[str]]:
    """Return the labels of the operators behind which each contact stands, by label, by
    the contact's HID, of those that are not retired."""
    found: dict[str, list[str]] = defaultdict(list)
    for contact_hid, label in db.execute(
        select(Operator.contact_hid, Operator.label)
        .where(Operator.contact_hid.is_not(None), Operator.record_status != "retired")
        .order_by(Operator.label_key)
    ):
        found[str(contact_hid)].append(label)
    return found


def rows(db: Session) -> list[dict[str, Any]]:
    """Return a row to each user, by username, in plain values."""
    users = list(db.scalars(select(User).order_by(User.username_key)))
    contacts = {
        one.hid: one
        for one in db.scalars(
            select(Contact).where(
                Contact.hid.in_({user.contact_hid for user in users if user.contact_hid})
            )
        )
    }
    groups, roles, operators = _groups(db), _roles(db), _operators(db)
    written: list[dict[str, Any]] = []
    for user in users:
        contact = contacts.get(user.contact_hid or "")
        written.append(
            {
                "username": user.username,
                "name": contact.name if contact else None,
                "email": contact.email if contact else None,
                "phone": contact.phone if contact else None,
                "phone2": contact.phone2 if contact else None,
                "role": roles.get(user.hid),
                "groups": groups.get(user.hid, []),
                "operators": operators.get(contact.hid, []) if contact else [],
                "kind": "service" if user.is_service_account else "person",
                "state": "disabled" if user.disabled else "enabled",
                "last_sign_in_at": (
                    user.last_sign_in_at.isoformat() if user.last_sign_in_at else None
                ),
                "notes": user.notes,
            }
        )
    return written


def file_name(db: Session) -> str:
    """Return a name for the file, named as any download is (P-168)."""
    stem = product.file_stem(product.name(db))
    return f"{stem}-users-{clock.stamp(clock.now(), settings.time_zone(db))}.csv"


def export(db: Session, context: AuditContext) -> UsersFile:
    """Write the file of the users, and record in the audit trail that it was."""
    written = rows(db)
    name = file_name(db)
    audit.record(
        db,
        context,
        ACTION,
        RECORD,
        None,
        [change("file_name", None, name), change("users", None, len(written))],
    )
    return UsersFile(name=name, text=files.write_csv(list(COLUMNS), written), rows=len(written))
