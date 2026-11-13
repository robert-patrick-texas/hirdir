"""Exporting a list to a file, with the filter and the sort that a list takes.

The rows are chosen first, in one statement, and then read and written a piece at a
time, so an export of every item never holds them all at once.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from hirdir import clock
from hirdir.db import dialect
from hirdir.domain import settings
from hirdir.domain.errors import Invalid
from hirdir.io import columns as cells
from hirdir.io import files, filters
from hirdir.io.columns import Column
from hirdir.io.entities import Entity, entity
from hirdir.io.fields import Listing, default_view

MAX_HIDS = 10_000
PIECE = 500
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "json": "application/json"}


@dataclass(frozen=True)
class Export:
    """One export, checked and ready to be written."""

    entity: Entity
    format: str
    columns: tuple[Column, ...]
    where: tuple[Any, ...]
    order: tuple[Any, ...]
    own_values: bool

    @property
    def names(self) -> list[str]:
        """The names of the columns, in the order they are written."""
        return [column.name for column in self.columns]


def _columns(
    which: Entity, wanted: Sequence[str] | None, include_sources: bool
) -> tuple[Column, ...]:
    """Return the columns to write: `hid` first, then those asked for, each once."""
    if wanted:
        chosen = []
        for name in wanted:
            column = which.column(name) if isinstance(name, str) else None
            if column is None:
                raise Invalid(
                    "a column is not known",
                    {"columns": f"{name} is not a column of {which.name}"},
                )
            chosen.append(column)
    else:
        chosen = list(which.settable)
    ordered: dict[str, Column] = {"hid": which.columns[0]}
    for column in chosen:
        ordered.setdefault(column.name, column)
        source = which.column(f"{column.name}_source") if include_sources else None
        if source is not None and column.inherits:
            ordered.setdefault(source.name, source)
    return tuple(ordered.values())


def plan(
    which: str,
    *,
    format_: str = "csv",
    filter_: Any = None,
    sort: list[str] | None = None,
    columns: Sequence[str] | None = None,
    hids: Sequence[str] | None = None,
    include_sources: bool = False,
    own_values: bool = False,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> Export:
    """Check what an export asks for, and return it ready to be written."""
    if format_ not in files.FORMATS:
        raise Invalid(
            "the format is not acceptable", {"format": f"one of {', '.join(files.FORMATS)}"}
        )
    found = entity(which)
    listing = found.listing
    where = [filters.to_sql(filters.parse(filter_), listing.fields)]
    if hids is None:
        where += default_view(listing, include_archived, include_drafts)
    else:
        # Records named one by one are exported whatever their status, as a bulk edit
        # changes them. A filter leaves out what a list leaves out.
        if len(hids) > MAX_HIDS:
            raise Invalid(
                "too many records are named",
                {"hids": f"at most {MAX_HIDS:,}; a filter chooses any number"},
            )
        where.append(listing.model.hid.in_(list(hids)))
    keys = filters.parse_sort(sort, listing.fields) or filters.parse_sort(
        list(listing.default_sort), listing.fields
    )
    order = [*filters.order_by(keys, listing.fields), listing.model.hid.asc()]
    return Export(
        entity=found,
        format=format_,
        columns=_columns(found, columns, include_sources),
        where=tuple(where),
        order=tuple(order),
        own_values=own_values,
    )


def file_name(db: Session, export: Export) -> str:
    """Return a name for the file, with the application's time in it."""
    zone = str(settings.value(db, "time_zone"))
    return f"hirdir-{export.entity.name}-{clock.stamp(clock.now(), zone)}.{export.format}"


def chosen(db: Session, listing: Listing, where: Sequence[Any], order: Sequence[Any]) -> list[str]:
    """Return the HIDs of the rows a filter keeps, in order. The whole filter runs here,
    within the time one request may spend on regular expressions."""
    choosing = listing.joined(select(listing.model.hid)).where(*where).order_by(*order)
    with dialect.regex_budget() as budget:
        try:
            return list(db.scalars(choosing))
        except OperationalError:
            if budget.failure:
                raise filters.refuse(budget.failure) from None
            raise
        except StatementError as error:
            if isinstance(error, DBAPIError):
                raise
            raise filters.refuse("a value in the filter cannot be compared") from None


def pieces(db: Session, export: Export) -> Iterator[list[dict[str, Any]]]:
    """Yield the rows of an export as plain values, a piece at a time.

    The first piece may be empty: it is yielded once the rows are chosen, so that a
    filter that cannot be run is refused before anything is written.
    """
    which = export.entity
    model = which.listing.model
    hids = chosen(db, which.listing, export.where, export.order)
    yield []
    for start in range(0, len(hids), PIECE):
        wanted = hids[start : start + PIECE]
        found = {
            record.hid: record for record in db.scalars(select(model).where(model.hid.in_(wanted)))
        }
        rows = which.read(db, [found[hid] for hid in wanted if hid in found], own=export.own_values)
        yield [
            {column.name: cells.plain(column, row[column.name]) for column in export.columns}
            for row in rows
        ]
        db.expunge_all()


def _text(export: Export, rows: Iterator[list[dict[str, Any]]]) -> Iterator[str]:
    if export.format == "json":
        yield from files.write_json(export.entity.name, rows)
        return
    yield files.write_csv(export.names, [])
    for piece in rows:
        if piece:
            yield files.write_csv(export.names, piece, header=False)


def write(db: Session, export: Export) -> Iterator[bytes]:
    """Yield the file of an export, a piece at a time, read through one session."""
    rows = pieces(db, export)
    next(rows)
    for text in _text(export, rows):
        yield text.encode("utf-8")


def stream(sessions: sessionmaker[Session], export: Export) -> Iterator[bytes]:
    """Yield the file of an export through a session of its own.

    The session is opened here and not by the request, because the file is still being
    written after the request's own session has been given back.
    """
    with sessions() as db:
        yield from write(db, export)


def text_of(db: Session, export: Export) -> str:
    """Return the whole file of an export as text."""
    return b"".join(write(db, export)).decode("utf-8")
