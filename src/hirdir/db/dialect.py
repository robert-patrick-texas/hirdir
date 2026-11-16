"""Everything that differs between SQLite and PostgreSQL lives in this module.

Comparison without regard to case, wildcard and regular expression matching, where
blank values fall in a sorted list, the order of addresses, the least text of a list
that is kept as JSON, and a number that a JSON object holds. The rest of the code
builds its SQL from these and never asks which database it is talking to.

Regular expressions are bounded. A pattern has a longest length and a limit on how far
its counted repeats multiply, each match has a time limit, and one request has a budget
for all its matches together. So a pattern that is costly to compile is refused before
it is compiled, and one that backtracks without end costs a refused request and never a
stalled server. The engine is the `regex` package, which offers the per-match time
limit. See P-19 in docs/decisions.md for when RE2 takes its place.
"""

import json
import re
import socket
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import regex
from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    Date,
    Float,
    Integer,
    Numeric,
    String,
    cast,
    func,
    literal,
    select,
    text,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from hirdir import clock
from hirdir.db.models import Setting

REGEX_MAX_LENGTH = 200
REGEX_MAX_REPEAT = 100
REGEX_MATCH_SECONDS = 0.05
REGEX_REQUEST_SECONDS = 1.0
LIKE_ESCAPE = "\\"


class PatternError(ValueError):
    """A pattern that is too long or cannot be compiled."""


@dataclass
class RegexBudget:
    """The time one request may spend matching, and what went wrong if it ran out."""

    seconds: float
    spent: float = 0.0
    failure: str = ""


_budget: ContextVar[RegexBudget | None] = ContextVar("hirdir_regex_budget", default=None)


@contextmanager
def regex_budget(seconds: float | None = None) -> Generator[RegexBudget]:
    """Give the statements run inside this block one shared allowance of matching time."""
    budget = RegexBudget(REGEX_REQUEST_SECONDS if seconds is None else seconds)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


_COUNTED_REPEAT = re.compile(r"\{(\d*)(?:,(\d*))?\}")


def _check_repeats(pattern: str) -> None:
    """Refuse a pattern whose counted repeats multiply past the limit.

    Compiling `a{n}` costs time and memory in proportion to n, and nested repeats
    multiply: `(?:a{3000}){3000}` is seventeen characters and takes gigabytes. Every
    count in the pattern is multiplied together, nested or not, which refuses a little
    more than it must and never less.
    """
    product = 1
    for low, high in _COUNTED_REPEAT.findall(pattern):
        product *= max(int(low or 0), int(high or 0), 1)
        if product > REGEX_MAX_REPEAT:
            raise PatternError(
                f"the counted repeats of a pattern may multiply to at most {REGEX_MAX_REPEAT}"
            )


@lru_cache(maxsize=16)
def compile_pattern(pattern: str) -> Any:
    """Compile pattern, to be matched without regard to case, or say why it is refused."""
    if len(pattern) > REGEX_MAX_LENGTH:
        raise PatternError(f"a pattern may be at most {REGEX_MAX_LENGTH} characters long")
    _check_repeats(pattern)
    try:
        # The package keeps a cache of its own, which is not bounded by size in memory.
        return regex.compile(pattern, regex.IGNORECASE, cache_pattern=False)
    except regex.error as error:
        raise PatternError(f"the pattern cannot be compiled: {error}") from None


def regex_search(pattern: str, value: str) -> bool:
    """Say whether pattern matches anywhere in value, within the limits.

    Raises TimeoutError when the match or the request's budget runs out of time.
    """
    budget = _budget.get()
    limit = REGEX_MATCH_SECONDS
    if budget is not None:
        left = budget.seconds - budget.spent
        if left <= 0:
            budget.failure = "the pattern takes too long to match against this list"
            raise TimeoutError(budget.failure)
        limit = min(limit, left)
    started = time.perf_counter()
    try:
        return compile_pattern(pattern).search(value, timeout=limit) is not None
    except TimeoutError:
        if budget is not None:
            budget.failure = "the pattern takes too long to match"
        raise
    finally:
        if budget is not None:
            budget.spent += time.perf_counter() - started


