"""The routes of reports: the summary of a view, and the addresses held more than once."""

from typing import Annotated

from fastapi import APIRouter, Query

from hirdir.api import records as r
from hirdir.api import shapes
from hirdir.api.deps import Audit, Db, Viewer
from hirdir.api.lists import DEFAULT_LIMIT, Limit, Offset, sort_of
from hirdir.api.schemas import Page
from hirdir.io import alerts, balance, filters, kept, planning, reports, tables

router = APIRouter(prefix="/reports", tags=["Reports"])
renewals_ = APIRouter(prefix="/renewals", tags=["Reports"])

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
    asked = kept.asked(filter_, include_drafts, within_days, section, sort, limit, offset)
    return kept.answer(
        db,
        "coverage",
        asked,
        lambda: shapes.coverage_report_out(
            db,
            planning.coverage(
                db,
                filter_=filter_,
                include_drafts=include_drafts,
                within_days=within_days,
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
) -> r.RenewalsReport:
    """Say what a person must act on to keep the cover going: the renewal worklist.

    The contracts that end within the warning period with no renewal entered, those
    that have lapsed, those whose renewal is pending and of them those that are
    overdue, those let go with their term, and the items that more than one contract
    covers. Each is counted under its vendor and its agreement in `groups`, and each
    count says the filter that lists its rows. `section` asks for a page of one list,
    the soonest end first. The agreements on the same lists are counted beside them.
    """
    asked = kept.asked(filter_, include_drafts, within_days, section, sort, limit, offset)
    return kept.answer(
        db,
        "renewals",
        asked,
        lambda: shapes.renewals_report_out(
            db,
            planning.renewals(
                db,
                filter_=filter_,
                include_drafts=include_drafts,
                within_days=within_days,
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
    and whether to show it to the person signed in: for the Inventory and the Admin
    role, once until a contract comes onto one of those lists that was not on it when
    they last saw it."""
    return shapes.renewal_alert_out(alerts.alert(db, caller.user.hid, caller.role))


@renewals_.post("/alert/seen")
def renewal_alert_seen(body: r.AlertSeen, caller: Viewer, context: Audit, db: Db) -> r.AlertSeenOut:
    """Keep that the person signed in has seen the alert as it was answered, by its
    `version`. It is a change of their own, audited on their user, and changes no
    contract. A version that is no longer in force is a `409`: read the alert again."""
    view = alerts.seen(db, context, caller.user.hid, body.version)
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
    against supply, without the drafts and with them."""
    return shapes.capacity_out(balance.balance(db))


ROUTERS = (router, renewals_)
