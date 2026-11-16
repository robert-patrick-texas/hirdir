"""The support weight of a place, a default and a minimum of each kind, the places and
the circuits in the demand of the capacity report, and Try (P-139, P-141, P-155, P-156).

Circuits are made through the ORM here: their routes are built beside this part."""

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from typer.testing import CliRunner, Result

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from hirdir.db.models import CapacityRecord, Circuit
from hirdir.domain import records
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, counts, table

TODAY = date.today()
NONE = {"value": None, "source": "none", "source_hid": None, "raised_from": None}


def put(client: TestClient, admin: dict, key: str, value: Any) -> None:
    """Give a setting a value, as an Admin."""
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=admin).json()}
    answer = client.put(
        f"{API}/settings/{key}",
        json={"row_version": now[key]["row_version"], "value": value},
        headers=admin,
    )
    assert answer.status_code == 200, answer.text


def weight(value: str | None, source: str, hid: str | None = None, raised: str | None = None):
    return {"value": value, "source": source, "source_hid": hid, "raised_from": raised}


def line(make: Maker, category: str, name: str, quantity: str, units: str, **more: Any) -> dict:
    side = "demand" if category == "other_work" else "supply"
    body = {"side": side, "category": category, "name": name, **more}
    return make.post("/capacity-lines", {**body, "quantity": quantity, "units_each": units})


def circuit(db: Session, name: str, a: dict | None, z: dict | None = None, **more: Any) -> str:
    made = Circuit(
        name=name,
        name_key=records.key(name),
        a_location_hid=a["hid"] if a else None,
        z_location_hid=z["hid"] if z else None,
        a_note=None if a else "carrier network",
        **more,
    )
    db.add(made)
    db.commit()
    return made.hid


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


# --- the support weight of a place ---------------------------------------------------


def test_a_place_has_a_weight_of_its_own_that_no_place_beneath_inherits(
    make: Maker, client: TestClient, viewer: dict
) -> None:
    americas = make.region("Americas", support_weight="4")
    site = make.site("Site-2", americas, support_weight="1.5")
    building = make.location("Building 1", site, support_weight="2")
    room = make.location("Room 102", parent=building)
    other = make.site("Site-3", americas)
    assert americas["support_weight"] == "4"
    assert site["support_weight"] == "1.5"
    assert site["effective"]["support_weight"] == weight("1.5", "own", site["hid"])
    assert (building["support_weight"], room["support_weight"]) == ("2", None)
    assert other["support_weight"] is None
    assert other["effective"]["support_weight"] == NONE
    assert make.get(f"/sites/{other['hid']}")["effective"]["support_weight"] == NONE
    # Changed and cleared as any field, and audited.
    path = f"/sites/{site['hid']}"
    changed = make.patch(path, {"row_version": site["row_version"], "support_weight": "0"})
    assert changed["support_weight"] == "0"
    assert changed["effective"]["support_weight"] == weight("0", "own", site["hid"])
    [event, *_] = make.audit(record_type="site", record_hid=site["hid"])
    found = {entry["field"]: entry for entry in event["changes"]}
    assert (found["support_weight"]["old"], found["support_weight"]["new"]) == ("1.5", "0")
    path = f"/regions/{americas['hid']}"
    cleared = make.patch(path, {"row_version": americas["row_version"], "support_weight": None})
    assert cleared["support_weight"] is None
    for bad in ("-1", "0.001"):
        make.post("/regions", {"name": "Europe", "support_weight": bad}, 422)
    # Only the Inventory role changes it.
    refused = client.patch(
        f"{API}/locations/{building['hid']}",
        json={"row_version": building["row_version"], "support_weight": "3"},
        headers=viewer,
    )
    assert refused.status_code == 403
    # The lists filter and sort by it.
    assert make.found("/locations", filter="support_weight:gt:1") == ["Building 1"]
    assert make.found("/sites", sort="-support_weight") == ["Site-2", "Site-3"]
    assert make.found("/regions", filter="support_weight:empty:true") == ["Americas"]


