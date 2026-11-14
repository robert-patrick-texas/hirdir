"""The routes of reports: the summary of a view, and the addresses held more than once."""

from typing import Annotated

from fastapi import APIRouter, Query

from hirdir.api import records as r
from hirdir.api.deps import Db, Viewer
from hirdir.api.lists import Limit, Offset
from hirdir.api.schemas import Page
from hirdir.io import reports

router = APIRouter(prefix="/reports", tags=["Reports"])

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
            max_length=8000,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    by: Annotated[r.SummaryBy | None, Query(description="One row for each value of this.")] = None,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
) -> r.SummaryOut:
    """Count a view of the items: components, managed nodes, weight, value and cost.

    The view is what the item list shows for the same filter. With `by`, the answer
    also holds one row for each value.
    """
    found = reports.summary(
        db,
        filter_=filter_,
        by=by,
        include_archived=include_archived,
        include_drafts=include_drafts,
    )
    return r.SummaryOut.model_validate(found)


@router.get("/duplicates")
def duplicates(
    _: Viewer,
    db: Db,
    include_archived: Archived = False,
    include_drafts: Drafts = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[r.DuplicateOut]:
    """List each address that is held more than once under one network.

    The unlabelled address space counts as one network. The same address under two
    networks is two addresses, and is not listed.
    """
    page, total = reports.duplicates(
        db,
        include_archived=include_archived,
        include_drafts=include_drafts,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[r.DuplicateOut.model_validate(found) for found in page],
        total=total,
        limit=limit,
        offset=offset,
    )


ROUTERS = (router,)
