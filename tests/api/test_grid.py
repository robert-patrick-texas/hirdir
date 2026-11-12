"""The item list as the grid uses it: filtering, sorting and paging on the server."""

import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import dialect, migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit
from tests.api.inventory import Maker, errors
from tests.conftest import INVENTORY_CODE, sign_in


@pytest.fixture(scope="module")
def stocked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Maker]:
    """A small, fictional inventory with something for every operator to find.

    It is made once for this module. The tests that use it only read.
    """
    config = Config(state_dir=tmp_path_factory.mktemp("grid"), trusted_proxies=("testclient",))
    migrate.upgrade(config.database_url)
    with make_sessions(make_engine(config.database_url))() as session:
        user, _ = accounts.create_user(
            session, audit.SYSTEM, username="ivy", access_code=INVENTORY_CODE
        )
        accounts.grant_role(session, audit.SYSTEM, role="inventory", user_hid=user.hid)
        session.commit()
    with TestClient(create_app(config)) as client:
        make = Maker(client, sign_in(client, "ivy", INVENTORY_CODE))
        _stock(make)
        yield make


def _stock(make: Maker) -> None:
    cisco, juniper = make.vendor("Cisco"), make.vendor("Juniper")
    c9300 = make.entry(
        cisco, "C9300-48P", type="switch", function="access", est_value="18000", ldos="2034-04-30"
    )
    c9500 = make.entry(
        cisco, "C9500-24Y4C", type="switch", function="core", est_value="42000", ldos="2036-10-31"
    )
    ex4400 = make.entry(juniper, "EX4400-48P", type="switch", function="access", est_value="15000")
    netops, lab = make.owner("Network Engineering"), make.owner("Lab Team")
    for label in ("refresh-2030", "core"):
        make.tag(label)

    def add(name: str, entry: dict, serial: str, state: str | None, **more: object) -> None:
        standing = {"lifecycle_state": state} if state else {}
        make.item(
            hostname=name, catalog_entry_hid=entry["hid"], serial_number=serial, **standing, **more
        )

    add("site2-sw-core-01", c9500, "FCW0000X001", "Prod", owner_hid=netops["hid"], tags=["core"])
    add(
        "site2-sw-core-02",
        c9500,
        "FCW0000X002",
        "Test",
        owner_hid=netops["hid"],
        mac_address="00:00:5e:00:53:02",
        est_value="45000",
        tags=["core", "refresh-2030"],
    )
    add("site2-sw-dist-01", c9300, "FCW0000X003", "Prod", owner_hid=netops["hid"])
    add("site2-sw-access-01", c9300, "FCW0000X004", "Prod", tags=["refresh-2030"])
    add("site2-sw-access-02", ex4400, "JN0000X005", "Assigned", mac_address="00005e0053aa")
    add("site3-sw-access-01", ex4400, "JN0000X006", "Delivered", owner_hid=lab["hid"])
    add("lab-sw-01", ex4400, "JN0000X007", None, owner_hid=lab["hid"], ldos="2031-01-31")
    make.item(name="Fluke tester", asset_tag="AT-000900", comments="100% charged_ok")


def test_default_order_is_by_name_with_the_hostname_standing_in(stocked: Maker) -> None:
    assert stocked.found() == [
        "Fluke tester",
        "lab-sw-01",
        "site2-sw-access-01",
        "site2-sw-access-02",
        "site2-sw-core-01",
        "site2-sw-core-02",
        "site2-sw-dist-01",
        "site3-sw-access-01",
    ]


@pytest.mark.parametrize(
    ("short", "expected"),
    [
        ("lifecycle_state:eq:prod", ["site2-sw-access-01", "site2-sw-core-01", "site2-sw-dist-01"]),
        ("lifecycle_state:in:Test,Assigned", ["site2-sw-access-02", "site2-sw-core-02"]),
        ("lifecycle_state:empty:true", ["Fluke tester", "lab-sw-01"]),
        ("lifecycle_state:ne:Prod name:prefix:SITE3", ["site3-sw-access-01"]),
        ("catalog.pid:glob:C95*", ["site2-sw-core-01", "site2-sw-core-02"]),
        (
            "catalog.pid:glob:?X4400-48P owner.label:eq:lab team",
            ["lab-sw-01", "site3-sw-access-01"],
        ),
        (
            "catalog.vendor:eq:juniper lifecycle_state:empty:false",
            ["site2-sw-access-02", "site3-sw-access-01"],
        ),
        ("catalog.function:eq:core", ["site2-sw-core-01", "site2-sw-core-02"]),
        (
            "hostname:regex:^site2-sw-(core|dist)-[0-9]+$",
            ["site2-sw-core-01", "site2-sw-core-02", "site2-sw-dist-01"],
        ),
        ("hostname:regex:CORE", ["site2-sw-core-01", "site2-sw-core-02"]),
        (
            "hostname:contains:-sw-access-",
            ["site2-sw-access-01", "site2-sw-access-02", "site3-sw-access-01"],
        ),
        ("comments:contains:100%", ["Fluke tester"]),
        ("comments:contains:d_o", ["Fluke tester"]),
        ("comments:contains:dxo", []),
        ("tags:has:refresh-2030", ["site2-sw-access-01", "site2-sw-core-02"]),
        ("tags:has:core tags:has:refresh-2030", ["site2-sw-core-02"]),
        ("tags:empty:false owner_hid:empty:true", ["site2-sw-access-01"]),
        ("mac_address:eq:00-00-5E-00-53-02", ["site2-sw-core-02"]),
        ("mac_address:contains:5e00.53", ["site2-sw-access-02", "site2-sw-core-02"]),
        ("mac_address:prefix:0000.5e00.53a", ["site2-sw-access-02"]),
        ("serial_number:prefix:jn", ["lab-sw-01", "site2-sw-access-02", "site3-sw-access-01"]),
        ("asset_tag:eq:at-000900", ["Fluke tester"]),
        (
            "expected_online:eq:true",
            ["site2-sw-access-01", "site2-sw-core-01", "site2-sw-core-02", "site2-sw-dist-01"],
        ),
        ("effective.est_value:gte:42000", ["site2-sw-core-01", "site2-sw-core-02"]),
        (
            "effective.est_value:between:15000,18000 lifecycle_state:eq:Prod",
            ["site2-sw-access-01", "site2-sw-dist-01"],
        ),
        ("est_value:empty:false", ["site2-sw-core-02"]),
        ("effective.ldos:lt:2035-01-01", ["lab-sw-01", "site2-sw-access-01", "site2-sw-dist-01"]),
        ("effective.ldos:empty:true", ["Fluke tester", "site2-sw-access-02", "site3-sw-access-01"]),
        ("quantity:eq:1 disposition:eq:staging", ["site2-sw-access-02", "site2-sw-core-02"]),
    ],
)
def test_short_filters_find_the_right_rows(stocked: Maker, short: str, expected: list[str]) -> None:
    assert stocked.found(filter=short) == expected


