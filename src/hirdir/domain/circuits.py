"""Circuits: telecommunication circuits beside the inventory (D-157, D-158, P-145 to P-154).

A circuit shares what the inventory holds: its two sides are locations, its carriers
vendors, its contacts contact records, its owner an owner, and its devices items and
device groups. This module holds the rules of a circuit that the reports, the capacity
balance and the records all read: which side it counts at, and when it is in service.
"""

from datetime import date

from sqlalchemy import ColumnElement, and_, case, or_

from hirdir.db.models import Circuit

# The two sides: the A side, the source, and the Z side, the destination.
SIDES = ("a", "z")
# The roles of a carrier's own contacts, named on the vendor or on the circuit (P-149).
CARRIER_CONTACT_ROLES = ("account_manager", "support_contact")


def cost_location_hid(circuit: Circuit) -> str | None:
    """Return the location whose site the circuit's cost and weight count at.

    It is that of the side `cost_side` names, or of the other side where that one has
    no location (P-150). At least one side has a location.
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


def counted_status(include_drafts: bool) -> tuple[str, ...]:
    """Return the record statuses of a circuit that a view counts."""
    return ("active", "draft") if include_drafts else ("active",)


def in_service_on(circuit: Circuit, day: date, include_drafts: bool = False) -> bool:
    """Say whether a circuit is in service on a day (P-145).

    It is on a day that is not before its activation and not after its disconnection,
    a blank being open, while it is active, or a draft in a view that includes drafts.
    A retired circuit that has a disconnection was in service until then; one retired
    with none was taken out, and is in service on no day.
    """
    if circuit.record_status == "retired":
        if circuit.disconnected_on is None:
            return False
    elif circuit.record_status not in counted_status(include_drafts):
        return False
    if circuit.activated_on is not None and day < circuit.activated_on:
        return False
    return not (circuit.disconnected_on is not None and day > circuit.disconnected_on)


def carries_weight_column(today: date, include_drafts: bool = False) -> ColumnElement[bool]:
    """Return, as SQL, whether a circuit carries its support weight today (P-155).

    A circuit carries it while it is active, or a draft with the drafts, and is not
    disconnected before today; an installation that waits for its activation is work
    already.
    """
    return and_(
        Circuit.record_status.in_(counted_status(include_drafts)),
        or_(Circuit.disconnected_on.is_(None), Circuit.disconnected_on >= today),
    )
