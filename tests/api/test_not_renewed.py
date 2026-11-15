"""A model or a device whose support is not to be renewed (P-118, P-131): the flag, how an
item inherits it, the lists and files that carry it, and the coverage report that counts
what is left out on purpose. What a renewal does with a flagged item is tested with the
renewals."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Item
from hirdir.domain import not_renewed
from tests.api.inventory import Maker, errors
from tests.api.test_contracts import Desk
from tests.api.test_files import Files, changes, table

TODAY = date.today()
LAST_YEAR = (TODAY - timedelta(days=200)).isoformat()
NEXT_MONTH = (TODAY + timedelta(days=30)).isoformat()
NEXT_YEAR = (TODAY + timedelta(days=400)).isoformat()


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _flag(item: dict[str, Any]) -> tuple[Any, str, str | None]:
    found = item["effective"]["do_not_renew"]
    return found["value"], found["source"], found["source_hid"]


@pytest.fixture
def gear(desk: Desk) -> dict[str, Any]:
    """An access point model that is not renewed, a switch model that is, and items."""
    cisco = desk.vendor("Cisco")
    desk.cisco = cisco
    ap = desk.entry(cisco, "C9120AXI-B", model_name="Catalyst 9120 access point", do_not_renew=True)
    switch = desk.entry(cisco, "C9300-48P")
    return {
        "ap": ap,
        "switch": switch,
        "ap1": desk.switch(ap, "FGL0000A001", hostname="site2-ap-01"),
        "ap2": desk.switch(ap, "FGL0000A002", hostname="site2-ap-02"),
        "ap3": desk.switch(ap, "FGL0000A003", hostname="site2-ap-03", do_not_renew=False),
        "sw1": desk.switch(switch, "FCW0000X001", hostname="site2-sw-01"),
    }


def test_an_item_has_the_flag_of_its_model_unless_it_says_otherwise(desk: Desk, gear: dict) -> None:
    ap, switch = gear["ap"], gear["switch"]
    assert (ap["do_not_renew"], switch["do_not_renew"]) == (True, False)
    assert _flag(gear["ap1"]) == (True, "catalog", ap["hid"])
    assert gear["ap1"]["do_not_renew"] is None
    assert _flag(gear["ap3"]) == (False, "own", gear["ap3"]["hid"])
    assert _flag(gear["sw1"]) == (False, "catalog", switch["hid"])
    # An item with no model and no word of its own has none.
    bare = desk.item(name="site2-phone-01")
    assert _flag(bare) == (None, "none", None)
    # A minor item has its own model's, not that of the item it is in.
    power = desk.entry(desk.cisco, "PWR-C1-715WAC")
    module = desk.item(
        catalog_entry_hid=power["hid"],
        serial_number="LIT0000P001",
        parent_item_hid=gear["ap1"]["hid"],
    )
    assert _flag(module) == (False, "catalog", power["hid"])

    # Nothing is copied down: the model is changed, and its items show it at once.
    desk.change(f"/catalog-entries/{ap['hid']}", do_not_renew=False)
    again = desk.get(f"/items/{gear['ap1']['hid']}")
    assert (_flag(again), again["row_version"]) == (
        (False, "catalog", ap["hid"]),
        gear["ap1"]["row_version"],
    )
    # An item's own word overrides, and null has its model's again.
    own = desk.change(f"/items/{gear['ap1']['hid']}", do_not_renew=True)
    assert _flag(own) == (True, "own", own["hid"])
    back = desk.change(f"/items/{gear['ap1']['hid']}", do_not_renew=None)
    assert _flag(back) == (False, "catalog", ap["hid"])
    # A catalog entry says true or false: null is false.
    assert desk.change(f"/catalog-entries/{ap['hid']}", do_not_renew=None)["do_not_renew"] is False
    refused = desk.patch(
        f"/items/{back['hid']}", {"row_version": back["row_version"], "do_not_renew": "maybe"}, 422
    )
    assert "do_not_renew" in errors(refused)

    # Each change is audited.
    # The second change of the model changed nothing, and wrote no event.
    update = desk.audit(record_type="catalog_entry", record_hid=ap["hid"])[0]
    assert update["changes"] == [{"field": "do_not_renew", "old": True, "new": False}]
    cleared = desk.audit(record_type="item", record_hid=back["hid"])[0]
    assert cleared["changes"] == [{"field": "do_not_renew", "old": True, "new": None}]


def test_the_flag_is_a_field_of_the_lists_and_a_column_of_their_files(
    desk: Desk, gear: dict, files: Files
) -> None:
    flagged = desk.found(filter="effective.do_not_renew:eq:true", sort="name")
    assert flagged == ["site2-ap-01", "site2-ap-02"]
    assert desk.found(filter="do_not_renew:eq:false") == ["site2-ap-03"]
    assert desk.get("/items", filter="do_not_renew:empty:true")["total"] == 3
    ordered = desk.found(sort="-effective.do_not_renew,name")
    assert ordered[:2] == ["site2-ap-01", "site2-ap-02"]
    models = desk.get("/catalog-entries", filter="do_not_renew:eq:true")["items"]
    assert [model["pid"] for model in models] == ["C9120AXI-B"]

    # An export writes the flag in force with its source, or the item's own.
    rows = {
        row["serial_number"]: row
        for row in table(files.export("items", include_sources=True, sort=["serial_number"]))
    }
    assert (rows["FGL0000A001"]["do_not_renew"], rows["FGL0000A001"]["do_not_renew_source"]) == (
        "true",
        "catalog",
    )
    assert rows["FGL0000A003"]["do_not_renew_source"] == "own"
    own = table(files.export("items", own_values=True, sort=["serial_number"]))
    # By serial number: the switch first, then the three access points.
    assert [row["do_not_renew"] for row in own] == ["", "", "", "false"]
    models = table(files.export("catalog_entries"))
    assert {row["pid"]: row["do_not_renew"] for row in models} == {
        "C9120AXI-B": "true",
        "C9300-48P": "false",
    }


def test_a_file_and_a_bulk_edit_set_the_flag_and_the_very_value_inherited_is_no_override(
    desk: Desk, gear: dict, files: Files
) -> None:
    # A row that holds what the item has from its model leaves it inheriting (D-65).
    same = files.preview(
        "items", "vendor,pid,serial_number,do_not_renew\nCisco,C9120AXI-B,FGL0000A001,true\n"
    )
    assert same["rows"][0]["outcome"] == "unchanged"
    files.load(
        "items",
        "vendor,pid,serial_number,do_not_renew\n"
        "Cisco,C9120AXI-B,FGL0000A002,false\n"
        "Cisco,C9120AXI-B,FGL0000A003,!clear\n",
    )
    assert _flag(desk.get(f"/items/{gear['ap2']['hid']}"))[:2] == (False, "own")
    assert _flag(desk.get(f"/items/{gear['ap3']['hid']}"))[:2] == (True, "catalog")
    # A file of the catalog says it of a model.
    loaded = files.load("catalog_entries", "vendor,pid,do_not_renew\nCisco,C9300-48P,true\n")
    assert loaded["updated"] == 1
    assert _flag(desk.get(f"/items/{gear['sw1']['hid']}"))[:2] == (True, "catalog")

    # A bulk edit sets it on many at once, and clears it.
    preview = desk.post(
        "/items/bulk-update", {"filter": "hostname:prefix:site2-ap-", "set": {"do_not_renew": True}}
    )
    told = {row["record_hid"]: changes(row) for row in preview["rows"] if row["changes"]}
    assert told == {gear["ap2"]["hid"]: {"do_not_renew": (False, True)}}
    assert desk.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")["status"] == "applied"
    assert _flag(desk.get(f"/items/{gear['ap2']['hid']}"))[:2] == (True, "own")
    cleared = desk.post(
        "/items/bulk-update",
        {"hids": [gear["ap2"]["hid"]], "set": {"do_not_renew": None}},
    )
    assert desk.apply(f"/items/bulk-update/{cleared['job']['hid']}/apply")["status"] == "applied"
    assert _flag(desk.get(f"/items/{gear['ap2']['hid']}"))[:2] == (True, "catalog")


def test_the_flag_in_force_is_asked_of_many_items_at_once(
    desk: Desk, gear: dict, db: Session
) -> None:
    bare = desk.item(name="site2-phone-01", do_not_renew=True)
    hids = [gear[name]["hid"] for name in ("ap1", "ap2", "ap3", "sw1")] + [bare["hid"]]
    expected = {gear["ap1"]["hid"], gear["ap2"]["hid"], bare["hid"]}
    assert not_renewed.flagged(db, hids) == expected
    assert not_renewed.flagged(db, []) == set()
    # The SQL test says the same, wherever an item is in the statement.
    found = set(db.scalars(select(Item.hid).where(not_renewed.in_force(Item))))
    assert found == expected


def test_what_is_not_renewed_is_no_gap_and_is_counted_by_model(desk: Desk, gear: dict) -> None:
    # One flagged access point is covered, and its cover runs out within the window;
    # so is a switch.
    contract = desk.contract("CON-2026-0001", starts_on=LAST_YEAR, ends_on=NEXT_MONTH)
    ap4 = desk.switch(gear["ap"], "FGL0000A004", hostname="site2-ap-04")
    sw2 = desk.switch(gear["switch"], "FCW0000X002", hostname="site2-sw-02")
    desk.cover(contract, ap4, sw2)
    phone = desk.item(name="site2-phone-01", lifecycle_state="Prod", do_not_renew=True)

    report = desk.get("/reports/coverage")
    totals, sections = report["totals"], report["sections"]
    assert (totals["in_service"], totals["covered"]) == (7, 2)
    assert (totals["uncovered"], totals["not_renewed"], totals["expiring"]) == (2, 3, 1)
    assert sections["not_renewed"]["count"] == 3
    # Each section's filter lists its rows on the item list.
    for name, wanted in (
        ("uncovered", ["site2-ap-03", "site2-sw-01"]),
        ("not_renewed", ["site2-ap-01", "site2-ap-02", "site2-phone-01"]),
        ("expiring", ["site2-sw-02"]),
    ):
        listed = desk.post(
            "/items/query", {"filter": sections[name]["filter"], "sort": ["name"]}, 200
        )
        assert [one["name"] or one["hostname"] for one in listed["items"]] == wanted, name
    page = desk.get("/reports/coverage", section="not_renewed")
    assert page["total"] == 3

    # Counted by model, by vendor and PID, and the items with no model last.
    by_model = sections["not_renewed"]["by_model"]
    assert [(one["pid"], one["vendor"], one["count"]) for one in by_model] == [
        ("C9120AXI-B", "Cisco", 2),
        (None, None, 1),
    ]
    assert by_model[0]["catalog_entry_hid"] == gear["ap"]["hid"]
    assert by_model[0]["model_name"] == "Catalyst 9120 access point"
    for one, wanted in zip(by_model, (2, 1), strict=True):
        assert desk.post("/items/query", {"filter": one["filter"]}, 200)["total"] == wanted
    assert sections["uncovered"]["by_model"] is None
    # A filter of the report narrows the count by model too.
    narrowed = desk.get("/reports/coverage", filter="catalog.pid:eq:C9120AXI-B")
    assert [one["count"] for one in narrowed["sections"]["not_renewed"]["by_model"]] == [2]
    assert phone["effective"]["do_not_renew"]["source"] == "own"


def test_a_flag_is_set_only_by_the_inventory_role(
    gear: dict, client: TestClient, viewer: dict[str, str], make: Maker
) -> None:
    item = gear["ap1"]
    body = {"row_version": item["row_version"], "do_not_renew": False}
    assert (
        client.patch(f"/api/v1/items/{item['hid']}", json=body, headers=viewer).status_code == 403
    )
    entry = gear["ap"]
    body = {"row_version": entry["row_version"], "do_not_renew": False}
    path = f"/api/v1/catalog-entries/{entry['hid']}"
    assert client.patch(path, json=body, headers=viewer).status_code == 403
    assert make.get(f"/items/{item['hid']}")["effective"]["do_not_renew"]["value"] is True
