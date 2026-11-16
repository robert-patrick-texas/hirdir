"""Try: the capacity balance as other figures and other staff lines would give it,
beside the balance in force (P-141, P-156).

A Try takes any of the six weights of the settings, `weight_per_resource_unit` and
`stack_discount_pct`, each checked as its setting checks a change: a key left out is as
it is in force, and None tries the setting at its default, which for a weight is blank.
It takes staff lines to add, staff lines that are there to change, and staff lines that
are there to leave out; each line tried adds, and is active and in date in both views.
A line that multiplies works on a changed line as it is tried, on none that is left
out, and on no line that is added, since it names the lines it works on.

The balance in force is the capacity report's own, kept as the report is (P-157), since
it answers the same; the balance tried is worked out here, by the work of the report
itself, each time. Nothing is saved, nothing is written to the audit trail, and the
answer is never kept.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from hirdir.db.models import CapacityLine
from hirdir.domain import capacity, records, settings, weights
from hirdir.domain.errors import Invalid
from hirdir.io import balance

# The most a quantity or the units of one tried may be, as for a line that is saved.
BIGGEST = capacity.BIGGEST
HUNDREDTH = Decimal("0.01")


@dataclass(frozen=True)
class LineTried:
    """A staff line as it was tried: one added, with no HID, or one that is there."""

    hid: str | None
    name: str
    quantity: Decimal
    units_each: Decimal
    units: Decimal


@dataclass(frozen=True)
class LeftOut:
    """A staff line that was left out."""

    hid: str
    name: str


@dataclass(frozen=True)
class StaffAsTried:
    """The staff lines as they were tried."""

    add: list[LineTried]
    change: list[LineTried]
    leave_out: list[LeftOut]


@dataclass(frozen=True)
class Parameters:
    """What was tried: every figure as the balance tried was worked out with it, the
    staff lines, and the settings whose value tried is not the one in force."""

    default_item_weight: Decimal | None
    minimum_item_weight: Decimal | None
    default_site_weight: Decimal | None
    minimum_site_weight: Decimal | None
    default_circuit_weight: Decimal | None
    minimum_circuit_weight: Decimal | None
    stack_discount_pct: Decimal
    weight_per_resource_unit: Decimal
    staff: StaffAsTried
    changed: list[str]


@dataclass(frozen=True)
class Answer:
    """The capacity balance in force, the balance tried, and what was tried."""

    in_force: balance.Balance
    tried: balance.Balance
    parameters: Parameters


def checked_figures(base: weights.Figures, asked: Mapping[str, Any]) -> weights.Figures:
    """Return the figures to try: those in force, with each that is asked for checked
    as its setting checks a change. None is the setting's default."""
    values: dict[str, Decimal | None] = {}
    for key in weights.KEYS:
        if key not in asked:
            continue
        given = asked[key]
        spec = settings.SPECS[key]
        if given is None:
            values[key] = None if spec.default is None else Decimal(str(spec.default))
            continue
        try:
            spec.check(str(given) if isinstance(given, Decimal) else given)
        except Invalid as error:
            raise Invalid(
                f"the value of {key} is not acceptable", {key: error.fields.get("value", "")}
            ) from None
        values[key] = Decimal(str(given).strip())
    return base.with_values(values)


def _units(field: str, value: Any) -> Decimal:
    """Return a quantity or the units of one, checked as those of a line that is saved."""
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        number = Decimal(-1)
    if (
        isinstance(value, bool)
        or not number.is_finite()
        or number < 0
        or number > BIGGEST
        or number != number.quantize(HUNDREDTH)
    ):
        raise Invalid(
            f"{field} is not acceptable",
            {field: "a number that is not negative, with at most two decimal places"},
        )
    return number


def _staff_line(db: Session, hid: Any, field: str) -> CapacityLine:
    """Return a staff line that adds and is there, as a Try names it, by its HID."""
    line = db.get(CapacityLine, hid) if isinstance(hid, str) else None
    if line is None:
        raise Invalid("there is no such line", {field: f"there is no capacity line {hid}"})
    if not capacity.can_be_multiplied(line):
        raise Invalid(
            f"{line.name} is not a staff line that adds",
            {field: f"{line.name} is not a supply line of the category staff that adds"},
        )
    if line.record_status == "retired":
        raise Invalid(f"{line.name} is retired", {field: f"{line.name} is retired"})
    return line


