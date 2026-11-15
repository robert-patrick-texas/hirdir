"""Scenarios S44 to S46 of docs/build-plan.md, against a real server process: the
capacity balance over time, the demand of each region, and links.

S44 needs two weeks. The server records the week it starts in by itself, before it
answers its first request. The week before is recorded as the server records it each
Monday: by its own scheduler, run in this process against the server's database for a
moment that the scenario chooses, last Monday just after midnight. Nothing in the
server is told another day.
"""

import csv
import io
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from hirdir import config as config_module
from hirdir.db.engine import make_engine, make_sessions
from hirdir.schedule import CAPACITY_RECORD, Scheduler
from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_file_scenarios import WAIT_FOR_JOB
from tests.acceptance.test_item_scenarios import IVY
from tests.acceptance.test_money_scenarios import Money

# The application's time zone, which a new installation has.
ZONE = ZoneInfo("America/New_York")


@pytest.fixture
def money(server: Server) -> Money:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Money(server.sign_in(*IVY))


def _last_monday_just_after_midnight() -> tuple[datetime, datetime]:
    """Return the moment the scheduler last looked on the Sunday of last week, and the
    moment just after midnight on the Monday that began last week, in the zone."""
    today = datetime.now(ZONE).date()
    monday = today - timedelta(days=today.weekday() + 7)
    due = datetime(monday.year, monday.month, monday.day, 0, 2, tzinfo=ZONE)
    return due - timedelta(minutes=5), due


def wait_for_job(money: Any, hid: str) -> dict[str, Any]:
    """Return a job of an import once the server has applied it in the background."""
    deadline = time.monotonic() + WAIT_FOR_JOB
    while True:
        job = money.get(f"/imports/{hid}")
        if job["status"] not in ("queued", "applying"):
            return job
        assert time.monotonic() < deadline, f"the job {hid} is still {job['status']}"
        time.sleep(0.05)


def test_s44_the_trend_shows_both_weeks_the_first_corrected_and_a_line_multiplies_two(
    server: Server, money: Money
) -> None:
    money.weigh("2400")
    lines = money.worked_example()
    # The server recorded this week when it started, as the system.
    [this_week] = money.get("/capacity-records")["items"]
    started = money.get("/audit-events", record_type="capacity_record")["items"]
    assert [(event["action"], event["via"]) for event in started] == [("create", "system")]

    # Last Monday, just after midnight, the server recorded the week before.
    database = config_module.load(Path(server.env["HIRDIR_CONFIG"])).database_url
    engine = make_engine(database)
    scheduler = Scheduler(make_sessions(engine), (CAPACITY_RECORD,))
    scheduler.checked, due = _last_monday_just_after_midnight()
    assert scheduler.run_due(due) == ["capacity record"]
    engine.dispose()

    # A line is added in between, and this week is recorded again by hand.
    money.line("supply", "professional_services", "Contract engineer", "1", "0.5")
    recorded = money.post("/capacity-records", {"note": "a contractor started this week"})
    assert recorded["hid"] == this_week["hid"]
    trend = money.get("/capacity-records")["items"]
    assert [one["week_of"] for one in trend] == sorted(one["week_of"] for one in trend)
    first, second = trend
    assert (first["active"]["supply"], second["active"]["supply"]) == ("9", "9.5")
    assert (first["active"]["balance"], second["active"]["balance"]) == ("-1", "-0.5")

    # The figures of the first week are corrected, with why.
    corrected = money.patch(
        f"/capacity-records/{first['hid']}",
        {
            "row_version": first["row_version"],
            "note": "the escalation partner was on hold that week",
            "active": {"supply": "8"},
        },
    )
    assert (corrected["adjusted"], corrected["active"]["balance"]) == (True, "-2")
    trend = money.get("/capacity-records")["items"]
    assert [(one["adjusted"], one["active"]["coverage_pct"]) for one in trend] == [
        (True, "80"),
        (False, "95"),
    ]
    assert trend[0]["note"] == "the escalation partner was on hold that week"

    # A line that multiplies two of the staff lines: their supply is multiplied, and
    # no other line's.
    before = money.get("/reports/capacity")["active"]
    engineer, senior = lines["Network engineer"], lines["Senior network engineer"]
    money.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "services",
            "name": "AI assistant",
            "effect": "multiply",
            "factor": "1.25",
            "share": "0.5",
            "applies_to": [engineer["hid"], senior["hid"]],
        },
    )
    after = money.get("/reports/capacity")["active"]
    [gain] = after["multiplying_lines"]
    assert [(one["name"], one["units"]) for one in gain["applies_to"]] == [
        ("Network engineer", "3"),
        ("Senior network engineer", "1.8"),
    ]
    assert (gain["base_units"], gain["units"]) == ("4.8", "0.6")
    assert (before["supply"], after["supply"]) == ("9.5", "10.1")

    def units(view: dict[str, Any]) -> dict[str, str]:
        return {row["category"]: row["units"] for row in view["by_category"]}

    assert units(after) == {**units(before), "services": "0.6"}
    assert after["own_units"] == before["own_units"] == "6"


