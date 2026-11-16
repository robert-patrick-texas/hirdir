"""What circuits cost, by fiscal year (P-151).

The report is of one fiscal year. Each cost line of a circuit counts its monthly cost
for each month of the year in which it is billed: a whole month in full, and a month
that the line's dates and the circuit's service share only in part for the days they
share, the monthly cost times those days over the days of the month, as the carrier
bills it. Beside the year's cost are the monthly figure on the day the report is of and
twelve times that, since support costs are tracked as annual numbers. Every sum is
worked out exactly and rounded to two places once, half up.
"""

import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from math import floor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import (
    Choice,
    Circuit,
    CircuitCost,
    CircuitGroup,
    CircuitGroupMember,
    Location,
    Owner,
    Tag,
    TagLink,
    Vendor,
)
from hirdir.domain import circuits as rules
from hirdir.domain import contracts, settings
from hirdir.domain.errors import Invalid
from hirdir.domain.geography import Atlas
from hirdir.io import fields, filters, listing
from hirdir.io.planning import fiscal_year as fiscal_year_of

BY = ("carrier", "site", "region", "group", "circuit_type", "owner", "tag")
# The record type of a circuit's tags, as the circuits lane links them.
TAGGED = "circuit"


def rounded(value: Fraction) -> Decimal:
    """Return an exact amount rounded to two places, half up, as every sum is."""
    cents = value * 100
    whole = floor(cents + Fraction(1, 2)) if cents >= 0 else -floor(-cents + Fraction(1, 2))
    return Decimal(whole).scaleb(-2)


def _months(first: date, last: date) -> Iterable[tuple[date, date]]:
    """Yield the first and the last day of each month from `first` to `last`."""
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def billed(
    monthly: Decimal, first: date, last: date, starts_on: date | None, ends_on: date | None
) -> Fraction:
    """Return what a line of `monthly` a month costs from `first` to `last`, as the
    carrier bills it: each whole month in full, and a part month for its days."""
    start = max(first, starts_on) if starts_on else first
    end = min(last, ends_on) if ends_on else last
    if start > end:
        return Fraction(0)
    total = Fraction(0)
    each = Fraction(monthly)
    for month_first, month_last in _months(start, end):
        days = (min(end, month_last) - max(start, month_first)).days + 1
        length = (month_last - month_first).days + 1
        total += each if days == length else each * days / length
    return total


def _in_date(line: CircuitCost, day: date) -> bool:
    return not (line.starts_on and day < line.starts_on) and not (
        line.ends_on and day > line.ends_on
    )


def service_in(
    circuit: Circuit, first: date, last: date, include_drafts: bool
) -> tuple[date, date] | None:
    """Return the days from `first` to `last` on which a circuit is in service, as one
    range, or nothing: its activation and disconnection bound it, and a retired circuit
    with no disconnection was taken out (P-145)."""
    if circuit.record_status == "retired":
        if circuit.disconnected_on is None:
            return None
    elif circuit.record_status not in rules.counted_status(include_drafts):
        return None
    start = max(first, circuit.activated_on) if circuit.activated_on else first
    end = min(last, circuit.disconnected_on) if circuit.disconnected_on else last
    return (start, end) if start <= end else None


@dataclass
class Row:
    """One row of the report: the circuits of one value of `by`, and what they cost."""

    key: str | None
    label: str | None
    filter: dict[str, Any] | None
    circuits: int = 0
    cost: Decimal = Decimal(0)
    monthly_cost: Decimal = Decimal(0)
    annual_cost: Decimal = Decimal(0)


@dataclass
class CircuitCosts:
    """The report of what circuits cost in one fiscal year.

    The filters of its rows list the circuits on the circuit list with retired ones
    among them, `include_archived`, and drafts where the report counted them.
    """

    fiscal_year: int
    starts_on: date
    ends_on: date
    as_of: date
    by: str
    currency: str
    include_drafts: bool
    totals: Row
    rows: list[Row] = field(default_factory=list)
    include_archived: bool = True


@dataclass
class _Tally:
    circuits: set[str] = field(default_factory=set)
    cost: Fraction = Fraction(0)
    monthly: Fraction = Fraction(0)


def _condition(by: str, key: str | None, label: str | None) -> dict[str, Any]:
    """Return the condition of the circuit list that finds the circuits of a row."""
    if by == "carrier":
        # The carrier that bills a line: the line's own, or else the primary carrier.
        # The lines that no carrier bills are those of a circuit with no primary carrier.
        if key is None:
            return {"field": "carrier_hid", "op": "empty", "value": True}
        return {"field": "billed_by", "op": "eq", "value": key}
    if by == "site":
        return {"field": "cost_site_hid", "op": "eq", "value": key}
    if by == "region":
        if key is None:
            return {"field": "cost_location", "op": "empty", "value": True}
        return {"field": "cost_location", "op": "within", "value": key}
    if by == "group":
        if key is None:
            return {"field": "groups.hid", "op": "empty", "value": True}
        return {"field": "groups.hid", "op": "eq", "value": key}
    if by == "tag":
        if key is None:
            return {"field": "tags", "op": "empty", "value": True}
        return {"field": "tags", "op": "has", "value": label}
    name = "owner_hid" if by == "owner" else "circuit_type"
    if key is None:
        return {"field": name, "op": "empty", "value": True}
    return {"field": name, "op": "eq", "value": key}


