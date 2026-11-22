"""The contacts of a carrier and of a circuit (P-149): contact records named in a role.

A vendor that is a carrier names its account team and its support desk once, in
`vendor_contacts`. A circuit has those of its primary carrier, for each of the two
roles by itself, unless it names its own of that role in `circuit_contacts`, which then
stand in place of the carrier's, all of them, as a contract's stand in place of its
agreement's. The site contacts of a circuit are those of the locations of its two
sides, each role of the `contact_role` list resolved as for the location itself, with
the level each came from; a circuit may name its own for a side and a role, which then
stand in place of what the location gives. A side with no location has only its own.

That is worked out when a circuit is read, for a page of circuits at once. Nothing is
copied: a new telephone number of a carrier's support desk shows on every circuit of
that carrier, and no circuit is written to.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import Circuit, CircuitContact, Contact, Vendor, VendorContact
from hirdir.domain import audit, choices, geography, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.circuits import CARRIER_CONTACT_ROLES, SIDES
from hirdir.domain.errors import Conflict, Invalid, NotFound

VENDOR_TYPE = "vendor_contact"
CIRCUIT_TYPE = "circuit_contact"
ROLES = CARRIER_CONTACT_ROLES
# The name of each of the carrier's roles in the `effective` block of a circuit.
IN_FORCE = {"account_manager": "account_managers", "support_contact": "support_contacts"}
VENDOR_FIELDS = ("vendor_hid", "role", "contact_hid", "priority")
CIRCUIT_FIELDS = ("circuit_hid", "side", "role", "contact_hid", "priority")
MAX_PRIORITY = 1000

CarrierSource = Literal["own", "vendor", "none"]
SiteSource = Literal["own", "location", "site", "region"]
# The level a site contact came from, as the resolution of the location of a side names
# it: what that location has of its own is, for the circuit, from the location.
LEVELS: dict[str, SiteSource] = {
    "own": "location",
    "location": "location",
    "site": "site",
    "region": "region",
}


@dataclass(frozen=True)
class Naming:
    """A contact in force, and what names it: a contact of the circuit, of its carrier,
    or an assignment of a place."""

    hid: str
    role: str
    priority: int
    contact: Contact


@dataclass(frozen=True)
class InForce:
    """The carrier's contacts in force for one role, and the record they came from."""

    named: list[Naming]
    source: CarrierSource
    source_hid: str | None


@dataclass(frozen=True)
class SideRole:
    """The site contacts in force for one side and one role, and the level they came
    from: the circuit's own, or the location of the side, a location above it, its
    site or a region."""

    role: str
    named: list[Naming]
    source: SiteSource
    source_hid: str


@dataclass(frozen=True)
class OfCircuit:
    """What a circuit names of its own, and the contacts it has in force."""

    own: list[tuple[CircuitContact, Contact]]
    # The account managers and the support contacts, by role.
    carrier: dict[str, InForce]
    # The site contacts of each side, `a` and `z`, one entry for each role that has any.
    sites: dict[str, list[SideRole]]


# --- reading -------------------------------------------------------------------------


def get_vendor(db: Session, hid: str) -> Vendor:
    """Return the vendor whose contacts are asked for."""
    vendor = db.get(Vendor, hid)
    if vendor is None:
        raise NotFound(f"there is no vendor {hid}")
    return vendor


def get_circuit(db: Session, hid: str) -> Circuit:
    """Return the circuit whose contacts are asked for."""
    circuit = db.get(Circuit, hid)
    if circuit is None:
        raise NotFound(f"there is no circuit {hid}")
    return circuit


def get_vendor_link(db: Session, hid: str, link_hid: str) -> VendorContact:
    """Return one contact of one vendor."""
    link = db.get(VendorContact, link_hid)
    if link is None or link.vendor_hid != hid:
        raise NotFound(f"there is no contact {link_hid} of this vendor")
    return link


def get_circuit_link(db: Session, hid: str, link_hid: str) -> CircuitContact:
    """Return one contact of one circuit."""
    link = db.get(CircuitContact, link_hid)
    if link is None or link.circuit_hid != hid:
        raise NotFound(f"there is no contact {link_hid} of this circuit")
    return link


def named_by_vendors(
    db: Session, hids: Collection[str]
) -> dict[str, list[tuple[VendorContact, Contact]]]:
    """Return what each of the vendors names, with the contacts: by role, then by
    priority, then by name."""
    found: dict[str, list[tuple[VendorContact, Contact]]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(VendorContact, Contact)
            .join(Contact, Contact.hid == VendorContact.contact_hid)
            .where(VendorContact.vendor_hid.in_(wanted[start : start + 500]))
            .order_by(
                VendorContact.role, VendorContact.priority, Contact.name_key, VendorContact.hid
            )
        )
        for link, contact in rows:
            found[link.vendor_hid].append((link, contact))
    return found


