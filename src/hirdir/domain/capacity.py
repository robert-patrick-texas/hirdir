"""Capacity lines: where resource units come from, and what calls on them beside the
infrastructure.

A supply line is a kind of position and how many, an outside service, a tool. A demand
line is work that is not the infrastructure: a project, a transition. The units of a
line are its quantity times the units of one, exactly. The balance that the lines and
the support weight of the inventory come to is worked out in `hirdir.io.balance`.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import CapacityLine, Region, Site, Vendor
from hirdir.domain import choices, records
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "capacity_line"
SIDES = ("supply", "demand")
SUPPLY, DEMAND = SIDES
CATEGORY_LIST = "capacity_category"
# The one category of the demand side, and the category that is the team's own positions.
OTHER_WORK = "other_work"
STAFF = "staff"
FIELDS = (
    "side",
    "category",
    "name",
    "quantity",
    "units_each",
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
    """Return the resource units of a line: its quantity times the units of one."""
    return line.quantity * line.units_each


def in_date(line: CapacityLine, day: date) -> bool:
    """Say whether a line counts on a day: not before it starts, not after it ends."""
    return (line.starts_on is None or line.starts_on <= day) and (
        line.ends_on is None or day <= line.ends_on
    )


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


def _checked(db: Session, fields: dict[str, Any], line: CapacityLine | None) -> dict[str, Any]:
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
    for name in ("quantity", "units_each"):
        if name in fields:
            given = fields[name]
            if given is None:
                given = Decimal(1) if name == "quantity" else None
            values[name] = _number(name, given)
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
    return values


def create_line(db: Session, context: AuditContext, fields: dict[str, Any]) -> CapacityLine:
    """Create a capacity line: a source of resource units, or other work that calls on
    them."""
    given = {"side": None, "name": None, "units_each": None, **fields}
    line = CapacityLine(**_checked(db, given, None))
    records.created(db, context, RECORD_TYPE, line, FIELDS)
    return line


def update_line(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> CapacityLine:
    """Change a capacity line."""
    line = get_line(db, hid)
    records.apply(db, context, RECORD_TYPE, line, row_version, _checked(db, fields, line))
    return line


def retire_line(db: Session, context: AuditContext, hid: str, row_version: int) -> CapacityLine:
    """Retire a capacity line. It counts for nothing any more."""
    line = get_line(db, hid)
    records.apply(
        db, context, RECORD_TYPE, line, row_version, {"record_status": "retired"}, action="retire"
    )
    return line