def test_a_site_with_none_counts_at_the_default_raised_to_the_minimum(
    make: Maker, client: TestClient, admin: dict
) -> None:
    region = make.region("Americas")
    plain = make.site("Site-2", region)
    light = make.site("Site-3", region, support_weight="0.5")
    make.site("Site-4", region, support_weight="3")
    before = make.get("/reports/capacity")["active"]
    # The sites with a weight of their own count it before any setting is given.
    assert (before["places_weight"], before["defaulted"], before["raised"]) == (
        "3.5",
        {"items": 0, "sites": 0, "circuits": 0},
        {"items": 0, "sites": 0, "circuits": 0},
    )
    put(client, admin, "default_site_weight", 2)
    put(client, admin, "minimum_site_weight", 1)
    assert make.get(f"/sites/{plain['hid']}")["effective"]["support_weight"] == weight(
        "2", "setting"
    )
    assert make.get(f"/sites/{light['hid']}")["effective"]["support_weight"] == weight(
        "1", "own", light["hid"], "0.5"
    )
    assert make.found("/sites", filter="effective.support_weight:eq:2") == ["Site-2"]
    assert make.found("/sites", sort="effective.support_weight") == ["Site-3", "Site-2", "Site-4"]
    report = make.get("/reports/capacity")["active"]
    assert (report["places_weight"], report["support_weight"]) == ("6", "6")
    assert (report["defaulted"]["sites"], report["raised"]["sites"]) == (1, 1)
    # A region and a location count their own alone: the setting is of sites.
    make.location("Building 1", plain)
    assert make.get("/reports/capacity")["active"]["places_weight"] == "6"


def test_the_weight_of_a_place_goes_out_to_a_file_and_back(
    make: Maker, files: Files, client: TestClient, admin: dict
) -> None:
    region = make.region("Americas", support_weight="4")
    site = make.site("Site-2", region)
    make.site("Site-3", region, support_weight="0.5")
    make.location("Building 1", site, support_weight="2")
    put(client, admin, "default_site_weight", 2)
    put(client, admin, "minimum_site_weight", 1)
    written = table(files.export("sites", include_sources=True))
    sites = {row["name"]: row for row in written}
    assert (sites["Site-2"]["support_weight"], sites["Site-2"]["support_weight_source"]) == (
        "2",
        "setting",
    )
    assert (sites["Site-3"]["support_weight"], sites["Site-3"]["support_weight_source"]) == (
        "1",
        "own",
    )
    own = {
        row["name"]: row["support_weight"] for row in table(files.export("sites", own_values=True))
    }
    assert own == {"Site-2": "", "Site-3": "0.5"}
    # Whether in force or as it is kept, a file of them changes nothing when loaded back.
    for text in (files.export("sites"), files.export("sites", own_values=True)):
        assert counts(files.load("sites", text)) == (0, 0, 2, 0)
    assert make.get(f"/sites/{site['hid']}")["support_weight"] is None
    assert table(files.export("regions"))[0]["support_weight"] == "4"
    assert table(files.export("locations"))[0]["support_weight"] == "2"
    # A file sets the weight of a place, and refuses one below zero.
    loaded = files.load("locations", "site,name,support_weight\nAmericas > Site-2,Room 9,1.25\n")
    assert counts(loaded) == (1, 0, 0, 0)
    assert make.found("/locations", filter="support_weight:eq:1.25") == ["Room 9"]
    refused = files.preview("regions", "name,support_weight\nEurope,-1\n")
    assert refused["job"]["rejected"] == 1


# --- a default and a minimum of an item ----------------------------------------------


