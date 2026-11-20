"""Contacts: the one list of people and shared mailboxes, and their assignments.

A contact is one record, assigned to a region, a site or a location in a role. What a
place has in force for a role is resolved in `hirdir.domain.geography`, from the place
outward: nothing is copied down. A user and an operator are each a part that a contact
plays, and read its name, email and numbers when they are read (P-172).
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db import dialect
from hirdir.db.models import (
    Agreement,
    Circuit,
    CircuitContact,
    Contact,
    ContactAssignment,
    Contract,
    ContractContact,
    Location,
    Operator,
    Owner,
    OwnerMember,
    Region,
    Site,
    User,
    Vendor,
    VendorContact,
)
from hirdir.domain import audit, choices, contracts, geography, records, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound

RECORD_TYPE = "contact"
ASSIGNMENT_TYPE = "contact_assignment"
FIELDS = ("name", "organization", "email", "phone", "phone2", "notes", "record_status")
ASSIGNMENT_FIELDS = (
    "contact_hid",
    "region_hid",
    "site_hid",
    "location_hid",
    "role",
    "priority",
    "stop_inheritance",
)
PLACES = {
    "region_hid": geography.REGION,
    "site_hid": geography.SITE,
    "location_hid": geography.LOCATION,
}
MAX_PRIORITY = 1000


@dataclass(frozen=True)
class Naming:
    """One kind of record that names a contact (P-205): the column of the link that
    holds the contact, and what tells a link of this kind from the others of its table."""

    kind: str
    contact: Any
    where: tuple[Any, ...] = ()


# What names a contact: a place and an owner it is assigned to, an operator it stands
# behind, and, so that a person about to retire a contact sees every record it is named
# by, an agreement and a contract (D-183), a carrier and a circuit (P-149). What a
# contact's record counts and what `GET /contacts/{hid}/uses` lists are both by these.
NAMINGS: tuple[Naming, ...] = (
    Naming("places", ContactAssignment.contact_hid),
    Naming("owners", OwnerMember.contact_hid),
    Naming("operators", Operator.contact_hid),
    Naming(
        "agreements", ContractContact.contact_hid, (ContractContact.agreement_hid.is_not(None),)
    ),
    Naming("contracts", ContractContact.contact_hid, (ContractContact.contract_hid.is_not(None),)),
    Naming("vendors", VendorContact.contact_hid),
    Naming("circuits", CircuitContact.contact_hid),
)
# The columns that name a contact, each once: `hirdir.io.fields` counts by them, to sort
# by. A link of an agreement and one of a contract are one table, and either names one.
USED_BY: tuple[Any, ...] = tuple(dict.fromkeys(naming.contact for naming in NAMINGS))
# The most records of one kind that the uses of a contact list, as a page of a list.
MAX_NAMED = 100


def get_contact(db: Session, hid: str) -> Contact:
    """Return the contact with hid."""
    contact = db.get(Contact, hid)
    if contact is None:
        raise NotFound(f"there is no contact {hid}")
    return contact


def known_as(db: Session, text: str, limit: int = 2) -> list[Contact]:
    """Return the contacts known by text: an HID, an email address or a name."""
    text = text.strip()
    if ids.is_hid(text):
        contact = db.get(Contact, text)
        if contact is not None:
            return [contact]
    wanted = records.key(text)
    return list(
        db.scalars(
            select(Contact)
            .where(or_(Contact.email_key == wanted, Contact.name_key == wanted))
            .order_by(Contact.hid)
            .limit(limit)
        )
    )


def the_one(db: Session, text: str, field: str) -> Contact:
    """Return the one contact known by text, or refuse: none, or more than one, is no answer."""
    found = known_as(db, text)
    if not found:
        raise Invalid("there is no such contact", {field: f"there is no contact {text}"})
    if len(found) > 1:
        raise Invalid(
            f"more than one contact answers to {text}",
            {field: f"more than one contact answers to {text}; give the email address or the HID"},
        )
    return found[0]


def reference_texts(db: Session, found: list[Contact]) -> dict[str, str]:
    """Return how a file names each of the contacts, so that the name finds that one alone.

    The email address when there is one, and otherwise the name, unless another
    contact answers to it or it has the form of an HID: then the contact's HID.
    """
    texts = {contact.hid: contact.email or contact.name for contact in found}
    # Who answers to each text, as `known_as` finds them: by email address or by name.
    answering: dict[str, set[str]] = {records.key(text): set() for text in texts.values()}
    wanted = sorted(answering)
    for start in range(0, len(wanted), 500):
        piece = wanted[start : start + 500]
        rows = db.execute(
            select(Contact.hid, Contact.email_key, Contact.name_key).where(
                or_(Contact.email_key.in_(piece), Contact.name_key.in_(piece))
            )
        )
        for hid, email, name in rows:
            for known in (email, name):
                if known in answering:
                    answering[known].add(hid)
    return {
        hid: text if answering[records.key(text)] == {hid} and not ids.is_hid(text) else hid
        for hid, text in texts.items()
    }


def _checked(db: Session, fields: dict[str, Any], contact: Contact | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None:
            raise Invalid("the name is not acceptable", {"name": "must not be blank"})
        values["name"] = name
        values["name_key"] = records.key(name)
    for name in ("organization", "phone", "phone2", "notes"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if "email" in fields:
        email = records.clean(fields["email"])
        if email is not None:
            local, at, domain = email.partition("@")
            if not local or not at or not domain or " " in email or "@" in domain:
                raise Invalid("the email address is not acceptable", {"email": "as name@host"})
            taken = db.scalar(select(Contact).where(Contact.email_key == records.key(email)))
            if taken is not None and (contact is None or taken.hid != contact.hid):
                raise Conflict(
                    f"{taken.name} already has the email address {taken.email}",
                    {"email": "another contact has this email address"},
                    Existing(RECORD_TYPE, taken.hid, taken.name),
                )
        values["email"] = email
        values["email_key"] = records.key(email) if email else None
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


def create_contact(db: Session, context: AuditContext, fields: dict[str, Any]) -> Contact:
    """Create a contact."""
    labels = fields.pop("tags", None) or []
    contact = Contact(**_checked(db, {"name": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        contact,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, contact.hid, labels),
    )
    return contact


def update_contact(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Contact:
    """Change a contact. Every place and owner it is assigned to shows the change at once."""
    contact = get_contact(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, contact)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, contact, row_version, values, tag_change)
    return contact


def retire_contact(db: Session, context: AuditContext, hid: str, row_version: int) -> Contact:
    """Retire a contact. Its assignments stay, and show it as retired."""
    contact = get_contact(db, hid)
    records.apply(
        db,
        context,
        RECORD_TYPE,
        contact,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return contact


def _counts(db: Session, naming: Naming, hids: list[str]) -> dict[str, int]:
    """Return how many records of one kind name each of the contacts."""
    column = naming.contact
    counted = db.execute(
        select(column, func.count()).where(column.in_(hids), *naming.where).group_by(column)
    )
    return {hid: count for hid, count in counted if hid is not None}


def uses(db: Session, hids: list[str]) -> dict[str, int]:
    """Return how many records name each of the contacts: the places and owners it is
    assigned to, the operators it stands behind, and the agreements, contracts, vendors
    and circuits that name it. A retired record counts as any other."""
    counts = dict.fromkeys(hids, 0)
    if hids:
        for naming in NAMINGS:
            for hid, count in _counts(db, naming, hids).items():
                counts[hid] += count
    return counts


@dataclass(frozen=True)
class Named:
    """One record that names a contact, and how (P-205)."""

    # Its kind as the audit trail names it: `site`, `owner`, `agreement`.
    record_type: str
    hid: str
    # What it is known by: a place by its path, a contract by its number and its vendor.
    label: str
    record_status: str
    # The role the contact has there: of the `contact_role` list for a place and a side of
    # a circuit, `primary` or `alternate` for an owner, `account_manager` or
    # `support_contact` for an agreement, a contract, a carrier and a circuit's carrier,
    # and none for an operator, which the contact stands behind.
    role: str | None = None
    priority: int | None = None
    # The side of a circuit, `a` or `z`, a contact of that side names; none for the carrier.
    side: str | None = None
    # The colour of an operator's label.
    colour: str | None = None


@dataclass(frozen=True)
class NamedBy:
    """The records of one kind that name a contact: how many, and at most `MAX_NAMED`."""

    total: int
    records: list[Named]


def named_by(db: Session, hid: str, limit: int = MAX_NAMED) -> dict[str, NamedBy]:
    """Return, for each kind in `NAMINGS`, the records that name a contact, by what each
    is known by, with how many there are: what `uses` counts, listed (P-205)."""
    get_contact(db, hid)
    found: dict[str, NamedBy] = {}
    for naming in NAMINGS:
        total = _counts(db, naming, [hid]).get(hid, 0)
        records_ = _LISTED[naming.kind](db, hid, limit) if total else []
        found[naming.kind] = NamedBy(total, records_)
    return found


def _places(db: Session, hid: str, limit: int) -> list[Named]:
    """The places a contact is assigned to, each by its path, in the order of their names."""
    rows = db.execute(
        select(ContactAssignment, Region, Site, Location)
        .outerjoin(Region, Region.hid == ContactAssignment.region_hid)
        .outerjoin(Site, Site.hid == ContactAssignment.site_hid)
        .outerjoin(Location, Location.hid == ContactAssignment.location_hid)
        .where(ContactAssignment.contact_hid == hid)
        .order_by(
            func.coalesce(Region.name_key, Site.name_key, Location.name_key),
            ContactAssignment.role,
            ContactAssignment.hid,
        )
        .limit(limit)
    ).all()
    atlas = geography.Atlas(db)
    atlas.take(place for row in rows for place in row[1:] if place is not None)
    atlas.read_locations(row[0].location_hid for row in rows)
    named = []
    for assignment, region, site, location in rows:
        if region is not None:
            level, place, path = geography.REGION, region, atlas.region_path(region.hid)
        elif site is not None:
            level, place, path = geography.SITE, site, atlas.site_path(site.hid)
        else:
            level, place, path = geography.LOCATION, location, atlas.location_path(location.hid)
        named.append(
            Named(
                level,
                place.hid,
                path,
                place.record_status,
                role=assignment.role,
                priority=assignment.priority,
            )
        )
    # In the order they were taken in, by the place's own name: the first of many are
    # then the first by name, as the page says of them.
    return named


def _owners(db: Session, hid: str, limit: int) -> list[Named]:
    rows = db.execute(
        select(OwnerMember, Owner)
        .join(Owner, Owner.hid == OwnerMember.owner_hid)
        .where(OwnerMember.contact_hid == hid)
        .order_by(Owner.label_key, OwnerMember.hid)
        .limit(limit)
    ).all()
    return [
        Named(
            "owner",
            owner.hid,
            owner.label,
            owner.record_status,
            role=member.role,
            priority=member.priority,
        )
        for member, owner in rows
    ]


def _operators(db: Session, hid: str, limit: int) -> list[Named]:
    found = db.scalars(
        select(Operator)
        .where(Operator.contact_hid == hid)
        .order_by(Operator.label_key, Operator.hid)
        .limit(limit)
    )
    return [
        Named("operator", one.hid, one.label, one.record_status, colour=one.colour) for one in found
    ]


def _agreements(db: Session, hid: str, limit: int) -> list[Named]:
    rows = db.execute(
        select(ContractContact, Agreement)
        .join(Agreement, Agreement.hid == ContractContact.agreement_hid)
        .where(ContractContact.contact_hid == hid)
        .order_by(Agreement.name_key, ContractContact.role, ContractContact.hid)
        .limit(limit)
    ).all()
    return [
        Named(
            "agreement",
            agreement.hid,
            agreement.name,
            agreement.record_status,
            role=link.role,
            priority=link.priority,
        )
        for link, agreement in rows
    ]


def _contracts(db: Session, hid: str, limit: int) -> list[Named]:
    number = contracts.term_value(Contract, "number")
    rows = db.execute(
        select(ContractContact, Contract, number, Vendor.name)
        .join(Contract, Contract.hid == ContractContact.contract_hid)
        .join(Vendor, Vendor.hid == Contract.vendor_hid)
        .where(ContractContact.contact_hid == hid)
        .order_by(func.lower(number), Vendor.name_key, ContractContact.role, ContractContact.hid)
        .limit(limit)
    ).all()
    return [
        Named(
            "contract",
            contract.hid,
            f"{held} ({vendor})",
            contract.record_status,
            role=link.role,
            priority=link.priority,
        )
        for link, contract, held, vendor in rows
    ]


def _vendors(db: Session, hid: str, limit: int) -> list[Named]:
    # A vendor is never retired: it is active while it is there.
    rows = db.execute(
        select(VendorContact, Vendor)
        .join(Vendor, Vendor.hid == VendorContact.vendor_hid)
        .where(VendorContact.contact_hid == hid)
        .order_by(Vendor.name_key, VendorContact.role, VendorContact.hid)
        .limit(limit)
    ).all()
    return [
        Named(
            "vendor",
            vendor.hid,
            vendor.name,
            "active",
            role=link.role,
            priority=link.priority,
        )
        for link, vendor in rows
    ]


def _circuits(db: Session, hid: str, limit: int) -> list[Named]:
    known = func.coalesce(Circuit.enterprise_circuit_id_key, Circuit.name_key)
    rows = db.execute(
        select(CircuitContact, Circuit)
        .join(Circuit, Circuit.hid == CircuitContact.circuit_hid)
        .where(CircuitContact.contact_hid == hid)
        # The carrier's contact has no side: blank, so that it stands first in every
        # database, which place a null where they please.
        .order_by(
            known,
            func.coalesce(CircuitContact.side, ""),
            CircuitContact.role,
            CircuitContact.hid,
        )
        .limit(limit)
    ).all()
    return [
        Named(
            "circuit",
            circuit.hid,
            circuit.enterprise_circuit_id or circuit.name,
            circuit.record_status,
            role=link.role,
            priority=link.priority,
            side=link.side,
        )
        for link, circuit in rows
    ]


# How the records of each kind of `NAMINGS` are listed.
_LISTED = {
    "places": _places,
    "owners": _owners,
    "operators": _operators,
    "agreements": _agreements,
    "contracts": _contracts,
    "vendors": _vendors,
    "circuits": _circuits,
}


def users_of(db: Session, hids: list[str]) -> dict[str, User]:
    """Return the user that each of the contacts is, where it is one (P-172)."""
    if not hids:
        return {}
    found = db.scalars(select(User).where(User.contact_hid.in_(hids)))
    return {user.contact_hid: user for user in found if user.contact_hid is not None}


def operators_of(db: Session, hids: list[str]) -> dict[str, list[Operator]]:
    """Return the operators each of the contacts stands behind, retired ones among them,
    in the order of their labels, read in one query for them all (P-280)."""
    found: dict[str, list[Operator]] = {hid: [] for hid in hids}
    if not hids:
        return found
    for operator in db.scalars(
        select(Operator)
        .where(Operator.contact_hid.in_(set(hids)))
        .order_by(Operator.label_key, Operator.hid)
    ):
        found[operator.contact_hid or ""].append(operator)
    return found


def is_operator(operators: list[Operator]) -> bool:
    """Say whether a contact stands behind an operator, of those it stands behind, that
    is not retired: one that is retired stands for nobody (P-280)."""
    return any(operator.record_status != "retired" for operator in operators)


# --- assignments ---------------------------------------------------------------------


def get_assignment(db: Session, hid: str) -> ContactAssignment:
    """Return the contact assignment with hid."""
    assignment = db.get(ContactAssignment, hid)
    if assignment is None:
        raise NotFound(f"there is no contact assignment {hid}")
    return assignment


def place_of(assignment: ContactAssignment) -> tuple[str, str]:
    """Return the field that names the place of an assignment, and the HID in it."""
    for name in PLACES:
        hid = getattr(assignment, name)
        if hid:
            return name, hid
    raise NotFound(f"the contact assignment {assignment.hid} names no place")


def _beside(
    db: Session, name: str, hid: str, role: str, but: str | None
) -> list[ContactAssignment]:
    """Return the other assignments of one place for one role."""
    return list(
        db.scalars(
            select(ContactAssignment).where(
                getattr(ContactAssignment, name) == hid,
                ContactAssignment.role == role,
                ContactAssignment.hid != (but or ""),
            )
        )
    )


def _checked_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PRIORITY:
        raise Invalid(
            "the priority is not acceptable",
            {"priority": f"a whole number from 1, the primary, to {MAX_PRIORITY}"},
        )
    return value


def _checked_assignment(
    db: Session, fields: dict[str, Any], assignment: ContactAssignment | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    # Checked against the other assignments of the place, so nobody may be changing them.
    dialect.hold_other_writers(db)
    if assignment is None:
        named = [name for name in PLACES if fields.get(name)]
        if len(named) != 1:
            raise Invalid(
                "an assignment is to one place",
                dict.fromkeys(named or PLACES, "exactly one of a region, a site and a location"),
            )
        place = geography.get_place(db, PLACES[named[0]], fields[named[0]])
        if place.record.record_status == "retired":
            raise Invalid("the place is retired", {named[0]: f"this {place.level} is retired"})
        values[named[0]] = place.hid
        where = (named[0], place.hid)
    else:
        for name in PLACES:
            if name in fields and (fields[name] or None) != getattr(assignment, name):
                raise Invalid(
                    "an assignment stays with its place",
                    {name: "remove this assignment and make the other"},
                )
        where = place_of(assignment)

    def final(name: str, default: Any = None) -> Any:
        if name in values:
            return values[name]
        if name in fields:
            return fields[name]
        return getattr(assignment, name) if assignment is not None else default

    if "role" in fields or assignment is None:
        role = records.clean(fields.get("role"))
        if role is None:
            raise Invalid("an assignment is in a role", {"role": "must not be blank"})
        values["role"] = choices.checked(db, geography.ROLE_LIST, role, "role")
    role = values.get("role", assignment.role if assignment is not None else "")
    stop = bool(final("stop_inheritance", False))
    contact_hid = final("contact_hid") or None
    if stop and contact_hid is not None:
        raise Invalid(
            "an assignment that stops inheritance names no contact",
            {"stop_inheritance": "it says: none here, and do not look further up"},
        )
    if not stop and contact_hid is None:
        raise Invalid(
            "an assignment names a contact",
            {"contact_hid": "name the contact, or set stop_inheritance for none here"},
        )
    if "stop_inheritance" in fields or assignment is None:
        values["stop_inheritance"] = stop
    if "contact_hid" in fields or assignment is None:
        if contact_hid is not None and (
            assignment is None or assignment.contact_hid != contact_hid
        ):
            contact = db.get(Contact, contact_hid)
            if contact is None:
                raise Invalid(
                    "there is no such contact",
                    {"contact_hid": f"there is no contact {contact_hid}"},
                )
            if contact.record_status == "retired":
                raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
        values["contact_hid"] = contact_hid
    beside = _beside(db, *where, role, assignment.hid if assignment is not None else None)
    if stop and beside:
        raise Conflict(
            "contacts are assigned here in this role; remove them first",
            {"stop_inheritance": "it stands alone for its place and role"},
        )
    if not stop:
        if any(other.stop_inheritance for other in beside):
            raise Conflict(
                "this place says that it has nobody in this role; remove that assignment first",
                {"contact_hid": "an assignment here stops inheritance for this role"},
            )
        if any(other.contact_hid == contact_hid for other in beside):
            raise Conflict(
                "this contact is already assigned here in this role",
                {"contact_hid": "a contact is assigned once to one place in one role"},
            )
    if fields.get("priority") is not None:
        values["priority"] = _checked_priority(fields["priority"])
    elif assignment is None:
        values["priority"] = 1 + max((other.priority for other in beside), default=0)
    return values


def create_assignment(
    db: Session, context: AuditContext, fields: dict[str, Any]
) -> ContactAssignment:
    """Assign a contact to a region, a site or a location in a role."""
    assignment = ContactAssignment(**_checked_assignment(db, fields, None))
    records.created(db, context, ASSIGNMENT_TYPE, assignment, ASSIGNMENT_FIELDS)
    return assignment


def update_assignment(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> ContactAssignment:
    """Change an assignment: its role, its priority or its contact. It stays with its place."""
    assignment = get_assignment(db, hid)
    values = _checked_assignment(db, fields, assignment)
    records.apply(db, context, ASSIGNMENT_TYPE, assignment, row_version, values)
    return assignment


def delete_assignment(db: Session, context: AuditContext, hid: str) -> None:
    """Remove an assignment. The audit event of the removal holds what it was."""
    assignment = get_assignment(db, hid)
    audit.record(
        db,
        context,
        "delete",
        ASSIGNMENT_TYPE,
        assignment.hid,
        [
            change(name, records.jsonable(getattr(assignment, name)), None)
            for name in ASSIGNMENT_FIELDS
            if getattr(assignment, name) not in (None, False)
        ],
    )
    db.delete(assignment)
    db.flush()
