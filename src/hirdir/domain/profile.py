"""A person's own profile: the contact they are, the operators they are behind and
their access code (P-289, P-294, P-295).

The rules of a contact, of an operator and of an access code stay where they are, in
`contacts`, `operators` and `accounts`: this module says whose record a person changes,
and which fields of it. Nothing here takes the HID of a user or of a contact, so that
nothing here can be turned on the record of another.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.throttle import Throttle
from hirdir.db.models import Contact, Operator, User
from hirdir.domain import accounts, contacts, operators
from hirdir.domain.accounts import Principal
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotAllowed, NotFound

# What a person changes of the contact they are, and of an operator they are behind.
CONTACT_FIELDS = ("name", "email", "phone", "phone2", "organization")
OPERATOR_FIELDS = ("label", "colour")
ASK_AN_ADMIN = "an Admin gives an account its contact"


def contact_of(db: Session, user: User) -> Contact | None:
    """Return the contact a user is, retired or not, or none."""
    return db.get(Contact, user.contact_hid) if user.contact_hid else None


def operators_of(db: Session, user: User) -> list[Operator]:
    """Return the operators a user is behind, in the order of their labels: those that
    are not retired and whose contact is the user's. A user with no contact is behind
    none, and neither is one whose contact is retired, as nobody is behind the labels of
    a retired contact (P-280)."""
    if not operators.behind(contact_of(db, user)):
        return []
    return list(
        db.scalars(
            select(Operator)
            .where(Operator.contact_hid == user.contact_hid, Operator.record_status != "retired")
            .order_by(Operator.label_key, Operator.hid)
        )
    )


def _person(principal: Principal) -> User:
    """Return the person a request comes from, whatever role they hold; or refuse a
    service account or an agent, which is no person and has no profile (P-316)."""
    if principal.kind != "session" or not accounts.is_person(principal.user):
        which = "an agent" if accounts.is_agent(principal.user) else "a service account"
        raise NotAllowed(f"{which} has no profile")
    return principal.user


def _own(fields: dict[str, Any], known: tuple[str, ...]) -> dict[str, Any]:
    """Return the fields of a change, or refuse one that a profile does not change."""
    unknown = {name: "not changed on a profile" for name in fields if name not in known}
    if unknown:
        raise Invalid("a profile does not change this", unknown)
    return dict(fields)


def update_contact(
    db: Session,
    principal: Principal,
    context: AuditContext,
    row_version: int,
    fields: dict[str, Any],
) -> Contact:
    """Change the name, the email, the numbers or the organization of the contact the
    person is, by the rules of any change of a contact, audited as one, by the person."""
    contact = contact_of(db, _person(principal))
    if contact is None:
        raise Conflict(f"this account has no contact: {ASK_AN_ADMIN}")
    if contact.record_status == "retired":
        raise Conflict(f"the contact of this account is retired: {ASK_AN_ADMIN}")
    return contacts.update_contact(
        db, context, contact.hid, row_version, _own(fields, CONTACT_FIELDS)
    )


def update_operator(
    db: Session,
    principal: Principal,
    context: AuditContext,
    hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> Operator:
    """Change the label or the colour of an operator the person is behind, by the rules
    of any change of an operator, audited as one, by the person. An operator of
    another, one with nobody behind it and one that is retired are as none."""
    if hid not in {one.hid for one in operators_of(db, _person(principal))}:
        raise NotFound(f"there is no operator {hid} that you are behind")
    return operators.update_operator(db, context, hid, row_version, _own(fields, OPERATOR_FIELDS))


def change_access_code(
    db: Session,
    principal: Principal,
    context: AuditContext,
    *,
    current: str,
    new: str,
    address: str,
    throttle: Throttle,
    signing_key: bytes,
    session_hours: int,
) -> tuple[str, datetime]:
    """Change the access code of the person, who gives the one they have. Return a new
    session token for the session in hand, and when it ends: every other is ended."""
    return accounts.change_access_code(
        db,
        context,
        _person(principal),
        current=current,
        new=new,
        address=address,
        throttle=throttle,
        signing_key=signing_key,
        session_hours=session_hours,
    )