def test_a_major_item_with_no_weight_counts_at_the_default_raised_to_the_minimum(
    make: Maker, client: TestClient, admin: dict
) -> None:
    vendor = make.vendor()
    blank = make.entry(vendor, "C9300-48P")
    light = make.entry(vendor, "C9200-24P", support_weight="0.5")
    switch = make.item(
        catalog_entry_hid=blank["hid"], serial_number="FCW0000X001", lifecycle_state="Prod"
    )
    small = make.item(
        catalog_entry_hid=light["hid"], serial_number="FCW0000X002", lifecycle_state="Prod"
    )
    make.item(name="site2-ap-01", lifecycle_state="Prod")
    supply = make.item(name="PS-A", parent_item_hid=switch["hid"])
    assert make.totals()["support_weight"] == "0.5"
    put(client, admin, "default_item_weight", 2)
    put(client, admin, "minimum_item_weight", 1)
    effective = {
        one["hid"]: one["effective"]["support_weight"]
        for one in (make.get(f"/items/{hid}") for hid in (switch["hid"], small["hid"]))
    }
    assert effective[switch["hid"]] == weight("2", "setting")
    assert effective[small["hid"]] == weight("1", "catalog", light["hid"], "0.5")
    # A minor item carries no weight, and has neither a default nor a minimum.
    assert make.get(f"/items/{supply['hid']}")["effective"]["support_weight"] == NONE
    assert make.totals()["support_weight"] == "5"
    assert sorted(make.found("/items", filter="effective.support_weight:eq:2")) == [
        "FCW0000X001",
        "site2-ap-01",
    ]
    report = make.get("/reports/capacity")["active"]
    assert (report["items_weight"], report["support_weight"]) == ("5", "5")
    assert (report["defaulted"]["items"], report["raised"]["items"]) == (2, 1)
    # Wherever an item's weight is used: the scoreboard and the portfolio of a vendor.
    scoreboard = make.get("/reports/summary", by="operator", operators="true")
    assert [one["support_weight"] for one in scoreboard["rows"]] == ["5"]
    assert make.get(f"/vendors/{vendor['hid']}/portfolio")["totals"]["support_weight"] == "3"


@pytest.mark.parametrize(
    ("default", "minimum", "counts_at"),
    [(2, 1, "2"), (1, 2, "2"), (None, 1, "0"), (0, 1, "1")],
)
def test_the_worked_examples_of_a_default_and_a_minimum(
    make: Maker,
    client: TestClient,
    admin: dict,
    default: int | None,
    minimum: int,
    counts_at: str,
) -> None:
    make.item(name="site2-ap-01", lifecycle_state="Prod")
    put(client, admin, "default_item_weight", default)
    put(client, admin, "minimum_item_weight", minimum)
    assert make.totals()["support_weight"] == counts_at


def test_a_stack_and_a_switch_alone_start_from_the_same_weight(
    make: Maker, client: TestClient, admin: dict
) -> None:
    entry = make.entry(make.vendor(), "C9300-48P")
    make.stack("site2-sw-stack1", make.switches(entry, "stack", 4, lifecycle_state="Prod"))
    make.switches(entry, "alone", 1, lifecycle_state="Prod")
    licence = make.entry(make.vendor("Example Software"), "NCM-250", kind="software")
    make.item(
        catalog_entry_hid=licence["hid"], name="NCM licence", quantity=3, lifecycle_state="Prod"
    )
    put(client, admin, "default_item_weight", 1)
    # Four at 1, at the global discount of 50, and one alone at 1; three seats at 1.
    assert make.totals()["support_weight"] == "6"
    put(client, admin, "minimum_item_weight", 1.5)
    # Each unit is raised before the quantity and the discount: 3 + 1.5 + 4.5.
    assert make.totals()["support_weight"] == "9"