def _sqlite_regexp(pattern: str | None, value: Any) -> bool | None:
    if pattern is None or value is None:
        return None
    return regex_search(pattern, str(value))


def _sqlite_fold(value: Any) -> str | None:
    return None if value is None else str(value).lower()


def _sqlite_address_key(value: Any) -> str | None:
    """Return text that sorts as the address does: IPv4 before IPv6, each by its number.

    It is the family and the bytes of the address in hexadecimal, which are as many
    for every address of one family. It is called for every address a sort looks at,
    so it reads the stored form with the socket library and not with `ipaddress`,
    which takes ten times as long.
    """
    if value is None:
        return None
    text = str(value)
    family, version = (socket.AF_INET6, "6") if ":" in text else (socket.AF_INET, "4")
    try:
        return version + socket.inet_pton(family, text).hex()
    except OSError:
        # Nothing but an address is stored. What is none sorts after every one that is.
        return f"9{text}"


def _sqlite_today(setting: Any) -> str:
    """Return today's date in the application's time zone, as SQLite keeps a date.

    `setting` is the `time_zone` setting as the database holds it: JSON text, or
    nothing where it was never changed or was returned to its default.
    """
    zone = None
    if setting is not None:
        try:
            zone = json.loads(setting)
        except ValueError:
            zone = None
    if not isinstance(zone, str) or not zone:
        zone = clock.DEFAULT_ZONE
    try:
        return clock.today(zone).isoformat()
    except KeyError, ValueError, OSError:
        return clock.today().isoformat()


def is_busy(error: Exception) -> bool:
    """Say whether a statement failed because another writer held the database too long.

    SQLite lets one transaction write at a time. A second waits as long as
    `busy_timeout` says, and is then refused. Nothing of the second was done.
    """
    return "database is locked" in str(getattr(error, "orig", error))


# The key of the lock that PostgreSQL holds for a change that is checked against others.
WRITER_LOCK = 8715


def hold_other_writers(db: Any) -> None:
    """Take the one writer's place now, and keep it until the transaction ends.

    Some rules are about several records at once: an item is in one stack, a stack has
    one master, an item is never above itself. Such a rule is checked by reading and
    kept by writing, and of two requests that check at the same moment each would find
    nothing in its way. So a change of that kind takes the writer's place before it
    looks, and the second waits until the first is stored and then sees it.

    SQLite gives the place to whoever writes first: a statement that writes nothing
    takes it. PostgreSQL holds a lock of this name until the transaction ends. One
    that waits longer than `busy_timeout` is refused, as any change is.
    """
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("UPDATE settings SET row_version = row_version WHERE 0"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WRITER_LOCK})


def prepare_sqlite(dbapi_connection: Any) -> None:
    """Give a new SQLite connection the functions this module's SQL calls."""
    dbapi_connection.create_function("hirdir_regexp", 2, _sqlite_regexp)
    dbapi_connection.create_function("hirdir_fold", 1, _sqlite_fold, deterministic=True)
    dbapi_connection.create_function(
        "hirdir_address_key", 1, _sqlite_address_key, deterministic=True
    )
    dbapi_connection.create_function("hirdir_today", 1, _sqlite_today)


class regex_match(FunctionElement):
    """`column` matches `pattern` somewhere, without regard to case."""

    type = Boolean()
    name = "regex_match"
    inherit_cache = True


@compiles(regex_match, "sqlite")
def _regex_match_sqlite(element: regex_match, compiler: Any, **kw: Any) -> str:
    column, pattern = list(element.clauses)
    return f"hirdir_regexp({compiler.process(pattern, **kw)}, {compiler.process(column, **kw)})"


