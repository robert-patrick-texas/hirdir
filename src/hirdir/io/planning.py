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

from sqlalchemy import and_, case, distinct, func, or_, select, true
from sqlalchemy.orm import Session

from hirdir.db.models import (
    Agreement,
    CapacityLine,
    CatalogEntry,
    Contract,
    ContractCoverage,
    Item,
    ItemReplacement,
    Vendor,
)
from hirdir.domain import catalog, choices, contracts, records, settings
from hirdir.domain.errors import Invalid
from hirdir.io import fields, filters, listing, reports
from hirdir.io.fields import ITEMS, REPLACEMENTS

COVERAGE_SECTIONS = (
    "uncovered",
    "out_of_service",
    "expiring",
    "overlapping",
    "renewal_pending",
    "not_renewed",
)
END_OF_LIFE_SECTIONS = ("past", "approaching")
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


def _sql(db: Session, tree: dict[str, Any] | None, of: Any = ITEMS) -> Any:
    """Return the conditions of a section as SQL, over the fields of a list."""
    if tree is None:
        return true()
    return filters.to_sql(filters.from_tree(tree), of.fields, settings.time_zone(db), db)


def _joined(asked: Any, conditions: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the filter of a section: the one asked with, and its own conditions. Where
    the two would be more than the grammar takes, there is none, and the section is
    read with `section`."""
    joined = filters.both(filters.to_tree(filters.parse(asked)), conditions)
    try:
        filters.parse(joined)
    except Invalid:
        return None
    return joined


def _tallied(
    db: Session,
    asked: Any,
    conditions: dict[str, dict[str, Any] | None],
    archived: set[str],
    include_drafts: bool,
    of: Any = ITEMS,
) -> dict[str, int]:
    """Count every section of a report in one pass over the records (P-133). The
    records of a section that `archived` names are counted whatever their status, and
    those of every other as the list leaves them by default."""
    by_default = and_(*fields.default_view(of, False, include_drafts))
    return listing.tally(
        db,
        of,
        {
            name: _sql(db, tree, of) if name in archived else and_(by_default, _sql(db, tree, of))
            for name, tree in conditions.items()
        },
        filter_=asked,
        include_archived=True,
        include_drafts=include_drafts,
    )


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
    count = listing.count(
        db,
        ITEMS,
        filter_=asked,
        include_archived=include_archived,
        include_drafts=include_drafts,
        also=also,
    )
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


# --- not to be renewed, by model -----------------------------------------------------

# The flag in force on the item list: its own word, or its model's.
NOT_RENEWED = "effective.do_not_renew"


@dataclass(frozen=True)
class NotRenewed:
    """How many items of one model are not to be renewed and are under no contract,
    with the filter that lists them. A row with no model is the items that have none."""

    catalog_entry_hid: str | None
    vendor_hid: str | None
    vendor: str | None
    pid: str | None
    model_name: str | None
    count: int
    filter: dict[str, Any] | None


def _not_renewed_by_model(
    db: Session,
    asked: Any,
    conditions: dict[str, Any] | None,
    section: Section,
    include_drafts: bool,
) -> list[NotRenewed]:
    """Count the items of the section `not_renewed` by model, in one statement: by
    vendor and PID, and the items with no model last."""
    zone = settings.time_zone(db)
    kept = [
        filters.to_sql(filters.parse(asked), ITEMS.fields, zone, db),
        *fields.default_view(ITEMS, False, include_drafts),
        filters.to_sql(filters.from_tree(conditions), ITEMS.fields, zone, db),
    ]
    model = (Item.catalog_entry_hid, Vendor.hid, Vendor.name, CatalogEntry.pid)
    counting: Any = select(*model, CatalogEntry.model_name, func.count(distinct(Item.hid)))
    statement = (
        ITEMS.joined(counting.select_from(Item))
        .where(*kept)
        .group_by(*model, CatalogEntry.model_name)
    )
    found = []
    for hid, vendor_hid, vendor, pid, model_name, count in reports._run(db, statement):
        its = (
            filters.where("catalog_entry_hid", "eq", hid)
            if hid is not None
            else filters.where("catalog_entry_hid", "empty", True)
        )
        joined = None if section.filter is None else filters.both(section.filter, its)
        try:
            filters.parse(joined)
        except Invalid:
            joined = None
        found.append(NotRenewed(hid, vendor_hid, vendor, pid, model_name, count, joined))
    return sorted(
        found,
        key=lambda one: (
            one.catalog_entry_hid is None,
            records.key(one.vendor or ""),
            records.key(one.pid or ""),
        ),
    )


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
    not_renewed: int


@dataclass(frozen=True)
class Lapsed:
    """The contracts whose period has ended while they still say they are active."""

    count: int
    filter: dict[str, Any] | None


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
    by_model: list[NotRenewed] = field(default_factory=list)


def coverage(
    db: Session,
    *,
    filter_: Any = None,
    include_drafts: bool = False,
    within_days: int | None = None,
    section: str | None = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Coverage:
    """Return what is in service with no cover, what is out of service and still
    counted by a contract, what runs out of cover within some days, what more than one
    contract covers, and what is covered while a renewal is pending. What runs out
    soon is within `within_days`, the setting `renewal_warning_days` unless asked."""
    _checked_section(section, COVERAGE_SECTIONS)
    if within_days is None:
        within_days = int(settings.value(db, "renewal_warning_days"))
    within_days = _checked_days(within_days)
    today = contracts.today(db)
    states = list(settings.value(db, "service_states"))
    where = filters.where
    in_service = filters.both(where(STATE, "in", states), where("is_major", "eq", True))
    covered = filters.both(in_service, where("covered", "eq", True))
    # An item not to be renewed that no contract covers, or whose cover runs out, is no
    # gap: it is left out of those two, and counted by itself (P-131).
    flagged = where(NOT_RENEWED, "eq", True)
    renewed = where(NOT_RENEWED, "ne", True)
    uncovered = filters.both(in_service, where("covered", "eq", False))
    conditions: dict[str, dict[str, Any] | None] = {
        "uncovered": filters.both(uncovered, renewed),
        "out_of_service": where("out_of_service_cover", "eq", True),
        "expiring": filters.both(
            covered,
            where("covered_until", "lte", (today + timedelta(days=within_days)).isoformat()),
            renewed,
        ),
        "overlapping": where("contract_count", "gt", 1),
        "renewal_pending": where("contract.status", "eq", contracts.RENEWAL_PENDING),
        "not_renewed": filters.both(uncovered, flagged),
    }
    # What is out of service is listed whatever its status: that is the point.
    archived = {"out_of_service"}
    counted = _tallied(
        db,
        filter_,
        {"in_service": in_service, "covered": covered, **conditions},
        archived,
        include_drafts,
    )
    sections = {
        name: Section(counted[name], _joined(filter_, its), name in archived, include_drafts)
        for name, its in conditions.items()
    }
    totals = CoverageTotals(
        in_service=counted["in_service"],
        covered=counted["covered"],
        **{name: one.count for name, one in sections.items()},
    )
    lapsed_contracts = _lapsed_in_view(db, filter_, include_drafts)
    default = ["covered_until", "name"] if section == "expiring" else ["name"]
    page = _page(db, filter_, section, conditions, sections, sort, default, limit, offset)
    by_model = _not_renewed_by_model(
        db, filter_, conditions["not_renewed"], sections["not_renewed"], include_drafts
    )
    return Coverage(today, within_days, states, totals, sections, lapsed_contracts, page, by_model)


# --- renewals ------------------------------------------------------------------------

RENEWAL_SECTIONS = (
    "ending",
    "lapsed",
    "renewal_pending",
    "overdue",
    "ends_with_term",
    "to_review",
    "overlapping",
)
# The lists of contracts, and of agreements, that the alert after sign-in is of.
ALERTED = ("lapsed", "renewal_pending", "ending")
AGREEMENT_SECTIONS = ("ending", "lapsed", "renewal_pending")
MAX_NAMED_IN_A_FILTER = 1000


@dataclass(frozen=True)
class RenewalGroup:
    """One vendor and one agreement of the worklist, or a vendor's contracts that
    stand by themselves: how many of its contracts are on each list, and the filter
    that lists them."""

    vendor_hid: str
    vendor: str
    agreement_hid: str | None
    agreement: str | None
    counts: dict[str, int]
    filters: dict[str, dict[str, Any] | None]


@dataclass(frozen=True)
class Renewals:
    """What a person must act on to keep the cover going: the renewal worklist."""

    as_of: date
    within_days: int
    overdue_after: int
    totals: dict[str, int]
    sections: dict[str, Section]
    agreements: dict[str, Section]
    groups: list[RenewalGroup]
    on_lists: dict[str, list[str]]
    agreement_lists: dict[str, list[str]]
    page: Page


def _renewal_conditions(today: date, within_days: int) -> dict[str, dict[str, Any] | None]:
    """Return what puts a contract on each list of the worklist, as filters of the
    contract list."""
    where = filters.where
    horizon = (today + timedelta(days=within_days)).isoformat()
    ends_within = filters.both(
        where("effective.ends_on", "gte", today.isoformat()),
        where("effective.ends_on", "lte", horizon),
    )
    return {
        # It covers, ends within the horizon, has no renewal entered, and is meant to go on.
        "ending": filters.both(
            where("status", "eq", contracts.ACTIVE),
            where("covers_today", "eq", True),
            ends_within,
            where("renewal_waiting", "eq", False),
            where("ends_with_term", "eq", False),
        ),
        "lapsed": where("lapsed", "eq", True),
        "renewal_pending": where("status", "eq", contracts.RENEWAL_PENDING),
        "overdue": where("renewal_overdue", "eq", True),
        # What the team marked not to renew, to be seen and never alerted: from when
        # it ends within the horizon, and also once it has ended, until a person says
        # it has expired or retires it. The mark changes nothing by itself (P-129).
        "ends_with_term": filters.both(
            where("ends_with_term", "eq", True),
            where("status", "eq", contracts.ACTIVE),
            where("effective.ends_on", "lte", horizon),
        ),
        # The members of an agreement that was renewed that still say their renewal is
        # pending or that they have expired: no renewal of an agreement changes them.
        "to_review": where("to_review", "eq", True),
    }


def _agreement_conditions(today: date, within_days: int) -> dict[str, dict[str, Any] | None]:
    where = filters.where
    horizon = (today + timedelta(days=within_days)).isoformat()
    return {
        "ending": filters.both(
            where("status", "eq", contracts.ACTIVE),
            where("ends_on", "gte", today.isoformat()),
            where("ends_on", "lte", horizon),
            where("next_starts_on", "empty", True),
        ),
        "lapsed": where("lapsed", "eq", True),
        "renewal_pending": where("status", "eq", contracts.RENEWAL_PENDING),
    }


def _hids_of(
    db: Session,
    of: Any,
    asked: Any,
    tree: dict[str, Any] | None,
    include_drafts: bool,
    include_archived: bool = False,
    also: tuple[Any, ...] = (),
) -> list[Any]:
    """Return the records of a list that a filter and a section's conditions match."""
    where = listing.where_of(
        db, of, asked, include_archived, include_drafts, (_sql(db, tree, of), *also)
    )
    return list(db.scalars(of.joined(select(of.model.hid)).where(*where)))


def _within(named: dict[str, Any] | None, tree: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a filter that keeps to the records named, or none where they are too many
    to name: never a wider one."""
    return None if named is None else filters.both(named, tree)


def _named(field_: str, hids: list[str]) -> dict[str, Any] | None:
    """Return the filter of the records named, or none where they are too many for one."""
    if len(hids) > MAX_NAMED_IN_A_FILTER:
        return None
    return filters.where(field_, "in", sorted(hids))


def renewals(
    db: Session,
    *,
    filter_: Any = None,
    include_drafts: bool = False,
    include_archived: bool = False,
    within_days: int | None = None,
    section: str | None = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Renewals:
    """Return the renewal worklist (P-127): the contracts that end within the warning
    period, those that have lapsed, those whose renewal is pending and of them those
    that are overdue, those let go with their term, and the items that more than one
    contract covers, each under its vendor and its agreement, each count with the
    filter that lists the same rows."""
    _checked_section(section, RENEWAL_SECTIONS)
    if within_days is None:
        within_days = int(settings.value(db, "renewal_warning_days"))
    within_days = _checked_days(within_days)
    today = contracts.today(db)
    after = contracts.overdue_after(db)
    conditions = _renewal_conditions(today, within_days)
    of = fields.CONTRACTS
    # The contracts of the view, and the lists each of them is on.
    in_view: list[tuple[Any, ...]] = [
        tuple(row)
        for row in db.execute(
            of.joined(
                select(
                    Contract.hid,
                    Contract.vendor_hid,
                    Vendor.name,
                    Contract.agreement_hid,
                    of.fields["agreement.name"].expression,
                )
            ).where(*listing.where_of(db, of, filter_, include_archived, include_drafts, ()))
        )
    ]
    on_lists = {
        name: _hids_of(db, of, filter_, tree, include_drafts, include_archived)
        for name, tree in conditions.items()
    }
    # The items that more than one contract covers today, and the contracts that do.
    pairs: list[tuple[Any, ...]] = [
        tuple(row)
        for row in db.execute(
            ITEMS.joined(select(Item.hid))
            .add_columns(ContractCoverage.contract_hid)
            .join(ContractCoverage, ContractCoverage.item_hid == Item.hid)
            .join(Contract, Contract.hid == ContractCoverage.contract_hid)
            .where(
                contracts.coverage_in_force(ContractCoverage, Contract),
                *fields.default_view(ITEMS, False, include_drafts),
                fields.CONTRACT_COUNT > 1,
            )
        )
    ]
    viewed = {row[0] for row in in_view}
    overlapping: dict[str, set[str]] = {}
    for item_hid, contract_hid in pairs:
        if contract_hid in viewed:
            overlapping.setdefault(contract_hid, set()).add(item_hid)
    where = filters.where
    item_overlap = where("contract_count", "gt", 1)
    asked_tree = filters.to_tree(filters.parse(filter_))
    whole_view = asked_tree is None
    overlap_items = {hid for items in overlapping.values() for hid in items}
    sections = {
        name: Section(len(on_lists[name]), _joined(filter_, tree), include_archived, include_drafts)
        for name, tree in conditions.items()
    }
    sections["overlapping"] = Section(
        len(overlap_items),
        item_overlap
        if whole_view
        else _within(_named("contract.hid", sorted(viewed)), item_overlap),
        False,
        include_drafts,
    )
    # Each vendor and agreement that has a contract on a list.
    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    for hid, vendor_hid, vendor, agreement_hid, agreement in in_view:
        key = (vendor_hid, agreement_hid)
        groups.setdefault(
            key,
            {"vendor": vendor, "agreement": agreement, "contracts": set()},
        )["contracts"].add(hid)
    found: list[RenewalGroup] = []
    sets = {name: set(hids) for name, hids in on_lists.items()}
    for (vendor_hid, agreement_hid), group in groups.items():
        held = group["contracts"]
        counts = {name: len(held & sets[name]) for name in conditions}
        items = {hid for contract in held for hid in overlapping.get(contract, ())}
        counts["overlapping"] = len(items)
        if not any(counts.values()):
            continue
        scope = filters.both(
            where("vendor_hid", "eq", vendor_hid),
            where("agreement_hid", "eq", agreement_hid)
            if agreement_hid is not None
            else where("agreement_hid", "empty", True),
        )
        found.append(
            RenewalGroup(
                vendor_hid,
                group["vendor"],
                agreement_hid,
                group["agreement"],
                counts,
                {
                    **{
                        name: _joined(filter_, filters.both(scope, tree))
                        for name, tree in conditions.items()
                    },
                    "overlapping": _within(_named("contract.hid", sorted(held)), item_overlap),
                },
            )
        )
    found.sort(
        key=lambda one: (
            records.key(one.vendor),
            one.agreement is None,
            records.key(one.agreement or ""),
        )
    )
    # The agreements, by themselves: renewing one renews what shares its period.
    agreement_hids = sorted({row[3] for row in in_view if row[3] is not None})
    by_agreement = _agreement_conditions(today, within_days)
    narrowed = () if whole_view else (Agreement.hid.in_(agreement_hids),)
    agreement_sections = {}
    agreement_lists: dict[str, list[str]] = {}
    for name, tree in by_agreement.items():
        agreement_lists[name] = _hids_of(
            db, fields.AGREEMENTS, None, tree, include_drafts, include_archived, narrowed
        )
        joined = tree if whole_view else _within(_named("hid", agreement_hids), tree)
        agreement_sections[name] = Section(
            len(agreement_lists[name]), joined, include_archived, include_drafts
        )
    totals = {name: one.count for name, one in sections.items()}
    page = Page(limit=limit, offset=offset)
    if section == "overlapping":
        items, total = listing.page(
            db,
            ITEMS,
            filter_=None,
            sort=sort or ["name"],
            limit=limit,
            offset=offset,
            include_drafts=include_drafts,
            also=[Item.hid.in_(sorted(overlap_items))]
            if not whole_view
            else [_sql(db, item_overlap)],
        )
        page = Page(section, items, total, limit, offset)
    elif section is not None:
        rows, total = listing.page(
            db,
            of,
            filter_=filter_,
            sort=sort or ["effective.ends_on", "number"],
            limit=limit,
            offset=offset,
            include_drafts=include_drafts,
            include_archived=include_archived,
            also=[_sql(db, conditions[section], of)],
        )
        page = Page(section, rows, total, limit, offset)
    alerted = {name: sorted(on_lists[name]) for name in ALERTED}
    return Renewals(
        today,
        within_days,
        after,
        totals,
        sections,
        agreement_sections,
        found,
        alerted,
        {name: sorted(hids) for name, hids in agreement_lists.items()},
        page,
    )


def _lapsed_in_view(db: Session, asked: Any, include_drafts: bool) -> Lapsed:
    """Count the contracts that have lapsed, of the view the coverage report is of: with
    no filter all of them, and with one those that have a coverage of an item in the
    view that follows the contract, as a lapsed contract covers nothing today (P-117)."""
    lapsed = filters.where("lapsed", "eq", True)
    if filters.to_tree(filters.parse(asked)) is None:
        return Lapsed(listing.count(db, fields.CONTRACTS, filter_=lapsed), lapsed)
    in_view = listing.where_of(db, ITEMS, asked, False, include_drafts, ())
    items = ITEMS.joined(select(Item.hid)).where(*in_view)
    followed = select(ContractCoverage.contract_hid).where(
        ContractCoverage.item_hid.in_(items),
        or_(
            ContractCoverage.ends_on.is_(None),
            ContractCoverage.ends_on >= contracts.in_force_of(Contract, "ends_on"),
        ),
        ContractCoverage.contract_hid == Contract.hid,
    )
    hids = _hids_of(db, fields.CONTRACTS, None, lapsed, False, False, (followed.exists(),))
    return Lapsed(len(hids), _within(_named("hid", sorted(hids)), lapsed))


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
    date_: str | None = None,
    within_days: int | None = None,
    section: str | None = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> EndOfLife:
    """Count the items past and approaching each end-of-life date, and list those of one.

    The date is `end_of_life_date` and the window `end_of_life_within_days`, settings
    both, unless asked."""
    _checked_section(section, END_OF_LIFE_SECTIONS)
    if date_ is None:
        date_ = str(settings.value(db, "end_of_life_date"))
    if within_days is None:
        within_days = int(settings.value(db, "end_of_life_within_days"))
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