def named_by_circuits(
    db: Session, hids: Collection[str]
) -> dict[str, list[tuple[CircuitContact, Contact]]]:
    """Return what each of the circuits names of its own, with the contacts: the
    carrier's first, then those of the A side and of the Z side, each by role, then by
    priority, then by name."""
    found: dict[str, list[tuple[CircuitContact, Contact]]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(CircuitContact, Contact)
            .join(Contact, Contact.hid == CircuitContact.contact_hid)
            .where(CircuitContact.circuit_hid.in_(wanted[start : start + 500]))
            .order_by(
                # A blank side sorts first in SQLite and last in PostgreSQL: a blank is
                # given a value, so that both list the carrier's first.
                func.coalesce(CircuitContact.side, ""),
                CircuitContact.role,
                CircuitContact.priority,
                Contact.name_key,
                CircuitContact.hid,
            )
        )
        for link, contact in rows:
            found[link.circuit_hid].append((link, contact))
    return found


def _naming(link: Any, contact: Contact) -> Naming:
    return Naming(link.hid, link.role, link.priority, contact)


def _carrier(
    circuit: Circuit,
    own: Sequence[tuple[CircuitContact, Contact]],
    theirs: Sequence[tuple[VendorContact, Contact]],
) -> dict[str, InForce]:
    """Return the carrier's contacts in force of a circuit, for each role by itself:
    its own where it names any, else its primary carrier's, else none."""
    found: dict[str, InForce] = {}
    for role in ROLES:
        mine = [_naming(*one) for one in own if one[0].side is None and one[0].role == role]
        given = [_naming(*one) for one in theirs if one[0].role == role]
        if mine:
            found[role] = InForce(mine, "own", circuit.hid)
        elif circuit.carrier_hid is not None and given:
            found[role] = InForce(given, "vendor", circuit.carrier_hid)
        else:
            found[role] = InForce([], "none", None)
    return found


def _side(
    circuit: Circuit,
    side: str,
    own: Sequence[tuple[CircuitContact, Contact]],
    there: Sequence[geography.RoleContacts],
    order: Sequence[str],
) -> list[SideRole]:
    """Return the site contacts in force of one side of a circuit: for each role, its
    own where it names any for the side, else what the location of the side has in
    force for the role, with the level it came from. A role with none is left out."""
    mine: dict[str, list[Naming]] = {}
    for link, contact in own:
        if link.side == side:
            mine.setdefault(link.role, []).append(_naming(link, contact))
    placed = {one.role: one for one in there}
    roles = list(order) + sorted({*mine, *placed} - set(order))
    found: list[SideRole] = []
    for role in roles:
        if role in mine:
            found.append(SideRole(role, mine[role], "own", circuit.hid))
            continue
        resolved = placed.get(role)
        level = LEVELS.get(resolved.source) if resolved is not None else None
        if resolved is None or level is None or not resolved.contacts:
            continue
        found.append(
            SideRole(
                role,
                [
                    Naming(assignment.hid, role, assignment.priority, contact)
                    for assignment, contact in resolved.contacts
                ],
                level,
                resolved.source_hid or "",
            )
        )
    return found


def of_circuits(db: Session, circuits: Sequence[Circuit]) -> dict[str, OfCircuit]:
    """Return, for each circuit by its HID, what it names of its own and the contacts
    it has in force: the carrier's, `effective.account_managers` and
    `effective.support_contacts`, and the sites', `effective.site_contacts`.

    One statement reads what the circuits name, one what their carriers name, and the
    locations of their sides are resolved together, so a page of circuits costs a
    handful of statements, as one circuit does.
    """
    own = named_by_circuits(db, [circuit.hid for circuit in circuits])
    theirs = named_by_vendors(
        db, {circuit.carrier_hid for circuit in circuits if circuit.carrier_hid}
    )
    atlas = geography.Atlas(db)
    located = {
        hid
        for circuit in circuits
        for hid in (circuit.a_location_hid, circuit.z_location_hid)
        if hid is not None
    }
    atlas.read_locations(located)
    places = [
        geography.Place(geography.LOCATION, location)
        for hid in sorted(located)
        if (location := atlas.location(hid)) is not None
    ]
    resolved = geography.contacts_in_force(db, places, atlas)
    order = [choice.value for choice in choices.list_choices(db, geography.ROLE_LIST)]
    found: dict[str, OfCircuit] = {}
    for circuit in circuits:
        mine = own[circuit.hid]
        sides = {
            "a": _side(circuit, "a", mine, resolved.get(circuit.a_location_hid or "", []), order),
            "z": _side(circuit, "z", mine, resolved.get(circuit.z_location_hid or "", []), order),
        }
        found[circuit.hid] = OfCircuit(
            own=mine,
            carrier=_carrier(circuit, mine, theirs.get(circuit.carrier_hid or "", [])),
            sites=sides,
        )
    return found


