"""What every list route takes: a filter, a sort, a page, and what to leave out."""

import types
from dataclasses import dataclass
from typing import Annotated, Any, Union, get_args, get_origin

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from hirdir.api import records as shapes
from hirdir.api.schemas import Page
from hirdir.domain.errors import Invalid
from hirdir.io import listing, tables
from hirdir.io.fields import Listing

Limit = Annotated[int, Query(ge=1, le=listing.MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0, le=listing.MAX_OFFSET)]


def sort_of(table: tables.Table) -> Any:
    """Return the `sort` of a route that pages a table: what it is, and what it takes."""
    return Query(description=table.help)


@dataclass(frozen=True)
class ListRequest:
    """One request for a page of a list."""

    filter: Any
    sort: list[str]
    limit: int
    offset: int
    include_archived: bool
    include_drafts: bool
    fields: tuple[str, ...] = ()


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
    fields: Annotated[
        list[str] | None,
        Query(
            description=(
                "Only these fields of each record, such as `name,catalog.pid`. Repeat or "
                "separate by commas. `hid` and `row_version` always come."
            )
        ),
    ] = None,
) -> ListRequest:
    return ListRequest(
        filter_, sort or [], limit, offset, include_archived, include_drafts, _names(fields)
    )


def _names(given: list[str] | None) -> tuple[str, ...]:
    names = [name.strip() for entry in given or [] for name in entry.split(",")]
    return tuple(name for name in names if name)


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
        _names(body.fields),
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


ALWAYS = ("hid", "row_version")


def _within(model: type[BaseModel], name: str) -> type[BaseModel] | None:
    """Return the record that one field of a record holds, when it holds one."""
    annotation = model.model_fields[name].annotation
    if get_origin(annotation) in (Union, types.UnionType):
        inner = [part for part in get_args(annotation) if part is not type(None)]
        annotation = inner[0] if len(inner) == 1 else None
    return (
        annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None
    )


def _wanted(model: type[BaseModel], names: tuple[str, ...]) -> dict[str, Any]:
    """Return what to keep of a record, refusing a name the record does not have."""
    keep: dict[str, Any] = {name: True for name in ALWAYS if name in model.model_fields}
    for name in names:
        outer, _, inner = name.partition(".")
        within = _within(model, outer) if outer in model.model_fields else None
        known = outer in model.model_fields and (
            not inner or (within is not None and inner in within.model_fields)
        )
        if not known:
            raise Invalid(
                "a field is not known", {"fields": f"{name} is not a field of this record"}
            )
        if not inner:
            keep[outer] = True
        elif keep.get(outer) is not True:
            keep.setdefault(outer, {})[inner] = True
    return keep


def narrowed(page: Page[Any], request: ListRequest, model: type[BaseModel]) -> Any:
    """Return a page as it is, or with only the fields the request asks for."""
    if not request.fields:
        return page
    keep = _wanted(model, request.fields)
    return JSONResponse(
        {
            "items": [item.model_dump(mode="json", include=keep) for item in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }
    )