def test_filter_tree_combines_with_and_and_or(stocked: Maker) -> None:
    tree = {
        "and": [
            {"field": "lifecycle_state", "op": "in", "value": ["Test", "Prod"]},
            {
                "or": [
                    {"field": "catalog.pid", "op": "glob", "value": "C9300*"},
                    {"field": "tags", "op": "has", "value": "core"},
                ]
            },
            {"field": "effective.ldos", "op": "lt", "value": "2037-01-01"},
        ]
    }
    expected = ["site2-sw-access-01", "site2-sw-core-01", "site2-sw-core-02", "site2-sw-dist-01"]
    page = stocked.post("/items/query", {"filter": tree, "sort": ["name"]}, 200)
    assert [row["hostname"] for row in page["items"]] == expected
    # The same tree as JSON text in the URL finds the same rows.
    assert stocked.found(filter=json.dumps(tree)) == expected


def test_sort_by_any_column_keeps_blanks_last_both_ways(stocked: Maker) -> None:
    by_value = stocked.found(sort="effective.est_value,name")
    assert by_value[:3] == ["lab-sw-01", "site2-sw-access-02", "site3-sw-access-01"]
    assert by_value[-1] == "Fluke tester"
    assert stocked.found(sort="-effective.est_value,name")[:2] == [
        "site2-sw-core-02",
        "site2-sw-core-01",
    ]
    assert stocked.found(sort="-effective.est_value,name")[-1] == "Fluke tester"
    assert stocked.found(sort="catalog.vendor,-serial_number", limit=3) == [
        "site2-sw-access-01",
        "site2-sw-dist-01",
        "site2-sw-core-02",
    ]
    assert stocked.found(sort=["owner.label", "-name"], limit=2) == [
        "site3-sw-access-01",
        "lab-sw-01",
    ]


def test_paging_covers_every_row_once(stocked: Maker) -> None:
    seen: list[str] = []
    for offset in range(0, 9, 3):
        page = stocked.get("/items", sort="lifecycle_state", limit=3, offset=offset)
        assert (page["total"], page["limit"], page["offset"]) == (8, 3, offset)
        seen += [row["hid"] for row in page["items"]]
    assert len(seen) == len(set(seen)) == 8
    assert "query.limit" in errors(stocked.get("/items", 422, limit=1001))


@pytest.mark.parametrize(
    ("short", "says"),
    [
        ("nope:eq:1", "nope is not a field"),
        ("hostname:within:Americas", "hostname does not take within"),
        ("lifecycle_state:regex:^P", "lifecycle_state does not take regex"),
        ("quantity:contains:1", "quantity does not take contains"),
        ("quantity:gt:many", "a whole number"),
        ("effective.ldos:lt:tomorrow", "a date"),
        ("effective.est_value:between:1", "two values"),
        ("expected_online:eq:maybe", "true or false"),
        ("mac_address:contains:xyz", "a MAC address or part of one"),
        ("hostname:regex:(unclosed", "cannot be compiled"),
        ("hostname:regex:" + "a" * 201, "at most 200 characters"),
        ("just some words", "the short form is field:op:value"),
        ('{"field": "hostname"}', "an object with field, op and value"),
        ('{"and": []}', "one or more parts"),
        ("{not json", "not well-formed JSON"),
    ],
)
def test_bad_filter_is_refused_and_says_why(stocked: Maker, short: str, says: str) -> None:
    problem = stocked.get("/items", 422, filter=short)
    assert says in errors(problem)["filter"], problem
    assert stocked.get("/items")["total"] == 8


def test_bad_sort_is_refused(stocked: Maker) -> None:
    assert "tags is not a field" in errors(stocked.get("/items", 422, sort="tags"))["sort"]
    assert "sort" in errors(stocked.get("/items", 422, sort="-nope"))


def test_pattern_that_backtracks_without_end_is_refused_in_time(make: Maker) -> None:
    make.item(name="lab-sw-01")
    make.item(name="long-comment", comments="a" * 5000 + "b")
    started = time.monotonic()
    problem = make.get("/items", 422, filter="comments:regex:(a|aa)+$")
    assert "takes too long" in errors(problem)["filter"]
    assert time.monotonic() - started < 2 * dialect.REGEX_REQUEST_SECONDS + 1
    # The server and the database are as they were.
    assert make.found(filter="name:regex:^lab-") == ["lab-sw-01"]