def test_a_file_of_items_that_holds_the_default_leaves_it_inheriting(
    make: Maker, files: Files, client: TestClient, admin: dict
) -> None:
    vendor = make.vendor()
    blank = make.entry(vendor, "C9300-48P")
    light = make.entry(vendor, "C9200-24P", support_weight="0.5")
    switch = make.item(
        catalog_entry_hid=blank["hid"], serial_number="FCW0000X001", lifecycle_state="Prod"
    )
    small = make.item(
        catalog_entry_hid=light["hid"], serial_number="FCW0000X002", lifecycle_state="Prod"
    )
    low = make.item(
        catalog_entry_hid=blank["hid"],
        serial_number="FCW0000X003",
        lifecycle_state="Prod",
        support_weight="0.25",
    )
    put(client, admin, "default_item_weight", 2)
    put(client, admin, "minimum_item_weight", 1)
    written = {
        row["serial_number"]: (row["support_weight"], row["support_weight_source"])
        for row in table(files.export("items", include_sources=True))
    }
    assert written == {
        "FCW0000X001": ("2", "setting"),
        "FCW0000X002": ("1", "catalog"),
        "FCW0000X003": ("1", "own"),
    }
    assert counts(files.load("items", files.export("items"))) == (0, 0, 3, 0)
    assert [make.get(f"/items/{one['hid']}")["support_weight"] for one in (switch, small, low)] == [
        None,
        None,
        "0.25",
    ]


# --- places and circuits in the demand -----------------------------------------------


def test_places_and_circuits_are_demand_beside_the_items_and_in_their_regions(
    make: Maker, db: Session
) -> None:
    americas = make.region("Americas", support_weight="1")
    central = make.region("Central", americas)
    europe = make.region("Europe")
    site = make.site("Site-2", central, support_weight="2")
    room = make.location("Room 1", site, support_weight="0.5")
    make.site("Paris", europe, record_status="draft", support_weight="4")
    lyon = make.site("Lyon", europe, support_weight="8")
    make.post(f"/sites/{lyon['hid']}/retire", {"row_version": lyon["row_version"]}, 200)
    berlin = make.location("Room 2", make.site("Berlin", europe))
    heavy = make.entry(make.vendor(), "C9606R", support_weight="300")
    make.item(
        catalog_entry_hid=heavy["hid"],
        serial_number="FXS0000X001",
        lifecycle_state="Prod",
        location_hid=room["hid"],
    )
    yesterday = TODAY - timedelta(days=1)
    circuit(db, "Site-2 internet", room, support_weight=3)
    circuit(db, "Berlin internet", None, berlin, record_status="draft", support_weight=5)
    circuit(db, "Old line", room, support_weight=7, disconnected_on=yesterday)
    circuit(db, "Last day", room, support_weight=0.25, disconnected_on=TODAY)
    circuit(db, "Taken out", room, record_status="retired", support_weight=9)
    # Between two places, counted at its far end.
    circuit(db, "Site-2 to Berlin", room, berlin, cost_side="z", support_weight=10)
    report = make.get("/reports/capacity")
    active, drafts = report["active"], report["with_drafts"]
    assert (active["items_weight"], active["places_weight"], active["circuits_weight"]) == (
        "300",
        "3.5",
        "13.25",
    )
    assert active["support_weight"] == "316.75"
    assert (drafts["places_weight"], drafts["circuits_weight"]) == ("7.5", "18.25")
    assert drafts["support_weight"] == "325.75"

    def rows(view: dict) -> list[tuple]:
        return [(row["path"], row["support_weight"]) for row in view["demand_by_region"]]

    assert rows(active) == [
        ("Americas", "306.75"),
        ("Americas > Central", "305.75"),
        ("Europe", "10"),
        (None, "0"),
    ]
    assert rows(drafts) == [
        ("Americas", "306.75"),
        ("Americas > Central", "305.75"),
        ("Europe", "19"),
        (None, "0"),
    ]
    for view in (active, drafts):
        tops = [row for row in view["demand_by_region"] if row["parent_region_hid"] is None]
        whole = sum(float(row["support_weight"]) for row in tops)
        assert whole == float(view["support_weight"])
    assert active["infrastructure_demand"] == "1.06"