@compiles(regex_match, "postgresql")
def _regex_match_postgresql(element: regex_match, compiler: Any, **kw: Any) -> str:
    column, pattern = list(element.clauses)
    return f"({compiler.process(column, **kw)} ~* {compiler.process(pattern, **kw)})"


def matches_regex(column: ColumnElement[Any], pattern: str) -> ColumnElement[bool]:
    """Return the test that column matches pattern. The pattern is checked first."""
    compile_pattern(pattern)
    return regex_match(column, literal(pattern))


class fold(FunctionElement):
    """A text value as it is compared when case does not count.

    Like the other functions of this module that a sort may use, it is written as
    PostgreSQL writes it unless the database is SQLite, so that a statement can be
    built before it is known which of the two will run it.
    """

    type = String()
    name = "fold"
    inherit_cache = True


@compiles(fold, "sqlite")
def _fold_sqlite(element: fold, compiler: Any, **kw: Any) -> str:
    # SQLite's own lower() folds the letters A to Z and nothing else.
    return f"hirdir_fold({compiler.process(element.clauses, **kw)})"


@compiles(fold)
@compiles(fold, "postgresql")
def _fold_postgresql(element: fold, compiler: Any, **kw: Any) -> str:
    return f"lower({compiler.process(element.clauses, **kw)})"


def folded(expression: Any) -> ColumnElement[str]:
    """Return expression as it is compared when case does not count: in lower case.

    The database lowers both sides of a comparison, so the two always agree with each
    other, in whatever alphabet.
    """
    return fold(expression)


class address_key(FunctionElement):
    """An address as it is sorted: as the number it is, and not as the text it is kept as."""

    type = String()
    name = "address_key"
    inherit_cache = True


@compiles(address_key, "sqlite")
def _address_key_sqlite(element: address_key, compiler: Any, **kw: Any) -> str:
    return f"hirdir_address_key({compiler.process(element.clauses, **kw)})"


@compiles(address_key)
@compiles(address_key, "postgresql")
def _address_key_postgresql(element: address_key, compiler: Any, **kw: Any) -> str:
    return f"CAST({compiler.process(element.clauses, **kw)} AS inet)"


def as_address(expression: Any) -> ColumnElement[Any]:
    """Return what an address is sorted by, so that 192.0.2.9 comes before 192.0.2.10.

    An IPv4 address comes before an IPv6 one, and each family is in the order of its
    numbers. The least and the greatest of several are taken of this, not of the text.
    """
    return address_key(expression)


class today_here(FunctionElement):
    """Today's date in the application's time zone, as the database works it out.

    The zone is the `time_zone` setting, read by the statement itself, so that a list
    which asks what is in force today needs nothing handed to it. It stands in a
    subquery of its own, which a statement works out once and not for every row.
    """

    type = Date()
    name = "today_here"
    inherit_cache = True


_TIME_ZONE = "(SELECT value FROM settings WHERE key = 'time_zone')"


@compiles(today_here, "sqlite")
def _today_sqlite(element: today_here, compiler: Any, **kw: Any) -> str:
    return f"(SELECT hirdir_today({_TIME_ZONE}))"


@compiles(today_here)
@compiles(today_here, "postgresql")
def _today_postgresql(element: today_here, compiler: Any, **kw: Any) -> str:
    setting = "(SELECT value #>> '{}' FROM settings WHERE key = 'time_zone')"
    return f"CAST(now() AT TIME ZONE coalesce({setting}, '{clock.DEFAULT_ZONE}') AS date)"


def today() -> ColumnElement[Any]:
    """Return today's date in the application's time zone, for a statement to compare
    a day with: what a contract covers today, which line is in date."""
    return today_here()


class days_between(FunctionElement):
    """The number of days from the second date to the first, as a whole number."""

    name = "days_between"
    inherit_cache = True


