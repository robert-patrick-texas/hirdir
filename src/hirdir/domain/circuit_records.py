"""Circuits and their parts: the carriers beside the primary one, the lines of what a
carrier bills each month, and the devices a circuit connects (P-145 to P-148, P-150).

A circuit shares what the inventory holds: its sides are locations, its carriers
vendors, its owner an owner, its devices items and device groups. Nothing of theirs is
copied onto it, and what follows from them, the site a side has or the rate in force,
is worked out when the circuit is read. The rules that every part reads, which side a
circuit counts at and when it is in service, are in `hirdir.domain.circuits`.

A part, a carrier, a cost line or a device, has a version of its own and is removed
outright when it was a mistake, the audit event of the removal holding what it was.
"""

from collections.abc import Collection, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, and_, func, or_, select, type_coerce
from sqlalchemy.orm import Session

from hirdir import clock, ids
from hirdir.db import dialect
from hirdir.db.models import (
    Circuit,
    CircuitCarrier,
    CircuitCost,
    CircuitDevice,
    DeviceGroup,
    Item,
    Location,
    Owner,
    Scaled,
    Vendor,
)
from hirdir.domain import audit, choices, circuits, items, records, settings, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.inheritance import NOTHING, Effective

RECORD_TYPE = "circuit"
CARRIER_TYPE = "circuit_carrier"
COST_TYPE = "circuit_cost"
DEVICE_TYPE = "circuit_device"
TYPE_LIST = "circuit_type"
ROLE_LIST = "carrier_role"
SIDES = circuits.SIDES
RATES = ("down_mbps", "up_mbps")
SPEEDS = ("port_mbps", *RATES)
DATES = ("installed_on", "activated_on", "disconnected_on")
TEXTS = ("description", "notes", "a_note", "z_note", "billing_account", "billing_contract")
FIELDS = (
    "name",
    "enterprise_circuit_id",
    "description",
    "circuit_type",
    *SPEEDS,
    "a_location_hid",
    "a_note",
    "z_location_hid",
    "z_note",
    "cost_side",
    "carrier_hid",
    "carrier_circuit_number",
    "billing_account",
    "billing_contract",
    *DATES,
    "production",
    "support_weight",
    "owner_hid",
    "notes",
    "record_status",
)
CARRIER_FIELDS = ("circuit_hid", "vendor_hid", "role", "circuit_number", "priority", "notes")
COST_FIELDS = (
    "circuit_hid",
    "description",
    "monthly_cost",
    "vendor_hid",
    "starts_on",
    "ends_on",
    "notes",
)
DEVICE_FIELDS = ("circuit_hid", "item_hid", "group_hid", "side", "notes")
DEVICE_HOLDERS: dict[str, tuple[Any, str]] = {
    "item_hid": (Item, "item"),
    "group_hid": (DeviceGroup, "device group"),
}
MAX_PRIORITY = 1000
# The fastest port and the dearest line taken: far beyond any circuit, and within what
# a decimal of two places keeps exactly.
FASTEST = Decimal(10) ** 9
DEAREST = Decimal(10) ** 13
HUNDREDTH = Decimal("0.01")
THOUSAND = Decimal(1000)
MONTHS = 12


def today(db: Session) -> date:
    """Return today's date in the application's time zone."""
    return clock.today(settings.time_zone(db))


# --- finding a circuit ---------------------------------------------------------------


def get_circuit(db: Session, hid: str) -> Circuit:
    """Return the circuit with hid."""
    circuit = db.get(Circuit, hid)
    if circuit is None:
        raise NotFound(f"there is no circuit {hid}")
    return circuit


def known_as(db: Session, text: str, limit: int = 2) -> list[Circuit]:
    """Return the circuits known by text: an HID, an enterprise circuit ID or a name.

    Retired circuits and drafts answer too, because a record is always reachable by
    what it is known as.
    """
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(Circuit, text)
        if found is not None:
            return [found]
    wanted = records.key(text)
    return list(
        db.scalars(
            select(Circuit)
            .where(or_(Circuit.enterprise_circuit_id_key == wanted, Circuit.name_key == wanted))
            .order_by(Circuit.hid)
            .limit(limit)
        )
    )


def the_one(db: Session, text: str, field: str) -> Circuit:
    """Return the one circuit known by text, or refuse: none, or more than one, is no answer."""
    found = known_as(db, text)
    if not found:
        raise Invalid("there is no such circuit", {field: f"there is no circuit {text}"})
    if len(found) > 1:
        raise Invalid(
            f"more than one circuit answers to {text}",
            {field: f"more than one circuit answers to {text}; give the HID of the one meant"},
        )
    return found[0]


