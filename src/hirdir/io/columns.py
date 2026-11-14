"""The columns of a file: what kind each is, and reading and writing one value.

A value has three forms. In a CSV file it is the text of a cell. In JSON, in a stored
preview and in a list of changes it is *plain*: text, a whole number, true or false, a
list of text, with a date as `YYYY-MM-DD` and a decimal as text. The rules work on the
*typed* form: dates and decimals as Python has them.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

CLEAR_MARK = "!clear"
# A cell that begins with one of these is run as a formula by a spreadsheet.
FORMULA_STARTS = ("=", "+", "-", "@")
LIST_SEPARATOR = ";"
MAX_LIST = 100
BIGGEST_AMOUNT = Decimal(10) ** 13
BIGGEST_WHOLE = 1_000_000_000
TRUE_WORDS = ("true", "yes", "1")
FALSE_WORDS = ("false", "no", "0")

# What reading a value returns when the file says nothing about the field.
BLANK: Final[Any] = object()


class Unreadable(ValueError):
    """A value that its column cannot hold. The message says what the column takes."""


@dataclass(frozen=True)
class Column:
    """One column of a file.

    `kind` is text, integer, boolean, date, money, number, degrees, list or timestamp. `limit`
    is the longest text the column takes, or the longest entry of a list. A column that
    is not `settable` is written by an export and passed over by an import. One that is
    not `listed` is taken by an import, and written by an export only when it is asked
    for by name: what it holds is in a file of its own already.
    """

    name: str
    kind: str = "text"
    limit: int = 200
    settable: bool = True
    inherits: bool = False
    listed: bool = True


def _text(column: Column, value: str) -> str:
    text = value.strip()
    if len(text) > column.limit:
        raise Unreadable(f"at most {column.limit} characters")
    try:
        text.encode("utf-8")
    except UnicodeError:
        raise Unreadable("text that can be written as UTF-8") from None
    return text


def _guarded(text: str) -> bool:
    """Say whether text is apostrophes and then a character that starts a formula."""
    return text.lstrip("'")[:1] in FORMULA_STARTS


def _whole(value: Any) -> int:
    try:
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError
        whole = int(value.strip()) if isinstance(value, str) else int(value)
    except ValueError, TypeError, OverflowError:
        raise Unreadable("a whole number") from None
    if abs(whole) > BIGGEST_WHOLE:
        raise Unreadable("a whole number of at most a thousand million")
    return whole


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    word = value.strip().lower() if isinstance(value, str) else str(value)
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise Unreadable("true or false")


def _day(value: Any) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise Unreadable("a date, as YYYY-MM-DD") from None


def _moment(value: Any) -> str:
    """Read a date and time in ISO 8601, and write it in UTC when it names its zone.

    One that names no zone is left as it is: the rules read it in the application's
    time zone, which only they know.
    """
    unreadable = Unreadable("a date and time in ISO 8601, such as 2026-11-14T15:04:05Z")
    try:
        if not isinstance(value, str):
            raise unreadable
        moment = datetime.fromisoformat(value.strip())
        if moment.tzinfo is None:
            return moment.isoformat()
        # A moment at the very edge of the calendar cannot be told in another zone.
        return moment.astimezone(UTC).isoformat()
    except ValueError, OverflowError:
        raise unreadable from None


def _amount(column: Column, value: Any) -> str:
    expected = "a number with at most two decimal places"
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise Unreadable(expected)
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or abs(number) >= BIGGEST_AMOUNT:
            raise Unreadable(expected)
        if number != number.quantize(Decimal("0.01")):
            raise Unreadable(expected)
    except InvalidOperation:
        raise Unreadable(expected) from None
    return decimal_text(column, number)


def _degrees(value: Any) -> str:
    expected = "decimal degrees with at most six decimal places"
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise Unreadable(expected)
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or abs(number) > 180:
            raise Unreadable(expected)
        if number != number.quantize(Decimal("0.000001")):
            raise Unreadable(expected)
    except InvalidOperation:
        raise Unreadable(expected) from None
    return format(number.normalize(), "f")


def _entries(column: Column, value: Any) -> list[str]:
    parts = value.split(LIST_SEPARATOR) if isinstance(value, str) else value
    if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
        raise Unreadable("a list of text")
    if len(parts) > MAX_LIST:
        raise Unreadable(f"at most {MAX_LIST} entries")
    return [_text(column, part) for part in parts if part.strip()]


def decimal_text(column: Column, number: Decimal) -> str:
    """Write a decimal as every interface shows it: money with two places, the rest plain."""
    if column.kind == "money":
        return f"{number:.2f}"
    return format(number.normalize(), "f")


def read(column: Column, value: Any) -> Any:
    """Return the plain form of a value that is not blank, or refuse it as Unreadable."""
    kind = column.kind
    if kind == "integer":
        return _whole(value)
    if kind == "boolean":
        return _truth(value)
    if kind == "date":
        return _day(value)
    if kind == "timestamp":
        return _moment(value)
    if kind in ("money", "number"):
        return _amount(column, value)
    if kind == "degrees":
        return _degrees(value)
    if kind == "list":
        return _entries(column, value)
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise Unreadable("text")
    return _text(column, str(value))


def from_cell(column: Column, cell: str) -> Any:
    """Read one cell of a CSV file: BLANK to leave the field alone, None to clear it."""
    text = cell.strip()
    if not text:
        return BLANK
    if text == CLEAR_MARK:
        return None
    return read(column, unguarded(text))


def unguarded(text: str) -> str:
    """Return a cell of a CSV file without the apostrophe an export put before it so
    that a spreadsheet runs no formula."""
    return text[1:] if text[:1] == "'" and _guarded(text) else text


def from_json(column: Column, value: Any) -> Any:
    """Read one value of a JSON record: BLANK for empty text, None for null."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return BLANK
        if value.strip() == CLEAR_MARK:
            return None
    return read(column, value)


def to_cell(value: Any) -> str:
    """Write a plain value as one cell of a CSV file."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = LIST_SEPARATOR.join(value) if isinstance(value, list) else str(value)
    # A value that begins with an apostrophe of its own before such a character gets
    # one more, so that reading the cell takes off the export's and leaves the value's.
    return "'" + text if _guarded(text) else text


def typed(column: Column, value: Any) -> Any:
    """Return a plain value in the form the rules work on."""
    if value is None:
        return None
    if column.kind == "date":
        return date.fromisoformat(value)
    if column.kind == "timestamp":
        return datetime.fromisoformat(value)
    if column.kind in ("money", "number", "degrees"):
        return Decimal(value)
    return value


def plain(column: Column, value: Any) -> Any:
    """Return a typed value in the form a file, a preview and a list of changes hold."""
    if isinstance(value, Decimal):
        return decimal_text(column, value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
