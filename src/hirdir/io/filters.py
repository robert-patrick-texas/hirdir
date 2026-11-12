"""The filter grammar: one way to say which records are wanted, for every front door.

A filter is a tree. A leaf is a condition, `{"field": ..., "op": ..., "value": ...}`,
and a branch is `{"and": [...]}` or `{"or": [...]}`. The short form used on a command
line and in a URL is conditions written `field:op:value`, separated by spaces and
joined by AND. A list route says which fields it allows; this module checks a filter
against them and turns it into SQL.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement, and_, false, literal, or_, true

from hirdir.db import dialect
from hirdir.domain.errors import Invalid

MAX_DEPTH = 8
MAX_CONDITIONS = 100
MAX_LIST = 1000

COMPARING = ("eq", "ne", "in", "empty")
ORDERING = ("lt", "lte", "gt", "gte", "between")
MATCHING = ("contains", "prefix", "glob", "regex")
OPERATORS = (*COMPARING, *MATCHING, *ORDERING, "has", "within")

# The operators each kind of field takes.
KINDS: dict[str, tuple[str, ...]] = {
    "text": (*COMPARING, *MATCHING),
    "choice": COMPARING,
    "reference": COMPARING,
    "mac": (*COMPARING, "contains", "prefix"),
    "number": (*COMPARING, *ORDERING),
    "integer": (*COMPARING, *ORDERING),
    "date": (*COMPARING, *ORDERING),
    "timestamp": (*COMPARING, *ORDERING),
    "boolean": ("eq", "ne", "empty"),
    "tags": ("has", "empty"),
}


@dataclass(frozen=True)
class Field:
    """One field a list may be filtered and sorted by.

    `expression` is the SQL that yields its value. A field of kind `tags` has none:
    `test` builds the condition that a record carries the tag with a label, or any tag
    at all when the label is blank. `convert` turns one value of a filter into the form
    the column is compared with, when the kind alone does not say how, and raises
    ValueError for a value it cannot take.
    """

    kind: str
    expression: Any = None
    test: Callable[[str], ColumnElement[bool]] | None = None
    convert: Callable[[str], Any] | None = None


@dataclass(frozen=True)
class Condition:
    """One test of one field."""

    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class Branch:
    """Conditions joined by AND or by OR."""

    joined_by: str
    parts: tuple[Condition | Branch, ...]


Node = Condition | Branch


def refuse(message: str) -> Invalid:
    """Return the error for a filter that is not acceptable."""
    return Invalid("the filter is not acceptable", {"filter": message})


# --- reading a filter ----------------------------------------------------------------


def _node(source: Any, depth: int, count: list[int]) -> Node:
    if not isinstance(source, dict):
        raise refuse("each part is an object with field, op and value, or with and, or or")
    if depth > MAX_DEPTH:
        raise refuse(f"a filter nests at most {MAX_DEPTH} deep")
    keys = set(source)
    for joined_by in ("and", "or"):
        if keys == {joined_by}:
            parts = source[joined_by]
            if not isinstance(parts, list) or not parts:
                raise refuse(f"'{joined_by}' takes a list of one or more parts")
            return Branch(joined_by, tuple(_node(part, depth + 1, count) for part in parts))
    if "field" not in keys or "op" not in keys or not keys <= {"field", "op", "value"}:
        raise refuse("each part is an object with field, op and value, or with and, or or")
    field, op = source["field"], source["op"]
    if not isinstance(field, str) or not isinstance(op, str):
        raise refuse("field and op are text")
    count[0] += 1
    if count[0] > MAX_CONDITIONS:
        raise refuse(f"a filter has at most {MAX_CONDITIONS} conditions")
    return Condition(field.strip(), op.strip().lower(), source.get("value"))


def from_tree(source: Any) -> Node:
    """Read a filter from its JSON form, already decoded."""
    return _node(source, 1, [0])


_SHORT = re.compile(rf"(?:^|\s+)([A-Za-z_][A-Za-z0-9_.]*):({'|'.join(OPERATORS)}):")


def from_short(text: str) -> Node:
    """Read a filter from its short form: `field:op:value` conditions joined by AND.

    A value runs to the start of the next condition, so it may hold spaces. The values
    of `in` and `between` are separated by commas.
    """
    text = text.strip()
    starts = list(_SHORT.finditer(text))
    if not starts or starts[0].start() != 0:
        raise refuse("the short form is field:op:value, with a space between conditions")
    conditions: list[Node] = []
    for place, match in enumerate(starts):
        end = starts[place + 1].start() if place + 1 < len(starts) else len(text)
        value: Any = text[match.end() : end].strip()
        op = match[2]
        if op in ("in", "between"):
            value = [part.strip() for part in value.split(",")]
        conditions.append(Condition(match[1], op, value))
    if len(conditions) > MAX_CONDITIONS:
        raise refuse(f"a filter has at most {MAX_CONDITIONS} conditions")
    return conditions[0] if len(conditions) == 1 else Branch("and", tuple(conditions))


def parse(source: Any) -> Node | None:
    """Read a filter in whichever form it came: a decoded tree, JSON text or the short form.

    Nothing, or blank text, is no filter at all.
    """
    if source is None:
        return None
    if isinstance(source, str):
        text = source.strip()
        if not text:
            return None
        if not text.startswith("{"):
            return from_short(text)
        try:
            source = json.loads(text)
        except ValueError:
            raise refuse("the filter is not well-formed JSON") from None
    return from_tree(source)


# --- turning a filter into SQL -------------------------------------------------------


def _truth(value: Any, what: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise refuse(f"{what} takes true or false")


def _converted(field: Field, name: str, value: Any) -> Any:
    """Return one value of a condition in the form its field is compared with."""
    if isinstance(value, list | dict) or value is None:
        raise refuse(f"{name} is compared with a single value")
    kind = field.kind
    if kind == "boolean":
        return _truth(value, name)
    text = str(value).strip() if not isinstance(value, bool) else ""
    try:
        if field.convert is not None:
            return field.convert(text)
        if kind == "number":
            number = Decimal(text)
            if not number.is_finite():
                raise ValueError
            return number
        if kind == "integer":
            return int(text)
        if kind == "date":
            return date.fromisoformat(text)
        if kind == "timestamp":
            moment = datetime.fromisoformat(text)
            return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    except ValueError, InvalidOperation, ArithmeticError:
        expected = {
            "number": "a number",
            "integer": "a whole number",
            "date": "a date, as YYYY-MM-DD",
            "timestamp": "a date and time in ISO 8601",
            "mac": "a MAC address or part of one",
        }.get(kind, "a value it can hold")
        raise refuse(f"{name} is compared with {expected}") from None
    if not isinstance(value, str):
        raise refuse(f"{name} is compared with text")
    return value.strip()


def _is_text(field: Field) -> bool:
    return field.kind in ("text", "choice", "reference", "mac")


def _equal(field: Field, value: Any) -> ColumnElement[bool]:
    if _is_text(field):
        return dialect.equals_text(field.expression, value)
    return field.expression == literal(value, type_=field.expression.type)


def _condition(condition: Condition, fields: Mapping[str, Field]) -> ColumnElement[bool]:
    name, op, value = condition.field, condition.op, condition.value
    field = fields.get(name)
    if field is None:
        raise refuse(f"{name} is not a field this list can be filtered by")
    if op not in OPERATORS:
        raise refuse(f"{op} is not an operator; the operators are {', '.join(OPERATORS)}")
    if op not in KINDS[field.kind]:
        raise refuse(f"{name} does not take {op}; it takes {', '.join(KINDS[field.kind])}")

    if field.kind == "tags":
        if field.test is None:
            raise refuse(f"{name} cannot be filtered here")
        if op == "has":
            if not isinstance(value, str) or not value.strip():
                raise refuse(f"{name} has takes the label of one tag")
            return field.test(value.strip())
        tagged = field.test("")
        return ~tagged if _truth(value, f"{name} empty") else tagged

    column = field.expression
    if op == "empty":
        blank = column.is_(None)
        return blank if _truth(value, f"{name} empty") else ~blank
    if op == "in":
        if not isinstance(value, list) or not value:
            raise refuse(f"{name} in takes a list of one or more values")
        if len(value) > MAX_LIST:
            raise refuse(f"a list holds at most {MAX_LIST} values")
        return or_(*(_equal(field, _converted(field, name, entry)) for entry in value))
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise refuse(f"{name} between takes two values, the lowest first")
        low, high = (literal(_converted(field, name, entry), type_=column.type) for entry in value)
        return and_(column >= low, column <= high)

    wanted = _converted(field, name, value)
    if op == "eq":
        return _equal(field, wanted)
    if op == "ne":
        return or_(column.is_(None), ~_equal(field, wanted))
    if op in ORDERING:
        bound = literal(wanted, type_=column.type)
        return {"lt": column < bound, "lte": column <= bound, "gt": column > bound}.get(
            op, column >= bound
        )
    if op == "contains":
        return dialect.contains_text(column, wanted)
    if op == "prefix":
        return dialect.starts_with_text(column, wanted)
    if op == "glob":
        return dialect.matches_glob(column, wanted)
    try:
        return dialect.matches_regex(column, wanted)
    except dialect.PatternError as error:
        raise refuse(str(error)) from None


def to_sql(node: Node | None, fields: Mapping[str, Field]) -> ColumnElement[bool]:
    """Return the SQL condition of a filter, checked against the fields a list allows."""
    if node is None:
        return true()
    if isinstance(node, Condition):
        return _condition(node, fields)
    parts = [to_sql(part, fields) for part in node.parts]
    if node.joined_by == "and":
        return and_(true(), *parts)
    return or_(false(), *parts)


@dataclass(frozen=True)
class SortKey:
    """One field to sort by, and in which direction."""

    field: str
    descending: bool


def parse_sort(source: list[str] | None, fields: Mapping[str, Field]) -> list[SortKey]:
    """Read a sort: field names, each with `-` in front for descending order.

    Names may come one to an entry or several to an entry with commas between.
    """
    keys: list[SortKey] = []
    for entry in source or []:
        for part in str(entry).split(","):
            name = part.strip()
            if not name:
                continue
            descending = name.startswith("-")
            name = name.lstrip("+-").strip()
            field = fields.get(name)
            if field is None or field.expression is None:
                raise Invalid(
                    "the sort is not acceptable",
                    {"sort": f"{name} is not a field this list can be sorted by"},
                )
            if all(key.field != name for key in keys):
                keys.append(SortKey(name, descending))
    return keys


def order_by(keys: list[SortKey], fields: Mapping[str, Field]) -> list[ColumnElement[Any]]:
    """Return the ORDER BY terms of a sort. Text sorts without regard to case."""
    terms: list[ColumnElement[Any]] = []
    for key in keys:
        field = fields[key.field]
        expression = dialect.folded(field.expression) if _is_text(field) else field.expression
        terms += dialect.blanks_last(expression, key.descending)
    return terms