def reference_texts(db: Session, found: Sequence[Circuit]) -> dict[str, str]:
    """Return how a file names each of the circuits, so that the text finds it alone: the
    enterprise circuit ID where there is one, then the name, and the HID where another
    circuit answers to the same text or the text has the form of an HID."""
    texts = {circuit.hid: circuit.enterprise_circuit_id or circuit.name for circuit in found}
    keys = sorted({records.key(text) for text in texts.values()})
    answering: dict[str, set[str]] = {key: set() for key in keys}
    for start in range(0, len(keys), 500):
        piece = keys[start : start + 500]
        rows = db.execute(
            select(Circuit.hid, Circuit.enterprise_circuit_id_key, Circuit.name_key).where(
                or_(
                    Circuit.enterprise_circuit_id_key.in_(piece),
                    Circuit.name_key.in_(piece),
                )
            )
        )
        for hid, ecid, name in rows:
            for known in (ecid, name):
                if known in answering:
                    answering[known].add(hid)

    def alone(hid: str, text: str) -> bool:
        return answering[records.key(text)] == {hid} and not ids.is_hid(text.strip())

    return {hid: text if alone(hid, text) else hid for hid, text in texts.items()}


def by_carrier_number(db: Session, vendor_hid: str, number: str) -> list[Circuit]:
    """Return the circuits a carrier gives a number, as their primary or as another."""
    wanted = records.key(number)
    listed = select(CircuitCarrier.circuit_hid).where(
        CircuitCarrier.vendor_hid == vendor_hid, CircuitCarrier.circuit_number_key == wanted
    )
    return list(
        db.scalars(
            select(Circuit)
            .where(
                or_(
                    and_(Circuit.carrier_hid == vendor_hid, Circuit.carrier_number_key == wanted),
                    Circuit.hid.in_(listed),
                )
            )
            .order_by(Circuit.hid)
            .limit(2)
        )
    )


def by_name(db: Session, name: str) -> list[Circuit]:
    """Return the circuits that are not retired and have a name, two at most."""
    return list(
        db.scalars(
            select(Circuit)
            .where(Circuit.name_key == records.key(name), Circuit.record_status != "retired")
            .order_by(Circuit.hid)
            .limit(2)
        )
    )


def by_enterprise_id(db: Session, text: str) -> Circuit | None:
    """Return the circuit with an enterprise circuit ID."""
    return db.scalar(select(Circuit).where(Circuit.enterprise_circuit_id_key == records.key(text)))


# --- what is worked out when a circuit is read ---------------------------------------


def _plain(number: Decimal) -> str:
    return format(number.normalize(), "f")


def _short(mbps: Decimal) -> str:
    """Write a speed short: a multiple of 1,000 in G, one below 1 in k, the rest in M."""
    if mbps >= THOUSAND and mbps % THOUSAND == 0:
        return f"{_plain(mbps / THOUSAND)}G"
    if mbps < 1:
        return f"{_plain(mbps * THOUSAND)}k"
    return f"{_plain(mbps)}M"


def speed(circuit: Circuit) -> str | None:
    """Return the speed of a circuit written short (P-146): `1G` for a port of 1,000 at its
    full rate, `1G / 200M` for one limited to 200 both ways, `1G / 200M / 20M` for 200
    down and 20 up. A circuit with no port speed has none."""
    port = circuit.port_mbps
    if port is None:
        return None
    down = port if circuit.down_mbps is None else circuit.down_mbps
    up = port if circuit.up_mbps is None else circuit.up_mbps
    if down == port and up == port:
        return _short(port)
    if down == up:
        return f"{_short(port)} / {_short(down)}"
    return f"{_short(port)} / {_short(down)} / {_short(up)}"


def rates_in_force(circuit: Circuit) -> dict[str, Effective]:
    """Return the rate in force each way: its own, or the full rate of its port, with the
    source `port`. A circuit with neither has none."""
    found: dict[str, Effective] = {}
    for name in RATES:
        own = getattr(circuit, name)
        if own is not None:
            found[name] = Effective(own, "own", None)
        elif circuit.port_mbps is not None:
            found[name] = Effective(circuit.port_mbps, "port", None)
        else:
            found[name] = NOTHING
    return found


def in_date(line: CircuitCost, day: date) -> bool:
    """Say whether a cost line is billed on a day: not before it starts, not after it ends."""
    return (line.starts_on is None or line.starts_on <= day) and (
        line.ends_on is None or day <= line.ends_on
    )


def monthly_cost(lines: Sequence[CircuitCost], day: date) -> Decimal:
    """Return what the lines billed on a day add up to: a circuit's monthly cost."""
    return sum((line.monthly_cost for line in lines if in_date(line, day)), Decimal("0.00"))


def in_service_column(
    model: Any = Circuit, include_drafts: bool = False, day: Any = None
) -> ColumnElement[bool]:
    """Return, as SQL, whether a circuit is in service on a day, today unless given, as
    `hirdir.domain.circuits.in_service_on` says it."""
    when = dialect.today() if day is None else day
    return and_(
        or_(
            model.record_status.in_(circuits.counted_status(include_drafts)),
            and_(model.record_status == "retired", model.disconnected_on.is_not(None)),
        ),
        or_(model.activated_on.is_(None), model.activated_on <= when),
        or_(model.disconnected_on.is_(None), model.disconnected_on >= when),
    )


