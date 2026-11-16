"""Capacity lines: where resource units come from, and what calls on them beside the
infrastructure; and the records of the balance, week by week.

A supply line is a kind of position and how many, an outside service, a tool. A demand
line is work that is not the infrastructure: a project, a transition. The units of a
line that adds are its quantity times the units of one, exactly. A line that multiplies
works on staff lines instead, and its units are worked out with the balance in
`hirdir.io.balance`: `factor` less 1, times `share`, times the units of the lines it
applies to that are counted in the same view.

A record of the balance keeps the figures of one week, to show the trend. They are
worked out in `hirdir.io.balance`; here they are kept, corrected and removed.
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, null, select
from sqlalchemy.orm import Session

from hirdir.db.models import CapacityLine, CapacityLineTarget, CapacityRecord, Region, Site, Vendor
from hirdir.domain import audit, choices, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "capacity_line"
SIDES = ("supply", "demand")
SUPPLY, DEMAND = SIDES
CATEGORY_LIST = "capacity_category"
# The one category of the demand side, and the category that is the team's own positions.
OTHER_WORK = "other_work"
STAFF = "staff"
# A line adds a fixed amount, or multiplies the staff lines it applies to. Only a tool
# or a service multiplies: it makes the people who use it do more (R14.8, D-188).
EFFECTS = ("add", "multiply")
ADD, MULTIPLY = EFFECTS
MULTIPLYING_CATEGORIES = ("tools", "services")
APPLIES_TO = "applies_to"
FIELDS = (
    "side",
    "category",
    "name",
    "effect",
    "quantity",
    "units_each",
    "factor",
    "share",
    "annual_cost",
    "vendor_hid",
    "region_hid",
    "site_hid",
    "starts_on",
    "ends_on",
    "notes",
    "record_status",
)
BIGGEST = Decimal(10) ** 9
HUNDREDTH = Decimal("0.01")


def get_line(db: Session, hid: str) -> CapacityLine:
    """Return the capacity line with hid."""
    line = db.get(CapacityLine, hid)
    if line is None:
        raise NotFound(f"there is no capacity line {hid}")
    return line


def find_line(db: Session, side: str, name: str) -> CapacityLine | None:
    """Return the line of one side with a name."""
    return db.scalar(
        select(CapacityLine).where(
            CapacityLine.side == records.key(side), CapacityLine.name_key == records.key(name)
        )
    )


def units(line: CapacityLine) -> Decimal:
    """Return the resource units of a line that adds: its quantity times the units of
    one. A line that multiplies has none of its own; see `hirdir.io.balance`."""
    return (line.quantity or Decimal(0)) * (line.units_each or Decimal(0))


def multiplies(line: CapacityLine) -> bool:
    """Say whether a line multiplies the staff lines it applies to."""
    return line.effect == MULTIPLY


def can_be_multiplied(line: CapacityLine) -> bool:
    """Say whether a line is one that a line which multiplies works on: a supply line
    of the category `staff` that adds."""
    return line.side == SUPPLY and line.category == STAFF and not multiplies(line)


def in_date(line: CapacityLine, day: date) -> bool:
    """Say whether a line counts on a day: not before it starts, not after it ends."""
    return (line.starts_on is None or line.starts_on <= day) and (
        line.ends_on is None or day <= line.ends_on
    )


def targets_of(db: Session, hids: list[str]) -> dict[str, list[str]]:
    """Return, for each of the lines with hids, the HIDs of the lines it applies to."""
    found: dict[str, list[str]] = {hid: [] for hid in hids}
    if hids:
        for line_hid, target_hid in db.execute(
            select(CapacityLineTarget.line_hid, CapacityLineTarget.target_hid)
            .where(CapacityLineTarget.line_hid.in_(hids))
            .order_by(CapacityLineTarget.line_hid, CapacityLineTarget.target_hid)
        ):
            found[line_hid].append(target_hid)
    return found


def _number(name: str, value: Any) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value > BIGGEST
        or value != value.quantize(HUNDREDTH)
    ):
        raise Invalid(
            f"{name} is not acceptable",
            {name: "a number that is not negative, with at most two decimal places"},
        )
    return value


def _targets(db: Session, given: Any, line: CapacityLine | None) -> list[str]:
    """Return the staff lines a line that multiplies is to work on, checked.

    Each is a supply line of the category `staff` that adds, and not the line itself,
    and is not retired. One that the line works on already is not looked at again, as
    a reference that is left as it is: a line that has retired since gives it nothing.
    """
    if not isinstance(given, list) or not all(isinstance(hid, str) for hid in given):
        raise Invalid("applies_to is not acceptable", {APPLIES_TO: "a list of capacity lines"})
    held = set(targets_of(db, [line.hid])[line.hid]) if line is not None else set()
    hids = list(dict.fromkeys(hid.strip() for hid in given if hid.strip()))
    for hid in hids:
        if hid in held:
            continue
        if line is not None and hid == line.hid:
            raise Invalid(
                "a line does not multiply itself", {APPLIES_TO: "this is the line itself"}
            )
        target = db.get(CapacityLine, hid)
        if target is None:
            raise Invalid("there is no such line", {APPLIES_TO: f"there is no capacity line {hid}"})
        if not can_be_multiplied(target):
            raise Invalid(
                f"{target.name} is not a staff line that adds",
                {APPLIES_TO: f"{target.name} is not a supply line of the category staff that adds"},
            )
        if target.record_status == "retired":
            raise Invalid(f"{target.name} is retired", {APPLIES_TO: f"{target.name} is retired"})
    return sorted(hids)


def _effect(
    db: Session,
    fields: dict[str, Any],
    values: dict[str, Any],
    line: CapacityLine | None,
    final: Callable[[str], Any],
) -> list[str] | None:
    """Hold a line to what its effect asks of it, and return the lines it is to apply
    to, when that changes.

    A line that adds has a quantity, 1 unless said, and the units of one. A line that
    multiplies is a supply line of the category `tools` or `services`, with a factor of
    at least 1, a share from 0 to 1, 1 unless said, and at least one staff line to
    apply to; it has no quantity and no units of its own.
    """
    if final("effect") != MULTIPLY:
        for name in ("factor", "share"):
            if fields.get(name) is not None:
                raise Invalid(
                    f"a line that adds has no {name}",
                    {name: "only a line that multiplies has one: its effect is multiply"},
                )
            values[name] = None
        if fields.get(APPLIES_TO):
            raise Invalid(
                "a line that adds applies to nothing",
                {APPLIES_TO: "only a line that multiplies applies to staff lines"},
            )
        if final("quantity") is None:
            values["quantity"] = Decimal(1)
        if final("units_each") is None:
            raise Invalid(
                "units_each is not acceptable",
                {"units_each": "a number that is not negative, with at most two decimal places"},
            )
        # A line that multiplied and now adds works on nothing any more.
        return [] if line is not None and multiplies(line) else None
    if final("side") != SUPPLY or final("category") not in MULTIPLYING_CATEGORIES:
        raise Invalid(
            "only a tool or a service multiplies",
            {"effect": "multiply is for a supply line of the category tools or services"},
        )
    for name in ("quantity", "units_each"):
        if fields.get(name) is not None:
            raise Invalid(
                f"a line that multiplies has no {name}",
                {name: "blank: a line that multiplies works on the units of other lines"},
            )
        values[name] = None
    factor = final("factor")
    if factor is None or factor < 1:
        raise Invalid(
            "a line that multiplies has a factor",
            {"factor": "how much more one person does with it, at least 1"},
        )
    share = final("share")
    if share is None:
        values["share"] = share = Decimal(1)
    if share > 1:
        raise Invalid(
            "the share is not acceptable",
            {"share": "the share of the positions that use it, from 0 to 1"},
        )
    if APPLIES_TO not in fields and line is not None and multiplies(line):
        return None
    targets = _targets(db, fields.get(APPLIES_TO) or [], line)
    if not targets:
        raise Invalid(
            "a line that multiplies applies to staff lines",
            {APPLIES_TO: "at least one supply line of the category staff that adds"},
        )
    return targets


def _checked(
    db: Session, fields: dict[str, Any], line: CapacityLine | None
) -> tuple[dict[str, Any], list[str] | None]:
    """Return the values that fields give a line, checked, and the lines it is to apply
    to when that changes."""
    values: dict[str, Any] = {}
    if "side" in fields:
        side = records.checked_choice(fields["side"], SIDES, "side")
        if line is not None and side != line.side:
            raise Invalid(
                "a line stays on its side", {"side": "retire this line and enter the other"}
            )
        values["side"] = side
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None:
            raise Invalid("the name is not acceptable", {"name": "must not be blank"})
        values["name"] = name
        values["name_key"] = records.key(name)
    if "effect" in fields or line is None:
        values["effect"] = records.checked_choice(fields.get("effect") or ADD, EFFECTS, "effect")
    for name in ("quantity", "units_each", "factor", "share"):
        if name in fields:
            given = fields[name]
            values[name] = None if given is None else _number(name, given)
    if "annual_cost" in fields:
        values["annual_cost"] = records.checked_amount("annual_cost", fields["annual_cost"])
    if "vendor_hid" in fields:
        values["vendor_hid"] = records.linked(
            db, Vendor, "vendor_hid", fields["vendor_hid"], line, "vendor"
        )
    for name, model, what in (("region_hid", Region, "region"), ("site_hid", Site, "site")):
        if name in fields:
            values[name] = records.linked(db, model, name, fields[name], line, what)
    for name in ("starts_on", "ends_on"):
        if name in fields:
            values[name] = records.checked_day(name, fields[name])
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])

    def final(name: str) -> Any:
        return values.get(name, getattr(line, name) if line is not None else None)

    side = final("side")
    if "category" in fields or line is None:
        given = records.clean(fields.get("category"))
        if given is None:
            if side != DEMAND:
                raise Invalid(
                    "a supply line has a category",
                    {"category": f"a value of the {CATEGORY_LIST} list other than {OTHER_WORK}"},
                )
            given = OTHER_WORK
        category = (
            given
            if line is not None and records.key(given) == line.category
            else choices.checked(db, CATEGORY_LIST, given, "category")
        )
        if (category == OTHER_WORK) != (side == DEMAND):
            raise Invalid(
                "the category is not of this side",
                {
                    "category": f"a demand line has {OTHER_WORK}, "
                    "and a supply line any other value of the list"
                },
            )
        values["category"] = category
    targets = _effect(db, fields, values, line, final)
    if final("region_hid") and final("site_hid"):
        raise Invalid(
            "a line serves a region or a site",
            {"site_hid": "at most one of region_hid and site_hid; neither serves everywhere"},
        )
    records.checked_span(final("starts_on"), final("ends_on"))
    if "name_key" in values:
        taken = find_line(db, side, values["name"])
        if taken is not None and (line is None or taken.hid != line.hid):
            raise Conflict(
                f"there is already a {side} line {taken.name}",
                {"name": "another line of this side has this name"},
            )
    return values, targets


def _set_targets(db: Session, line: CapacityLine, targets: list[str]) -> list[dict[str, Any]]:
    """Give a line the lines it applies to. Return the change, for its audit event."""
    held = targets_of(db, [line.hid])[line.hid]
    if held == targets:
        return []
    db.execute(delete(CapacityLineTarget).where(CapacityLineTarget.line_hid == line.hid))
    db.add_all(CapacityLineTarget(line_hid=line.hid, target_hid=hid) for hid in targets)
    db.flush()
    return [change(APPLIES_TO, held or None, targets or None)]


def create_line(db: Session, context: AuditContext, fields: dict[str, Any]) -> CapacityLine:
    """Create a capacity line: a source of resource units, or other work that calls on
    them."""
    given = {"side": None, "name": None, "units_each": None, **fields}
    values, targets = _checked(db, given, None)
    line = CapacityLine(**values)
    for name in ("quantity", "units_each"):
        if values.get(name) is None:
            # A line that multiplies has neither: kept blank, and not given the
            # defaults of a line that adds, which a blank would otherwise take.
            setattr(line, name, null())
    records.created(
        db,
        context,
        RECORD_TYPE,
        line,
        FIELDS,
        then=lambda: _set_targets(db, line, targets) if targets else [],
    )
    return line


def update_line(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> CapacityLine:
    """Change a capacity line. `applies_to` of a line that multiplies is changed whole."""
    line = get_line(db, hid)
    values, targets = _checked(db, fields, line)
    applied = _set_targets(db, line, targets) if targets is not None else []
    records.apply(db, context, RECORD_TYPE, line, row_version, values, applied)
    return line


def retire_line(db: Session, context: AuditContext, hid: str, row_version: int) -> CapacityLine:
    """Retire a capacity line. It counts for nothing any more, also to a line that
    multiplies it."""
    line = get_line(db, hid)
    records.apply(
        db, context, RECORD_TYPE, line, row_version, {"record_status": "retired"}, action="retire"
    )
    return line


# --- the records of the balance ------------------------------------------------------

RECORD_OF_BALANCE = "capacity_record"
VIEWS = ("active", "with_drafts")
# The figures of a view that a record keeps, as the capacity report answered them, and
# the two of them that a person may correct.
KEPT = (
    "support_weight",
    "infrastructure_demand",
    "other_demand",
    "demand",
    "supply",
    "own_units",
    "outside_units",
)
CORRECTED = ("demand", "supply")
# The parts of the support weight, and how many items, sites and circuits counted at a
# default and were raised to a minimum: kept since 0.8.0 (P-155), and blank in a record
# of a week before it, which is read as it was kept.
WEIGHT_PARTS = ("items_weight", "places_weight", "circuits_weight")
WEIGHT_COUNTS = ("defaulted", "raised")
COUNTED_KINDS = ("items", "sites", "circuits")
RECORD_FIELDS = (
    "week_of",
    "recorded_at",
    "weight_per_resource_unit",
    "active",
    "with_drafts",
    "adjusted",
    "note",
)
BIGGEST_FIGURE = Decimal(10) ** 15


def monday_of(day: date) -> date:
    """Return the Monday that begins the week a day is in."""
    return day - timedelta(days=day.weekday())


def get_record(db: Session, hid: str) -> CapacityRecord:
    """Return the record of the balance with hid."""
    record = db.get(CapacityRecord, hid)
    if record is None:
        raise NotFound(f"there is no record of the balance {hid}")
    return record


def record_of_week(db: Session, week_of: date) -> CapacityRecord | None:
    """Return the record of the week that begins on a Monday, if there is one."""
    return db.scalar(select(CapacityRecord).where(CapacityRecord.week_of == week_of))


def figure_text(value: Decimal) -> str:
    """Write a figure as a record keeps it: plain, without zeros it does not need."""
    return records.decimal_text("", value)


def _rounded(value: Decimal) -> Decimal:
    rounded = value.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)
    return rounded if rounded else Decimal("0.00")


def figures(kept: Mapping[str, Any]) -> dict[str, Any]:
    """Return the figures of one view of a record, with the balance and the coverage
    worked out from its demand and its supply, as they are when it is read."""
    found: dict[str, Any] = {name: Decimal(str(kept.get(name) or 0)) for name in KEPT}
    for name in WEIGHT_PARTS:
        found[name] = None if kept.get(name) is None else Decimal(str(kept[name]))
    for name in WEIGHT_COUNTS:
        counted = kept.get(name)
        found[name] = (
            {kind: int(counted.get(kind) or 0) for kind in COUNTED_KINDS}
            if isinstance(counted, Mapping)
            else None
        )
    demand, supply = found["demand"], found["supply"]
    found["balance"] = _rounded(supply - demand)
    found["coverage_pct"] = _rounded(supply / demand * 100) if demand else None
    found["by_category"] = list(kept.get("by_category") or [])
    return found


def _note(value: Any) -> str | None:
    note = records.clean(value)
    if note is not None and not isinstance(note, str):
        raise Invalid("the note is not acceptable", {"note": "text"})
    return note


def keep_record(
    db: Session,
    context: AuditContext,
    *,
    week_of: date,
    recorded_at: datetime,
    weight_per_resource_unit: Decimal,
    views: Mapping[str, dict[str, Any]],
    note: Any = None,
) -> CapacityRecord:
    """Keep the balance of a week: a new record, or the one the week has, replaced.

    What a record held before is in the audit event of the change that replaced it. A
    record that is replaced is worked out anew, and is not adjusted any more.
    """
    values: dict[str, Any] = {
        "recorded_at": recorded_at,
        "weight_per_resource_unit": weight_per_resource_unit,
        "active": dict(views["active"]),
        "with_drafts": dict(views["with_drafts"]),
        "adjusted": False,
        "note": _note(note),
    }
    held = record_of_week(db, week_of)
    if held is None:
        record = CapacityRecord(week_of=week_of, **values)
        records.created(db, context, RECORD_OF_BALANCE, record, RECORD_FIELDS)
        return record
    records.apply(db, context, RECORD_OF_BALANCE, held, None, values)
    return held


def _figure(name: str, value: Any) -> Decimal:
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        number = Decimal(-1)
    if (
        isinstance(value, bool)
        or not number.is_finite()
        or number < 0
        or number >= BIGGEST_FIGURE
        or number != number.quantize(HUNDREDTH)
    ):
        raise Invalid(
            f"{name} is not acceptable",
            {name: "a number of resource units that is not negative, with two places at most"},
        )
    return number


def correct_record(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> CapacityRecord:
    """Correct the demand and the supply of a saved week, each of `active` and of
    `with_drafts`, with a note that says why. The record is then adjusted."""
    record = get_record(db, hid)
    note = _note(fields.get("note"))
    if note is None:
        raise Invalid("a correction says why", {"note": "say why the figures are corrected"})
    values: dict[str, Any] = {"note": note}
    for view in VIEWS:
        given = fields.get(view)
        if given is None:
            continue
        if not isinstance(given, Mapping):
            raise Invalid(f"{view} is not acceptable", {view: "the demand and the supply"})
        kept = dict(getattr(record, view))
        for name in CORRECTED:
            if given.get(name) is not None:
                kept[name] = figure_text(_figure(f"{view}.{name}", given[name]))
        values[view] = kept
    if any(values.get(view, getattr(record, view)) != getattr(record, view) for view in VIEWS):
        values["adjusted"] = True
    records.apply(db, context, RECORD_OF_BALANCE, record, row_version, values)
    return record


def remove_record(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a record of the balance that was a mistake. The audit event of the removal
    holds what it was."""
    record = get_record(db, hid)
    audit.record(
        db,
        context,
        "delete",
        RECORD_OF_BALANCE,
        record.hid,
        [
            change(name, records.jsonable(getattr(record, name), name), None)
            for name in RECORD_FIELDS
            if getattr(record, name) is not None
        ],
    )
    db.delete(record)
    db.flush()