def _window(first: date, last: date) -> dict[str, Any]:
    """Return the condition of the circuit list that keeps the circuits in service on
    some day from `first` to `last`, as `service_in` has it: activated by the last day,
    not disconnected before the first, and, retired, with a disconnection."""
    return {
        "and": [
            {
                "or": [
                    {"field": "activated_on", "op": "empty", "value": True},
                    {"field": "activated_on", "op": "lte", "value": last.isoformat()},
                ]
            },
            {
                "or": [
                    {"field": "disconnected_on", "op": "empty", "value": True},
                    {"field": "disconnected_on", "op": "gte", "value": first.isoformat()},
                ]
            },
            {
                "or": [
                    {"field": "record_status", "op": "ne", "value": "retired"},
                    {"field": "disconnected_on", "op": "empty", "value": False},
                ]
            },
        ]
    }


def _overlaps(line: CircuitCost, served: tuple[date, date]) -> bool:
    """Say whether a line is billed on some day of a circuit's service in the year."""
    return not (line.starts_on and line.starts_on > served[1]) and not (
        line.ends_on and line.ends_on < served[0]
    )


def circuit_costs(
    db: Session,
    *,
    fiscal_year: int | None = None,
    by: str = "carrier",
    include_drafts: bool = False,
    filter_: Any = None,
) -> CircuitCosts:
    """Say what circuits cost in a fiscal year, in total and for each value of `by`.

    `filter_` is a filter of the circuit list, in the short form or as JSON, which
    chooses the circuits counted; each row's filter narrows it, so that it lists the
    circuits of the row. Retired circuits are among those it may choose, since one that
    was disconnected ran for part of a year.
    """
    if by not in BY:
        raise Invalid("the report cannot be grouped so", {"by": f"one of {', '.join(BY)}"})
    today = contracts.today(db)
    start_month = int(settings.value(db, "fiscal_year_start_month"))
    if fiscal_year is None:
        year, first, last = fiscal_year_of(today, start_month)
    else:
        if not date.min.year < fiscal_year < date.max.year:
            raise Invalid("there is no such fiscal year", {"fiscal_year": "a year"})
        ending = date(fiscal_year, start_month, 1) - timedelta(days=1)
        year, first, last = fiscal_year_of(
            ending if start_month != 1 else date(fiscal_year, 1, 1), start_month
        )
    as_of = min(max(today, first), last)

    asked = filters.to_tree(filters.parse(filter_))
    # The places, the carrier and the owner a filter may name are joined as the
    # circuit list joins them: without them each named one would be a cross join, which
    # neither narrows the circuits nor counts each once.
    query = fields.CIRCUITS.joined(select(Circuit))
    if asked is not None:
        query = query.where(*listing.where_of(db, fields.CIRCUITS, asked, True, include_drafts, ()))
    held = list(db.scalars(query))
    lines: dict[str, list[CircuitCost]] = defaultdict(list)
    for line in db.scalars(
        select(CircuitCost).where(CircuitCost.circuit_hid.in_([c.hid for c in held]))
    ):
        lines[line.circuit_hid].append(line)

    atlas = Atlas(db)
    counted_at = [hid for hid in map(rules.cost_location_hid, held) if hid]
    locations = {
        one.hid: one for one in db.scalars(select(Location).where(Location.hid.in_(counted_at)))
    }
    atlas.take(locations.values())
    grouped, tagged = _memberships(db, [c.hid for c in held], by)

    totals = _Tally()
    tallies: dict[str | None, _Tally] = defaultdict(_Tally)
    for circuit in held:
        served = service_in(circuit, first, last, include_drafts)
        if served is None:
            continue
        on_day = rules.in_service_on(circuit, as_of, include_drafts)
        totals.circuits.add(circuit.hid)
        by_carrier: dict[str | None, _Tally] = defaultdict(_Tally)
        whole = _Tally()
        for line in lines[circuit.hid]:
            if not _overlaps(line, served):
                # A line billed on no day of the year's service bills nothing of it.
                continue
            cost = billed(line.monthly_cost, served[0], served[1], line.starts_on, line.ends_on)
            monthly = (
                Fraction(line.monthly_cost) if on_day and _in_date(line, as_of) else Fraction(0)
            )
            carrier = by_carrier[line.vendor_hid or circuit.carrier_hid]
            carrier.cost += cost
            carrier.monthly += monthly
            whole.cost += cost
            whole.monthly += monthly
        totals.cost += whole.cost
        totals.monthly += whole.monthly
        if by == "carrier":
            for key, part in (by_carrier or {circuit.carrier_hid: _Tally()}).items():
                tallies[key].circuits.add(circuit.hid)
                tallies[key].cost += part.cost
                tallies[key].monthly += part.monthly
            continue
        for key in _keys(atlas, locations, grouped, tagged, circuit, by):
            tallies[key].circuits.add(circuit.hid)
            tallies[key].cost += whole.cost
            tallies[key].monthly += whole.monthly

    labels = _labels(db, atlas, by, [key for key in tallies if key is not None])
    # The filters list the circuits in service on some day of the year (P-151).
    in_year = filters.both(asked, _window(first, last))
    rows = [
        _row(by, key, labels.get(key) if key is not None else None, tally, in_year)
        for key, tally in tallies.items()
    ]
    rows.sort(key=lambda one: (one.key is None, (one.label or "").casefold(), one.key or ""))
    return CircuitCosts(
        year,
        first,
        last,
        as_of,
        by,
        str(settings.value(db, "currency")),
        include_drafts,
        _row(by, None, None, totals, in_year, whole=True),
        rows,
    )