# --- what a naming may be ------------------------------------------------------------


def _checked_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PRIORITY:
        raise Invalid(
            "the priority is not acceptable",
            {"priority": f"a whole number from 1, the first listed, to {MAX_PRIORITY}"},
        )
    return value


def _checked_contact(db: Session, value: Any) -> Contact:
    """Return the contact a naming is to name: one that is there and is not retired."""
    hid = value if isinstance(value, str) else ""
    contact = db.get(Contact, hid) if hid else None
    if contact is None:
        raise Invalid(
            "there is no such contact",
            {"contact_hid": f"there is no contact {hid}" if hid else "must not be blank"},
        )
    # A retired contact stays named where it is (P-311).
    if records.refuses_retired(contact, "contact", kept=True):
        raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
    return contact


def _checked_side(value: Any) -> str | None:
    """Return the side of a contact of a circuit: blank for one of the carrier's."""
    side = records.clean(value)
    return None if side is None else records.checked_choice(side, SIDES, "side")


def _checked_role(db: Session, value: Any, side: str | None) -> str:
    """Return the role of a naming: with no side, one of the carrier's two; with a
    side, a value of the `contact_role` list."""
    role = records.clean(value) if isinstance(value, str) else None
    if role is None:
        raise Invalid("a contact is named in a role", {"role": "must not be blank"})
    if side is None:
        return records.checked_choice(role, ROLES, "role")
    return choices.checked(db, geography.ROLE_LIST, role, "role")


def _check_once(taken: bool, what: str) -> None:
    if taken:
        raise Conflict(
            f"this contact is already named for this {what} in this role",
            {"contact_hid": f"a contact is named once for one {what}, side and role"},
        )


def _next(priorities: list[int]) -> int:
    """Return the priority of a naming that is listed last."""
    return min(1 + max(priorities, default=0), MAX_PRIORITY)


