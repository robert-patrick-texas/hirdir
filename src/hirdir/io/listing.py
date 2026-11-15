"""Reading one page of a list: filtered, sorted and counted by the database."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.domain import settings
from hirdir.io import filters
from hirdir.io.fields import Listing, default_view

MAX_LIMIT = 1000
MAX_OFFSET = 10_000_000


def where_of(
    db: Session,
    listing: Listing,
    filter_: Any,
    include_archived: bool,
    include_drafts: bool,
    also: Sequence[Any],
) -> list[ColumnElement[bool]]:
    return [
        filters.to_sql(filters.parse(filter_), listing.fields, settings.time_zone(db), db),
        *default_view(listing, include_archived, include_drafts),
        *also,
    ]


@contextmanager
def _answered() -> Generator[None]:
    """Run the statements of a list, and say what is wrong with a filter that fails."""
    with dialect.regex_budget() as budget:
        try:
            yield
        except OperationalError:
            # A pattern that ran out of time stops the statement. Anything else is not
            # the caller's doing and is left to surface as it is.
            if budget.failure:
                raise filters.refuse(budget.failure) from None
            raise
        except StatementError as error:
            # A value that could not be handed to the database at all. The grammar
            # refuses the ones it knows of; this is the net under it.
            if isinstance(error, DBAPIError):
                raise
            raise filters.refuse("a value in the filter cannot be compared") from None


def _counting(listing: Listing, where: list[ColumnElement[bool]]) -> Any:
    return dialect.count_of(listing.joined(select(listing.model.hid)).where(*where))


def count(
    db: Session,
    listing: Listing,
    *,
    filter_: Any = None,
    include_archived: bool = False,
    include_drafts: bool = False,
    also: Sequence[Any] = (),
) -> int:
    """Return how many records of a list the filter matches, as a page of it counts
    them, and read none of them."""
    where = where_of(db, listing, filter_, include_archived, include_drafts, also)
    with _answered():
        return db.scalar(_counting(listing, where)) or 0


def tally(
    db: Session,
    listing: Listing,
    conditions: dict[str, ColumnElement[bool]],
    *,
    filter_: Any = None,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> dict[str, int]:
    """Return how many records of a list meet each of several conditions, within what
    the filter matches, counted in one pass over the records (P-133): one statement
    reads the matching records once and tallies every condition as it goes."""
    if not conditions:
        return {}
    where = where_of(db, listing, filter_, include_archived, include_drafts, ())
    marks = [
        case((condition, 1), else_=0).label(f"c{place}")
        for place, condition in enumerate(conditions.values())
    ]
    rows = listing.joined(select(listing.model.hid, *marks)).where(*where)
    matched = dialect.materialized(rows, "tallied")
    summed = select(
        *(func.coalesce(func.sum(matched.c[f"c{place}"]), 0) for place in range(len(marks)))
    )
    with _answered():
        found = db.execute(summed).one()
    return {name: int(found[place]) for place, name in enumerate(conditions)}


def page(
    db: Session,
    listing: Listing,
    *,
    filter_: Any = None,
    sort: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
    include_drafts: bool = False,
    also: Sequence[Any] = (),
) -> tuple[list[Any], int]:
    """Return one page of a list, and how many records the filter matches in all.

    `also` narrows the list further, to the part of it that a route is of: the
    coverage of one contract, the lines of one request, a section of a report.

    The filter may be a decoded tree, JSON text or the short form. Blank values sort
    last, and records that tie are kept in a steady order by their HIDs, so that paging
    never repeats or skips one.
    """
    model = listing.model
    where = where_of(db, listing, filter_, include_archived, include_drafts, also)
    keys = filters.parse_sort(sort, listing.fields) or filters.parse_sort(
        list(listing.default_sort), listing.fields
    )
    order = [*filters.order_by(keys, listing.fields), model.hid.asc()]
    reading = (
        listing.joined(select(model)).where(*where).order_by(*order).limit(limit).offset(offset)
    )
    with _answered():
        total = db.scalar(_counting(listing, where)) or 0
        rows = list(db.scalars(reading))
    return rows, total
