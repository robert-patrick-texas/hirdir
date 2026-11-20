"""The routes of reports: the summary of a view, and the addresses held more than once."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import Field, PlainSerializer, WithJsonSchema

from hirdir.api import records as r
from hirdir.api import shapes
from hirdir.api.deps import Admin, Audit, Db, Viewer
from hirdir.api.lists import DEFAULT_LIMIT, Limit, Offset, sort_of
from hirdir.api.schemas import Model, Page
from hirdir.domain import settings
from hirdir.io import (
    alerts,
    balance,
    circuit_costs,
    filters,
    kept,
    planning,
    reports,
    tables,
    tried,
)

router = APIRouter(prefix="/reports", tags=["Reports"])
renewals_ = APIRouter(prefix="/renewals", tags=["Reports"])
kept_ = APIRouter(prefix="/kept-answers", tags=["Reports"])

Archived = Annotated[
    bool, Query(description="Count retired records and items in Archived as well.")
]
Drafts = Annotated[bool, Query(description="Count draft records as well.")]


@router.get("/summary")
def summary(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    by: Annotated[r.SummaryBy | None, Query(description="One row for each value of this.")] = None,
    operators: Annotated[
        bool,
        Query(description="With `by`: list in each row the operators in force among its items."),
    ] = False,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
) -> r.SummaryOut:
    """Count a view of the items: components, managed nodes, support weight and health.

    The view is what the item list shows for the same filter. With `by`, the answer
    also holds one row for each value. The money is in the management report.
    """
    found = reports.summary(
        db,
        filter_=filter_,
        by=by,
        include_archived=include_archived,
        include_drafts=include_drafts,
        operators=operators,
    )
    return shapes.summary_out(db, found)


@router.get("/management")
def management(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    by: Annotated[
        r.ManagementBy | None, Query(description="One row for each value of this.")
    ] = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
) -> r.ManagementOut:
    """Return the estimated value and the annual support cost of a view of the items.

    For the people who pay for the network: the whole view, and with `by` one row for
    each value. Neither condition nor health is in it.
    """
    found = reports.management(
        db,
        filter_=filter_,
        by=by,
        include_archived=include_archived,
        include_drafts=include_drafts,
    )
    return r.ManagementOut.model_validate(found)


@router.get("/duplicates")
def duplicates(
    _: Viewer,
    db: Db,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    sort: Annotated[list[str] | None, sort_of(tables.DUPLICATES)] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> Page[r.DuplicateOut]:
    """List each address that is held more than once under one network.

    The unlabelled address space counts as one network. The same address under two
    networks is two addresses, and is not listed. They are by address unless a sort
    says otherwise.
    """
    page, total = reports.duplicates(
        db,
        include_archived=include_archived,
        include_drafts=include_drafts,
        limit=limit,
        offset=offset,
        arrange=tables.arrange(tables.DUPLICATES, sort),
    )
    return Page(
        items=[r.DuplicateOut.model_validate(found) for found in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/coverage")
def coverage(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    within_days: Annotated[
        int | None,
        Query(
            ge=0,
            le=36_500,
            description=(
                "How far ahead cover that runs out is looked for. Left out, the setting "
                "`renewal_warning_days`."
            ),
        ),
    ] = None,
    section: Annotated[
        r.CoverageSection | None, Query(description="The list to return a page of.")
    ] = None,
    sort: Annotated[
        list[str] | None, Query(description="As the item list is sorted. For a section.")
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    include_drafts: Drafts = False,
) -> r.CoverageReport:
    """Say what contracts cover today: the items in service that none covers, the items
    out of service that a contract still counts, those whose cover runs out soon, those
    that more than one contract covers, and those covered while a renewal is pending.

    Each of the five is a list of items. `section` asks for a page of one, and each
    says the filter that lists the same items on `GET /items`. The contracts that
    have lapsed are counted beside them.
    """
    return coverage_answer(
        db,
        filter_=filter_,
        include_drafts=include_drafts,
        within_days=within_days,
        section=section,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def coverage_answer(
    db: Db,
    *,
    filter_: str = "",
    include_drafts: bool = False,
    within_days: int | None = None,
    section: r.CoverageSection | None = None,
    sort: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> r.CoverageReport:
    """Return the coverage report, kept until a change or the day makes it stale.

    A request that leaves `within_days` out asks for the setting's, and is kept as the
    same request as one that names it, so that the home page and the report share one
    answer.
    """
    days = within_days if within_days is not None else settings.value(db, "renewal_warning_days")
    asked = kept.asked(filter_, include_drafts, days, section, sort, limit, offset)
    return kept.answer(
        db,
        "coverage",
        asked,
        lambda session: shapes.coverage_report_out(
            session,
            planning.coverage(
                session,
                filter_=filter_,
                include_drafts=include_drafts,
                within_days=days,
                section=section,
                sort=sort,
                limit=limit,
                offset=offset,
            ),
        ),
    )


@router.get("/renewals")
def renewals(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the contract list, in the short form or as JSON.",
        ),
    ] = "",
    within_days: Annotated[
        int | None,
        Query(
            ge=0,
            le=36_500,
            description="How far ahead a contract counts as ending. Left out, the "
            "`renewal_warning_days` setting.",
        ),
    ] = None,
    section: Annotated[
        r.RenewalSection | None, Query(description="The list to return a page of.")
    ] = None,
    sort: Annotated[
        list[str] | None,
        Query(description="As the contract list is sorted, or the item list for `overlapping`."),
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    include_drafts: Drafts = False,
    include_archived: Archived = False,
) -> r.RenewalsReport:
    """Say what a person must act on to keep the cover going: the renewal worklist.

    The contracts that end within the warning period with no renewal entered, those
    that have lapsed, those whose renewal is pending and of them those that are
    overdue, those let go with their term, and the items that more than one contract
    covers. Each is counted under its vendor and its agreement in `groups`, and each
    count says the filter that lists its rows. `section` asks for a page of one list,
    the soonest end first. The agreements on the same lists are counted beside them.
    """
    return renewals_answer(
        db,
        filter_=filter_,
        include_drafts=include_drafts,
        include_archived=include_archived,
        within_days=within_days,
        section=section,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def renewals_answer(
    db: Db,
    *,
    filter_: str = "",
    include_drafts: bool = False,
    include_archived: bool = False,
    within_days: int | None = None,
    section: r.RenewalSection | None = None,
    sort: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> r.RenewalsReport:
    """Return the renewal worklist, kept until a change or the day makes it stale."""
    days = within_days if within_days is not None else settings.value(db, "renewal_warning_days")
    asked = kept.asked(
        filter_, include_drafts, include_archived, days, section, sort, limit, offset
    )
    return kept.answer(
        db,
        "renewals",
        asked,
        lambda session: shapes.renewals_report_out(
            session,
            planning.renewals(
                session,
                filter_=filter_,
                include_drafts=include_drafts,
                include_archived=include_archived,
                within_days=days,
                section=section,
                sort=sort,
                limit=limit,
                offset=offset,
            ),
        ),
    )


@renewals_.get("/alert")
def renewal_alert(caller: Viewer, db: Db) -> r.RenewalAlert:
    """Say how many contracts have lapsed, have a renewal pending, of which overdue,
    and end within the warning period, each with the list of the worklist it leads to,
    and the same of the agreements, and whether to show it to the person signed in:
    for the Inventory and the Admin role, once a day while any count is more than
    none."""
    return shapes.renewal_alert_out(alerts.alert(db, caller.user.hid, caller.role))


@renewals_.post("/alert/seen")
def renewal_alert_seen(body: r.AlertSeen, caller: Viewer, context: Audit, db: Db) -> r.AlertSeenOut:
    """Keep that the person signed in has seen the alert today: it is not shown to them
    again until the next day, in the application's time zone. It is a change of their
    own, audited on their user, and changes no contract."""
    view = alerts.seen(db, context, caller.user.hid)
    return r.AlertSeenOut(as_of=view.as_of, seen_at=view.seen_at)


@router.get("/end-of-life")
def end_of_life(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    date: Annotated[
        r.EndOfLifeDate | None,
        Query(
            description=(
                "Which of the four dates the lists are of. Left out, the setting "
                "`end_of_life_date`."
            )
        ),
    ] = None,
    within_days: Annotated[
        int | None,
        Query(
            ge=0,
            le=36_500,
            description=(
                "How far ahead a date counts as approaching. Left out, the setting "
                "`end_of_life_within_days`."
            ),
        ),
    ] = None,
    section: Annotated[
        r.EndOfLifeSection | None, Query(description="The list to return a page of.")
    ] = None,
    sort: Annotated[
        list[str] | None, Query(description="As the item list is sorted. For a section.")
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
) -> r.EndOfLifeReport:
    """Count the items of a view that are past, and that approach, each of the four
    end-of-life dates, and those of one date by fiscal year. It holds no money."""
    found = planning.end_of_life(
        db,
        filter_=filter_,
        date_=date,
        within_days=within_days,
        section=section,
        sort=sort,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
        include_drafts=include_drafts,
    )
    return shapes.end_of_life_out(db, found)


@router.get("/replacements")
def replacements(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the replacements, in the short form or as JSON.",
        ),
    ] = "",
    sort: Annotated[
        list[str] | None,
        Query(description="Field names, `-` in front for descending. The newest first."),
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> r.ReplacementsReport:
    """List the replacements: the item that left and the item that took its place,
    with the count of each reason among all that the filter matches."""
    page, total, by_reason = planning.replacements(
        db, filter_=filter_, sort=sort, limit=limit, offset=offset
    )
    return r.ReplacementsReport(
        items=shapes.replacement_rows_out(db, page),
        total=total,
        limit=limit,
        offset=offset,
        by_reason=[r.ReasonCount.model_validate(one) for one in by_reason],
    )


@router.get("/capacity")
def capacity(_: Viewer, db: Db) -> r.CapacityOut:
    """Return the capacity balance of the whole installation as of today: demand
    against supply, without the drafts and with them. It is kept as the coverage
    report is, and given again to every person while nothing could have changed it."""
    return capacity_answer(db)


def capacity_answer(db: Db) -> r.CapacityOut:
    """Return the capacity balance, kept until a change or the day makes it stale (P-157)."""
    return shapes.capacity_out(balance.kept_balance(db))


# The view each page opens with is worked out ahead and kept in the database (P-275):
# the coverage report and the renewal worklist here, the summary of the renewal alert
# in `hirdir.io.alerts` and the capacity balance in `hirdir.io.balance`.
kept.worked_ahead("coverage", r.CoverageReport, coverage_answer)
kept.worked_ahead("renewals", r.RenewalsReport, renewals_answer)


def work_out_ahead(db: Db) -> list[str]:
    """Work out the long reports for the view each page opens with, those that the
    database does not hold good, and keep them there: the coverage report, the renewal
    worklist, the summary of the renewal alert and the capacity balance (P-142, P-157,
    P-275). Return those kept. It stores what it keeps, and changes no record."""
    return kept.work_ahead(db)


def _two_places(value: Decimal) -> str:
    return f"{value:.2f}"


# A sum of what circuits cost: a credit line is below zero, so a sum may be too.
CostSum = Annotated[
    Decimal,
    PlainSerializer(_two_places, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["12000.00"]}),
]
CostsBy = Literal["carrier", "site", "region", "group", "circuit_type", "owner", "tag"]


class CircuitCostRow(Model):
    """What the circuits of one value of `by` cost in the year, or all of them."""

    key: str | None
    label: str | None
    circuits: int
    cost: CostSum
    monthly_cost: CostSum
    annual_cost: CostSum
    filter: dict[str, Any] | None = Field(
        description="The filter that lists the circuits of the row on `GET /circuits`, in "
        "the view `include_archived` and `include_drafts` say: the report's own, the year's "
        "window of service and the row's condition. A carrier's lists the circuits of the "
        "year it provides or bills a line of, whatever the dates of the line. Blank where it "
        "would be more than the grammar takes."
    )


class CircuitCostsOut(Model):
    """What circuits cost in one fiscal year, in total and for each value of `by`."""

    fiscal_year: int
    starts_on: date
    ends_on: date
    as_of: date
    by: CostsBy
    currency: str
    include_archived: bool = Field(
        description="The view the filters of the rows are of: retired circuits among them, "
        "since one that was disconnected ran for part of the year."
    )
    include_drafts: bool = Field(description="Drafts among them, where the report counted them.")
    totals: CircuitCostRow
    rows: list[CircuitCostRow]


def _cost_row(row: circuit_costs.Row) -> CircuitCostRow:
    return CircuitCostRow(
        key=row.key,
        label=row.label,
        circuits=row.circuits,
        cost=row.cost,
        monthly_cost=row.monthly_cost,
        annual_cost=row.annual_cost,
        filter=row.filter,
    )


@router.get("/circuit-costs")
def circuit_cost_report(
    _: Viewer,
    db: Db,
    fiscal_year: Annotated[
        int | None,
        Query(
            ge=2,
            le=9998,
            description="The fiscal year, named for the calendar year it "
            "ends in. Left out, the one today is in.",
        ),
    ] = None,
    by: Annotated[CostsBy, Query(description="What the rows are of.")] = "carrier",
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=filters.MAX_FILTER_LENGTH,
            description="A filter of the circuit list, in the short form or as JSON.",
        ),
    ] = "",
    include_drafts: Drafts = False,
) -> CircuitCostsOut:
    """Say what circuits cost in one fiscal year: `cost`, what the year costs, with a
    month in which a circuit or a line is in service only in part counted for its days,
    as the carrier bills it; `monthly_cost`, what is billed for a month on `as_of`, and
    `annual_cost`, twelve times that. Each row's `filter` lists its circuits; the
    totals count each circuit once (P-151)."""
    found = circuit_costs.circuit_costs(
        db, fiscal_year=fiscal_year, by=by, include_drafts=include_drafts, filter_=filter_ or None
    )
    return CircuitCostsOut(
        fiscal_year=found.fiscal_year,
        starts_on=found.starts_on,
        ends_on=found.ends_on,
        as_of=found.as_of,
        by=by,
        currency=found.currency,
        include_archived=found.include_archived,
        include_drafts=found.include_drafts,
        totals=_cost_row(found.totals),
        rows=[_cost_row(row) for row in found.rows],
    )


class KeptAnswer(Model):
    """A long report that is kept, and would be given as it is now."""

    report: str
    request: str
    kept_at: datetime
    uses: Annotated[
        int,
        Field(description="How many times the server has given it since it had it."),
    ]
    ahead: Annotated[
        bool,
        Field(
            description="Whether the database holds it, worked out ahead for the view "
            "its page opens with (P-275). The others are in the memory of the server "
            "alone."
        ),
    ]


class KeptDiffered(Model):
    """A kept answer that was not the same as the one worked out anew."""

    report: str
    request: str
    kept_at: datetime


class KeptCheck(Model):
    """What a check of the kept answers found: none should have differed."""

    checked_at: datetime
    checked: int
    differed: list[KeptDiffered]


@kept_.get("")
def kept_answers(_: Admin, db: Db) -> list[KeptAnswer]:
    """List the long reports that are kept and would be given now: the report, the
    request whole, when it was worked out, how many times the server has given it
    since, and whether the database holds it, worked out ahead (P-275). Those the
    server has given come first, then what the database holds that nobody has asked
    for yet."""
    return [
        KeptAnswer(
            report=e.report, request=e.request, kept_at=e.kept_at, uses=e.uses, ahead=e.ahead
        )
        for e in kept.listing(db)
    ]


@kept_.post("/check")
def check_kept_answers(_: Admin, context: Audit, db: Db) -> KeptCheck:
    """Work out each kept answer anew, compare it with what was kept, and keep the new
    one: those the server has given, and those the database holds, worked out ahead.
    `differed` names each that was not the same, which none should be: one that was is
    a defect to report. Audited as `kept_answers_checked`; it changes no record and
    leaves the kept answers good (P-157)."""
    found = kept.check(db, context)
    return KeptCheck(
        checked_at=found.checked_at,
        checked=found.checked,
        differed=[
            KeptDiffered(report=d.report, request=d.request, kept_at=d.kept_at)
            for d in found.differed
        ],
    )


# --- Try, the what-if of the capacity report (P-156) ---


@router.post("/capacity/try")
def capacity_try(body: r.CapacityTry, _: Viewer, db: Db) -> r.CapacityTryOut:
    """Return the capacity balance in force beside the balance that other figures and
    staff lines would give: any of the six weights of the settings,
    `weight_per_resource_unit` and `stack_discount_pct`, a key left out being as it is
    and null trying the setting at its default, and staff lines added, changed and
    left out. Nothing is saved, nothing is audited, and the answer is never kept. Any
    role may Try; an Admin saves the settings tried by `PUT /settings/{key}`."""
    return shapes.capacity_try_out(tried.capacity_tried(db, body.model_dump(exclude_unset=True)))


# --- end of Try ---


ROUTERS = (router, renewals_, kept_)