def test_circuits_count_at_the_default_raised_to_the_minimum(
    make: Maker, db: Session, client: TestClient, admin: dict
) -> None:
    room = make.location("Room 1", make.site("Site-2", make.region("Americas")))
    circuit(db, "Site-2 internet", room)
    circuit(db, "Site-2 backup", room, support_weight=0.5)
    circuit(db, "Site-2 voice", room, support_weight=4)
    assert make.get("/reports/capacity")["active"]["circuits_weight"] == "4.5"
    put(client, admin, "default_circuit_weight", 2)
    put(client, admin, "minimum_circuit_weight", 1)
    active = make.get("/reports/capacity")["active"]
    assert active["circuits_weight"] == "7"
    assert (active["defaulted"]["circuits"], active["raised"]["circuits"]) == (1, 1)


def test_a_record_keeps_the_parts_and_a_week_before_them_reads_as_it_was(
    make: Maker, db: Session
) -> None:
    make.region("Americas", support_weight="2")
    made = make.post("/capacity-records", {})
    assert (made["active"]["items_weight"], made["active"]["places_weight"]) == ("0", "2")
    assert made["active"]["circuits_weight"] == "0"
    assert made["active"]["defaulted"] == {"items": 0, "sites": 0, "circuits": 0}
    kept = db.get(CapacityRecord, made["hid"])
    assert kept is not None
    held = {
        name: value
        for name, value in kept.active.items()
        if name not in ("items_weight", "places_weight", "circuits_weight", "defaulted", "raised")
    }
    db.execute(update(CapacityRecord).values(active=held))
    db.commit()
    listed = make.get("/capacity-records")["items"][0]["active"]
    assert (listed["support_weight"], listed["items_weight"], listed["defaulted"]) == (
        "2",
        None,
        None,
    )


# --- Try ------------------------------------------------------------------------------


@pytest.fixture
def staff(make: Maker) -> dict[str, dict[str, Any]]:
    """The staff of the worked example on the data model page, a tool, a contractor in
    draft and a line that multiplies two of them."""
    found = {
        "junior": line(make, "staff", "Junior network engineer", "2", "0.6"),
        "engineer": line(make, "staff", "Network engineer", "3", "1.0"),
        "senior": line(make, "staff", "Senior network engineer", "1", "1.8"),
        "tooling": line(make, "tools", "Automation and tooling", "1", "1.5"),
        "contractor": line(make, "staff", "Contract engineer", "1", "1", record_status="draft"),
        "left": line(make, "staff", "Engineer who left", "1", "1", ends_on="2020-12-31"),
    }
    found["ai"] = make.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "services",
            "name": "AI assistant",
            "effect": "multiply",
            "factor": "1.25",
            "share": "0.5",
            "applies_to": [found["engineer"]["hid"], found["senior"]["hid"]],
        },
    )
    entry = make.entry(make.vendor(), "C9300-48P")
    make.switches(entry, "site2-sw", 3, lifecycle_state="Prod")
    return found


def tried(client: TestClient, headers: dict, body: dict, expect: int = 200) -> dict:
    answer = client.post(f"{API}/reports/capacity/try", json=body, headers=headers)
    assert answer.status_code == expect, answer.text
    return answer.json()


