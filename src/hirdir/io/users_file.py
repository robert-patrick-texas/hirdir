"""The users as a file, for an Admin (P-288).

A row to each user, by username, with what the Users list tells of it: the person it is,
the role in force, its groups and its operators, what kind of account it is and whether
it signs in. It holds no access code, no token and no hash of either, ever: none of them
is read here. No file makes or changes a user, so this file is written and never read.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import User
from hirdir.domain import accounts, audit, product, settings
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


def rows(db: Session) -> list[dict[str, Any]]:
    """Return a row to each user, by username, in plain values."""
    users = list(db.scalars(select(User).order_by(User.username_key)))
    contacts = accounts.contacts_of(db, users)
    groups, roles = accounts.groups_of_users(db, users), accounts.roles_of(db, users)
    operators = accounts.operators_of(db, users)
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
                "role": role.value if (role := roles[user.hid]) else None,
                "groups": [group.name for group in groups[user.hid]],
                # Those that are not retired: a retired label stands for nothing.
                "operators": [
                    operator.label
                    for operator in operators.get(user.hid, [])
                    if operator.record_status != "retired"
                ],
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