def checked_staff(db: Session, asked: Mapping[str, Any]) -> tuple[balance.StaffTried, StaffAsTried]:
    """Return the staff lines to try, checked: as the balance takes them, and as the
    answer says what was tried. A line that is there is named once."""
    named: set[str] = set()

    def once(line: CapacityLine, field: str) -> None:
        if line.hid in named:
            raise Invalid(
                f"{line.name} is named twice", {field: f"{line.name} is changed or left out once"}
            )
        named.add(line.hid)

    changed: dict[str, CapacityLine] = {}
    change: list[LineTried] = []
    for number, one in enumerate(_listed(asked, "change")):
        field = f"staff.change.{number}"
        line = _staff_line(db, one.get("hid"), field)
        once(line, field)
        quantity = _units(
            f"{field}.quantity",
            one["quantity"] if one.get("quantity") is not None else line.quantity or Decimal(0),
        )
        units_each = _units(
            f"{field}.units_each",
            one["units_each"]
            if one.get("units_each") is not None
            else line.units_each or Decimal(0),
        )
        changed[line.hid] = balance.line_tried(
            line.hid, line.name, quantity, units_each, line.annual_cost
        )
        change.append(LineTried(line.hid, line.name, quantity, units_each, quantity * units_each))
    leave_out: list[LeftOut] = []
    for number, hid in enumerate(_listed(asked, "leave_out")):
        field = f"staff.leave_out.{number}"
        line = _staff_line(db, hid, field)
        once(line, field)
        leave_out.append(LeftOut(line.hid, line.name))
    added: list[CapacityLine] = []
    add: list[LineTried] = []
    for number, one in enumerate(_listed(asked, "add")):
        field = f"staff.add.{number}"
        name = records.clean(one.get("name"))
        if not isinstance(name, str):
            raise Invalid("a staff line has a name", {f"{field}.name": "must not be blank"})
        quantity = _units(
            f"{field}.quantity", one["quantity"] if one.get("quantity") is not None else 1
        )
        units_each = _units(f"{field}.units_each", one.get("units_each"))
        # Its own HID in the balance alone, which never names it: no line names it.
        added.append(balance.line_tried(f"tried-{number + 1}", name, quantity, units_each))
        add.append(LineTried(None, name, quantity, units_each, quantity * units_each))
    tried = balance.StaffTried(
        added=tuple(added),
        changed=changed,
        left_out=frozenset(one.hid for one in leave_out),
    )
    return tried, StaffAsTried(add=add, change=change, leave_out=leave_out)


def _listed(asked: Mapping[str, Any], name: str) -> Sequence[Any]:
    found = asked.get(name) or []
    if not isinstance(found, list | tuple):
        raise Invalid(f"staff.{name} is not acceptable", {f"staff.{name}": "a list"})
    return found


def capacity_tried(db: Session, asked: Mapping[str, Any]) -> Answer:
    """Return the capacity balance in force and the balance that what is asked would
    give, worked out as the report works it out, as of today. Nothing is saved.

    `asked` holds the figures to try, by the names of their settings, each left out to
    be as it is in force, and `staff`, with `add`, `change` and `leave_out`.
    """
    base = weights.in_force(db)
    figures = checked_figures(base, asked)
    staff, said = checked_staff(db, asked.get("staff") or {})
    in_force = balance.kept_balance(db)
    tried = balance.balance(db, in_force.as_of, figures=figures, staff=staff)
    changed = [
        key
        for key in (*weights.WEIGHT_SETTINGS, "weight_per_resource_unit", "stack_discount_pct")
        if getattr(figures, key) != getattr(base, key)
    ]
    shown = {one.name: getattr(figures, one.name) for one in fields(weights.Figures)}
    return Answer(
        in_force=in_force,
        tried=tried,
        parameters=Parameters(**shown, staff=said, changed=changed),
    )
