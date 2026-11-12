"""Scenarios S06 to S11 of docs/build-plan.md, against a real server process."""

import time
from typing import Any

import httpx2
import pytest

from tests.acceptance.conftest import ADMIN, Server


class Inventory:
    """A signed-in client with short ways to make the records a scenario needs."""

    def __init__(self, client: httpx2.Client) -> None:
        self.client = client

    def post(self, path: str, body: dict[str, Any], expect: int = 201) -> dict[str, Any]:
        response = self.client.post(path, json=body)
        assert response.status_code == expect, response.text
        return response.json()

    def patch(self, path: str, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        response = self.client.patch(path, json=body)
        assert response.status_code == expect, response.text
        return response.json()

    def get(self, path: str, expect: int = 200, **params: Any) -> Any:
        response = self.client.get(path, params=params)
        assert response.status_code == expect, response.text
        return response.json()

    def entry(self, pid: str = "C9300-48P", vendor: str = "Cisco", **more: Any) -> dict[str, Any]:
        found = self.get("/vendors", filter=f"name:eq:{vendor}")["items"]
        maker = found[0] if found else self.post("/vendors", {"name": vendor})
        return self.post("/catalog-entries", {"vendor_hid": maker["hid"], "pid": pid, **more})

    def hostnames(self, **params: Any) -> list[str]:
        return [row["hostname"] for row in self.get("/items", **params)["items"]]


@pytest.fixture
def inventory(server: Server) -> Inventory:
    return Inventory(server.sign_in(*ADMIN))


def test_s06_one_item_shows_the_catalog_value_and_the_other_its_own(inventory: Inventory) -> None:
    entry = inventory.entry(est_value="18000.00", support_weight="1.0", ldos="2034-04-30")
    first, second = (
        inventory.post("/items", {"catalog_entry_hid": entry["hid"], "serial_number": serial})
        for serial in ("FCW0000X001", "FCW0000X002")
    )
    second = inventory.patch(
        f"/items/{second['hid']}", {"row_version": second["row_version"], "est_value": "21500.00"}
    )

    first = inventory.get(f"/items/{first['hid']}")
    assert first["est_value"] is None
    assert first["effective"]["est_value"] == {
        "value": "18000.00",
        "source": "catalog",
        "source_hid": entry["hid"],
    }
    assert second["effective"]["est_value"] == {
        "value": "21500.00",
        "source": "own",
        "source_hid": second["hid"],
    }
    # Weight and the date still come from the catalog on both.
    for item in (first, second):
        assert item["effective"]["support_weight"]["source"] == "catalog"
        assert item["effective"]["ldos"] == {
            "value": "2034-04-30",
            "source": "catalog",
            "source_hid": entry["hid"],
        }


def test_s07_a_new_ldos_on_the_catalog_entry_shows_on_both_items(inventory: Inventory) -> None:
    entry = inventory.entry(est_value="18000.00", support_weight="1.0", ldos="2034-04-30")
    items = [
        inventory.post("/items", {"catalog_entry_hid": entry["hid"], "serial_number": serial})
        for serial in ("FCW0000X001", "FCW0000X002")
    ]

    inventory.patch(
        f"/catalog-entries/{entry['hid']}",
        {"row_version": entry["row_version"], "ldos": "2035-10-31"},
    )

    for item in items:
        now = inventory.get(f"/items/{item['hid']}")
        assert now["effective"]["ldos"]["value"] == "2035-10-31"
        assert now["row_version"] == item["row_version"]
    listed = inventory.get("/items", filter="effective.ldos:eq:2035-10-31")
    assert listed["total"] == 2


def test_s08_an_item_with_only_vendor_pid_serial_number_and_owner(inventory: Inventory) -> None:
    entry = inventory.entry("Versiv-2", vendor="Fluke Networks", kind="hardware")
    owner = inventory.post("/owners", {"label": "Network Engineering"})

    item = inventory.post(
        "/items",
        {
            "catalog_entry_hid": entry["hid"],
            "serial_number": "FLK0000X001",
            "owner_hid": owner["hid"],
        },
    )

    given = {"catalog_entry_hid", "serial_number", "owner_hid"}
    derived = {"hid", "catalog", "owner", "effective", "tags", "created_at", "updated_at"}
    defaults = {"quantity": 1, "record_status": "active", "row_version": 1}
    for field, value in item.items():
        if field in given | derived or field in ("created_by", "updated_by"):
            continue
        assert value == defaults.get(field), field
    assert item["catalog"]["vendor"] == "Fluke Networks"
    assert item["catalog"]["pid"] == "Versiv-2"
    assert item["owner"]["label"] == "Network Engineering"
    assert item["tags"] == []
    assert all(value["source"] == "none" for value in item["effective"].values())


def test_s09_same_serial_number_is_refused_and_same_mac_address_is_accepted(
    inventory: Inventory,
) -> None:
    entry = inventory.entry()
    first = inventory.post(
        "/items",
        {
            "catalog_entry_hid": entry["hid"],
            "serial_number": "FCW0000X001",
            "mac_address": "00:00:5E:00:53:01",
        },
    )

    twin = inventory.post(
        "/items", {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X001"}, expect=409
    )
    assert twin["status"] == 409
    assert first["hid"] in twin["detail"]

    shared = inventory.post(
        "/items",
        {
            "catalog_entry_hid": entry["hid"],
            "serial_number": "FCW0000X002",
            "mac_address": "0000.5e00.5301",
        },
    )
    assert shared["mac_address"] == first["mac_address"] == "00005e005301"
    assert inventory.get("/items", filter="mac_address:eq:00-00-5e-00-53-01")["total"] == 2


def test_s10_each_move_is_in_the_history_and_excess_online_is_refused(inventory: Inventory) -> None:
    item = inventory.post(
        "/items", {"hostname": "site2-sw-access-01", "lifecycle_state": "Delivered"}
    )
    path = f"/items/{item['hid']}"

    for to, reason in (("Assigned", "received"), ("Test", "staged"), ("Prod", "deployed")):
        item = inventory.post(
            f"{path}/transition",
            {"to": to, "reason": reason, "row_version": item["row_version"]},
            200,
        )
        assert item["lifecycle_state"] == to
    assert (item["disposition"], item["expected_online"]) == ("Production", True)

    item = inventory.patch(
        path, {"row_version": item["row_version"], "disposition": "Spare", "expected_online": False}
    )
    assert (item["disposition"], item["expected_online"]) == ("Spare", False)

    refused = inventory.patch(
        path,
        {"row_version": item["row_version"], "disposition": "Excess", "expected_online": True},
        expect=422,
    )
    assert refused["errors"][0]["field"] == "disposition"
    now = inventory.get(path)
    assert (
        now["lifecycle_state"],
        now["disposition"],
        now["expected_online"],
        now["row_version"],
    ) == (
        "Prod",
        "Spare",
        False,
        item["row_version"],
    )

    history = inventory.get(f"{path}/history")["items"]
    moves = [event for event in reversed(history) if event["action"] == "transition"]

    def change(event: dict[str, Any], field: str) -> tuple[Any, Any]:
        return next((c["old"], c["new"]) for c in event["changes"] if c["field"] == field)

    assert [change(event, "lifecycle_state") for event in moves] == [
        ("Delivered", "Assigned"),
        ("Assigned", "Test"),
        ("Test", "Prod"),
    ]
    assert [change(event, "state_reason")[1] for event in moves] == [
        "received",
        "staged",
        "deployed",
    ]
    assert all(event["actor_name"] == ADMIN[0] and event["at"] for event in history)
    spare = next(event for event in history if event["action"] == "update")
    assert change(spare, "disposition") == ("Production", "Spare")
    assert change(spare, "expected_online") == (True, False)
    # The refused change left nothing behind.
    assert len(history) == 5


def test_s11_the_grid_filter_finds_the_right_rows_and_a_bad_pattern_is_refused(
    inventory: Inventory,
) -> None:
    c9300 = inventory.entry("C9300-48P")
    c9500 = inventory.entry("C9500-24Y4C")
    ex4400 = inventory.entry("EX4400-48P", vendor="Juniper")
    inventory.post("/tags", {"label": "refresh-2030"})
    rows = (
        ("site2-sw-core-01", c9500, "Prod", ["refresh-2030"]),
        ("site2-sw-dist-01", c9300, "Prod", ["refresh-2030"]),
        ("site2-sw-dist-02", c9300, "Test", ["refresh-2030"]),
        ("site2-sw-access-01", c9300, "Prod", ["refresh-2030"]),
        ("site2-sw-core-02", c9300, "Prod", []),
        ("site2-sw-core-03", ex4400, "Prod", ["refresh-2030"]),
        ("site2-sw-dist-03", c9300, "Assigned", ["refresh-2030"]),
    )
    for number, (hostname, entry, state, tags) in enumerate(rows):
        inventory.post(
            "/items",
            {
                "hostname": hostname,
                "catalog_entry_hid": entry["hid"],
                "serial_number": f"SN0000X{number:03}",
                "lifecycle_state": state,
                "tags": tags,
            },
        )

    short = (
        "lifecycle_state:in:Test,Prod catalog.pid:glob:C9* "
        "hostname:regex:^site2-sw-(core|dist)-[0-9]+$ tags:has:refresh-2030"
    )
    expected = ["site2-sw-core-01", "site2-sw-dist-01", "site2-sw-dist-02"]
    assert inventory.hostnames(filter=short, sort="hostname") == expected
    tree = {
        "and": [
            {"field": "lifecycle_state", "op": "in", "value": ["Test", "Prod"]},
            {"field": "catalog.pid", "op": "glob", "value": "C9*"},
            {"field": "hostname", "op": "regex", "value": "^site2-sw-(core|dist)-[0-9]+$"},
            {"field": "tags", "op": "has", "value": "refresh-2030"},
        ]
    }
    queried = inventory.post("/items/query", {"filter": tree, "sort": ["-hostname"]}, 200)
    assert [row["hostname"] for row in queried["items"]] == expected[::-1]
    assert queried["total"] == 3

    started = time.monotonic()
    too_long = inventory.get("/items", expect=422, filter="hostname:regex:" + "(a|aa)+" * 40)
    assert "at most 200 characters" in too_long["errors"][0]["message"]
    assert too_long["errors"][0]["field"] == "filter"
    # A pattern that is short enough and backtracks without end is stopped as well.
    inventory.post("/items", {"name": "long-comment", "comments": "a" * 5000 + "b"})
    slow = inventory.get("/items", expect=422, filter="comments:regex:(a|aa)+$")
    assert "too long" in slow["errors"][0]["message"]
    assert time.monotonic() - started < 5
    # The server still answers, and answers the good filter as before.
    assert inventory.get("/health/ready") == {"status": "ok", "detail": ""}
    assert inventory.hostnames(filter=short, sort="hostname") == expected
