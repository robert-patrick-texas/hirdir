"""Capacity over time (R14.7, R14.8, R14.9, D-188): a line that multiplies staff lines,
the demand of each region beside the balance of the whole, and the balance kept week
by week, recorded by hand, corrected, removed, and recorded by the server by itself."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import AuditEvent, CapacityRecord
from hirdir.domain import audit
from hirdir.io import balance
from hirdir.schedule import CAPACITY_RECORD, JOBS, Job, Scheduler, daily, weekly
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, counts, table


def line(make: Maker, category: str, name: str, quantity: str, units: str, **more: Any) -> dict:
    side = "demand" if category == "other_work" else "supply"
    body = {"side": side, "category": category, "name": name, **more}
    body |= {"quantity": quantity, "units_each": units}
    return make.post("/capacity-lines", body)


def multiplier(make: Maker, name: str, factor: str, targets: list[dict], expect: int = 201, **more):
    body = {
        "side": "supply",
        "category": "services",
        "name": name,
        "effect": "multiply",
        "factor": factor,
        "applies_to": [target["hid"] for target in targets],
        **more,
    }
    return make.post("/capacity-lines", body, expect)


@pytest.fixture
def staff(make: Maker) -> dict[str, dict[str, Any]]:
    """The staff of the worked example on the data model page, and a tool."""
    return {
        "junior": line(make, "staff", "Junior network engineer", "2", "0.6"),
        "engineer": line(make, "staff", "Network engineer", "3", "1.0"),
        "senior": line(make, "staff", "Senior network engineer", "1", "1.8"),
        "tooling": line(make, "tools", "Automation and tooling", "1", "1.5"),
    }


# --- a line that multiplies ----------------------------------------------------------


def test_a_line_that_multiplies_works_on_the_staff_lines_it_names_and_no_other(
    make: Maker, staff: dict
) -> None:
    before = make.get("/reports/capacity")["active"]
    ai = multiplier(make, "AI assistant", "1.25", [staff["engineer"], staff["senior"]], share="0.5")
    assert (ai["effect"], ai["factor"], ai["share"]) == ("multiply", "1.25", "0.5")
    assert (ai["quantity"], ai["units_each"], ai["units"]) == (None, None, None)
    assert [target["name"] for target in ai["applies_to"]] == [
        "Network engineer",
        "Senior network engineer",
    ]
    report = make.get("/reports/capacity")["active"]
    # A quarter more of half of 4.8 units: 0.6, in its own category.
    assert (before["supply"], report["supply"]) == ("7.5", "8.1")
    by_category = {row["category"]: row for row in report["by_category"]}
    assert by_category["staff"]["units"] == "6"
    assert (by_category["services"]["units"], by_category["services"]["lines"]) == ("0.6", 1)
    assert by_category["tools"]["units"] == "1.5"
    assert (report["own_units"], report["outside_units"]) == ("6", "2.1")
    [gain] = report["multiplying_lines"]
    assert (gain["name"], gain["base_units"], gain["units"]) == ("AI assistant", "4.8", "0.6")
    assert [(one["name"], one["counted"], one["units"]) for one in gain["applies_to"]] == [
        ("Network engineer", True, "3"),
        ("Senior network engineer", True, "1.8"),
    ]


def test_multipliers_work_on_the_base_units_and_do_not_compound(make: Maker, staff: dict) -> None:
    multiplier(make, "AI assistant", "1.5", [staff["engineer"]])
    multiplier(
        make,
        "Runbook automation",
        "2",
        [staff["engineer"]],
        category="tools",
        record_status="draft",
    )
    report = make.get("/reports/capacity")
    active, drafts = report["active"], report["with_drafts"]
    # Half again of three units; the draft doubles the same three, not four and a half.
    assert [one["units"] for one in active["multiplying_lines"]] == ["1.5"]
    assert [one["units"] for one in drafts["multiplying_lines"]] == ["1.5", "3"]
    assert (active["supply"], drafts["supply"]) == ("9", "12")


def test_what_a_multiplier_works_on_is_counted_in_its_own_view(make: Maker, staff: dict) -> None:
    contractor = line(make, "staff", "Contract engineer", "1", "1", record_status="draft")
    ended = line(make, "staff", "Engineer who left", "1", "1", ends_on="2020-12-31")
    ai = multiplier(make, "AI assistant", "2", [staff["junior"], contractor, ended])
    report = make.get("/reports/capacity")
    active = report["active"]["multiplying_lines"][0]
    drafts = report["with_drafts"]["multiplying_lines"][0]
    # The draft works only with the drafts, and the line that has ended in neither.
    assert (active["base_units"], active["units"]) == ("1.2", "1.2")
    assert (drafts["base_units"], drafts["units"]) == ("2.2", "2.2")
    assert {one["name"]: one["counted"] for one in active["applies_to"]} == {
        "Contract engineer": False,
        "Engineer who left": False,
        "Junior network engineer": True,
    }
    # A staff line that retires later gives it nothing, and stays named on the line.
    junior = make.get(f"/capacity-lines/{staff['junior']['hid']}")
    make.post(
        f"/capacity-lines/{junior['hid']}/retire", {"row_version": junior["row_version"]}, 200
    )
    assert make.get("/reports/capacity")["active"]["multiplying_lines"][0]["units"] == "0"
    assert len(make.get(f"/capacity-lines/{ai['hid']}")["applies_to"]) == 3
    # A retired line is not named anew.
    refused = multiplier(make, "Another", "2", [junior], expect=422)
    assert "retired" in errors(refused)["applies_to"]
    # Sent again whole, the list keeps a line it already had.
    ai = make.get(f"/capacity-lines/{ai['hid']}")
    kept = make.patch(
        f"/capacity-lines/{ai['hid']}",
        {"row_version": ai["row_version"], "applies_to": [junior["hid"], staff["senior"]["hid"]]},
    )
    assert [one["name"] for one in kept["applies_to"]] == [
        "Junior network engineer",
        "Senior network engineer",
    ]


def test_what_a_line_that_multiplies_must_be(make: Maker, staff: dict) -> None:
    engineer = staff["engineer"]
    base = {
        "side": "supply",
        "category": "services",
        "name": "AI assistant",
        "effect": "multiply",
        "factor": "1.2",
        "applies_to": [engineer["hid"]],
    }

    def refused(expect: int = 422, **change: Any) -> dict[str, str]:
        return errors(make.post("/capacity-lines", {**base, **change}, expect))

    assert "effect" in refused(category="staff")
    assert "effect" in refused(category="smart_hands")
    assert "effect" in refused(side="demand", category=None)
    assert "factor" in refused(factor=None)
    assert "factor" in refused(factor="0.99")
    assert "share" in refused(share="1.01")
    assert "quantity" in refused(quantity="1")
    assert "units_each" in refused(units_each="1")
    assert "applies_to" in refused(applies_to=[])
    assert "applies_to" in refused(applies_to=[staff["tooling"]["hid"]])
    assert "applies_to" in refused(applies_to=["0193a1f4-0000-7000-8000-000000000000"])
    # A line that adds has none of what a line that multiplies has.
    adds = {"side": "supply", "category": "tools", "name": "Tooling 2", "units_each": "1"}
    assert "factor" in errors(make.post("/capacity-lines", {**adds, "factor": "2"}, 422))
    assert "applies_to" in errors(
        make.post("/capacity-lines", {**adds, "applies_to": [engineer["hid"]]}, 422)
    )
    made = make.post("/capacity-lines", base)
    # It does not multiply itself, and a share left out is the whole.
    assert made["share"] == "1"
    assert "applies_to" in errors(
        make.patch(
            f"/capacity-lines/{made['hid']}",
            {"row_version": made["row_version"], "applies_to": [made["hid"]]},
            422,
        )
    )
    # Changed to a line that adds, it works on nothing and takes the units of one.
    assert "units_each" in errors(
        make.patch(
            f"/capacity-lines/{made['hid']}",
            {"row_version": made["row_version"], "effect": "add"},
            422,
        )
    )
    adding = make.patch(
        f"/capacity-lines/{made['hid']}",
        {"row_version": made["row_version"], "effect": "add", "units_each": "0.5"},
    )
    assert (adding["quantity"], adding["units"], adding["factor"], adding["applies_to"]) == (
        "1",
        "0.5",
        None,
        [],
    )
    events = make.audit(record_type="capacity_line", record_hid=made["hid"])
    changed = {entry["field"]: entry for entry in events[0]["changes"]}
    assert changed["applies_to"] == {"field": "applies_to", "old": [engineer["hid"]], "new": None}
    created = {entry["field"]: entry["new"] for entry in events[-1]["changes"]}
    assert (created["effect"], created["applies_to"]) == ("multiply", [engineer["hid"]])
    assert "quantity" not in created
    listed = make.get("/capacity-lines", filter="effect:eq:add", sort="name")
    assert "AI assistant" in [one["name"] for one in listed["items"]]


def test_lines_that_multiply_go_out_to_a_file_and_back(
    make: Maker, staff: dict, files: Files
) -> None:
    multiplier(make, "AI assistant", "1.25", [staff["engineer"], staff["senior"]], share="0.5")
    exported = files.export("capacity_lines", own_values=True)
    rows = {row["name"]: row for row in table(exported)}
    ai = rows["AI assistant"]
    assert (ai["effect"], ai["factor"], ai["share"], ai["quantity"], ai["units_each"]) == (
        "multiply",
        "1.25",
        "0.5",
        "",
        "",
    )
    asked = files.export("capacity_lines", columns=["name", "units"])
    assert {row["name"]: row["units"] for row in table(asked)}["AI assistant"] == ""
    assert ai["applies_to"] == "Network engineer;Senior network engineer"
    assert (rows["Network engineer"]["effect"], rows["Network engineer"]["applies_to"]) == (
        "add",
        "",
    )
    assert counts(files.load("capacity_lines", exported)) == (0, 0, 5, 0)
    # A line that multiplies stands first, and is worked after the lines it applies to.
    made = files.load(
        "capacity_lines",
        "side,category,name,effect,quantity,units_each,factor,applies_to\n"
        "supply,tools,Runbook automation,multiply,,,1.1,Field engineer;Network engineer\n"
        "supply,staff,Field engineer,,2,0.8,,\n",
    )
    assert counts(made) == (2, 0, 0, 0)
    found = make.get("/capacity-lines", filter="name:eq:Runbook automation")["items"][0]
    assert [one["name"] for one in found["applies_to"]] == ["Field engineer", "Network engineer"]
    assert found["effect"] == "multiply"
    refused = files.preview(
        "capacity_lines",
        "side,category,name,effect,factor,applies_to\n"
        "supply,tools,Robot,multiply,2,Nobody by that name\n",
    )
    assert refused["rows"][0]["reasons"] == [
        {"field": "applies_to", "message": "there is no supply line Nobody by that name"}
    ]


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


# --- the demand of each region ---------------------------------------------------------


def test_the_demand_of_each_region_is_beside_the_balance_of_the_whole(make: Maker) -> None:
    americas = make.region("Americas")
    central = make.region("Central", americas)
    europe = make.region("Europe")
    rooms = {
        name: make.location("Room 1", make.site(f"{name} site", region))
        for name, region in (("central", central), ("europe", europe), ("americas", americas))
    }
    heavy = make.entry(make.vendor(), "C9606R", support_weight="600")
    light = make.entry(make.vendor("Juniper"), "EX4400", support_weight="300")
    for serial, entry, room in (
        ("FXS0000X001", heavy, "central"),
        ("FXS0000X002", light, "europe"),
        ("FXS0000X003", light, "americas"),
    ):
        make.item(
            catalog_entry_hid=entry["hid"],
            serial_number=serial,
            lifecycle_state="Prod",
            location_hid=rooms[room]["hid"],
        )
    make.item(catalog_entry_hid=light["hid"], serial_number="FXS0000X004", lifecycle_state="Prod")
    make.item(
        catalog_entry_hid=light["hid"],
        serial_number="FXS0000X005",
        lifecycle_state="Prod",
        location_hid=rooms["europe"]["hid"],
        record_status="draft",
    )
    line(make, "staff", "Network engineer", "3", "1", region_hid=europe["hid"])
    report = make.get("/reports/capacity")
    active = report["active"]
    rows = [
        (row["path"], row["support_weight"], row["infrastructure_demand"], row["share_pct"])
        for row in active["demand_by_region"]
    ]
    assert rows == [
        ("Americas", "900", "3", "60"),
        ("Americas > Central", "600", "2", "40"),
        ("Europe", "300", "1", "20"),
        (None, "300", "1", "20"),
    ]
    tops = [row for row in active["demand_by_region"] if row["parent_region_hid"] is None]
    assert sum(float(row["support_weight"]) for row in tops) == float(active["support_weight"])
    assert active["demand_by_region"][1]["parent_region_hid"] == americas["hid"]
    # One balance for the whole: the line that names a region serves everywhere.
    assert (active["supply"], active["demand"], active["balance"]) == ("3", "5", "-2")
    drafts = {
        row["path"]: row["support_weight"] for row in report["with_drafts"]["demand_by_region"]
    }
    assert drafts == {"Americas": "900", "Americas > Central": "600", "Europe": "600", None: "300"}


def test_with_nothing_weighed_every_share_is_blank(make: Maker) -> None:
    active = make.get("/reports/capacity")["active"]
    assert active["demand_by_region"] == [
        {
            "region_hid": None,
            "parent_region_hid": None,
            "path": None,
            "support_weight": "0",
            "infrastructure_demand": "0",
            "share_pct": None,
        }
    ]
    assert active["multiplying_lines"] == []


# --- the records of the balance --------------------------------------------------------


def monday() -> date:
    """Return the Monday that begins this week in the application's time zone, as a
    record of the balance is dated."""
    today = datetime.now(ZoneInfo("America/New_York")).date()
    return today - timedelta(days=today.weekday())


def test_a_record_of_the_balance_is_made_corrected_and_listed(
    make: Maker, staff: dict, client: TestClient, viewer: dict[str, str]
) -> None:
    line(make, "other_work", "Site consolidation project", "1", "1.5")
    first = make.post("/capacity-records", {"note": "the first week"})
    assert first["active"]["supply"] == "7.5"
    assert (first["active"]["demand"], first["active"]["balance"]) == ("1.5", "6")
    assert first["active"]["coverage_pct"] == "500"
    assert (first["adjusted"], first["note"]) == (False, "the first week")
    assert first["weight_per_resource_unit"] == "300"
    assert {row["category"]: row["units"] for row in first["active"]["by_category"]}["staff"] == "6"
    # Recorded again in the same week, the record of the week is replaced.
    line(make, "staff", "Contract engineer", "1", "1")
    again = make.post("/capacity-records", {})
    assert (again["hid"], again["active"]["supply"], again["note"]) == (first["hid"], "8.5", None)
    listed = make.get("/capacity-records")
    assert listed["total"] == 1
    events = make.audit(record_type="capacity_record", record_hid=first["hid"])
    assert [event["action"] for event in events] == ["update", "create"]
    replaced = {entry["field"]: entry for entry in events[0]["changes"]}
    assert replaced["active"]["old"]["supply"] == "7.5"
    assert replaced["active"]["new"]["supply"] == "8.5"
    # A correction says why, and the balance and the coverage follow its figures.
    path = f"/capacity-records/{again['hid']}"
    unsaid = make.patch(path, {"row_version": again["row_version"], "active": {"supply": "9"}}, 422)
    assert "note" in errors(unsaid)
    negative = make.patch(
        path,
        {"row_version": again["row_version"], "note": "x", "active": {"demand": "-1"}},
        422,
    )
    assert "active.demand" in errors(negative)
    corrected = make.patch(
        path,
        {
            "row_version": again["row_version"],
            "note": "a contractor who started on Monday",
            "active": {"supply": "9.5"},
            "with_drafts": {"demand": "0"},
        },
    )
    assert corrected["adjusted"] is True
    assert (corrected["active"]["supply"], corrected["active"]["balance"]) == ("9.5", "8")
    assert corrected["active"]["coverage_pct"] == "633.33"
    assert (corrected["with_drafts"]["demand"], corrected["with_drafts"]["coverage_pct"]) == (
        "0",
        None,
    )
    # The totals are corrected and the parts stay as they were recorded, for the trend
    # to show both: the two parts of the demand, and the supply by category.
    for view in ("active", "with_drafts"):
        for part in ("infrastructure_demand", "other_demand", "by_category"):
            assert corrected[view][part] == again[view][part], (view, part)
    assert (again["active"]["infrastructure_demand"], again["active"]["other_demand"]) == (
        "0",
        "1.5",
    )
    listed = make.get("/capacity-records")["items"][0]
    assert listed["with_drafts"]["by_category"] == again["with_drafts"]["by_category"]
    assert listed["with_drafts"]["other_demand"] == "1.5"
    make.patch(path, {"row_version": again["row_version"], "note": "stale", "active": {}}, 409)
    # Any role reads them; only the Inventory role records, corrects and removes.
    assert client.get(f"{API}/capacity-records", headers=viewer).status_code == 200
    assert client.get(f"{API}{path}", headers=viewer).json()["adjusted"] is True
    for method, where in (
        ("post", "/capacity-records"),
        ("patch", path),
        ("delete", path),
    ):
        assert client.request(method, API + where, json={}, headers=viewer).status_code == 403
        assert client.request(method, API + where, json={}).status_code == 401


def test_a_record_that_was_a_mistake_is_removed_with_what_it_was(make: Maker, db) -> None:
    made = make.post("/capacity-records", {"note": "by mistake"})
    make.delete(f"/capacity-records/{made['hid']}")
    make.get(f"/capacity-records/{made['hid']}", expect=404)
    [event] = make.audit(record_type="capacity_record", action="delete")
    held = {entry["field"]: entry["old"] for entry in event["changes"]}
    assert (held["note"], held["week_of"]) == ("by mistake", made["week_of"])
    assert held["active"]["supply"] == "0"
    make.delete(f"/capacity-records/{made['hid']}", expect=404)


def test_the_records_are_the_oldest_week_first_and_sorted_by_any_column(
    make: Maker, staff: dict, db
) -> None:
    this_week = monday()
    # Noon of the Wednesday of each earlier week, in the application's time zone: a
    # moment so many weeks before now may fall into another week late on a Sunday, where
    # the clocks changed between.
    zone = ZoneInfo("America/New_York")
    for weeks in (3, 1, 2):
        wednesday = this_week - timedelta(weeks=weeks) + timedelta(days=2)
        balance.record(db, audit.SYSTEM, datetime.combine(wednesday, time(12), tzinfo=zone))
    db.commit()
    made = make.post("/capacity-records", {})
    listed = make.get("/capacity-records")
    weeks = [one["week_of"] for one in listed["items"]]
    assert weeks == sorted(weeks)
    assert weeks[-1] == made["week_of"]
    assert date.fromisoformat(weeks[-1]) in (this_week, this_week - timedelta(days=7))
    oldest = listed["items"][0]
    make.patch(
        f"/capacity-records/{oldest['hid']}",
        {"row_version": oldest["row_version"], "note": "more", "active": {"supply": "100"}},
    )
    by_supply = make.get("/capacity-records", sort="-active.supply")["items"]
    assert by_supply[0]["hid"] == oldest["hid"]
    by_balance = make.get("/capacity-records", sort="-active.balance,week_of")["items"]
    assert by_balance[0]["hid"] == oldest["hid"]
    assert make.get("/capacity-records", sort="-adjusted")["items"][0]["hid"] == oldest["hid"]
    assert make.get("/capacity-records", sort="with_drafts.coverage_pct")["total"] == 4
    page = make.get("/capacity-records", limit=2, offset=1)
    assert [one["week_of"] for one in page["items"]] == weeks[1:3]
    make.get("/capacity-records", expect=422, sort="nothing")


# --- what the server does by itself ------------------------------------------------------


def test_the_scheduler_records_each_monday_just_after_midnight(config: Config) -> None:
    sessions = make_sessions(make_engine(config.database_url))
    scheduler = Scheduler(sessions, (CAPACITY_RECORD,))
    # The application's time zone is America/New_York: a Monday just after midnight
    # there is five hours later in UTC, in the winter.
    sunday = datetime(2027, 1, 10, 23, 30, tzinfo=UTC)
    assert scheduler.run_due(sunday, starting=True) == ["capacity record"]
    assert scheduler.run_due(datetime(2027, 1, 11, 4, 59, tzinfo=UTC)) == []
    assert scheduler.run_due(datetime(2027, 1, 11, 5, 2, tzinfo=UTC)) == ["capacity record"]
    assert scheduler.run_due(datetime(2027, 1, 11, 5, 3, tzinfo=UTC)) == []
    with sessions() as db:
        kept = list(db.scalars(select(CapacityRecord).order_by(CapacityRecord.week_of)))
        assert [record.week_of for record in kept] == [date(2027, 1, 4), date(2027, 1, 11)]
        events = list(
            db.scalars(select(AuditEvent).where(AuditEvent.record_type == "capacity_record"))
        )
        assert {(event.action, event.via, event.actor_hid) for event in events} == {
            ("create", "system", None)
        }
    # Started again in a week that has its record, it makes none.
    again = Scheduler(sessions, (CAPACITY_RECORD,))
    assert again.run_due(datetime(2027, 1, 12, 12, 0, tzinfo=UTC), starting=True) == [
        "capacity record"
    ]
    with sessions() as db:
        assert len(list(db.scalars(select(CapacityRecord)))) == 2


def test_a_job_that_fails_is_tried_again_at_the_next_wake(config: Config) -> None:
    sessions = make_sessions(make_engine(config.database_url))
    tries: list[datetime] = []

    def flaky(db: Any, moment: datetime) -> None:
        tries.append(moment)
        if len(tries) == 1:
            raise RuntimeError("the first try fails")

    scheduler = Scheduler(sessions, (Job("flaky", daily(), flaky, at_start=True),))
    start = datetime(2027, 1, 11, 12, 0, tzinfo=UTC)
    assert scheduler.run_due(start, starting=True) == []
    assert scheduler.run_due(start + timedelta(minutes=1)) == ["flaky"]
    assert scheduler.run_due(start + timedelta(minutes=2)) == []
    assert len(tries) == 2


def test_the_times_of_a_job_follow_the_time_zone() -> None:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Berlin")
    each_monday = weekly()
    # A Wednesday: the last time it was due is the Monday before, just after midnight.
    wednesday = datetime(2027, 3, 31, 9, 0, tzinfo=UTC)
    assert each_monday(wednesday, zone) == datetime(2027, 3, 29, 0, 1, tzinfo=zone)
    # Just before it is due on a Monday, it was last due a week before.
    early = datetime(2027, 3, 28, 22, 0, 30, tzinfo=UTC)
    assert each_monday(early, zone) == datetime(2027, 3, 22, 0, 1, tzinfo=zone)
    assert daily()(wednesday, zone) == datetime(2027, 3, 31, 0, 1, tzinfo=zone)
    assert [job.name for job in JOBS] == ["capacity record", "long reports"]


def test_the_server_records_the_week_when_it_starts(config: Config) -> None:
    app = create_app(config, scheduled=True)
    with TestClient(app), make_sessions(make_engine(config.database_url))() as db:
        [record] = db.scalars(select(CapacityRecord))
        assert record.week_of in (monday(), monday() - timedelta(days=7))
    app.state.engine.dispose()
