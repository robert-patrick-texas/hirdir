"""Owners: who answers for an item.

Release 0.2.0 has the owner itself. Its people, and the marked exception when an item
is given to an owner outside the operations team, arrive with contacts in 0.5.0.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Owner
from hirdir.domain import records
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound

FIELDS = ("label", "organization", "is_external", "exception_reason", "record_status")


def get_owner(db: Session, hid: str) -> Owner:
    """Return the owner with hid."""
    owner = db.get(Owner, hid)
    if owner is None:
        raise NotFound(f"there is no owner {hid}")
    return owner


def _checked(db: Session, fields: dict[str, Any], owner: Owner | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "label" in fields:
        label = records.clean(fields["label"])
        if label is None:
            raise Invalid("the label is not acceptable", {"label": "must not be blank"})
        taken = db.scalar(select(Owner).where(Owner.label_key == records.key(label)))
        if taken is not None and (owner is None or taken.hid != owner.hid):
            raise Conflict(
                f"there is already an owner {taken.label}",
                {"label": "another owner has this label"},
            )
        values["label"] = label
        values["label_key"] = records.key(label)
    for name in ("organization", "exception_reason"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if "is_external" in fields:
        values["is_external"] = bool(fields["is_external"])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])

    def final(name: str) -> Any:
        return values.get(name, getattr(owner, name) if owner is not None else None)

    if final("is_external") and not final("exception_reason"):
        raise Invalid(
            "an owner outside the operations team needs a reason",
            {"exception_reason": "say why this owner is an exception"},
        )
    return values


def create_owner(db: Session, context: AuditContext, fields: dict[str, Any]) -> Owner:
    """Create an owner."""
    owner = Owner(**_checked(db, {"label": None, **fields}, None))
    records.created(db, context, "owner", owner, FIELDS)
    return owner


def update_owner(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Owner:
    """Change an owner."""
    owner = get_owner(db, hid)
    records.apply(db, context, "owner", owner, row_version, _checked(db, fields, owner))
    return owner


def retire_owner(db: Session, context: AuditContext, hid: str, row_version: int) -> Owner:
    """Retire an owner. The record and what refers to it stay."""
    owner = get_owner(db, hid)
    records.apply(
        db, context, "owner", owner, row_version, {"record_status": "retired"}, action="retire"
    )
    return owner
