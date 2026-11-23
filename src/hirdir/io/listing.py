"""Reading one page of a list: filtered, sorted and counted by the database."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.domain import settings
from hirdir.io import filters
from hirdir.io.fields import Listing, default_view

# The rows of a page where none is asked for, the most of one page, and the furthest
# a page may start: limits that protect the service (D-187).
DEFAULT_LIMIT = 100
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

    The records the filter matches are matched once, with what each sorts by, and both
    the page and the total are read from them, in one statement (P-326). A page with
    nothing on it has nothing to carry the total: from the first record, the filter
    matches none, and past the last, or with no room for one, they are counted by
    themselves.
    """
    model = listing.model
    where = where_of(db, listing, filter_, include_archived, include_drafts, also)
    keys = filters.parse_sort(sort, listing.fields) or filters.parse_sort(
        list(listing.default_sort), listing.fields
    )
    sorted_on = [
        value.label(f"sorted_on_{place}")
        for place, value in enumerate(filters.sorted_on(keys, listing.fields))
    ]
    # The joins are made from the record of the list, whatever else a value to sort by
    # reads.
    matched = dialect.materialized(
        listing.joined(select(model.hid.label("hid")).select_from(model))
        .add_columns(*sorted_on)
        .where(*where),
        "matched",
    )

    def order(rows: Any) -> list[Any]:
        values = [rows.c[one.name] for one in sorted_on]
        return [*filters.ordered(keys, values), rows.c.hid.asc()]

    total = select(func.count()).select_from(matched).scalar_subquery()
    chosen = (
        select(matched, total.label("total"))
        .order_by(*order(matched))
        .limit(limit)
        .offset(offset)
        .subquery("chosen")
    )
    reading = (
        select(model, chosen.c.total)
        .select_from(chosen)
        .join(model, model.hid == chosen.c.hid)
        .order_by(*order(chosen))
    )
    with _answered():
        found = db.execute(reading).all()
        if found:
            return [row[0] for row in found], found[0][1]
        if offset == 0 and limit > 0:
            return [], 0
        return [], db.scalar(select(func.count()).select_from(matched)) or 0
