"""Reading and writing the two file formats: CSV, and JSON in its envelope.

Reading turns a file into rows of plain values, each with what was wrong with it.
Nothing here looks at the database.
"""

import csv
import io
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from hirdir.domain.errors import Invalid
from hirdir.io import columns as cells
from hirdir.io.columns import BLANK, Column, Unreadable
from hirdir.io.entities import Entity, entity

SCHEMA = "hirdir/1"
MODES = ("create", "upsert")
FORMATS = ("csv", "json")
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000


class TooLarge(Invalid):
    """The file is over a limit."""


@dataclass
class Row:
    """One row as read: the fields it sets, and what could not be read.

    A field that is absent from `values` is left alone, and one that is None is cleared.
    """

    values: dict[str, Any] = field(default_factory=dict)
    reasons: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Parsed:
    """A file as read."""

    entity: Entity
    mode: str
    rows: list[Row]


def reason(name: str, message: str) -> dict[str, str]:
    """Return one reason a row is rejected."""
    return {"field": name, "message": message}


def refuse(message: str, name: str = "file") -> Invalid:
    """Return the error for a file that cannot be read at all."""
    return Invalid("the file is not acceptable", {name: message})


def checked_mode(mode: Any) -> str:
    """Return a mode an import may run in."""
    if mode not in MODES:
        raise Invalid("the mode is not acceptable", {"mode": f"one of {', '.join(MODES)}"})
    return mode


def _known(which: Entity, names: Iterable[str]) -> list[Column]:
    """Return the column of each name, refusing a name the entity does not know."""
    found: list[Column] = []
    for name in names:
        column = which.column(name) if isinstance(name, str) and name.strip() else None
        if column is None:
            raise refuse(
                f"{name!r} is not a column of {which.name}; its columns are "
                f"{', '.join(column.name for column in which.columns if column.settable)}",
                "column",
            )
        found.append(column)
    return found


def _wanted(column: Column) -> bool:
    """Say whether an import reads a column, or passes it over as one nobody can set."""
    return column.settable or column.name == "hid"


def _read_csv(which: Entity, text: str) -> list[Row]:
    lines = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(lines, None)
        if header is None or not any(cell.strip() for cell in header):
            raise refuse("the file has no header row")
        heads = _known(which, header)
        if len({column.name for column in heads}) != len(heads):
            raise refuse("a column is named twice", "column")
        rows: list[Row] = []
        for line in lines:
            if not any(cell.strip() for cell in line):
                continue
            if len(rows) >= MAX_ROWS:
                raise TooLarge(f"a file holds at most {MAX_ROWS:,} rows")
            row = Row()
            if len(line) > len(heads):
                row.reasons.append(reason("", "the row has more cells than there are columns"))
            for column, cell in zip(heads, line, strict=False):
                if not _wanted(column):
                    continue
                try:
                    value = cells.from_cell(column, cell)
                except Unreadable as error:
                    row.reasons.append(reason(column.name, str(error)))
                    continue
                if value is not BLANK:
                    row.values[column.name] = value
            rows.append(row)
    except csv.Error as error:
        raise refuse(f"the file is not well-formed CSV: {error}") from None
    return rows


def _read_json(which: Entity, records: Any) -> list[Row]:
    if not isinstance(records, list) or not all(isinstance(entry, dict) for entry in records):
        raise refuse("`records` is a list of objects")
    if len(records) > MAX_ROWS:
        raise TooLarge(f"a file holds at most {MAX_ROWS:,} rows")
    names: dict[str, Column] = {}
    rows: list[Row] = []
    for record in records:
        row = Row()
        for name, given in record.items():
            if name not in names:
                names[name] = _known(which, [name])[0]
            column = names[name]
            if not _wanted(column):
                continue
            if column.name in row.values:
                row.reasons.append(reason(column.name, "given twice"))
                continue
            try:
                value = cells.from_json(column, given)
            except Unreadable as error:
                row.reasons.append(reason(column.name, str(error)))
                continue
            if value is not BLANK:
                row.values[column.name] = value
        rows.append(row)
    return rows


def read(
    data: bytes, *, format_: str, entity_name: str | None = None, mode: str | None = None
) -> Parsed:
    """Read a file into rows of plain values.

    A CSV file takes its entity and mode from beside it. A JSON file names them in its
    envelope, and what is given beside it must not disagree. A file that cannot be read
    at all, or that has a column its entity does not know, is refused whole.
    """
    if len(data) > MAX_BYTES:
        raise TooLarge(f"a file is at most {MAX_BYTES // (1024 * 1024)} MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise refuse("the file is not UTF-8 text") from None
    if "\x00" in text:
        raise refuse("the file holds a NUL character")
    if format_ == "csv":
        if not entity_name:
            raise Invalid("a CSV file needs its entity", {"entity": "say which records it holds"})
        which = entity(entity_name)
        return Parsed(which, checked_mode(mode or "upsert"), _read_csv(which, text))
    if format_ != "json":
        raise Invalid("the format is not acceptable", {"format": f"one of {', '.join(FORMATS)}"})
    try:
        envelope = json.loads(text)
    except ValueError:
        raise refuse("the file is not well-formed JSON") from None
    if not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA:
        raise refuse(f'a JSON file is an object with "schema": "{SCHEMA}"')
    unknown = set(envelope) - {"schema", "entity", "mode", "records"}
    if unknown:
        raise refuse(f"the envelope does not take {', '.join(sorted(unknown))}")
    which = entity(envelope.get("entity") or entity_name)
    if entity_name and entity(entity_name) is not which:
        raise Invalid(
            "the file and the request disagree",
            {"entity": f"the file holds {which.name}"},
        )
    in_file = envelope.get("mode")
    if in_file is not None and mode is not None and in_file != mode:
        raise Invalid("the file and the request disagree", {"mode": f"the file says {in_file}"})
    return Parsed(
        which,
        checked_mode(in_file or mode or "upsert"),
        _read_json(which, envelope.get("records")),
    )


# --- writing -------------------------------------------------------------------------


def write_csv(names: list[str], rows: Iterable[dict[str, Any]], header: bool = True) -> str:
    """Write rows of plain values as CSV text."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    if header:
        writer.writerow(names)
    for row in rows:
        writer.writerow([cells.to_cell(row.get(name)) for name in names])
    return out.getvalue()


def write_json(entity_name: str, chunks: Iterable[list[dict[str, Any]]]) -> Iterator[str]:
    """Write rows of plain values as a JSON file in its envelope, a piece at a time."""
    yield f'{{"schema": "{SCHEMA}", "entity": "{entity_name}", "mode": "upsert", "records": ['
    first = True
    for chunk in chunks:
        for row in chunk:
            yield ("\n  " if first else ",\n  ") + json.dumps(row, ensure_ascii=False)
            first = False
    yield "\n]}\n"
