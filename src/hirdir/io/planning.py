"""The reports that look ahead: what no contract covers, what reaches the end of its
life, what was replaced, and everything from one vendor.

Each is of a view of the items, as the summary is, and each of its counts is the count
of a filter of the item list: the answer says which, so that a count leads to its rows,
to the grid and to an export of them, and can never disagree with them.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.orm import Session

from hirdir.db.models import (
    Agreement,
    CapacityLine,
    CatalogEntry,
    Contract,
    Item,
    ItemReplacement,
    Vendor,
)
from hirdir.domain import catalog, choices, contracts, records, settings
from hirdir.domain.errors import Invalid
from hirdir.io import fields, filters, listing, reports
from hirdir.io.fields import ITEMS, REPLACEMENTS

# The states in which an item has been in service and no longer is.
OUT_OF_SERVICE = ("Pending-Removal", "Released", "Archived")
COVERAGE_SECTIONS = ("uncovered", "out_of_service", "expiring", "overlapping", "renewal_pending")
END_OF_LIFE_SECTIONS = ("past", "approaching")
EXPIRING_WITHIN = 90
APPROACHING_WITHIN = 730
MAX_DAYS = 36_500
STATE = "effective.lifecycle_state"


@dataclass(frozen=True)
class Section:
    """One list of a report: how many items, and the filter that lists them."""

    count: int
    filter: dict[str, Any] | None
    include_archived: bool
    include_drafts: bool


@dataclass(frozen=True)
class Page:
    """A page of the items of one section of a report."""

    section: str | None = None
    items: list[Any] = field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


def _checked_days(value: int, name: str = "within_days") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_DAYS:
        raise Invalid(
            f"{name} is not acceptable", {name: f"a whole number of days from 0 to {MAX_DAYS}"}
        )
    return value


def _checked_section(section: str | None, allowed: tuple[str, ...]) -> None:
    if section is not None and section not in allowed:
        raise Invalid("the section is not acceptable", {"section": f"one of {', '.join(allowed)}"})


def _section(
    db: Session,
    asked: Any,
    conditions: dict[str, Any] | None,
    include_archived: bool,
    include_drafts: bool,
) -> tuple[int, Section]:
    """Count the items of a view that meet the conditions of a section, and return the
    count with the section: the filter that lists the same items on the item list.

    The count is made of the filter that was asked with and of the conditions, each
    read by itself, so a filter at the very limits of the grammar is counted like any
    other. The filter of the section joins the two. Where the join would be more than
    the grammar takes, the section has no filter, and is read with `section`.
    """
    also = (
        []
        if conditions is None
        else [
            filters.to_sql(filters.from_tree(conditions), ITEMS.fields, settings.time_zone(db), db)
        ]
    )
    count = listing.page(
        db,
        ITEMS,
        filter_=asked,
        limit=1,
        include_archived=include_archived,
        include_drafts=include_drafts,
        also=also,
    )[1]
    joined = filters.both(filters.to_tree(filters.parse(asked)), conditions)
    try:
        filters.parse(joined)
    except Invalid:
        joined = None
    return count, Section(count, joined, include_archived, include_drafts)


def _page(
    db: Session,
    asked: Any,
    name: str | None,
    conditions: dict[str, dict[str, Any] | None],
    sections: dict[str, Section],
    sort: list[str] | None,
    default_sort: list[str],
    limit: int,
    offset: int,
) -> Page:
    if name is None:
        return Page(limit=limit, offset=offset)
    section = sections[name]
    its = conditions[name]
    also = (
        []
        if its is None
        else [filters.to_sql(filters.from_tree(its), ITEMS.fields, settings.time_zone(db), db)]
    )
    items, total = listing.page(
        db,
        ITEMS,
        filter_=asked,
        sort=sort or default_sort,
        limit=limit,
        offset=offset,
        include_archived=section.include_archived,
        include_drafts=section.include_drafts,
        also=also,
    )
    return Page(name, items, total, limit, offset)


# --- coverage ------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageTotals:
    """The counts of the coverage report."""

    in_service: int
    covered: int
    uncovered: int
    out_of_service: int
    expiring: int
    overlapping: int
    renewal_pending: int


@dataclass(frozen=True)
class Lapsed:
    """The contracts whose period has ended while they still say they are active."""

    count: int
    filter: dict[str, Any]


@dataclass(frozen=True)
class Coverage:
    """What contracts cover, of a view of the items, today."""

    as_of: date
    within_days: int
    service_states: list[str]
    totals: CoverageTotals
    sections: dict[str, Section]
    lapsed_contracts: Lapsed
    page: Page


def coverage(
    db: Session,
    *,
    filter_: Any = None,
    include_drafts: bool = False,
    within_days: int = EXPIRING_WITHIN,
    section: str | None = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Coverage:
    """Return what is in service with no cover, what is out of service and still
    counted by a contract, what runs out of cover within some days, what more than one
    contract covers, and what is covered while a renewal is pending."""
    _checked_section(section, COVERAGE_SECTIONS)
    within_days = _checked_days(within_days)
    today = contracts.today(db)
    states = list(settings.value(db, "service_states"))
    where = filters.where
    in_service = filters.both(where(STATE, "in", states), where("is_major", "eq", True))
    covered = filters.both(in_service, where("covered", "eq", True))
    conditions: dict[str, dict[str, Any] | None] = {
        "uncovered": filters.both(in_service, where("covered", "eq", False)),
        "out_of_service": where("out_of_service_cover", "eq", True),
        "expiring": filters.both(
            covered,
            where("covered_until", "lte", (today + timedelta(days=within_days)).isoformat()),
        ),
        "overlapping": where("contract_count", "gt", 1),
        "renewal_pending": where("contract.status", "eq", contracts.RENEWAL_PENDING),
    }
    sections = {
        # What is out of service is listed whatever its status: that is the point.
        name: _section(db, filter_, its, name == "out_of_service", include_drafts)[1]
        for name, its in conditions.items()
    }
    totals = CoverageTotals(
        in_service=_section(db, filter_, in_service, False, include_drafts)[0],
        covered=_section(db, filter_, covered, False, include_drafts)[0],
        **{name: one.count for name, one in sections.items()},
    )
    lapsed = where("lapsed", "eq", True)
    lapsed_contracts = Lapsed(
        listing.page(db, fields.CONTRACTS, filter_=lapsed, limit=1)[1], lapsed
    )
    default = ["covered_until", "name"] if section == "expiring" else ["name"]
    page = _page(db, filter_, section, conditions, sections, sort, default, limit, offset)
    return Coverage(today, within_days, states, totals, sections, lapsed_contracts, page)


# --- end of life ---------------------------------------------------------------------


@dataclass(frozen=True)
class Counted:
    """Items, and the components among them."""

    items: int = 0
    component_count: int = 0


@dataclass(frozen=True)
class FiscalYear(Counted):
    """The items whose date falls in one fiscal year."""

    fiscal_year: int = 0
    starts_on: date = date.min
    ends_on: date = date.min


@dataclass(frozen=True)
class EndOfLife:
    """The items of a view that are past, or near, one of the four end-of-life dates."""

    as_of: date
    within_days: int
    date: str
    dates: dict[str, dict[str, Counted]]
    by_fiscal_year: list[FiscalYear]
    sections: dict[str, Section]
    page: Page


def fiscal_year(day: date, start_month: int) -> tuple[int, date, date]:
    """Return the fiscal year a day falls in, with its first and its last day. A fiscal
    year is named for the calendar year it ends in."""
    first_year = day.year if day.month >= start_month else day.year - 1
    # A date at either end of the calendar, a "never" of 9999-12-31, is in a fiscal
    # year that the calendar cuts short.
    first = date(first_year, start_month, 1) if first_year >= date.min.year else date.min
    if first_year + 1 > date.max.year:
        return first_year + (0 if start_month == 1 else 1), first, date.max
    last = date(first_year + 1, start_month, 1) - timedelta(days=1)
    return last.year, first, last


def end_of_life(
    db: Session,
    *,
    filter_: Any = None,
    date_: str = "ldos",
    within_days: int = APPROACHING_WITHIN,
    section: str | None = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> EndOfLife:
    """Count the items past and approaching each end-of-life date, and list those of one."""
    _checked_section(section, END_OF_LIFE_SECTIONS)
    within_days = _checked_days(within_days)
    if date_ not in catalog.DATES:
        raise Invalid("the date is not acceptable", {"date": f"one of {', '.join(catalog.DATES)}"})
    today = contracts.today(db)
    horizon = today + timedelta(days=within_days)
    terms = reports._terms(db, filter_, include_archived, include_drafts)

    def both(condition: Any) -> tuple[Any, Any]:
        return (
            func.count(distinct(case((condition, Item.hid)))),
            func.count(distinct(case((and_(condition, terms.component), Item.hid)))),
        )

    counting: list[Any] = []
    for name in catalog.DATES:
        day = ITEMS.fields[f"effective.{name}"].expression
        counting += [*both(day < today), *both(and_(day >= today, day <= horizon))]
    found = reports._run(db, terms.source(select(*counting)))[0]
    dates: dict[str, dict[str, Counted]] = {}
    for place, name in enumerate(catalog.DATES):
        past_items, past_components, near_items, near_components = found[place * 4 : place * 4 + 4]
        dates[name] = {
            "past": Counted(past_items, past_components),
            "approaching": Counted(near_items, near_components),
        }

    chosen = ITEMS.fields[f"effective.{date_}"].expression
    start_month = int(settings.value(db, "fiscal_year_start_month"))
    years: dict[int, list[Any]] = {}
    by_day = terms.source(select(chosen, terms.items, terms.components)).where(chosen.is_not(None))
    for day, items, components in reports._run(db, by_day.group_by(chosen)):
        year, first, last = fiscal_year(day, start_month)
        row = years.setdefault(year, [0, 0, first, last])
        row[0] += items
        row[1] += components
    by_fiscal_year = [
        FiscalYear(items, components, year, first, last)
        for year, (items, components, first, last) in sorted(years.items())
    ]

    its = f"effective.{date_}"
    conditions: dict[str, dict[str, Any] | None] = {
        "past": filters.where(its, "lt", today.isoformat()),
        "approaching": filters.where(its, "between", [today.isoformat(), horizon.isoformat()]),
    }
    sections = {
        name: _section(db, filter_, one, include_archived, include_drafts)[1]
        for name, one in conditions.items()
    }
    page = _page(db, filter_, section, conditions, sections, sort, [its, "name"], limit, offset)
    return EndOfLife(today, within_days, date_, dates, by_fiscal_year, sections, page)


# --- replacements --------------------------------------------------------------------


@dataclass(frozen=True)
class ByReason:
    """How many replacements were made for one reason."""

    reason: str
    label: str
    count: int


def replacements(
    db: Session,
    *,
    filter_: Any = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ItemReplacement], int, list[ByReason]]:
    """Return a page of the replacements a filter matches, how many it matches, and
    the count of each reason among them."""
    page, total = listing.page(
        db, REPLACEMENTS, filter_=filter_, sort=sort, limit=limit, offset=offset
    )
    matching = filters.to_sql(
        filters.parse(filter_), REPLACEMENTS.fields, settings.time_zone(db), db
    )
    counting: Any = select(ItemReplacement.reason, func.count()).select_from(ItemReplacement)
    counted = dict(
        reports._run(
            db, REPLACEMENTS.joined(counting).where(matching).group_by(ItemReplacement.reason)
        )
    )
    known = {
        choice.value: choice.label for choice in choices.list_choices(db, "replacement_reason")
    }
    order = [*known, *sorted(reason for reason in counted if reason not in known)]
    by_reason = [
        ByReason(reason, known.get(reason, reason), counted[reason])
        for reason in order
        if reason in counted
    ]
    return page, total, by_reason


# --- the portfolio of a vendor -------------------------------------------------------


@dataclass(frozen=True)
class Held:
    """What a vendor's items come to: how many, how heavy, how dear, and how many of
    the major ones are covered."""

    items: int = 0
    component_count: int = 0
    support_weight: Decimal = Decimal(0)
    est_value: Decimal = Decimal(0)
    annual_support_cost: Decimal = Decimal(0)
    covered: int = 0
    uncovered: int = 0


@dataclass(frozen=True)
class OfKind(Held):
    """The items of one kind."""

    kind: str = ""


@dataclass(frozen=True)
class OfModel(Held):
    """The items of one model, with the model's dates and when the first cover runs out."""

    entry: Any = None
    covered_until: date | None = None


