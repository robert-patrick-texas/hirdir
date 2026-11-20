"""A person's own profile: the contact they are and the operators they are behind
(P-289, P-294, P-295).

The rules of a contact and of an operator stay where they are, in `contacts` and
`operators`: this module says whose record a person changes, and which fields of it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Contact, Operator, User
from hirdir.domain import operators


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