def line_in_date_column(line: Any = CircuitCost, day: Any = None) -> ColumnElement[bool]:
    """Return, as SQL, whether a cost line is billed on a day, today unless given."""
    when = dialect.today() if day is None else day
    return and_(
        or_(line.starts_on.is_(None), line.starts_on <= when),
        or_(line.ends_on.is_(None), line.ends_on >= when),
    )


def hundredths_of_lines() -> ColumnElement[Any]:
    """Return, as SQL, the sum of the monthly cost of the lines a statement reads, in
    hundredths, and nought where there is none."""
    return func.coalesce(func.sum(type_coerce(CircuitCost.monthly_cost, BigInteger)), 0)


def as_money(hundredths: Any, times: int = 1) -> ColumnElement[Any]:
    """Return, as SQL, a whole number of hundredths times a number, as an amount."""
    whole = type_coerce(hundredths, BigInteger)
    return type_coerce(whole * times if times != 1 else whole, Scaled(2))


def lines_of(db: Session, hids: Collection[str]) -> dict[str, list[CircuitCost]]:
    """Return the cost lines of each circuit, by description."""
    found: dict[str, list[CircuitCost]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    for start in range(0, len(wanted), 500):
        for line in db.scalars(
            select(CircuitCost)
            .where(CircuitCost.circuit_hid.in_(wanted[start : start + 500]))
            .order_by(CircuitCost.description_key, CircuitCost.hid)
        ):
            found[line.circuit_hid].append(line)
    return found


def carriers_of(db: Session, hids: Collection[str]) -> dict[str, list[CircuitCarrier]]:
    """Return the carriers of each circuit beside its primary one, by priority."""
    found: dict[str, list[CircuitCarrier]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    for start in range(0, len(wanted), 500):
        for link in db.scalars(
            select(CircuitCarrier)
            .where(CircuitCarrier.circuit_hid.in_(wanted[start : start + 500]))
            .order_by(CircuitCarrier.priority, CircuitCarrier.hid)
        ):
            found[link.circuit_hid].append(link)
    return found


def devices_of(db: Session, hids: Collection[str]) -> dict[str, list[CircuitDevice]]:
    """Return the devices each circuit connects, the A side first."""
    found: dict[str, list[CircuitDevice]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    for start in range(0, len(wanted), 500):
        for link in db.scalars(
            select(CircuitDevice)
            .where(CircuitDevice.circuit_hid.in_(wanted[start : start + 500]))
            .order_by(CircuitDevice.side, CircuitDevice.created_at, CircuitDevice.hid)
        ):
            found[link.circuit_hid].append(link)
    return found


def connections_of(
    db: Session, field: str, hids: Collection[str]
) -> dict[str, list[tuple[CircuitDevice, Circuit]]]:
    """Return the circuits each item, or each device group, is connected to, by name.

    `field` is `item_hid` or `group_hid`. A retired circuit is listed too: the record of
    a device says where it was connected, and the circuit says that it is retired.
    """
    found: dict[str, list[tuple[CircuitDevice, Circuit]]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    column = getattr(CircuitDevice, field)
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(CircuitDevice, Circuit)
            .join(Circuit, Circuit.hid == CircuitDevice.circuit_hid)
            .where(column.in_(wanted[start : start + 500]))
            .order_by(Circuit.name_key, Circuit.hid)
        )
        for link, circuit in rows:
            found[getattr(link, field)].append((link, circuit))
    return found


# --- checking a circuit --------------------------------------------------------------


def _mbps(name: str, value: Any) -> Decimal | None:
    """Return a speed in Mbps: more than zero, with at most two decimal places."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= 0
        or value >= FASTEST
        or value != value.quantize(HUNDREDTH)
    ):
        raise Invalid(
            f"{name} is not acceptable",
            {name: "a number of Mbps more than zero, with at most two decimal places"},
        )
    return value


def _weight(value: Any) -> Decimal | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value >= DEAREST
        or value != value.quantize(HUNDREDTH)
    ):
        raise Invalid(
            "support_weight is not acceptable",
            {"support_weight": "a number that is not negative, with at most two decimal places"},
        )
    return value


def _money(name: str, value: Any) -> Decimal:
    """Return an amount of money a month: below zero for a credit."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or abs(value) >= DEAREST
        or value != value.quantize(HUNDREDTH)
    ):
        raise Invalid(
            f"{name} is not acceptable",
            {name: "an amount with at most two decimal places; below zero for a credit"},
        )
    return value


def _choice(db: Session, list_name: str, value: Any, field: str, held: str | None) -> str | None:
    """Return a value of an editable list, as the list spells it. One a record holds
    already is kept as it is, so that a value made inactive since stays where it is."""
    given = records.clean(value)
    if given is None:
        return None
    if not isinstance(given, str):
        raise Invalid(f"{field} is not acceptable", {field: f"a value of the {list_name} list"})
    if held is not None and records.key(given) == held:
        return held
    return choices.checked(db, list_name, given, field)


def _twin_enterprise_id(db: Session, key: str, own: str | None) -> None:
    twin = db.scalar(
        select(Circuit).where(Circuit.enterprise_circuit_id_key == key, Circuit.hid != (own or ""))
    )
    if twin is not None:
        raise Conflict(
            f"there is already a circuit with the enterprise circuit ID "
            f"{twin.enterprise_circuit_id}: {twin.hid}",
            {"enterprise_circuit_id": "another circuit has this enterprise circuit ID"},
        )


def check_number(
    db: Session,
    vendor_hid: str,
    key: str,
    field: str,
    circuit_hid: str | None = None,
    link_hid: str | None = None,
) -> None:
    """Refuse a carrier's number that the carrier gives another circuit, as its primary
    or as another, without regard to case (P-148).

    `circuit_hid` is the circuit whose primary number this is, and `link_hid` the
    carrier of a circuit whose number this is: neither is a twin of itself. The caller
    holds the one writer's place, so that nobody gives the number away meanwhile.
    """
    primary = db.scalar(
        select(Circuit).where(
            Circuit.carrier_hid == vendor_hid,
            Circuit.carrier_number_key == key,
            Circuit.hid != (circuit_hid or ""),
        )
    )
    listed = db.scalar(
        select(CircuitCarrier).where(
            CircuitCarrier.vendor_hid == vendor_hid,
            CircuitCarrier.circuit_number_key == key,
            CircuitCarrier.hid != (link_hid or ""),
        )
    )
    other = primary.hid if primary is not None else listed.circuit_hid if listed else None
    if other is not None:
        raise Conflict(
            f"this carrier gives circuit {other} this number already",
            {field: "the carrier gives another circuit this number"},
        )


def _vendors_named(db: Session, circuit_hid: str, but: str | None = None) -> set[str]:
    """Return the vendors a circuit names as its other carriers."""
    return set(
        db.scalars(
            select(CircuitCarrier.vendor_hid).where(
                CircuitCarrier.circuit_hid == circuit_hid, CircuitCarrier.hid != (but or "")
            )
        )
    )


def _lines_naming(db: Session, circuit_hid: str, vendor_hid: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(CircuitCost)
            .where(CircuitCost.circuit_hid == circuit_hid, CircuitCost.vendor_hid == vendor_hid)
        )
        or 0
    )


def _checked(db: Session, fields: dict[str, Any], circuit: Circuit | None) -> dict[str, Any]:
    """Return the values to store for fields, checked against the circuit as it will be."""
    values: dict[str, Any] = {}
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None:
            raise Invalid("the name is not acceptable", {"name": "must not be blank"})
        values["name"], values["name_key"] = name, records.key(name)
    if "enterprise_circuit_id" in fields:
        given = records.clean(fields["enterprise_circuit_id"])
        values["enterprise_circuit_id"] = given
        values["enterprise_circuit_id_key"] = records.key(given) if given else None
    for name in TEXTS:
        if name in fields:
            values[name] = records.clean(fields[name])
    if "circuit_type" in fields:
        held = circuit.circuit_type if circuit is not None else None
        values["circuit_type"] = _choice(
            db, TYPE_LIST, fields["circuit_type"], "circuit_type", held
        )
    for name in SPEEDS:
        if name in fields:
            values[name] = _mbps(name, fields[name])
    for side in SIDES:
        field = f"{side}_location_hid"
        if field in fields:
            if fields[field] and (circuit is None or getattr(circuit, field) != fields[field]):
                # Checked against the location, which is retired only while no circuit
                # has a side there: nobody may be retiring it between the look and the write.
                dialect.hold_other_writers(db)
            values[field] = records.linked(db, Location, field, fields[field], circuit, "location")
    if "cost_side" in fields:
        values["cost_side"] = records.checked_choice(fields["cost_side"], SIDES, "cost_side")
    if "carrier_hid" in fields:
        values["carrier_hid"] = records.linked(
            db, Vendor, "carrier_hid", fields["carrier_hid"], circuit, "vendor"
        )
    if "carrier_circuit_number" in fields:
        number = records.clean(fields["carrier_circuit_number"])
        values["carrier_circuit_number"] = number
        values["carrier_number_key"] = records.key(number) if number else None
    for name in DATES:
        if name in fields:
            values[name] = records.checked_day(name, fields[name])
    if "production" in fields:
        if not isinstance(fields["production"], bool):
            raise Invalid("production is not acceptable", {"production": "true or false"})
        values["production"] = fields["production"]
    if "support_weight" in fields:
        values["support_weight"] = _weight(fields["support_weight"])
    if "owner_hid" in fields:
        values["owner_hid"] = records.linked(
            db, Owner, "owner_hid", fields["owner_hid"], circuit, "owner"
        )
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])

    def final(name: str) -> Any:
        return values.get(name, getattr(circuit, name) if circuit is not None else None)

    _check_whole(db, values, circuit, final)
    return values