@dataclass(frozen=True)
class Portfolio:
    """Everything from one vendor, in one place."""

    vendor: Vendor
    as_of: date
    totals: Held
    kinds: list[OfKind]
    models: list[OfModel]
    agreements: list[Agreement]
    contracts: list[Contract]
    capacity_lines: list[CapacityLine]
    filter: dict[str, Any]


def _held(counts: Any, weight: list[int], money: list[int]) -> dict[str, Any]:
    items, components, major, covered = counts
    return {
        "items": items,
        "component_count": components,
        "support_weight": (Decimal(weight[0]) / reports.WEIGHT_STEPS).quantize(
            reports.HUNDREDTH, rounding=ROUND_HALF_UP
        ),
        "est_value": Decimal(money[0]) / reports.MONEY_STEPS,
        "annual_support_cost": Decimal(money[1]) / reports.MONEY_STEPS,
        "covered": covered,
        "uncovered": major - covered,
    }


def portfolio(
    db: Session, vendor: Vendor, *, include_archived: bool = False, include_drafts: bool = False
) -> Portfolio:
    """Return what one vendor makes or provides: its items as a whole, by kind and by
    model, its contracts, and the capacity lines that name it."""
    tree = filters.where("catalog.vendor_hid", "eq", vendor.hid)
    terms = reports._terms(db, tree, include_archived, include_drafts)
    major = Item.parent_item_hid.is_(None)
    counts = (
        terms.items,
        terms.components,
        func.count(distinct(case((major, Item.hid)))),
        func.count(distinct(case((and_(major, fields.COVERED), Item.hid)))),
    )
    nothing = [0, 0]

    def grouped(key: Any, *more: Any) -> tuple[list[Any], dict[Any, list[int]], dict[Any, Any]]:
        rows = reports._run(db, terms.source(select(key, *counts, *more)).group_by(key))
        return (
            rows,
            reports._sums(db, terms, terms.weight, key),
            reports._sums(db, terms, terms.money, key),
        )

    whole = reports._run(db, terms.source(select(*counts)))[0]
    totals = Held(
        **_held(
            whole,
            reports._sums(db, terms, terms.weight).get(None, nothing),
            reports._sums(db, terms, terms.money).get(None, nothing),
        )
    )
    rows, weights, money = grouped(reports.KIND)
    by_kind = {
        row[0]: OfKind(
            **_held(row[1:5], weights.get(row[0], nothing), money.get(row[0], nothing)),
            kind=row[0],
        )
        for row in rows
    }
    kinds = [by_kind.get(kind, OfKind(kind=kind)) for kind in settings.CATALOG_KINDS]

    soonest = func.min(case((and_(major, fields.COVERED), fields.COVERED_UNTIL)))
    rows, weights, money = grouped(CatalogEntry.hid, soonest)
    entries = {
        entry.hid: entry
        for entry in db.scalars(
            select(CatalogEntry).where(CatalogEntry.hid.in_([row[0] for row in rows if row[0]]))
        )
    }
    models = sorted(
        (
            OfModel(
                **_held(row[1:5], weights.get(row[0], nothing), money.get(row[0], nothing)),
                entry=entries[row[0]],
                covered_until=row[5],
            )
            for row in rows
            if row[0] in entries
        ),
        key=lambda one: (records.key(one.entry.pid), one.entry.hid),
    )

    def in_view(model: Any) -> list[Any]:
        statuses = ["active"]
        statuses += ["draft"] if include_drafts else []
        statuses += ["retired"] if include_archived else []
        return [model.vendor_hid == vendor.hid, model.record_status.in_(statuses)]

    # The contracts it provides, and those that were bought through it.
    provided, *status = in_view(Contract)
    its_contracts = list(
        db.scalars(
            select(Contract)
            .where(
                or_(provided, contracts.in_force_of(Contract, "reseller_hid") == vendor.hid),
                *status,
            )
            .order_by(Contract.number_key, Contract.hid)
        )
    )
    its_agreements = list(
        db.scalars(
            select(Agreement)
            .where(
                or_(Agreement.vendor_hid == vendor.hid, Agreement.reseller_hid == vendor.hid),
                *in_view(Agreement)[1:],
            )
            .order_by(Agreement.name_key)
        )
    )
    lines = list(
        db.scalars(
            select(CapacityLine)
            .where(*in_view(CapacityLine))
            .order_by(CapacityLine.side, CapacityLine.category, CapacityLine.name_key)
        )
    )
    return Portfolio(
        vendor,
        contracts.today(db),
        totals,
        kinds,
        models,
        its_agreements,
        its_contracts,
        lines,
        tree,
    )
