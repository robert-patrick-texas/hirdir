"""Everything that differs between SQLite and PostgreSQL lives in this module.

Comparison without regard to case, wildcard and regular expression matching, and where
blank values fall in a sorted list. The rest of the code builds its SQL from these and
never asks which database it is talking to.

Regular expressions are bounded. A pattern has a longest length and a limit on how far
its counted repeats multiply, each match has a time limit, and one request has a budget
for all its matches together. So a pattern that is costly to compile is refused before
it is compiled, and one that backtracks without end costs a refused request and never a
stalled server. The engine is the `regex` package, which offers the per-match time
limit. See P-19 in docs/decisions.md for when RE2 takes its place.
"""

import re
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import regex
from sqlalchemy import Boolean, ColumnElement, String, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

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
    return None if value is None else str(value).casefold()


def prepare_sqlite(dbapi_connection: Any) -> None:
    """Give a new SQLite connection the functions this module's SQL calls."""
    dbapi_connection.create_function("hirdir_regexp", 2, _sqlite_regexp)
    dbapi_connection.create_function("hirdir_fold", 1, _sqlite_fold, deterministic=True)


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
    """A text value as it is compared when case does not count."""

    type = String()
    name = "fold"
    inherit_cache = True


@compiles(fold, "sqlite")
def _fold_sqlite(element: fold, compiler: Any, **kw: Any) -> str:
    # SQLite's own lower() folds the letters A to Z and nothing else.
    return f"hirdir_fold({compiler.process(element.clauses, **kw)})"


@compiles(fold, "postgresql")
def _fold_postgresql(element: fold, compiler: Any, **kw: Any) -> str:
    return f"lower({compiler.process(element.clauses, **kw)})"


def folded(expression: Any) -> ColumnElement[str]:
    """Return expression as it is compared when case does not count.

    The database folds both sides of a comparison, so the two always agree with each
    other, in whatever alphabet.
    """
    return fold(expression)


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

    Left alone, SQLite puts NULL first and PostgreSQL puts it last.
    """
    ordered = expression.desc() if descending else expression.asc()
    return [expression.is_(None).asc(), ordered]