def _check_whole(db: Session, values: dict[str, Any], circuit: Circuit | None, final: Any) -> None:
    """Hold a circuit as it will be to the rules that tie its fields together."""
    if final("a_location_hid") is None and final("z_location_hid") is None:
        why = "at least one side of a circuit is a location"
        raise Invalid(why, {"a_location_hid": why, "z_location_hid": why})
    for side in SIDES:
        if final(f"{side}_location_hid") is None and final(f"{side}_note") is None:
            raise Invalid(
                f"the {side.upper()} side says where it ends",
                {f"{side}_note": "a side with no location has a note of where it ends"},
            )
    port = final("port_mbps")
    for rate in RATES:
        given = final(rate)
        if given is not None and port is None:
            raise Invalid(f"{rate} needs the port speed", {rate: "a rate needs port_mbps"})
        if given is not None and given > port:
            raise Invalid(f"{rate} is above the port speed", {rate: "not more than port_mbps"})
    installed, activated, disconnected = (final(name) for name in DATES)
    if installed is not None and activated is not None and activated < installed:
        raise Invalid(
            "the dates are not acceptable",
            {"activated_on": "must not be before the day it was installed"},
        )
    began = activated if activated is not None else installed
    if began is not None and disconnected is not None and disconnected < began:
        raise Invalid(
            "the dates are not acceptable",
            {"disconnected_on": "must not be before the day it was activated, or installed"},
        )
    carrier = final("carrier_hid")
    if final("carrier_circuit_number") is not None and carrier is None:
        raise Invalid(
            "a carrier's number needs its carrier",
            {"carrier_circuit_number": "the number a carrier gives needs carrier_hid"},
        )
    own = circuit.hid if circuit is not None else None
    if values.get("enterprise_circuit_id_key"):
        dialect.hold_other_writers(db)
        _twin_enterprise_id(db, values["enterprise_circuit_id_key"], own)
    changed_carrier = "carrier_hid" in values and (
        circuit is None or circuit.carrier_hid != values["carrier_hid"]
    )
    if circuit is not None and changed_carrier:
        if carrier is not None and carrier in _vendors_named(db, circuit.hid):
            raise Conflict(
                "this vendor is a carrier of the circuit already",
                {"carrier_hid": "a vendor is named once on a circuit, the primary among them"},
            )
        if circuit.carrier_hid is not None and _lines_naming(db, circuit.hid, circuit.carrier_hid):
            raise Invalid(
                "a cost line names the carrier that would be replaced",
                {
                    "carrier_hid": "a cost line is billed by the primary carrier by name; "
                    "give it another carrier, or a blank one, first"
                },
            )
    key = final("carrier_number_key")
    if key and carrier and (changed_carrier or "carrier_number_key" in values):
        dialect.hold_other_writers(db)
        check_number(db, carrier, key, "carrier_circuit_number", circuit_hid=own)
    brought_back = (
        circuit is not None
        and circuit.record_status == "retired"
        and values.get("record_status") in ("draft", "active")
    )
    if brought_back:
        dialect.hold_other_writers(db)
        for side in SIDES:
            location = db.get(Location, final(f"{side}_location_hid") or "")
            if location is not None and location.record_status == "retired":
                raise Invalid(
                    f"{location.name}, where the {side.upper()} side is, is retired",
                    {"record_status": "give that side another location, or none, with the change"},
                )


