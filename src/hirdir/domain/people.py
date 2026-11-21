"""A person: the user, the contact and the operators that are one person's (P-291).

A user names its contact and an operator names its contact, so the contact is what
joins them, and no field holds the link. This module says what is linked to a record,
and holds the one function that carries out a retirement with what it says of the
linked records, and the one that brings a user back. The change of each record is its
own module's: `accounts`, `contacts` and `operators`.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import Contact, Operator, User
from hirdir.domain import accounts, contacts, operators
from hirdir.domain.audit import AuditContext

USER = "user"
CONTACT = contacts.RECORD_TYPE
OPERATOR = operators.RECORD_TYPE
RETIRED = "retired"


@dataclass(frozen=True)
class Person:
    """The records of one person: the user whose contact it is, a retired one too, the
    contact, and every operator of that contact, in the order of their labels."""

    user: User | None
    contact: Contact | None
    operators: list[Operator]


def _around(db: Session, contact: Contact) -> Person:
    """Return the person a contact is."""
    user = db.scalar(select(User).where(User.contact_hid == contact.hid))
    return Person(user, contact, contacts.operators_of(db, [contact.hid])[contact.hid])


def of_contact(db: Session, hid: str) -> Person:
    """Return the person a contact is: itself, its user and its operators."""
    return _around(db, contacts.get_contact(db, hid))


def of_user(db: Session, hid: str) -> Person:
    """Return the person a user is. A user with no contact is itself alone."""
    user = accounts.get_user(db, hid)
    if user.contact_hid is None:
        return Person(user, None, [])
    return _around(db, contacts.get_contact(db, user.contact_hid))


def of_operator(db: Session, hid: str) -> Person:
    """Return the person behind an operator. An operator with no contact is itself alone."""
    operator = operators.get_operator(db, hid)
    if operator.contact_hid is None:
        return Person(None, None, [operator])
    return _around(db, contacts.get_contact(db, operator.contact_hid))


# The person of a record of each of the three kinds.
OF = {USER: of_user, CONTACT: of_contact, OPERATOR: of_operator}


@dataclass(frozen=True)
class BroughtBack:
    """A user brought back, with its new access code, shown this once."""

    user: User
    access_code: str | None


def _says_nothing(linked: dict[str, Any] | None) -> bool:
    return not linked or not (
        linked.get("user") or linked.get("contact") or linked.get("operators")
    )


def retire(
    db: Session,
    context: AuditContext,
    role: Role | None,
    kind: str,
    hid: str,
    row_version: int,
    linked: dict[str, Any] | None = None,
) -> None:
    """Retire a user, a contact or an operator, and carry out what `linked` says of the
    records linked to it (P-297). `role` is the role of whoever asks."""
    OF[kind](db, hid)
    if kind == CONTACT and _says_nothing(linked):
        contacts.retire_contact(db, context, hid, row_version)
    elif kind == OPERATOR and _says_nothing(linked):
        operators.retire_operator(db, context, hid, row_version)
    else:
        raise NotImplementedError


def bring_back(
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    linked: dict[str, Any] | None = None,
) -> BroughtBack:
    """Bring a retired user back, with what `linked` says is brought back with it (P-298)."""
    accounts.get_user(db, hid)
    raise NotImplementedError