def _row(
    by: str,
    key: str | None,
    label: str | None,
    tally: _Tally,
    filter_: dict[str, Any] | None,
    whole: bool = False,
) -> Row:
    condition = filter_ if whole else filters.both(filter_, _condition(by, key, label))
    try:
        filters.parse(condition)
    except Invalid:
        # More than the grammar takes: the row, or the totals, have no filter.
        condition = None
    monthly = rounded(tally.monthly)
    return Row(
        key,
        label,
        condition,
        len(tally.circuits),
        rounded(tally.cost),
        monthly,
        rounded(tally.monthly * 12),
    )


def _memberships(
    db: Session, hids: list[str], by: str
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return the groups and the tags of each circuit, read once."""
    grouped: dict[str, list[str]] = defaultdict(list)
    tagged: dict[str, list[str]] = defaultdict(list)
    if by == "group":
        # A retired group keeps its circuits, and its row: retiring it ends no membership.
        for circuit_hid, group_hid in db.execute(
            select(CircuitGroupMember.circuit_hid, CircuitGroupMember.group_hid).where(
                CircuitGroupMember.circuit_hid.in_(hids)
            )
        ):
            grouped[circuit_hid].append(group_hid)
    if by == "tag":
        for record_hid, tag_hid in db.execute(
            select(TagLink.record_hid, TagLink.tag_hid).where(
                TagLink.record_type == TAGGED, TagLink.record_hid.in_(hids)
            )
        ):
            tagged[record_hid].append(tag_hid)
    return grouped, tagged


def _keys(
    atlas: Atlas,
    locations: dict[str, Location],
    grouped: dict[str, list[str]],
    tagged: dict[str, list[str]],
    circuit: Circuit,
    by: str,
) -> list[str | None]:
    """Return the rows a circuit is in, for every `by` but the carrier."""
    if by in ("site", "region"):
        location = locations.get(rules.cost_location_hid(circuit) or "")
        if location is None:
            return [None]
        if by == "site":
            return [location.site_hid]
        site = atlas.site(location.site_hid)
        line = atlas.region_line(site.region_hid if site else None)
        return [region.hid for region in line] or [None]
    if by == "group":
        return list(grouped.get(circuit.hid, [])) or [None]
    if by == "tag":
        return list(tagged.get(circuit.hid, [])) or [None]
    if by == "owner":
        return [circuit.owner_hid]
    return [circuit.circuit_type]


def _pairs(rows: Any) -> dict[str, str]:
    return {row[0]: row[1] for row in rows}


def _labels(db: Session, atlas: Atlas, by: str, keys: list[str]) -> dict[str, str]:
    """Return the label of each key of a row, as people read it."""
    if not keys:
        return {}
    if by == "carrier":
        return _pairs(db.execute(select(Vendor.hid, Vendor.name).where(Vendor.hid.in_(keys))))
    if by == "site":
        return {key: atlas.site_path(key) for key in keys}
    if by == "region":
        return {key: atlas.region_path(key) for key in keys}
    if by == "group":
        return _pairs(
            db.execute(
                select(CircuitGroup.hid, CircuitGroup.name).where(CircuitGroup.hid.in_(keys))
            )
        )
    if by == "tag":
        return _pairs(db.execute(select(Tag.hid, Tag.label).where(Tag.hid.in_(keys))))
    if by == "owner":
        return _pairs(db.execute(select(Owner.hid, Owner.label).where(Owner.hid.in_(keys))))
    found = _pairs(
        db.execute(select(Choice.value, Choice.label).where(Choice.list_name == "circuit_type"))
    )
    return {key: found.get(key, key) for key in keys}