def _removal(link: Any, names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return what a naming was, for the audit event of its removal."""
    return [
        change(name, getattr(link, name), None) for name in names if getattr(link, name) is not None
    ]


# --- the contacts of a vendor --------------------------------------------------------


def _vendor_beside(db: Session, hid: str, role: str, but: str | None) -> list[VendorContact]:
    """Return the other namings of one vendor in one role."""
    return list(
        db.scalars(
            select(VendorContact).where(
                VendorContact.vendor_hid == hid,
                VendorContact.role == role,
                VendorContact.hid != (but or ""),
            )
        )
    )


def add_vendor_contact(
    db: Session, context: AuditContext, hid: str, fields: dict[str, Any]
) -> VendorContact:
    """Name a contact for a vendor as an account manager or a support contact.

    Left out, its priority is one more than the highest there is for the vendor and
    the role, so that it is listed last.
    """
    # Checked against the other namings of the vendor, so nobody may be changing them.
    dialect.hold_other_writers(db)
    vendor = get_vendor(db, hid)
    role = _checked_role(db, fields.get("role"), None)
    contact = _checked_contact(db, fields.get("contact_hid"))
    beside = _vendor_beside(db, vendor.hid, role, None)
    _check_once(any(one.contact_hid == contact.hid for one in beside), "vendor")
    priority = (
        _checked_priority(fields["priority"])
        if fields.get("priority") is not None
        else _next([one.priority for one in beside])
    )
    link = VendorContact(
        vendor_hid=vendor.hid, role=role, contact_hid=contact.hid, priority=priority
    )
    records.created(db, context, VENDOR_TYPE, link, VENDOR_FIELDS)
    return link


def update_vendor_contact(
    db: Session,
    context: AuditContext,
    hid: str,
    link_hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> VendorContact:
    """Change the role, the priority or the contact of a naming of a vendor. It stays
    with its vendor. A contact that is retired is not newly named, and stays where it
    is."""
    dialect.hold_other_writers(db)
    link = get_vendor_link(db, hid, link_hid)
    if "vendor_hid" in fields and fields["vendor_hid"] != link.vendor_hid:
        raise Invalid(
            "a contact stays with its vendor",
            {"vendor_hid": "remove this contact and name it where it belongs"},
        )
    values: dict[str, Any] = {}
    if "role" in fields:
        values["role"] = _checked_role(db, fields["role"], None)
    if "contact_hid" in fields and fields["contact_hid"] != link.contact_hid:
        values["contact_hid"] = _checked_contact(db, fields["contact_hid"]).hid
    if fields.get("priority") is not None:
        values["priority"] = _checked_priority(fields["priority"])
    role = values.get("role", link.role)
    contact_hid = values.get("contact_hid", link.contact_hid)
    if role != link.role or contact_hid != link.contact_hid:
        beside = _vendor_beside(db, hid, role, link.hid)
        _check_once(any(one.contact_hid == contact_hid for one in beside), "vendor")
    records.apply(db, context, VENDOR_TYPE, link, row_version, values)
    return link


def remove_vendor_contact(db: Session, context: AuditContext, hid: str, link_hid: str) -> None:
    """Remove a naming of a vendor that was a mistake. The audit event of the removal
    holds what it was."""
    link = get_vendor_link(db, hid, link_hid)
    audit.record(db, context, "delete", VENDOR_TYPE, link.hid, _removal(link, VENDOR_FIELDS))
    db.delete(link)
    db.flush()


# --- the contacts of a circuit -------------------------------------------------------


def _circuit_beside(
    db: Session, hid: str, side: str | None, role: str, but: str | None
) -> list[CircuitContact]:
    """Return the other namings of one circuit on one side, or of the carrier's, in one
    role."""
    return list(
        db.scalars(
            select(CircuitContact).where(
                CircuitContact.circuit_hid == hid,
                CircuitContact.side.is_(None) if side is None else CircuitContact.side == side,
                CircuitContact.role == role,
                CircuitContact.hid != (but or ""),
            )
        )
    )


def add_circuit_contact(
    db: Session, context: AuditContext, hid: str, fields: dict[str, Any]
) -> CircuitContact:
    """Name a contact for a circuit: with no side, one of the carrier's, in place of
    those of its carrier in that role; with a side, a site contact of that side, in
    place of what the location gives in that role.

    Left out, its priority is one more than the highest there is for the circuit, the
    side and the role, so that it is listed last. A retired circuit takes none.
    """
    dialect.hold_other_writers(db)
    circuit = get_circuit(db, hid)
    # A retired circuit keeps its parts (P-311).
    if records.refuses_retired(circuit, "circuit", kept=True):
        raise Invalid("the circuit is retired", {"circuit_hid": "this circuit is retired"})
    side = _checked_side(fields.get("side"))
    role = _checked_role(db, fields.get("role"), side)
    contact = _checked_contact(db, fields.get("contact_hid"))
    beside = _circuit_beside(db, circuit.hid, side, role, None)
    _check_once(any(one.contact_hid == contact.hid for one in beside), "circuit")
    priority = (
        _checked_priority(fields["priority"])
        if fields.get("priority") is not None
        else _next([one.priority for one in beside])
    )
    link = CircuitContact(
        circuit_hid=circuit.hid, side=side, role=role, contact_hid=contact.hid, priority=priority
    )
    records.created(db, context, CIRCUIT_TYPE, link, CIRCUIT_FIELDS)
    return link


def update_circuit_contact(
    db: Session,
    context: AuditContext,
    hid: str,
    link_hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> CircuitContact:
    """Change the side, the role, the priority or the contact of a naming of a circuit.
    It stays with its circuit, and its role is one that its side takes. A contact that
    is retired is not newly named, and stays where it is."""
    dialect.hold_other_writers(db)
    link = get_circuit_link(db, hid, link_hid)
    if "circuit_hid" in fields and fields["circuit_hid"] != link.circuit_hid:
        raise Invalid(
            "a contact stays with its circuit",
            {"circuit_hid": "remove this contact and name it where it belongs"},
        )
    values: dict[str, Any] = {}
    if "side" in fields:
        values["side"] = _checked_side(fields["side"])
    side = values.get("side", link.side)
    if "role" in fields or side != link.side:
        values["role"] = _checked_role(db, fields.get("role", link.role), side)
    if "contact_hid" in fields and fields["contact_hid"] != link.contact_hid:
        values["contact_hid"] = _checked_contact(db, fields["contact_hid"]).hid
    if fields.get("priority") is not None:
        values["priority"] = _checked_priority(fields["priority"])
    role = values.get("role", link.role)
    contact_hid = values.get("contact_hid", link.contact_hid)
    if (side, role, contact_hid) != (link.side, link.role, link.contact_hid):
        beside = _circuit_beside(db, hid, side, role, link.hid)
        _check_once(any(one.contact_hid == contact_hid for one in beside), "circuit")
    records.apply(db, context, CIRCUIT_TYPE, link, row_version, values)
    return link


def remove_circuit_contact(db: Session, context: AuditContext, hid: str, link_hid: str) -> None:
    """Remove a naming of a circuit that was a mistake. The audit event of the removal
    holds what it was. A circuit that names nobody left in a role has its carrier's, or
    its location's, again."""
    link = get_circuit_link(db, hid, link_hid)
    audit.record(db, context, "delete", CIRCUIT_TYPE, link.hid, _removal(link, CIRCUIT_FIELDS))
    db.delete(link)
    db.flush()
