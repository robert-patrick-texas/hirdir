"""The filter grammar: reading both forms, and refusing what a list does not allow."""

import json
from pathlib import Path

import pytest
from sqlalchemy import (
    JSON,
    Column,
    ColumnElement,
    Date,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects import postgresql

from hirdir.db import dialect
from hirdir.domain.errors import Invalid
from hirdir.io import filters
from hirdir.io.filters import Branch, Condition, Field

ROOT = Path(__file__).resolve().parents[2]

things = Table(
    "things",
    MetaData(),
    Column("name", String),
    Column("size", Integer),
    Column("made_on", Date),
)
FIELDS = {
    "name": Field("text", things.c.name),
    "size": Field("integer", things.c.size),
    "made_on": Field("date", things.c.made_on),
}
ROWS = [
    {"name": "Alpha", "size": 1, "made_on": None},
    {"name": "beta_1", "size": 20, "made_on": None},
    {"name": "Gamma 50%", "size": None, "made_on": None},
    {"name": None, "size": 3, "made_on": None},
]


def found(source: object) -> list[str | None]:
    engine = create_engine("sqlite://")
    things.metadata.create_all(engine)
    with engine.connect() as connection:
        dialect.prepare_sqlite(connection.connection.dbapi_connection)
        connection.execute(things.insert(), ROWS)
        where = filters.to_sql(filters.parse(source), FIELDS)
        return list(connection.scalars(select(things.c.name).where(where).order_by(things.c.size)))


def test_short_form_reads_conditions_joined_by_and() -> None:
    assert filters.parse("name:eq:alpha") == Condition("name", "eq", "alpha")
    assert filters.parse(" lifecycle_state:in:Test, Prod   hostname:prefix:site2- ") == Branch(
        "and",
        (
            Condition("lifecycle_state", "in", ["Test", "Prod"]),
            Condition("hostname", "prefix", "site2-"),
        ),
    )


def test_short_form_value_may_hold_spaces_and_colons() -> None:
    parsed = filters.parse("location:within:Americas > Central name:regex:^a:b c$")
    assert parsed == Branch(
        "and",
        (
            Condition("location", "within", "Americas > Central"),
            Condition("name", "regex", "^a:b c$"),
        ),
    )


def test_nothing_is_no_filter() -> None:
    assert filters.parse(None) is None
    assert filters.parse("   ") is None
    assert len(found(None)) == len(ROWS)


def test_tree_and_json_text_read_the_same() -> None:
    tree = {
        "or": [
            {"field": "name", "op": "eq", "value": "ALPHA"},
            {"field": "size", "op": "gt", "value": 5},
        ]
    }
    assert filters.parse(tree) == filters.parse(json.dumps(tree))
    assert found(tree) == ["Alpha", "beta_1"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("name:eq:ALPHA", ["Alpha"]),
        ("name:ne:alpha", ["Gamma 50%", None, "beta_1"]),
        ("name:in:alpha,BETA_1", ["Alpha", "beta_1"]),
        ("name:contains:a_1", ["beta_1"]),
        ("name:contains:0%", ["Gamma 50%"]),
        ("name:prefix:GAM", ["Gamma 50%"]),
        ("name:glob:*a", ["Alpha"]),
        ("name:glob:?eta_?", ["beta_1"]),
        ("name:glob:*_*", ["beta_1"]),
        ("name:regex:^(alpha|gamma)", ["Gamma 50%", "Alpha"]),
        ("name:empty:true", [None]),
        ("size:empty:true", ["Gamma 50%"]),
        ("size:between:2,20", [None, "beta_1"]),
        ("size:lte:3", ["Alpha", None]),
        ("size:ne:3", ["Gamma 50%", "Alpha", "beta_1"]),
        ("size:in:1,3", ["Alpha", None]),
    ],
)
def test_operators(source: str, expected: list[str | None]) -> None:
    assert sorted(found(source), key=str) == sorted(expected, key=str)


@pytest.mark.parametrize(
    "source",
    [
        "colour:eq:red",
        "name:has:x",
        "name:lt:b",
        "size:glob:1*",
        "size:eq:big",
        "size:between:1,2,3",
        "size:in:",
        "made_on:gt:2026-13-01",
        "name:regex:(",
        "name:regex:(?:a{1000}){1000}",
        "name:eq:a size:is:3",
        "size:eq:1.5",
        {"field": "name", "op": "eq"},
        {"field": "name", "op": "eq", "value": ["a"]},
        {"field": "name", "op": "like", "value": "a"},
        {"field": "name", "op": "eq", "value": "a", "extra": 1},
        {"and": [{"field": "name", "op": "eq", "value": "a"}], "or": []},
        {"not": {"field": "name", "op": "eq", "value": "a"}},
        ["name", "eq", "a"],
        "{}",
    ],
)
def test_what_is_refused(source: object) -> None:
    with pytest.raises(Invalid) as refused:
        filters.to_sql(filters.parse(source), FIELDS)
    assert "filter" in refused.value.fields


