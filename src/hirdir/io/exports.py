"""Exporting a list to a file, with the filter and the sort that a list takes.

The rows are chosen first, in one statement, and then read and written a piece at a
time, so an export of every item never holds them all at once.
"""

import io
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from hirdir import clock
from hirdir.db import dialect
from hirdir.domain import audit, geography, product, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Invalid
from hirdir.io import columns as cells
from hirdir.io import examples, files, filters
from hirdir.io.columns import Column
from hirdir.io.entities import LABELS, LOAD_ORDER, Entity, entity
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
    # Each place written the short way, by codes (P-235).
    place_codes: bool = False

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
        chosen = [column for column in which.settable if column.listed]
    ordered: dict[str, Column] = {"hid": which.columns[0]}
    for column in chosen:
        ordered.setdefault(column.name, column)
        source = which.column(f"{column.name}_source") if include_sources else None
        if source is not None and column.inherits:
            ordered.setdefault(source.name, source)
    return tuple(ordered.values())


def plan(
    db: Session,
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
    place_codes: bool = False,
) -> Export:
    """Check what an export asks for, and return it ready to be written."""
    if format_ not in files.FORMATS:
        raise Invalid(
            "the format is not acceptable", {"format": f"one of {', '.join(files.FORMATS)}"}
        )
    found = entity(which)
    listing = found.listing
    where = [filters.to_sql(filters.parse(filter_), listing.fields, settings.time_zone(db), db)]
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
        place_codes=place_codes,
    )


def file_name(db: Session, export: Export) -> str:
    """Return a name for the file, with the product's name and the application's time in
    it (P-168)."""
    zone = str(settings.value(db, "time_zone"))
    stem = product.file_stem(product.name(db))
    return f"{stem}-{export.entity.name}-{clock.stamp(clock.now(), zone)}.{export.format}"


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
        # Each place is written the short way where that was asked for (P-235). The
        # rows are read here and now, a piece at a time, so the choice holds no longer.
        with geography.by_codes(export.place_codes):
            rows = which.read(
                db, [found[hid] for hid in wanted if hid in found], own=export.own_values
            )
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


# --- every table, as the Import page lists them (P-286) -------------------------------

# The order of a table exported whole, where the order of its list is not the one its
# file is loaded in: an item stands before the minor items that are in it.
WHOLE_SORT: dict[str, list[str]] = {"items": ["depth", "name"]}


@dataclass(frozen=True)
class Table:
    """One table that a file is taken for: what it is called, how many records it holds,
    and the columns of its file."""

    entity: str
    label: str
    file: str
    count: int
    columns: list[str]


def whole(db: Session, which: str, format_: str = "csv") -> Export:
    """Return the export of a whole table in the form that loads back: the stored values,
    the retired and the drafts among them (P-286)."""
    return plan(
        db,
        which,
        format_=format_,
        sort=WHOLE_SORT.get(which),
        own_values=True,
        include_archived=True,
        include_drafts=True,
    )


def tables(db: Session) -> list[Table]:
    """Return every table that a file is taken for, in the order files are loaded, each
    with how many records it holds, counted once each, and the columns of its file."""
    found = []
    for name in LOAD_ORDER:
        which = entity(name)
        count = db.scalar(select(func.count()).select_from(which.listing.model)) or 0
        found.append(
            Table(
                entity=name,
                label=LABELS[name],
                file=examples.stem(name),
                count=count,
                columns=[column.name for column in _columns(which, None, False)],
            )
        )
    return found


def everything(db: Session, format_: str) -> list[Export]:
    """Return the export of every table, whole, in the order files are loaded."""
    if format_ not in files.FORMATS:
        raise Invalid(
            "the format is not acceptable", {"format": f"one of {', '.join(files.FORMATS)}"}
        )
    return [whole(db, name, format_) for name in LOAD_ORDER]


# How the audit trail names the taking of every table at once: it is of no one record.
TAKEN_ACTION = "export"
TAKEN_RECORD = "inventory"


def taken(db: Session, context: AuditContext, format_: str) -> tuple[list[Export], str]:
    """Return the export of every table and the name of its file, and record in the
    audit trail that the whole inventory was taken out, by whom and in which format
    (P-286). One table exported by itself is not recorded: it is what a list shows.

    The event is the request's only write, stored when the route returns and before the
    first piece of the file is sent, so the one writer's place is not held while the
    file is read.
    """
    wanted = everything(db, format_)
    name = zip_name(db, format_)
    audit.record(
        db,
        context,
        TAKEN_ACTION,
        TAKEN_RECORD,
        None,
        [
            change("file_name", None, name),
            change("format", None, format_),
            change("tables", None, len(wanted)),
        ],
    )
    return wanted, name


def zip_name(db: Session, format_: str) -> str:
    """Return a name for the file of every table, named as any download is (P-168)."""
    zone = str(settings.value(db, "time_zone"))
    stem = product.file_stem(product.name(db))
    return f"{stem}-all-{format_}-{clock.stamp(clock.now(), zone)}.zip"


class _Taken(io.RawIOBase):
    """Where a zip is written to: what is written is kept until it is taken."""

    def __init__(self) -> None:
        super().__init__()
        self._held: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        self._held.append(bytes(data))
        return len(data)

    def take(self) -> bytes:
        taken = b"".join(self._held)
        self._held.clear()
        return taken


def write_zip(db: Session, wanted: Sequence[Export]) -> Iterator[bytes]:
    """Yield one zip of the files of some exports, each named as `examples/` names it, a
    piece at a time: no file is held whole, and a piece goes out as soon as it is read."""
    out = _Taken()
    # A zip dates its files in no zone: in the application's, as a file name is.
    now = clock.now().astimezone(ZoneInfo(settings.time_zone(db)))
    moment = (now.year, now.month, now.day, now.hour, now.minute, now.second)
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for export in wanted:
            name = examples.file_name(export.entity.name, export.format)
            member = zipfile.ZipInfo(name, date_time=moment)
            member.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(member, mode="w") as file:
                for piece in write(db, export):
                    file.write(piece)
                    yield out.take()
            yield out.take()
    yield out.take()


def stream_zip(sessions: sessionmaker[Session], wanted: Sequence[Export]) -> Iterator[bytes]:
    """Yield the zip of some exports through a session of its own, as `stream` does."""
    with sessions() as db:
        for piece in write_zip(db, wanted):
            if piece:
                yield piece
