"""Reading one page of a list: filtered, sorted and counted by the database."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.io import filters
from hirdir.io.fields import Listing, default_view

MAX_LIMIT = 1000


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
) -> tuple[list[Any], int]:
    """Return one page of a list, and how many records the filter matches in all.

    The filter may be a decoded tree, JSON text or the short form. Blank values sort
    last, and records that tie are kept in a steady order by their HIDs, so that paging
    never repeats or skips one.
    """
    model = listing.model
    where = [
        filters.to_sql(filters.parse(filter_), listing.fields),
        *default_view(listing, include_archived, include_drafts),
    ]
    keys = filters.parse_sort(sort, listing.fields) or filters.parse_sort(
        list(listing.default_sort), listing.fields
    )
    order = [*filters.order_by(keys, listing.fields), model.hid.asc()]
    counting = listing.joined(select(func.count()).select_from(model)).where(*where)
    reading = (
        listing.joined(select(model)).where(*where).order_by(*order).limit(limit).offset(offset)
    )
    with dialect.regex_budget() as budget:
        try:
            total = db.scalar(counting) or 0
            rows = list(db.scalars(reading))
        except OperationalError:
            # A pattern that ran out of time stops the statement. Anything else is not
            # the caller's doing and is left to surface as it is.
            if budget.failure:
                raise filters.refuse(budget.failure) from None
            raise
    return rows, total
