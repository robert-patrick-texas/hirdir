"""What every list route takes: a filter, a sort, a page, and what to leave out."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from hirdir.api import records as shapes
from hirdir.io import listing
from hirdir.io.fields import Listing

Limit = Annotated[int, Query(ge=1, le=listing.MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0, le=listing.MAX_OFFSET)]


@dataclass(frozen=True)
class ListRequest:
    """One request for a page of a list."""

    filter: Any
    sort: list[str]
    limit: int
    offset: int
    include_archived: bool
    include_drafts: bool


def _from_query(
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=8000,
            description=(
                "The short form, `field:op:value` conditions separated by spaces, or a "
                "filter tree as JSON."
            ),
        ),
    ] = "",
    sort: Annotated[
        list[str] | None,
        Query(
            description="Field names, `-` in front for descending. Repeat or separate by commas."
        ),
    ] = None,
    limit: Limit = 100,
    offset: Offset = 0,
    include_archived: Annotated[
        bool, Query(description="Show retired records and items in Archived as well.")
    ] = False,
    include_drafts: Annotated[bool, Query(description="Show draft records as well.")] = False,
) -> ListRequest:
    return ListRequest(filter_, sort or [], limit, offset, include_archived, include_drafts)


Listed = Annotated[ListRequest, Depends(_from_query)]


def from_body(body: shapes.ListQuery) -> ListRequest:
    """Return the list request a query body asks for."""
    return ListRequest(
        body.filter,
        body.sort,
        body.limit,
        body.offset,
        body.include_archived,
        body.include_drafts,
    )


def read(db: Session, which: Listing, request: ListRequest) -> tuple[list[Any], int]:
    """Return the page of a list a request asks for, and the total it matches."""
    return listing.page(
        db,
        which,
        filter_=request.filter,
        sort=request.sort,
        limit=request.limit,
        offset=request.offset,
        include_archived=request.include_archived,
        include_drafts=request.include_drafts,
    )