# --- changing a circuit --------------------------------------------------------------


def create_circuit(db: Session, context: AuditContext, fields: dict[str, Any]) -> Circuit:
    """Create a circuit. One that names no side to count at is given the setting's."""
    labels = fields.pop("tags", None) or []
    given = {"name": None, "a_location_hid": None, "z_location_hid": None, **fields}
    if given.get("cost_side") is None:
        # The one value a setting gives once, when the circuit is made (P-150).
        given["cost_side"] = settings.value(db, "circuit_cost_side")
    if given.get("production") is None:
        given["production"] = True
    circuit = Circuit(**_checked(db, given, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        circuit,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, circuit.hid, labels),
    )
    return circuit


def update_circuit(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Circuit:
    """Change a circuit. A change of the setting `circuit_cost_side` changes no circuit."""
    circuit = get_circuit(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, circuit)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, circuit, row_version, values, tag_change)
    return circuit


def retire_circuit(db: Session, context: AuditContext, hid: str, row_version: int) -> Circuit:
    """Retire a circuit. Its parts and its groups stay on record, and it takes no new part."""
    circuit = get_circuit(db, hid)
    records.apply(
        db,
        context,
        RECORD_TYPE,
        circuit,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return circuit


# --- the parts of a circuit ----------------------------------------------------------


def _open(db: Session, hid: str) -> Circuit:
    """Return a circuit that may take a new part: one that is not retired."""
    circuit = get_circuit(db, hid)
    if circuit.record_status == "retired":
        raise Invalid(
            "the circuit is retired",
            {"circuit_hid": "a retired circuit takes no new part; bring it back first"},
        )
    return circuit


def _priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PRIORITY:
        raise Invalid(
            "the priority is not acceptable",
            {"priority": f"a whole number from 1, the first listed, to {MAX_PRIORITY}"},
        )
    return value


def _stays(part: Any, fields: dict[str, Any], names: Sequence[str], what: str) -> None:
    """Refuse a change of what a part of a circuit is of: it stays with it."""
    for name in names:
        if name in fields and (fields[name] or None) != getattr(part, name):
            raise Invalid(
                f"a {what} stays with what it is of",
                {name: f"remove this {what} and add the other in its place"},
            )


def _removed(db: Session, context: AuditContext, record_type: str, part: Any, names: Any) -> None:
    """Remove a part outright, with an audit event that holds what it was."""
    audit.record(
        db,
        context,
        "delete",
        record_type,
        part.hid,
        [
            change(name, records.jsonable(getattr(part, name), name), None)
            for name in names
            if getattr(part, name) is not None
        ],
    )
    db.delete(part)
    db.flush()


# --- carriers ------------------------------------------------------------------------


def get_carrier(db: Session, circuit_hid: str, link_hid: str) -> CircuitCarrier:
    """Return one carrier of one circuit."""
    get_circuit(db, circuit_hid)
    link = db.get(CircuitCarrier, link_hid)
    if link is None or link.circuit_hid != circuit_hid:
        raise NotFound(f"there is no carrier {link_hid} of this circuit")
    return link


def _carrier_vendor(db: Session, circuit: Circuit, value: Any, but: str | None) -> str:
    """Return the vendor a carrier of a circuit is to be: one there is, named once on
    the circuit, its primary among them."""
    hid = records.linked(db, Vendor, "vendor_hid", value, None, "vendor")
    if hid is None:
        raise Invalid("a carrier is a vendor", {"vendor_hid": "must not be blank"})
    if hid == circuit.carrier_hid or hid in _vendors_named(db, circuit.hid, but):
        raise Conflict(
            "this vendor is a carrier of the circuit already",
            {"vendor_hid": "a vendor is named once on a circuit, the primary among them"},
        )
    return hid


def add_carrier(
    db: Session, context: AuditContext, circuit_hid: str, fields: dict[str, Any]
) -> CircuitCarrier:
    """Name a carrier of a circuit beside its primary one, in its part, with the number
    it gives the circuit. Left out, its priority is one more than the highest."""
    # Checked against the carriers of every circuit, so nobody may be changing them.
    dialect.hold_other_writers(db)
    circuit = _open(db, circuit_hid)
    vendor_hid = _carrier_vendor(db, circuit, fields.get("vendor_hid"), None)
    role = _choice(db, ROLE_LIST, fields.get("role"), "role", None)
    if role is None:
        raise Invalid("a carrier has a part", {"role": f"a value of the {ROLE_LIST} list"})
    number = records.clean(fields.get("circuit_number"))
    key = records.key(number) if number else None
    if key:
        check_number(db, vendor_hid, key, "circuit_number")
    beside = carriers_of(db, [circuit.hid])[circuit.hid]
    priority = (
        _priority(fields["priority"])
        if fields.get("priority") is not None
        else min(1 + max((other.priority for other in beside), default=0), MAX_PRIORITY)
    )
    link = CircuitCarrier(
        circuit_hid=circuit.hid,
        vendor_hid=vendor_hid,
        role=role,
        circuit_number=number,
        circuit_number_key=key,
        priority=priority,
        notes=records.clean(fields.get("notes")),
    )
    records.created(db, context, CARRIER_TYPE, link, CARRIER_FIELDS)
    return link


def update_carrier(
    db: Session,
    context: AuditContext,
    circuit_hid: str,
    link_hid: str,
    row_version: int | None,
    fields: dict[str, Any],
) -> CircuitCarrier:
    """Change a carrier of a circuit: the vendor, its part, its number, its place in the
    list or its notes. It stays with its circuit."""
    dialect.hold_other_writers(db)
    link = get_carrier(db, circuit_hid, link_hid)
    circuit = get_circuit(db, circuit_hid)
    _stays(link, fields, ("circuit_hid",), "carrier")
    values: dict[str, Any] = {}
    if "vendor_hid" in fields and fields["vendor_hid"] != link.vendor_hid:
        if _lines_naming(db, circuit.hid, link.vendor_hid):
            raise Invalid(
                "a cost line names this carrier",
                {"vendor_hid": "a cost line is billed by this carrier; give it another first"},
            )
        values["vendor_hid"] = _carrier_vendor(db, circuit, fields["vendor_hid"], link.hid)
    if "role" in fields:
        role = _choice(db, ROLE_LIST, fields["role"], "role", link.role)
        if role is None:
            raise Invalid("a carrier has a part", {"role": f"a value of the {ROLE_LIST} list"})
        values["role"] = role
    if "circuit_number" in fields:
        number = records.clean(fields["circuit_number"])
        values["circuit_number"] = number
        values["circuit_number_key"] = records.key(number) if number else None
    if fields.get("priority") is not None:
        values["priority"] = _priority(fields["priority"])
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    vendor_hid = values.get("vendor_hid", link.vendor_hid)
    key = values.get("circuit_number_key", link.circuit_number_key)
    if key and (vendor_hid != link.vendor_hid or key != link.circuit_number_key):
        check_number(db, vendor_hid, key, "circuit_number", link_hid=link.hid)
    records.apply(db, context, CARRIER_TYPE, link, row_version, values)
    return link


def remove_carrier(db: Session, context: AuditContext, circuit_hid: str, link_hid: str) -> None:
    """Remove a carrier of a circuit that was a mistake. One that a cost line names is
    not removed while the line names it."""
    dialect.hold_other_writers(db)
    link = get_carrier(db, circuit_hid, link_hid)
    named = _lines_naming(db, circuit_hid, link.vendor_hid)
    if named:
        raise Conflict(
            f"{named} cost {'line names' if named == 1 else 'lines name'} this carrier; "
            "give them another carrier, or remove them, first",
            {"vendor_hid": "a cost line is billed by this carrier"},
        )
    _removed(db, context, CARRIER_TYPE, link, CARRIER_FIELDS)


# --- cost lines ----------------------------------------------------------------------


def get_cost(db: Session, circuit_hid: str, line_hid: str) -> CircuitCost:
    """Return one cost line of one circuit."""
    get_circuit(db, circuit_hid)
    line = db.get(CircuitCost, line_hid)
    if line is None or line.circuit_hid != circuit_hid:
        raise NotFound(f"there is no cost line {line_hid} of this circuit")
    return line


def find_cost(db: Session, circuit_hid: str, description: str) -> CircuitCost | None:
    """Return the line of a circuit with a description."""
    return db.scalar(
        select(CircuitCost).where(
            CircuitCost.circuit_hid == circuit_hid,
            CircuitCost.description_key == records.key(description),
        )
    )


def _checked_cost(
    db: Session, circuit: Circuit, fields: dict[str, Any], line: CircuitCost | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "description" in fields:
        description = records.clean(fields["description"])
        if description is None:
            raise Invalid("a cost line has a description", {"description": "must not be blank"})
        twin = find_cost(db, circuit.hid, description)
        if twin is not None and (line is None or twin.hid != line.hid):
            raise Conflict(
                f"the circuit has a line {twin.description} already",
                {"description": "another line of this circuit has this description"},
            )
        values["description"], values["description_key"] = description, records.key(description)
    if "monthly_cost" in fields:
        if fields["monthly_cost"] is None:
            raise Invalid("a cost line has a monthly cost", {"monthly_cost": "must not be blank"})
        values["monthly_cost"] = _money("monthly_cost", fields["monthly_cost"])
    if "vendor_hid" in fields:
        hid = fields["vendor_hid"] or None
        carriers = {circuit.carrier_hid, *_vendors_named(db, circuit.hid)} - {None}
        if hid is not None and (line is None or hid != line.vendor_hid) and hid not in carriers:
            raise Invalid(
                "the vendor is not a carrier of the circuit",
                {
                    "vendor_hid": f"{hid} is neither the circuit's primary carrier nor one "
                    "of its other carriers; blank is the primary carrier"
                },
            )
        values["vendor_hid"] = hid
    for name in ("starts_on", "ends_on"):
        if name in fields:
            values[name] = records.checked_day(name, fields[name])
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    starts = values.get("starts_on", line.starts_on if line is not None else None)
    ends = values.get("ends_on", line.ends_on if line is not None else None)
    records.checked_span(starts, ends)
    return values


def add_cost(
    db: Session, context: AuditContext, circuit_hid: str, fields: dict[str, Any]
) -> CircuitCost:
    """Add a line of what a carrier bills for a circuit each month. A credit is below zero."""
    # Checked against the other lines and the carriers of the circuit.
    dialect.hold_other_writers(db)
    circuit = _open(db, circuit_hid)
    given = {"description": None, "monthly_cost": None, **fields}
    line = CircuitCost(circuit_hid=circuit.hid, **_checked_cost(db, circuit, given, None))
    records.created(db, context, COST_TYPE, line, COST_FIELDS)
    return line


def update_cost(
    db: Session,
    context: AuditContext,
    circuit_hid: str,
    line_hid: str,
    row_version: int | None,
    fields: dict[str, Any],
) -> CircuitCost:
    """Change a cost line. One that was billed for a time is given an end."""
    dialect.hold_other_writers(db)
    line = get_cost(db, circuit_hid, line_hid)
    _stays(line, fields, ("circuit_hid",), "cost line")
    circuit = get_circuit(db, circuit_hid)
    records.apply(
        db, context, COST_TYPE, line, row_version, _checked_cost(db, circuit, fields, line)
    )
    return line


def remove_cost(db: Session, context: AuditContext, circuit_hid: str, line_hid: str) -> None:
    """Remove a cost line that was a mistake. The audit event holds what it was."""
    _removed(db, context, COST_TYPE, get_cost(db, circuit_hid, line_hid), COST_FIELDS)


# --- devices -------------------------------------------------------------------------


def get_device(db: Session, circuit_hid: str, link_hid: str) -> CircuitDevice:
    """Return one device of one circuit."""
    get_circuit(db, circuit_hid)
    link = db.get(CircuitDevice, link_hid)
    if link is None or link.circuit_hid != circuit_hid:
        raise NotFound(f"there is no device {link_hid} of this circuit")
    return link


def find_device(db: Session, circuit_hid: str, field: str, hid: str) -> CircuitDevice | None:
    """Return the connection of one item, or one group, to one circuit."""
    return db.scalar(
        select(CircuitDevice).where(
            CircuitDevice.circuit_hid == circuit_hid, getattr(CircuitDevice, field) == hid
        )
    )


def _holder(given: dict[str, Any]) -> tuple[str, Any, str]:
    named = [name for name in DEVICE_HOLDERS if given.get(name)]
    if len(named) != 1:
        raise Invalid(
            "a device is one item or one device group",
            dict.fromkeys(named or DEVICE_HOLDERS, "exactly one of item_hid and group_hid"),
        )
    model, what = DEVICE_HOLDERS[named[0]]
    return named[0], model, what


def add_devices(
    db: Session, context: AuditContext, circuit_hid: str, devices: Sequence[dict[str, Any]]
) -> list[CircuitDevice]:
    """Connect items and device groups to a circuit, each on a side, all together.

    A device is connected to a circuit once, and a retired one is connected to nothing
    new.
    """
    dialect.hold_other_writers(db)
    circuit = _open(db, circuit_hid)
    if not devices:
        raise Invalid("there is nothing to connect", {"devices": "name at least one device"})
    if len(devices) > settings.MOST_ITEMS_PER_REQUEST:
        raise Invalid(
            "too many devices at once",
            {"devices": f"at most {settings.MOST_ITEMS_PER_REQUEST:,} in one request"},
        )
    made: list[CircuitDevice] = []
    taken: set[tuple[str, str]] = set()
    for given in devices:
        field, model, what = _holder(given)
        hid = given[field]
        holder = db.get(model, hid) if isinstance(hid, str) else None
        if holder is None:
            raise Invalid(f"there is no such {what}", {field: f"there is no {what} {hid}"})
        if holder.record_status == "retired":
            raise Invalid(f"the {what} is retired", {field: f"this {what} is retired"})
        if (field, hid) in taken or find_device(db, circuit.hid, field, hid) is not None:
            raise Conflict(
                f"this {what} is connected to the circuit already",
                {field: f"a {what} is connected to a circuit once"},
            )
        taken.add((field, hid))
        link = CircuitDevice(
            circuit_hid=circuit.hid,
            **{field: hid},
            side=records.checked_choice(given.get("side"), SIDES, "side"),
            notes=records.clean(given.get("notes")),
        )
        records.created(db, context, DEVICE_TYPE, link, DEVICE_FIELDS)
        made.append(link)
    return made


def update_device(
    db: Session,
    context: AuditContext,
    circuit_hid: str,
    link_hid: str,
    row_version: int | None,
    fields: dict[str, Any],
) -> CircuitDevice:
    """Change the side of a device of a circuit, or its notes. The device stays."""
    link = get_device(db, circuit_hid, link_hid)
    _stays(link, fields, ("circuit_hid", *DEVICE_HOLDERS), "device")
    values: dict[str, Any] = {}
    if "side" in fields:
        values["side"] = records.checked_choice(fields["side"], SIDES, "side")
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    records.apply(db, context, DEVICE_TYPE, link, row_version, values)
    return link


def remove_device(db: Session, context: AuditContext, circuit_hid: str, link_hid: str) -> None:
    """Remove a device of a circuit that was a mistake, or that was taken out."""
    _removed(db, context, DEVICE_TYPE, get_device(db, circuit_hid, link_hid), DEVICE_FIELDS)


def hand_over(db: Session, context: AuditContext, old_hid: str, new_hid: str) -> None:
    """Give the item that took another's place the circuits that item was connected to,
    on the same side, in the change that replaces it (P-147).

    The connections of a retired circuit stay as they were: such a circuit takes no new
    part. Where the new item is connected to the circuit already, the old item's
    connection is removed, since a device is connected to a circuit once.
    """
    for link, circuit in connections_of(db, "item_hid", [old_hid])[old_hid]:
        if circuit.record_status == "retired":
            continue
        if find_device(db, circuit.hid, "item_hid", new_hid) is not None:
            _removed(db, context, DEVICE_TYPE, link, DEVICE_FIELDS)
            continue
        records.apply(db, context, DEVICE_TYPE, link, None, {"item_hid": new_hid})


def shown_name(holder: Any) -> str:
    """Return what a device of a circuit is called: an item's name, a group's name."""
    if isinstance(holder, Item):
        return items.shown_name(holder)
    return holder.name
