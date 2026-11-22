"""Circuits: telecommunication circuits beside the inventory (D-157, D-158, P-145 to P-154).

A circuit shares what the inventory holds: its two sides are locations, its carriers
vendors, its contacts contact records, its owner an owner, the network its Z side
reaches a circuit group, and its devices items and device groups. This module holds the
rules of a circuit that the reports, the capacity balance and the records all read:
which side it counts at, the dates of each side, and when it is in service.

Each side has its dates (P-317, P-320): the A side's are `a_installed_on`,
`a_activated_on` and `a_disconnected_on`, and the Z side's, `z_installed_on` and the
rest, are each read as the A side's where blank, never copied. The dates that decide
whether a circuit is in service, the months its cost counts and whether it carries its
weight are those of the side `cost_side` names, the Z side's in force where it is `z`.
"""

from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_

from hirdir.db.models import Circuit
from hirdir.domain.inheritance import NOTHING, Effective

# The two sides: the A side, the source, and the Z side, the destination.
SIDES = ("a", "z")
# The roles of a carrier's own contacts, named on the vendor or on the circuit (P-149).
CARRIER_CONTACT_ROLES = ("account_manager", "support_contact")
# The kinds of a circuit group (P-319): a carrier's network, which a Z side may name, or
# a collection of circuits for the enterprise's own purpose.
NETWORK = "network"
COLLECTION = "collection"
GROUP_KINDS = (NETWORK, COLLECTION)
# The dates each side has, in the order they come (P-317).
DAYS = ("installed_on", "activated_on", "disconnected_on")
A_DATES = tuple(f"a_{day}" for day in DAYS)
Z_DATES = tuple(f"z_{day}" for day in DAYS)


def cost_location_hid(circuit: Circuit) -> str | None:
    """Return the location whose site the circuit's cost and weight count at.

    It is that of the side `cost_side` names, or of the other side where that one has
    no location (P-150): a Z side that names a network has none. At least one side has
    a location.
    """
    named = circuit.a_location_hid if circuit.cost_side == "a" else circuit.z_location_hid
    if named is not None:
        return named
    return circuit.z_location_hid if circuit.cost_side == "a" else circuit.a_location_hid


def cost_location_column() -> ColumnElement[str | None]:
    """Return, as SQL, the location a circuit counts at, as `cost_location_hid` does."""
    return case(
        (
            and_(Circuit.cost_side == "a", Circuit.a_location_hid.is_not(None)),
            Circuit.a_location_hid,
        ),
        (
            and_(Circuit.cost_side == "z", Circuit.z_location_hid.is_not(None)),
            Circuit.z_location_hid,
        ),
        else_=case(
            (Circuit.a_location_hid.is_not(None), Circuit.a_location_hid),
            else_=Circuit.z_location_hid,
        ),
    )


# --- the dates of each side (P-317, P-320) -------------------------------------------


def z_dates_in_force(circuit: Any) -> dict[str, Effective]:
    """Return the Z side's dates in force, by the names of its own: each its own with the
    source `own`, or the A side's of the same name with the source `a_side`, or blank
    with `none`. `circuit` is a circuit, or anything with the six dates."""
    found: dict[str, Effective] = {}
    for day in DAYS:
        own, a_side = getattr(circuit, f"z_{day}"), getattr(circuit, f"a_{day}")
        if own is not None:
            found[f"z_{day}"] = Effective(own, "own", None)
        elif a_side is not None:
            found[f"z_{day}"] = Effective(a_side, "a_side", None)
        else:
            found[f"z_{day}"] = NOTHING
    return found


def side_dates(circuit: Any, side: str) -> tuple[date | None, date | None, date | None]:
    """Return the installation, the activation and the disconnection in force of one
    side: the A side's own, or the Z side's, each its own or the A side's."""
    if side == "a":
        return circuit.a_installed_on, circuit.a_activated_on, circuit.a_disconnected_on
    found = z_dates_in_force(circuit)
    installed, activated, disconnected = (found[name].value for name in Z_DATES)
    return installed, activated, disconnected


def deciding_dates(circuit: Any) -> tuple[date | None, date | None]:
    """Return the activation and the disconnection that decide whether a circuit is in
    service: those in force of the side `cost_side` names (P-320)."""
    _, activated, disconnected = side_dates(circuit, circuit.cost_side)
    return activated, disconnected


def z_in_force_column(day: str, model: Any = Circuit) -> ColumnElement[Any]:
    """Return, as SQL, one of the Z side's dates in force: its own, or the A side's.
    `day` is `installed_on`, `activated_on` or `disconnected_on`."""
    own, a_side = getattr(model, f"z_{day}"), getattr(model, f"a_{day}")
    return func.coalesce(own, a_side, type_=own.type)


def deciding_column(day: str, model: Any = Circuit) -> ColumnElement[Any]:
    """Return, as SQL, one date in force of the side a circuit's `cost_side` names, as
    `deciding_dates` reads it."""
    return case(
        (model.cost_side == "z", z_in_force_column(day, model)),
        else_=getattr(model, f"a_{day}"),
    )


# --- in service and the weight -------------------------------------------------------


def counted_status(include_drafts: bool) -> tuple[str, ...]:
    """Return the record statuses of a circuit that a view counts."""
    return ("active", "draft") if include_drafts else ("active",)


def in_service_on(circuit: Circuit, day: date, include_drafts: bool = False) -> bool:
    """Say whether a circuit is in service on a day (P-145, P-320).

    It is on a day that is not before the activation and not after the disconnection of
    the side `cost_side` names, as they are in force, a blank being open, while it is
    active, or a draft in a view that includes drafts. A retired circuit that has a
    disconnection there was in service until then; one retired with none was taken out,
    and is in service on no day.
    """
    activated, disconnected = deciding_dates(circuit)
    if circuit.record_status == "retired":
        if disconnected is None:
            return False
    elif circuit.record_status not in counted_status(include_drafts):
        return False
    if activated is not None and day < activated:
        return False
    return not (disconnected is not None and day > disconnected)


def in_service_column(
    model: Any = Circuit, include_drafts: bool = False, day: Any = None
) -> ColumnElement[bool]:
    """Return, as SQL, whether a circuit is in service on a day, as `in_service_on` says
    it. `day` is a date, or the SQL of one."""
    activated = deciding_column("activated_on", model)
    disconnected = deciding_column("disconnected_on", model)
    return and_(
        or_(
            model.record_status.in_(counted_status(include_drafts)),
            and_(model.record_status == "retired", disconnected.is_not(None)),
        ),
        or_(activated.is_(None), activated <= day),
        or_(disconnected.is_(None), disconnected >= day),
    )


def carries_weight_column(today: date, include_drafts: bool = False) -> ColumnElement[bool]:
    """Return, as SQL, whether a circuit carries its support weight today (P-155).

    A circuit carries it while it is active, or a draft with the drafts, and the side
    `cost_side` names is not disconnected before today (P-320); an installation that
    waits for its activation is work already.
    """
    disconnected = deciding_column("disconnected_on")
    return and_(
        Circuit.record_status.in_(counted_status(include_drafts)),
        or_(disconnected.is_(None), disconnected >= today),
    )
