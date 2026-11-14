"""Owners: who answers for an item, and the people of each owner.

An owner outside the operations team is an exception and says why. An item that is
given to such an owner says why as well: that rule is with the items, in
`hirdir.domain.items`.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import Contact, Owner, OwnerMember
from hirdir.domain import audit, records, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "owner"
MEMBER_TYPE = "owner_member"
FIELDS = ("label", "organization", "is_external", "exception_reason", "record_status")
MEMBER_FIELDS = ("owner_hid", "contact_hid", "role", "priority")
PRIMARY, ALTERNATE = "primary", "alternate"
ROLES = (PRIMARY, ALTERNATE)
MAX_PRIORITY = 1000


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
    labels = fields.pop("tags", None) or []
    owner = Owner(**_checked(db, {"label": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        owner,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, owner.hid, labels),
    )
    return owner


def update_owner(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Owner:
    """Change an owner."""
    owner = get_owner(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, owner)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, owner, row_version, values, tag_change)
    return owner


def retire_owner(db: Session, context: AuditContext, hid: str, row_version: int) -> Owner:
    """Retire an owner. The record and what refers to it stay."""
    owner = get_owner(db, hid)
    records.apply(
        db, context, RECORD_TYPE, owner, row_version, {"record_status": "retired"}, action="retire"
    )
    return owner


# --- the people of an owner ----------------------------------------------------------


def get_member(db: Session, owner_hid: str, member_hid: str) -> OwnerMember:
    """Return one member of one owner."""
    member = db.get(OwnerMember, member_hid)
    if member is None or member.owner_hid != owner_hid:
        raise NotFound(f"there is no member {member_hid} of this owner")
    return member


def members_of(db: Session, owner_hids: list[str]) -> dict[str, list[tuple[OwnerMember, Contact]]]:
    """Return the members of each of the owners with their contacts: the primary first,
    then the alternates by priority."""
    found: dict[str, list[tuple[OwnerMember, Contact]]] = {hid: [] for hid in owner_hids}
    if owner_hids:
        rows = db.execute(
            select(OwnerMember, Contact)
            .join(Contact, Contact.hid == OwnerMember.contact_hid)
            .where(OwnerMember.owner_hid.in_(owner_hids))
            .order_by(
                OwnerMember.role != PRIMARY,
                OwnerMember.priority,
                Contact.name_key,
                OwnerMember.hid,
            )
        )
        for member, contact in rows:
            found[member.owner_hid].append((member, contact))
    return found


def _members(db: Session, owner_hid: str) -> list[OwnerMember]:
    return list(db.scalars(select(OwnerMember).where(OwnerMember.owner_hid == owner_hid)))


def _checked_role(value: Any) -> str:
    role = records.key(str(value or ""))
    if role not in ROLES:
        raise Invalid("the role is not acceptable", {"role": f"one of {', '.join(ROLES)}"})
    return role


def _checked_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PRIORITY:
        raise Invalid(
            "the priority is not acceptable",
            {"priority": f"a whole number from 1 to {MAX_PRIORITY}"},
        )
    return value


def _demote_primary(db: Session, context: AuditContext, owner_hid: str, but: str | None) -> None:
    """Make the primary of an owner an alternate, because another member takes its place."""
    for member in _members(db, owner_hid):
        if member.role == PRIMARY and member.hid != but:
            records.apply(db, context, MEMBER_TYPE, member, None, {"role": ALTERNATE})


def add_member(
    db: Session, context: AuditContext, owner_hid: str, fields: dict[str, Any]
) -> OwnerMember:
    """Make a contact one of the people of an owner.

    The first member is the primary. A further one is an alternate unless it is named
    primary, which makes the one that had that role an alternate in the same change.
    """
    # Checked against the other members, so nobody else may be changing them meanwhile.
    dialect.hold_other_writers(db)
    owner = get_owner(db, owner_hid)
    if owner.record_status == "retired":
        raise Invalid("the owner is retired", {"owner_hid": "this owner is retired"})
    contact_hid = fields.get("contact_hid") or ""
    contact = db.get(Contact, contact_hid)
    if contact is None:
        raise Invalid(
            "there is no such contact", {"contact_hid": f"there is no contact {contact_hid}"}
        )
    if contact.record_status == "retired":
        raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
    there = _members(db, owner_hid)
    if any(member.contact_hid == contact.hid for member in there):
        raise Conflict(
            f"{contact.name} is already one of the people of {owner.label}",
            {"contact_hid": "a contact is a member of an owner once"},
        )
    role = _checked_role(fields["role"]) if fields.get("role") else None
    if not there:
        if role == ALTERNATE:
            raise Invalid(
                "the first member of an owner is its primary",
                {"role": "an owner that has members has exactly one primary"},
            )
        role = PRIMARY
    role = role or ALTERNATE
    priority = (
        _checked_priority(fields["priority"])
        if fields.get("priority") is not None
        else 1 + max((member.priority for member in there if member.role == ALTERNATE), default=0)
    )
    if role == PRIMARY:
        _demote_primary(db, context, owner_hid, None)
        priority = 1 if fields.get("priority") is None else priority
    member = OwnerMember(owner_hid=owner_hid, contact_hid=contact.hid, role=role, priority=priority)
    records.created(db, context, MEMBER_TYPE, member, MEMBER_FIELDS)
    return member


def update_member(
    db: Session,
    context: AuditContext,
    owner_hid: str,
    member_hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> OwnerMember:
    """Change the role or the priority of a member of an owner."""
    dialect.hold_other_writers(db)
    member = get_member(db, owner_hid, member_hid)
    values: dict[str, Any] = {}
    for name in ("owner_hid", "contact_hid"):
        if name in fields and fields[name] != getattr(member, name):
            raise Invalid(
                "a member stays with its owner and its contact",
                {name: "remove this member and add the other"},
            )
    if fields.get("role") is not None:
        role = _checked_role(fields["role"])
        if role == ALTERNATE and member.role == PRIMARY:
            raise Invalid(
                "an owner that has members has exactly one primary",
                {"role": "make another member the primary, and this one is an alternate"},
            )
        values["role"] = role
    if fields.get("priority") is not None:
        values["priority"] = _checked_priority(fields["priority"])
    if values.get("role") == PRIMARY and member.role != PRIMARY:
        if member.row_version != row_version:
            records.touch(member, context, row_version)
        _demote_primary(db, context, owner_hid, member.hid)
    records.apply(db, context, MEMBER_TYPE, member, row_version, values)
    return member


def remove_member(db: Session, context: AuditContext, owner_hid: str, member_hid: str) -> None:
    """Remove a member of an owner. The audit event of the removal holds what it was."""
    dialect.hold_other_writers(db)
    member = get_member(db, owner_hid, member_hid)
    if member.role == PRIMARY and len(_members(db, owner_hid)) > 1:
        raise Conflict(
            "the primary is not removed while the owner has other members; "
            "make another member the primary first",
            {"role": "an owner that has members has exactly one primary"},
        )
    audit.record(
        db,
        context,
        "delete",
        MEMBER_TYPE,
        member.hid,
        [change(name, getattr(member, name), None) for name in MEMBER_FIELDS],
    )
    db.delete(member)
    db.flush()
