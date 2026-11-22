"""The users as a file, for an Admin (P-288).

A row to each user, by username, with what the Users list tells of it: the person it is,
the role in force, its groups and its operators, what kind of account it is and whether
it signs in. It holds no access code, no token and no hash of either, ever: none of them
is read here. No file makes or changes a user, so this file is written and never read.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
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
    "answerable",
    "state",
    "record_status",
    "last_sign_in_at",
    "notes",
)
# A time is written in the one form the API gives it, in UTC: 2026-11-20T15:04:05.123456Z.
_TIME: TypeAdapter[datetime | None] = TypeAdapter(datetime | None)
# The audit trail names what was exported so.
RECORD = "user"
ACTION = "export"


@dataclass(frozen=True)
class UsersFile:
    """The file of the users, written, with its name and how many rows it holds."""

    name: str
    text: str
    rows: int


def rows(db: Session, retired: str = "no") -> list[dict[str, Any]]:
    """Return a row to each user, by username, in plain values: those that are not
    retired, unless the retired are asked for, as the list of users takes it (P-296)."""
    users = list(
        db.scalars(accounts.retired_or_not(select(User), retired).order_by(User.username_key))
    )
    contacts = accounts.contacts_of(db, users)
    groups, roles = accounts.groups_of_users(db, users), accounts.roles_of(db, users)
    persons = accounts.answerable_of(db, users)
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
                "kind": user.kind,
                # The username of the person answerable for an agent (P-316).
                "answerable": person.username
                if (person := persons.get(user.answerable_hid or ""))
                else None,
                "state": "disabled" if user.disabled else "enabled",
                "record_status": user.record_status,
                "last_sign_in_at": _TIME.dump_python(user.last_sign_in_at, mode="json"),
                "notes": user.notes,
            }
        )
    return written


def file_name(db: Session) -> str:
    """Return a name for the file, named as any download is (P-168)."""
    stem = product.file_stem(product.name(db))
    return f"{stem}-users-{clock.stamp(clock.now(), settings.time_zone(db))}.csv"


def export(db: Session, context: AuditContext, retired: str = "no") -> UsersFile:
    """Write the file of the users, and record in the audit trail that it was."""
    written = rows(db, retired)
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