def test_try_answers_the_balance_tried_beside_the_one_in_force_and_saves_nothing(
    make: Maker, client: TestClient, viewer: dict, staff: dict
) -> None:
    audited = make.get("/audit-events")["total"]
    lines = make.get("/capacity-lines", include_drafts="true")["items"]
    body = {
        "default_item_weight": "100",
        "weight_per_resource_unit": "150",
        "staff": {
            "add": [{"name": "Network engineer, new", "quantity": "2", "units_each": "1"}],
            "change": [{"hid": staff["engineer"]["hid"], "quantity": "4"}],
            "leave_out": [staff["senior"]["hid"]],
        },
    }
    # Any role may Try.
    answer = tried(client, viewer, body)
    in_force, now = answer["in_force"], make.get("/reports/capacity")
    assert in_force == now
    assert (in_force["active"]["support_weight"], in_force["active"]["supply"]) == ("0", "8.1")
    active, drafts = answer["tried"]["active"], answer["tried"]["with_drafts"]
    assert answer["tried"]["weight_per_resource_unit"] == "150"
    assert (active["support_weight"], active["infrastructure_demand"]) == ("300", "2")
    assert (active["defaulted"]["items"], active["items_weight"]) == (3, "300")
    # The staff: 1.2, the changed line at 4 and the new 2; a quarter of half of the 4 the
    # line that multiplies works on, the senior left out and the new line not named.
    staffed = {one["category"]: one["units"] for one in active["by_category"]}
    assert staffed["staff"] == "7.2"
    assert [(one["base_units"], one["units"]) for one in active["multiplying_lines"]] == [
        ("4", "0.5")
    ]
    assert {
        one["name"]: one["counted"] for one in active["multiplying_lines"][0]["applies_to"]
    } == {
        "Network engineer": True,
        "Senior network engineer": False,
    }
    assert (active["supply"], active["balance"]) == ("9.2", "7.2")
    assert {one["category"]: one["units"] for one in drafts["by_category"]}["staff"] == "8.2"
    parameters = answer["parameters"]
    assert parameters["changed"] == ["default_item_weight", "weight_per_resource_unit"]
    assert (parameters["default_item_weight"], parameters["minimum_item_weight"]) == ("100", None)
    assert (parameters["weight_per_resource_unit"], parameters["stack_discount_pct"]) == (
        "150",
        "50",
    )
    assert parameters["staff"] == {
        "add": [
            {
                "hid": None,
                "name": "Network engineer, new",
                "quantity": "2",
                "units_each": "1",
                "units": "2",
            }
        ],
        "change": [
            {
                "hid": staff["engineer"]["hid"],
                "name": "Network engineer",
                "quantity": "4",
                "units_each": "1",
                "units": "4",
            }
        ],
        "leave_out": [{"hid": staff["senior"]["hid"], "name": "Senior network engineer"}],
    }
    # Nothing was saved, nothing audited, and the report is as it was.
    assert make.get("/audit-events")["total"] == audited
    assert make.get("/capacity-lines", include_drafts="true")["items"] == lines
    settings = {one["key"]: one for one in make.get("/settings")}
    assert settings["default_item_weight"]["is_default"] is True
    assert make.get("/reports/capacity") == now
    assert client.post(f"{API}/reports/capacity/try", json={}).status_code == 401


def test_a_staff_line_tried_is_active_and_in_date_in_both_views(
    make: Maker, client: TestClient, staff: dict
) -> None:
    body = {
        "staff": {
            "change": [
                {"hid": staff["contractor"]["hid"], "units_each": "2"},
                {"hid": staff["left"]["hid"]},
            ]
        }
    }
    answer = tried(client, make.headers, body)
    in_force = {
        one["category"]: one["units"] for one in answer["in_force"]["active"]["by_category"]
    }
    active = {one["category"]: one["units"] for one in answer["tried"]["active"]["by_category"]}
    assert (in_force["staff"], active["staff"]) == ("6", "9")
    assert answer["parameters"]["changed"] == []


def test_try_refuses_what_a_setting_would_refuse_and_a_line_that_is_no_staff_line(
    make: Maker, client: TestClient, staff: dict
) -> None:
    for key, value in (
        ("default_item_weight", "-1"),
        ("minimum_site_weight", "0.001"),
        ("default_circuit_weight", "1000001"),
        ("stack_discount_pct", "101"),
        ("weight_per_resource_unit", "0"),
    ):
        problem = tried(client, make.headers, {key: value}, 422)
        assert key in errors(problem), key
    for staffed, field in (
        ({"change": [{"hid": staff["tooling"]["hid"], "quantity": "1"}]}, "staff.change.0"),
        ({"leave_out": [staff["ai"]["hid"]]}, "staff.leave_out.0"),
        ({"leave_out": ["0193a1f4-0000-7000-8000-000000000000"]}, "staff.leave_out.0"),
        (
            {"change": [{"hid": staff["junior"]["hid"]}], "leave_out": [staff["junior"]["hid"]]},
            "staff.leave_out.0",
        ),
        ({"add": [{"name": " ", "units_each": "1"}]}, "staff.add.0.name"),
    ):
        problem = tried(client, make.headers, {"staff": staffed}, 422)
        assert field in errors(problem), staffed
    named = errors(tried(client, make.headers, {"staff": {"leave_out": [staff["ai"]["hid"]]}}, 422))
    assert "AI assistant" in named["staff.leave_out.0"]
    junior = make.get(f"/capacity-lines/{staff['junior']['hid']}")
    retire = f"/capacity-lines/{junior['hid']}/retire"
    make.post(retire, {"row_version": junior["row_version"]}, 200)
    problem = tried(client, make.headers, {"staff": {"leave_out": [junior["hid"]]}}, 422)
    assert "retired" in errors(problem)["staff.leave_out.0"]