def test_s45_one_balance_for_the_whole_team_and_beside_it_the_share_of_each_region(
    money: Money,
) -> None:
    americas = money.region("Americas")
    europe = money.region("Europe")
    rooms = {
        "americas": money.location("Room 1", money.site("Site-2", americas)),
        "europe": money.location("Room 1", money.site("Site-7", europe)),
    }
    core = money.entry("C9606R", support_weight="1200")
    access = money.entry("C9300-48P", support_weight="600")
    for serial, entry, room in (
        ("FXS0000X001", core, "americas"),
        ("FCW0000X001", access, "americas"),
        ("FCW0000X002", access, "europe"),
        ("FCW0000X003", access, None),
    ):
        money.item(
            entry,
            serial,
            lifecycle_state="Prod",
            **({"location_hid": rooms[room]["hid"]} if room else {}),
        )
    money.line("supply", "staff", "Network engineer", "3", "1.0", region_hid=europe["hid"])
    money.line("supply", "tools", "Automation and tooling", "1", "1.5")

    report = money.get("/reports/capacity")
    active = report["active"]
    # One balance for the whole team: 3,000 of weight, ten units of demand, and every
    # line's supply in it, the one that names Europe among them.
    assert (active["support_weight"], active["demand"]) == ("3000", "10")
    assert (active["supply"], active["balance"]) == ("4.5", "-5.5")
    by_region = {row["path"]: row for row in active["demand_by_region"]}
    assert {path: row["share_pct"] for path, row in by_region.items()} == {
        "Americas": "60",
        "Europe": "20",
        None: "20",
    }
    assert {path: row["infrastructure_demand"] for path, row in by_region.items()} == {
        "Americas": "6",
        "Europe": "2",
        None: "2",
    }
    total = sum(float(row["support_weight"]) for row in active["demand_by_region"])
    assert total == float(active["support_weight"])
    # No supply is divided: no row of a region has any.
    assert all("supply" not in row for row in active["demand_by_region"])


def test_s46_links_show_on_their_records_go_out_to_a_file_and_back_and_a_bad_one_is_refused(
    money: Money,
) -> None:
    sheet = {"url": "https://www.example.com/c9300/datasheet.pdf", "text": "Data sheet"}
    plan = {"url": "https://intranet.example.net/site-2/room-102/plan.pdf", "text": "Floor plan"}
    racks = {"url": "https://intranet.example.net/site-2/room-102/racks", "text": "Racks"}
    page = {"url": "https://intranet.example.net/site-2", "text": "Site page"}
    region = money.region("Americas")
    site = money.site("Site-2", region, links=[page])
    room = money.location("Room 102", site, links=[plan, racks])
    entry = money.entry("C9300-48P", links=[sheet])
    item = money.item(entry, "FCW0000X001", location_hid=room["hid"])

    assert money.get(f"/locations/{room['hid']}")["links"] == [plan, racks]
    assert money.get(f"/sites/{site['hid']}")["links"] == [page]
    assert money.get(f"/catalog-entries/{entry['hid']}")["links"] == [sheet]
    # An item shows the link of its model, and a place none from the places above it.
    assert money.get(f"/items/{item['hid']}")["catalog"]["links"] == [sheet]
    assert money.get(f"/regions/{region['hid']}")["links"] == []

    # A file carries them out and back unchanged.
    for entity, route, hid, links in (
        ("locations", "/locations", room["hid"], [plan, racks]),
        ("sites", "/sites", site["hid"], [page]),
        ("catalog_entries", "/catalog-entries", entry["hid"], [sheet]),
    ):
        exported = money.client.post(
            "/exports", json={"entity": entity, "format": "csv", "own_values": True}
        )
        assert exported.status_code == 200, exported.text
        [row] = list(csv.DictReader(io.StringIO(exported.text)))
        preview = money.client.post(
            "/imports/preview",
            params={"entity": entity},
            content=exported.text,
            headers={"Content-Type": "text/csv"},
        ).json()
        assert (preview["job"]["unchanged"], preview["job"]["rejected"]) == (1, 0), preview
        begun = money.post(f"/imports/{preview['job']['hid']}/apply", {}, expect=202)
        applied = wait_for_job(money, begun["hid"])
        assert (applied["status"], applied["unchanged"]) == ("applied", 1)
        assert money.get(f"{route}/{hid}")["links"] == links
        if entity == "locations":
            assert row["links"] == f"Floor plan <{plan['url']}>; Racks <{racks['url']}>"

    # An address that is no web address is refused, naming the link.
    refused = money.client.patch(
        f"/sites/{site['hid']}",
        json={
            "row_version": money.get(f"/sites/{site['hid']}")["row_version"],
            "links": [page, {"url": "file:///srv/site-2/plan.pdf", "text": "Plan"}],
        },
    )
    assert refused.status_code == 422, refused.text
    [error] = refused.json()["errors"]
    assert (error["field"], error["message"].startswith("link 2: ")) == ("links", True)