def test_depth_and_size_are_bounded() -> None:
    leaf: dict = {"field": "name", "op": "eq", "value": "a"}
    deep = leaf
    for _ in range(filters.MAX_DEPTH):
        deep = {"and": [deep]}
    assert filters.parse(deep) is not None
    with pytest.raises(Invalid, match="not acceptable") as refused:
        filters.parse({"or": [deep]})
    assert "nests at most" in refused.value.fields["filter"]
    with pytest.raises(Invalid) as refused:
        filters.parse({"or": [leaf] * (filters.MAX_CONDITIONS + 1)})
    assert "at most" in refused.value.fields["filter"]


def test_sort_reads_names_and_directions_once_each() -> None:
    keys = filters.parse_sort(["name,-size", " +made_on ", "-name", ""], FIELDS)
    assert [(key.field, key.descending) for key in keys] == [
        ("name", False),
        ("size", True),
        ("made_on", False),
    ]
    with pytest.raises(Invalid) as refused:
        filters.parse_sort(["colour"], FIELDS)
    assert "sort" in refused.value.fields


def test_a_field_of_several_values_is_sorted_by_only_when_it_says_by_what() -> None:
    def some(condition: ColumnElement[bool]) -> ColumnElement[bool]:
        return condition

    several = Field("text", things.c.name, among=some)
    least = Field("text", things.c.name, among=some, ordered_by=things.c.size)
    only_sorted = Field("integer", ordered_by=things.c.size)
    known = {**FIELDS, "several": several, "least": least, "only_sorted": only_sorted}

    assert not filters.sorted_by(several)
    assert filters.sorted_by(least)
    assert filters.sorted_by(only_sorted)
    with pytest.raises(Invalid) as refused:
        filters.parse_sort(["several"], known)
    assert "several is not a field this list can be sorted by" in refused.value.fields["sort"]
    keys = filters.parse_sort(["least", "-only_sorted"], known)
    # What it is sorted by is taken as it is given, with the blanks last.
    assert [str(term) for term in filters.order_by(keys, known)] == [
        "things.size IS NULL ASC",
        "things.size ASC",
        "things.size IS NULL ASC",
        "things.size DESC",
    ]
    # A field that is only sorted by is no field of a filter.
    with pytest.raises(Invalid) as refused:
        filters.to_sql(filters.parse("only_sorted:eq:1"), known)
    assert "only_sorted is not a field" in refused.value.fields["filter"]


def test_addresses_are_put_in_order_as_addresses_and_a_list_by_its_least_text() -> None:
    held = Table("held", MetaData(), Column("address", String), Column("names", JSON))
    rows = [
        {"address": "192.0.2.10", "names": ["zed", "Beta"]},
        {"address": "2001:db8::2", "names": []},
        {"address": "192.0.2.9", "names": ["alpha"]},
        {"address": "2001:db8::10", "names": ["Émile", "éclair"]},
        {"address": "198.51.100.1", "names": ["Charlie"]},
    ]
    engine = create_engine("sqlite://")
    held.metadata.create_all(engine)
    with engine.connect() as connection:
        dialect.prepare_sqlite(connection.connection.dbapi_connection)
        connection.execute(held.insert(), rows)
        as_address = dialect.as_address(held.c.address)
        in_order = list(connection.scalars(select(held.c.address).order_by(as_address)))
        least_of_all = select(func.min(as_address)).scalar_subquery()
        lowest = connection.scalar(select(held.c.address).where(as_address == least_of_all))
        least = dialect.least_of_list(held.c.names)
        by_names = list(
            connection.scalars(
                select(held.c.address).order_by(*dialect.blanks_last(least, descending=False))
            )
        )
    # By the number an address is, every IPv4 one before any IPv6 one.
    assert in_order == ["192.0.2.9", "192.0.2.10", "198.51.100.1", "2001:db8::2", "2001:db8::10"]
    assert lowest == "192.0.2.9"
    # By the least of its names in any alphabet, and a list of none last.
    assert by_names == ["192.0.2.9", "192.0.2.10", "198.51.100.1", "2001:db8::10", "2001:db8::2"]
    # PostgreSQL is told the same in its own words.
    written = str(select(as_address, least).compile(dialect=postgresql.dialect()))
    assert "CAST(held.address AS inet)" in written
    assert "SELECT min(lower(" in written
    assert "FROM json_array_elements_text(held.names) AS " in written


def test_the_published_schema_names_the_same_operators() -> None:
    schema = json.loads((ROOT / "contract" / "filter.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["condition"]["properties"]["op"]["enum"] == list(filters.OPERATORS)