def test_null_tries_a_weight_blank_and_a_model_keeps_its_own_discount(
    make: Maker, client: TestClient, admin: dict
) -> None:
    region = make.region("Americas")
    make.site("Site-2", region)
    vendor = make.vendor()
    own = make.entry(vendor, "EX4400", support_weight="1", stack_discount_pct="30")
    plain = make.entry(vendor, "C9300-48P", support_weight="1")
    make.stack("site2-sw-stack1", make.switches(own, "ex", 4, lifecycle_state="Prod"))
    make.stack("site2-sw-stack2", make.switches(plain, "cat", 4, lifecycle_state="Prod"))
    put(client, admin, "default_site_weight", 2)
    answer = tried(client, admin, {"default_site_weight": None, "stack_discount_pct": "0"})
    in_force, active = answer["in_force"]["active"], answer["tried"]["active"]
    assert (in_force["places_weight"], active["places_weight"]) == ("2", "0")
    # The model's own 30 stays; the global discount tried is that of the other model.
    assert (in_force["items_weight"], active["items_weight"]) == ("4.8", "6.8")
    assert answer["parameters"]["changed"] == ["default_site_weight", "stack_discount_pct"]
    assert answer["parameters"]["default_site_weight"] is None


# --- the command line ----------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def hirdir(client: TestClient, inventory: dict[str, str], monkeypatch, tmp_path: Path):
    """Run `hirdir` as the Inventory user, with its calls going to the test client."""
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.setenv("HIRDIR_TOKEN", inventory["Authorization"].removeprefix("Bearer "))

    def run(*arguments: str, expect: int = 0) -> Result:
        result = runner.invoke(app, list(arguments))
        assert result.exit_code == expect, result.output
        return result

    return run


def test_the_command_line_tries_the_balance_and_shows_the_weight_of_a_place(
    hirdir, make: Maker, staff: dict
) -> None:
    rows = {
        row[0]: row[1:]
        for row in csv.reader(
            io.StringIO(
                hirdir(
                    "report",
                    "capacity",
                    "--format",
                    "csv",
                    "--try",
                    "default_item_weight=100",
                    "--try",
                    "weight_per_resource_unit=150",
                    "--try-staff-add",
                    "Network engineer, new=2x1",
                    "--try-staff-change",
                    "network engineer=4x",
                    "--try-staff-leave-out",
                    "Senior network engineer",
                ).stdout
            )
        )
    }
    assert rows["measure"] == ["active", "active_tried", "with_drafts", "with_drafts_tried"]
    assert rows["supply"] == ["8.1", "9.2", "9.1", "10.2"]
    assert rows["support_weight"] == ["0", "300", "0", "300"]
    assert rows["defaulted: items"] == ["0", "3", "0", "3"]
    assert rows["weight_per_resource_unit"] == ["300", "150", "300", "150"]
    assert "places_weight" in rows
    missing = hirdir("report", "capacity", "--try-staff-leave-out", "Nobody", expect=4)
    assert "no staff line Nobody" in missing.output
    hirdir("report", "capacity", "--try", "no_such_figure=1", expect=2)
    region = make.region("Americas")
    make.site("Site-2", region, support_weight="1.5")
    shown = hirdir("sites", "show", "Americas > Site-2").stdout
    assert "support_weight:      1.5" in shown
