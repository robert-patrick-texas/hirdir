"""The item list as the grid uses it: filtering, sorting and paging on the server."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import dialect, migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit
from hirdir.io import fields, filters, listing, tables
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
    # Which group, by its HID, has no order, and neither has a place: its name has.
    for name in ("group.hid", "location", "nope"):
        problem = stocked.get("/items", 422, sort=f"-{name}")
        assert f"{name} is not a field this list can be sorted by" in errors(problem)["sort"]
    # What is worked out for a column to be sorted by is no field of the filter.
    problem = stocked.get("/items", 422, filter="mgmt_address:eq:192.0.2.20")
    assert "mgmt_address is not a field" in errors(problem)["filter"]


def test_a_column_of_several_values_is_sorted_by_the_least_of_them(make: Maker) -> None:
    for label in ("Zulu", "beta", "alpha", "Charlie"):
        make.tag(label)
    red, blue, green = make.network("Red"), make.network("blue"), make.network("Green")
    # a has two of everything, and the one that counts is never the one that came first.
    a = make.item(name="a", tags=["Zulu", "beta"])
    b = make.item(name="b", tags=["alpha"])
    c = make.item(name="c", tags=["Charlie"])
    d = make.item(name="d")
    make.address(a, "192.0.2.20", red, is_primary=True)
    make.address(a, "192.0.2.9", blue, role="secondary")
    make.address(b, "192.0.2.100", green, is_primary=True)
    make.address(c, "2001:db8::5", is_primary=True)
    make.address(c, "192.0.2.5", role="secondary")
    make.group("site2-wlc-ha", "cluster", [(a, "active")])
    make.group("Bench", "custom", [(a, "member")])
    make.stack("alpha-stack", [b])
    make.group("Zoo", "custom", [(c, "member")])
    # A group that d has left is none of its groups.
    left = make.group("Aardvark", "custom", [(d, "member")])
    membership = make.members(left)[0]
    make.patch(
        f"/device-groups/{left['hid']}/members/{membership['hid']}",
        {"row_version": membership["row_version"], "left_on": "2099-01-01"},
    )

    def by(field: str) -> tuple[list[str], list[str]]:
        return make.found(sort=f"{field},name"), make.found(sort=f"-{field},name")

    # The first label without regard to case, and an item with none last either way.
    assert by("tags") == (["b", "a", "c", "d"], ["c", "a", "b", "d"])
    # The first group by name, bench before site2-wlc-ha, and the first of their types.
    assert by("group.name") == (["b", "a", "c", "d"], ["c", "a", "b", "d"])
    assert by("group.type") == (["a", "c", "b", "d"], ["b", "c", "a", "d"])
    # The lowest address, as an address: .5, .9 and .100, where the text has .100 first.
    assert by("address") == (["c", "a", "b", "d"], ["b", "a", "c", "d"])
    # The primary management address, and IPv4 before IPv6.
    assert by("mgmt_address") == (["a", "b", "c", "d"], ["c", "b", "a", "d"])
    # The first label of its networks: blue, then green, and what has none after them.
    assert by("network.label") == (["a", "b", "c", "d"], ["b", "a", "c", "d"])
    # Paged, such a sort still shows every row once.
    pages = [make.found(sort="address", limit=2, offset=offset) for offset in (0, 2)]
    assert sorted(pages[0] + pages[1]) == ["a", "b", "c", "d"]
    # A filter by such a field is what it was: by any one of them.
    assert make.found(filter="address:eq:192.0.2.20") == ["a"]
    assert make.found(filter="tags:has:zulu") == ["a"]


def test_what_a_sort_needs_is_in_the_statement_only_when_it_is_asked_for(db: Session) -> None:
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", note)
    listing.page(db, fields.ITEMS)
    plain = [one for one in statements if "FROM items" in one]
    statements.clear()
    listing.page(db, fields.ITEMS, sort=["tags", "address", "group.name", "minor_items"])
    asked = [one for one in statements if "FROM items" in one]
    event.remove(db.get_bind(), "before_cursor_execute", note)

    # The list as it is asked for by default reads no tag and no address, and counts
    # no minor item: a sort that nobody asked for costs it nothing.
    (count, page), (count_when_sorted, sorted_page) = plain, asked
    for part in ("tag_links", "addresses", "hirdir_address_key", "minor_item"):
        assert part not in page, part
        assert part in sorted_page, part
    # And a sorted list is counted as an unsorted one is: the sort is in the ORDER BY.
    assert count_when_sorted == count
    assert sorted_page.split("ORDER BY")[0] == page.split("ORDER BY")[0]


def test_pattern_that_backtracks_without_end_is_refused_in_time(make: Maker) -> None:
    make.item(name="lab-sw-01")
    make.item(name="long-comment", comments="a" * 5000 + "b")
    started = time.monotonic()
    problem = make.get("/items", 422, filter="comments:regex:(a|aa)+$")
    assert "takes too long" in errors(problem)["filter"]
    assert time.monotonic() - started < 2 * dialect.REGEX_REQUEST_SECONDS + 1
    # The server and the database are as they were.
    assert make.found(filter="name:regex:^lab-") == ["lab-sw-01"]


LISTS = {
    "/items": fields.ITEMS,
    "/device-groups": fields.DEVICE_GROUPS,
    "/networks": fields.NETWORKS,
    "/addresses": fields.ADDRESSES,
    "/catalog-entries": fields.CATALOG_ENTRIES,
    "/vendors": fields.VENDORS,
    "/owners": fields.OWNERS,
    "/regions": fields.REGIONS,
    "/sites": fields.SITES,
    "/locations": fields.LOCATIONS,
    "/contacts": fields.CONTACTS,
    "/operators": fields.OPERATORS,
    "/contact-assignments": fields.CONTACT_ASSIGNMENTS,
}


def test_every_list_is_sorted_by_every_field_it_says_it_is(make: Maker) -> None:
    # One record of each, so that every statement has a row to put in order.
    places = make.layout()
    contact = make.contact("Dana Whitfield")
    make.assign(contact, "technical", site_hid=places["site"]["hid"])
    make.post("/operators", {"label": "LM", "contact_hid": contact["hid"]})
    switch = make.item(
        catalog_entry_hid=make.entry(make.vendor(aliases=["Cisco Systems"]))["hid"],
        serial_number="FCW0000X001",
        owner_hid=make.owner()["hid"],
    )
    make.address(switch, "192.0.2.10", make.network("Red"), is_primary=True)
    make.stack("site2-sw-stack1", [switch])

    for path, listed in LISTS.items():
        names = [name for name, field in listed.fields.items() if filters.sorted_by(field)]
        assert len(names) >= len(listed.fields) - 4, path
        for way in ("", "-"):
            page = make.get(path, sort=",".join(way + name for name in names))
            assert page["total"] == len(page["items"]) >= 1, path


def test_every_paged_table_is_sorted_by_every_field_it_says_it_is(
    make: Maker, admin: dict[str, str]
) -> None:
    switch = make.item(name="site2-sw-access-01")
    make.item(name="PS-A", parent_item_hid=switch["hid"], position="PS-A")
    stack = make.stack("site2-sw-stack1", [switch])
    make.address(switch, "192.0.2.10")
    make.address(stack, "192.0.2.10")
    job = make.post("/items/bulk-update", {"hids": [switch["hid"]], "set": {"comments": "x"}})
    routes: dict[str, tuple[tables.Table, dict[str, Any]]] = {
        "/users": (tables.USERS, {}),
        "/audit-events": (tables.AUDIT_EVENTS, {}),
        "/imports": (tables.IMPORT_JOBS, {"source": "bulk"}),
        f"/imports/{job['job']['hid']}/rows": (tables.IMPORT_ROWS, {}),
        "/reports/duplicates": (tables.DUPLICATES, {}),
        f"/device-groups/{stack['hid']}/members": (tables.GROUP_MEMBERS, {}),
        f"/items/{switch['hid']}/children": (tables.CHILDREN, {}),
        f"/items/{switch['hid']}/history": (tables.HISTORY, {}),
    }
    as_admin = Maker(make.client, admin)
    for path, (table, more) in routes.items():
        names = [name for name, field in table.fields.items() if filters.sorted_by(field)]
        # With no sort it is as it was, and a field it does not have is refused.
        total = as_admin.get(path, **more)["total"]
        assert total >= 1, path
        for way in ("", "-"):
            page = as_admin.get(path, sort=",".join(way + name for name in names), **more)
            assert page["total"] == len(page["items"]) == total, path
        problem = as_admin.get(path, 422, sort="no_such_field", **more)
        assert "no_such_field is not a field" in errors(problem)["sort"], path