@compiles(days_between, "sqlite")
def _days_between_sqlite(element: days_between, compiler: Any, **kw: Any) -> str:
    later, earlier = list(element.clauses)
    return (
        f"CAST(julianday({compiler.process(later, **kw)}) - "
        f"julianday({compiler.process(earlier, **kw)}) AS INTEGER)"
    )


@compiles(days_between)
@compiles(days_between, "postgresql")
def _days_between_postgresql(element: days_between, compiler: Any, **kw: Any) -> str:
    later, earlier = list(element.clauses)
    return f"({compiler.process(later, **kw)} - {compiler.process(earlier, **kw)})"


class setting_number(FunctionElement):
    """The value of a setting that is a whole number, as the statement reads it from the
    settings, or the default where the setting has none: so a list that compares with
    a setting needs nothing handed to it."""

    name = "setting_number"
    inherit_cache = True


def _setting(element: setting_number, number: Any, is_number: Any) -> Any:
    key, default = list(element.clauses)
    held = (
        select(number(Setting.value))
        .where(Setting.key == key, is_number(Setting.value))
        .scalar_subquery()
    )
    return func.coalesce(held, default)


@compiles(setting_number, "sqlite")
def _setting_number_sqlite(element: setting_number, compiler: Any, **kw: Any) -> str:
    found = _setting(
        element,
        lambda value: cast(value, Integer),
        lambda value: func.json_type(value).in_(("integer", "real")),
    )
    return compiler.process(found, **kw)


@compiles(setting_number)
@compiles(setting_number, "postgresql")
def _setting_number_postgresql(element: setting_number, compiler: Any, **kw: Any) -> str:
    found = _setting(
        element,
        lambda value: cast(cast(value.op("#>>")(literal("{}")), Numeric), Integer),
        lambda value: func.json_typeof(value) == "number",
    )
    return compiler.process(found, **kw)


class setting_hundredths(FunctionElement):
    """The value of a setting that is a number of two places, in hundredths, as the
    statement reads it from the settings: blank where the setting has none. A support
    weight is kept in hundredths, so a weight in force that a default or a minimum
    decides is worked out by a list with nothing handed to it (P-155)."""

    type = BigInteger()
    name = "setting_hundredths"
    inherit_cache = True


def _hundredths(element: setting_hundredths, number: Any, is_number: Any) -> Any:
    (key,) = list(element.clauses)
    return (
        select(cast(func.round(number(Setting.value) * 100), BigInteger))
        .where(Setting.key == key, is_number(Setting.value))
        .scalar_subquery()
    )


@compiles(setting_hundredths, "sqlite")
def _setting_hundredths_sqlite(element: setting_hundredths, compiler: Any, **kw: Any) -> str:
    found = _hundredths(
        element,
        lambda value: cast(value, Float),
        lambda value: func.json_type(value).in_(("integer", "real")),
    )
    return compiler.process(found, **kw)


@compiles(setting_hundredths)
@compiles(setting_hundredths, "postgresql")
def _setting_hundredths_postgresql(element: setting_hundredths, compiler: Any, **kw: Any) -> str:
    found = _hundredths(
        element,
        lambda value: cast(value.op("#>>")(literal("{}")), Numeric),
        lambda value: func.json_typeof(value) == "number",
    )
    return compiler.process(found, **kw)


def setting_in_hundredths(key: str) -> ColumnElement[Any]:
    """Return a setting that is a number of two places, in hundredths, as the statement
    reads it: blank where it has none."""
    return setting_hundredths(literal(key))


class list_values(FunctionElement):
    """The values of a list that is kept as JSON, one to a row, in a column `value`."""

    name = "list_values"
    inherit_cache = True


@compiles(list_values, "sqlite")
def _list_values_sqlite(element: list_values, compiler: Any, **kw: Any) -> str:
    return f"json_each({compiler.process(element.clauses, **kw)})"


@compiles(list_values)
@compiles(list_values, "postgresql")
def _list_values_postgresql(element: list_values, compiler: Any, **kw: Any) -> str:
    return f"json_array_elements_text({compiler.process(element.clauses, **kw)})"


class json_number(FunctionElement):
    """A number that a JSON object kept in a column holds as text under a key, such as
    the demand of a record of the balance, as a number to sort by. The key is a bound
    value, as any value of a statement is."""

    type = Float()
    name = "json_number"
    inherit_cache = True


@compiles(json_number, "sqlite")
def _json_number_sqlite(element: json_number, compiler: Any, **kw: Any) -> str:
    column, key = (compiler.process(clause, **kw) for clause in element.clauses)
    return f"CAST(json_extract({column}, '$.' || {key}) AS REAL)"


@compiles(json_number)
@compiles(json_number, "postgresql")
def _json_number_postgresql(element: json_number, compiler: Any, **kw: Any) -> str:
    column, key = (compiler.process(clause, **kw) for clause in element.clauses)
    return f"CAST(({column} ->> {key}) AS double precision)"


def number_in_json(column: Any, key: str) -> ColumnElement[Any]:
    """Return the number a JSON column holds as text under a key, to sort by."""
    return json_number(column, literal(key))


def least_of_list(column: Any) -> ColumnElement[Any]:
    """Return the least text of a column that holds a list, as it is compared when case
    does not count. A list that holds nothing has none, and is blank."""
    values = list_values(column).table_valued("value")
    return select(func.min(folded(values.c.value))).scalar_subquery()


def equals_text(column: ColumnElement[Any], value: str) -> ColumnElement[bool]:
    """Return the test that column equals value, ignoring case."""
    return folded(column) == folded(literal(value))


def _escaped(text: str) -> str:
    for special in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(special, LIKE_ESCAPE + special)
    return text


def _like(column: ColumnElement[Any], pattern: str) -> ColumnElement[bool]:
    return folded(column).like(folded(literal(pattern)), escape=LIKE_ESCAPE)


def contains_text(column: ColumnElement[Any], value: str) -> ColumnElement[bool]:
    """Return the test that column holds value somewhere in it, ignoring case."""
    return _like(column, f"%{_escaped(value)}%")


def starts_with_text(column: ColumnElement[Any], value: str) -> ColumnElement[bool]:
    """Return the test that column begins with value, ignoring case."""
    return _like(column, f"{_escaped(value)}%")


def matches_glob(column: ColumnElement[Any], pattern: str) -> ColumnElement[bool]:
    """Return the test that column matches a pattern of `*` and `?`, ignoring case."""
    like = "".join(
        "%" if character == "*" else "_" if character == "?" else _escaped(character)
        for character in pattern
    )
    return _like(column, like)


def blanks_last(expression: ColumnElement[Any], descending: bool) -> list[ColumnElement[Any]]:
    """Return the ORDER BY terms that sort by expression with blank values at the end.

    Left alone, SQLite puts NULL first and PostgreSQL puts it last. Both say where it
    goes with NULLS LAST, in one term, so that a value that is worked out for each row,
    such as a count of what covers an item, is worked out once and not twice.
    """
    ordered = expression.desc() if descending else expression.asc()
    return [ordered.nulls_last()]


def count_of(rows: Any) -> Any:
    """Return the statement that counts the rows another statement reads.

    A list is joined to what its fields read, each join to one record at most, and the
    rows are counted under the same filter. SQLite leaves out of a statement the joins
    that nothing in it reads, but not out of a count, and it folds a subquery that is
    counted into the count. Asked to materialize the rows first, it plans them as the
    statement they are. PostgreSQL leaves such joins out of a count by itself.
    """
    return select(func.count()).select_from(materialized(rows, "counted"))


def materialized(rows: Any, name: str) -> Any:
    """Return the rows a statement reads as a table of their own, which SQLite works
    out once before it reads them: see `count_of`."""
    return rows.cte(name).prefix_with("MATERIALIZED", dialect="sqlite")
