"""Scenarios S29 to S35, S39 and S40 of docs/build-plan.md, against a real server process."""

import csv
import io
from datetime import date, timedelta
from typing import Any

import pytest

from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_geography_scenarios import Geography
from tests.acceptance.test_item_scenarios import IVY

TODAY = date.today()
# Days well clear of today, so that the application's day and this host's agree on them.
LAST_YEAR = (TODAY - timedelta(days=200)).isoformat()
NEXT_YEAR = (TODAY + timedelta(days=400)).isoformat()
LONG_AGO = (TODAY - timedelta(days=30)).isoformat()


class Money(Geography):
    """A signed-in Inventory user who enters contracts, purchases, systems and capacity."""

    def room(self, region: str) -> dict[str, Any]:
        """Make a region with one site and one room in it. Return the room."""
        site = self.site(f"{region} site", self.region(region))
        return self.location("Room 1", site, kind="room")

    def item(self, entry: dict[str, Any], serial: str, **more: Any) -> dict[str, Any]:
        body = {"catalog_entry_hid": entry["hid"], "serial_number": serial, **more}
        return self.post("/items", body)

    def move(self, item: dict[str, Any], *states: str) -> dict[str, Any]:
        """Move an item through states, one transition at a time."""
        for state in states:
            item = self.post(
                f"/items/{item['hid']}/transition",
                {"to": state, "row_version": item["row_version"]},
                expect=200,
            )
        return item

    def contract(self, number: str, vendor: str = "Cisco", **more: Any) -> dict[str, Any]:
        maker = self.get("/vendors", filter=f"name:eq:{vendor}")["items"][0]
        body = {"number": number, "vendor_hid": maker["hid"], **more}
        return self.post("/contracts", body)

    def cover(self, contract: dict[str, Any], *items: dict[str, Any]) -> list[dict[str, Any]]:
        body = {"items": [{"item_hid": item["hid"]} for item in items]}
        response = self.client.post(f"/contracts/{contract['hid']}/coverage", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def section(self, report: str, section: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/reports/{report}", section=section, **params)

    def line(self, side: str, category: str, name: str, quantity: str, units: str, **more: Any):
        body = {
            "side": side,
            "category": category,
            "name": name,
            "quantity": quantity,
            "units_each": units,
            **more,
        }
        return self.post("/capacity-lines", body)

    def worked_example(self) -> dict[str, dict[str, Any]]:
        """Enter the active lines of the worked example on the data model page."""
        lines = (
            ("demand", "other_work", "Site consolidation project", "1", "1.5"),
            ("demand", "other_work", "Organization transition", "1", "0.5"),
            ("supply", "staff", "Junior network engineer", "2", "0.6"),
            ("supply", "staff", "Network engineer", "3", "1.0"),
            ("supply", "staff", "Senior network engineer", "1", "1.8"),
            ("supply", "professional_services", "Escalation partner", "1", "1.0"),
            ("supply", "smart_hands", "Colocation smart hands", "1", "0.5"),
            ("supply", "tools", "Automation and tooling", "1", "1.5"),
        )
        return {name: self.line(side, category, name, q, u) for side, category, name, q, u in lines}

    def weigh(self, weight: str) -> None:
        """Seed an infrastructure of one support weight: a switch in production."""
        entry = self.entry("C9606R", support_weight=weight)
        self.item(entry, "FXS0000X001", lifecycle_state="Prod")


@pytest.fixture
def money(server: Server) -> Money:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Money(server.sign_in(*IVY))


def test_s29_an_archived_item_under_a_contract_is_out_of_service_while_the_term_runs(
    money: Money,
) -> None:
    entry = money.entry()
    east = money.item(
        entry, "FCW0000X001", lifecycle_state="Prod", location_hid=money.room("East")["hid"]
    )
    west = money.item(
        entry, "FCW0000X002", lifecycle_state="Prod", location_hid=money.room("West")["hid"]
    )
    contract = money.contract("CON-2026-0001", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    covered = money.cover(contract, east, west)
    assert [one["in_force"] for one in covered] == [True, True]
    assert {one["item"]["hid"] for one in covered} == {east["hid"], west["hid"]}

    before = money.get("/reports/coverage")
    assert (before["totals"]["in_service"], before["totals"]["covered"]) == (2, 2)
    assert (before["totals"]["uncovered"], before["totals"]["out_of_service"]) == (0, 0)

    money.move(west, "Pending-Removal", "Released", "Archived")

    # Its coverage ended on the day it left the team's hands, and says why.
    report = money.section("coverage", "out_of_service")
    today = report["as_of"]
    assert report["totals"]["out_of_service"] == 1
    assert report["totals"]["in_service"] == 1
    assert [item["hid"] for item in report["items"]] == [west["hid"]]
    listed = report["items"][0]
    assert listed["effective"]["lifecycle_state"]["value"] == "Archived"
    (its,) = listed["coverage"]
    assert (its["contract"]["number"], its["ends_on"], its["left_service"]) == (
        "CON-2026-0001",
        today,
        True,
    )
    # The filter the section gives lists the same item on the item list.
    section = report["sections"]["out_of_service"]
    same = money.post(
        "/items/query",
        {"filter": section["filter"], "include_archived": section["include_archived"]},
        expect=200,
    )
    assert [item["hid"] for item in same["items"]] == [west["hid"]]
    # The contract still runs, and still covers the switch that is in service: its
    # coverage of the other is on record, ended.
    of_contract = money.get(f"/contracts/{contract['hid']}/coverage")
    assert of_contract["total"] == 2
    assert {one["item"]["hid"] for one in of_contract["items"]} == {east["hid"], west["hid"]}
    assert money.get(f"/contracts/{contract['hid']}")["items_in_scope"] == 2
    assert money.get(f"/items/{east['hid']}")["covered"] is True


def test_s30_an_item_with_no_coverage_and_one_near_its_ldos_are_each_on_their_report(
    money: Money,
) -> None:
    ldos = date(TODAY.year + 1, 6, 30)
    lasting = money.entry("C9300-48P")
    ending = money.entry("WS-C3850-48P", ldos=ldos.isoformat())
    bare = money.item(lasting, "FCW0000X001", lifecycle_state="Prod")
    old = money.item(ending, "FOC0000X001", lifecycle_state="Prod")
    contract = money.contract("CON-2026-0002", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    money.cover(contract, old)

    coverage = money.section("coverage", "uncovered")
    assert coverage["totals"]["in_service"] == 2
    assert coverage["totals"]["uncovered"] == 1
    assert [item["hid"] for item in coverage["items"]] == [bare["hid"]]
    assert coverage["items"][0]["covered"] is False

    end_of_life = money.section("end-of-life", "approaching")
    assert end_of_life["date"] == "ldos"
    assert end_of_life["dates"]["ldos"]["approaching"] == {"items": 1, "component_count": 1}
    assert end_of_life["dates"]["ldos"]["past"] == {"items": 0, "component_count": 0}
    assert [item["hid"] for item in end_of_life["items"]] == [old["hid"]]
    assert [row["fiscal_year"] for row in end_of_life["by_fiscal_year"]] == [ldos.year]
    assert end_of_life["by_fiscal_year"][0]["items"] == 1


def test_s31_the_portfolio_of_a_vendor_lists_all_four_kinds_and_exports(money: Money) -> None:
    kinds = (
        ("C9300-48P", "hardware", "1.0", "1200.00", 2),
        ("C8000V", "virtual_machine", "0.5", "300.00", 1),
        ("NetConfig Manager", "software", "2.0", "9000.00", 1),
        ("Advanced Services", "service", "0.25", "20000.00", 1),
    )
    serial = 0
    for pid, kind, weight, cost, count in kinds:
        entry = money.entry(pid, kind=kind, support_weight=weight, annual_support_cost=cost)
        for _ in range(count):
            serial += 1
            money.item(entry, f"FCW0000X{serial:03d}", lifecycle_state="Prod")
    # Another vendor's switch is in nobody else's portfolio.
    money.item(money.entry("EX4400-48P", vendor="Juniper"), "JN0000X001", lifecycle_state="Prod")
    vendor = money.get("/vendors", filter="name:eq:Cisco")["items"][0]

    portfolio = money.get(f"/vendors/{vendor['hid']}/portfolio")
    by_kind = {row["kind"]: row for row in portfolio["kinds"]}
    assert list(by_kind) == ["hardware", "virtual_machine", "software", "service"]
    assert [by_kind[kind]["items"] for kind in by_kind] == [2, 1, 1, 1]
    assert by_kind["hardware"]["annual_support_cost"] == "2400.00"
    assert by_kind["hardware"]["support_weight"] == "2"
    assert by_kind["service"]["annual_support_cost"] == "20000.00"
    assert by_kind["service"]["support_weight"] == "0.25"
    assert portfolio["totals"]["items"] == 5
    assert portfolio["totals"]["annual_support_cost"] == "31700.00"
    assert portfolio["totals"]["support_weight"] == "4.75"
    assert [row["pid"] for row in portfolio["models"]] == [
        "Advanced Services",
        "C8000V",
        "C9300-48P",
        "NetConfig Manager",
    ]

    columns = ["pid", "kind", "serial_number", "annual_support_cost", "covered"]
    exported = money.client.post(
        "/exports", json={"entity": "items", "filter": portfolio["filter"], "columns": columns}
    )
    assert exported.status_code == 200, exported.text
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows[0] == ["hid", *columns]
    assert sorted(row[2] for row in rows[1:]) == [
        "hardware",
        "hardware",
        "service",
        "software",
        "virtual_machine",
    ]


def test_s32_receiving_six_of_ten_creates_six_delivered_items(money: Money) -> None:
    entry = money.entry()
    request = money.post("/purchase-requests", {"reference": "RITM0012345"})
    line = money.post(
        f"/purchase-requests/{request['hid']}/lines",
        {"catalog_entry_hid": entry["hid"], "quantity": 10},
    )
    assert (line["line"], line["received_quantity"], line["pending_quantity"]) == (1, 0, 10)
    # A line is not inventory: nothing of it is in any count.
    assert money.get("/reports/summary")["totals"]["component_count"] == 0
    assert money.get("/items", include_drafts=True)["total"] == 0

    serials = [f"FCW0000X{number:03d}" for number in range(1, 7)]
    received = money.post(
        f"/purchase-lines/{line['hid']}/receive",
        {"row_version": line["row_version"], "items": [{"serial_number": s} for s in serials]},
    )
    assert (received["received_quantity"], received["pending_quantity"]) == (6, 4)

    items = money.get("/items", filter=f"purchase_line_hid:eq:{line['hid']}", sort="serial_number")
    assert [item["serial_number"] for item in items["items"]] == serials
    for item in items["items"]:
        assert item["lifecycle_state"] == "Delivered"
        assert item["purchase_line"]["name"] == "RITM0012345/1"
        assert item["catalog"]["pid"] == "C9300-48P"
    # Delivered is not among the states that count: still no component.
    assert money.get("/reports/summary")["totals"]["component_count"] == 0
    pending = money.get("/purchase-lines", filter="pending_quantity:gt:0")
    assert [(one["name"], one["pending_quantity"]) for one in pending["items"]] == [
        ("RITM0012345/1", 4)
    ]
    # More than is still to come is refused, and nothing of it is created.
    too_many = [{"serial_number": f"FCW0000X1{number:02d}"} for number in range(5)]
    money.post(
        f"/purchase-lines/{line['hid']}/receive",
        {"row_version": received["row_version"], "items": too_many},
        expect=422,
    )
    assert money.get("/items")["total"] == 6
    # The other four arrive with nothing to know them by yet: each is named for its
    # line, and the request, all of it arrived, says so by itself.
    counted = money.post(
        f"/purchase-lines/{line['hid']}/receive",
        {"row_version": received["row_version"], "quantity": 4},
    )
    assert [item["name"] for item in counted["items"]] == [
        f"RITM0012345/1-{number:03d}" for number in range(7, 11)
    ]
    assert money.get(f"/purchase-requests/{request['hid']}")["status"] == "received"


def test_s33_a_stack_is_registered_and_its_members_are_not(money: Money) -> None:
    entry = money.entry()
    members = [money.item(entry, f"FCW0000X{number:03d}") for number in range(1, 5)]
    stack = money.post(
        "/device-groups",
        {
            "type": "stack",
            "name": "site2-sw-stack1",
            "members": [
                {"item_hid": member["hid"], "role": "master" if place == 1 else "member"}
                for place, member in enumerate(members, start=1)
            ],
        },
    )
    watch = money.post("/external-systems", {"name": "NetWatch", "kind": "monitoring"})
    fabric = money.post("/external-systems", {"name": "Fabric Director", "kind": "sdn_controller"})
    for system, key in ((watch, "node-4411"), (fabric, "site2-sw-stack1")):
        made = money.post(
            "/registrations",
            {"system_hid": system["hid"], "group_hid": stack["hid"], "external_id": key},
        )
        assert made["status"] == "registered"
        assert made["group"]["name"] == "site2-sw-stack1"

    stack = money.get(f"/device-groups/{stack['hid']}")
    assert [(one["system"]["name"], one["external_id"]) for one in stack["registrations"]] == [
        ("Fabric Director", "site2-sw-stack1"),
        ("NetWatch", "node-4411"),
    ]
    for member in members:
        its = money.get(f"/items/{member['hid']}")
        # Not on the member: but the member says what its stack is registered with.
        assert its["registrations"] == []
        assert [
            (one["system"]["name"], one["group"]["name"]) for one in its["group_registrations"]
        ] == [
            ("Fabric Director", "site2-sw-stack1"),
            ("NetWatch", "site2-sw-stack1"),
        ]
    found = money.get("/device-groups", filter="registration.system:eq:NetWatch")
    assert [group["hid"] for group in found["items"]] == [stack["hid"]]
    # What NetWatch knows: the stack, and so each of its four members.
    assert money.get("/items", filter="registration.system:eq:NetWatch")["total"] == 4
    alone = money.item(entry, "FCW0000X009")
    unknown = money.get("/items", filter="registration.system:ne:NetWatch")["items"]
    assert [item["hid"] for item in unknown] == [alone["hid"]]


def test_s34_a_draft_site_with_draft_items_is_left_out_of_every_count(money: Money) -> None:
    entry = money.entry(support_weight="1.0", est_value="18000.00", annual_support_cost="1200.00")
    region = money.region("Americas")
    site = money.site("Site-3", region, record_status="draft")
    room = money.location("Suite 300", site, kind="room", record_status="draft")
    drafts = [
        money.item(
            entry,
            f"FCW0000X{number:03d}",
            lifecycle_state="Prod",
            location_hid=room["hid"],
            record_status="draft",
        )
        for number in range(1, 4)
    ]

    def counts(**view: Any) -> dict[str, Any]:
        summary = money.get("/reports/summary", **view)["totals"]
        management = money.get("/reports/management", **view)["totals"]
        tree = money.get("/geography/tree", **view)
        capacity = money.get("/reports/capacity")
        coverage = money.get("/reports/coverage", **view)["totals"]
        return {
            "listed": money.get("/items", **view)["total"],
            "sites": money.get("/sites", **view)["total"],
            "components": summary["component_count"],
            "nodes": summary["managed_node_count"],
            "weight": summary["support_weight"],
            "cost": management["annual_support_cost"],
            "value": management["est_value"],
            "tree": tree["totals"]["items"],
            "demand": capacity["active"]["infrastructure_demand"],
            "what_if": capacity["with_drafts"]["support_weight"],
            "in_service": coverage["in_service"],
        }

    nothing = {
        "listed": 0,
        "sites": 0,
        "components": 0,
        "nodes": 0,
        "weight": "0",
        "cost": "0.00",
        "value": "0.00",
        "tree": 0,
        "demand": "0",
        "what_if": "3",
        "in_service": 0,
    }
    assert counts() == nothing
    with_drafts = counts(include_drafts=True)
    assert (with_drafts["listed"], with_drafts["sites"], with_drafts["components"]) == (3, 1, 3)
    assert (with_drafts["weight"], with_drafts["cost"]) == ("3", "3600.00")

    # Made active: the site, its room, and then the items.
    site = money.get(f"/sites/{site['hid']}")
    money.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "record_status": "active"}
    )
    room = money.get(f"/locations/{room['hid']}")
    money.patch(
        f"/locations/{room['hid']}", {"row_version": room["row_version"], "record_status": "active"}
    )
    for draft in drafts:
        money.patch(
            f"/items/{draft['hid']}",
            {"row_version": draft["row_version"], "record_status": "active"},
        )
    active = counts()
    assert active == {
        "listed": 3,
        "sites": 1,
        "components": 3,
        "nodes": 3,
        "weight": "3",
        "cost": "3600.00",
        "value": "54000.00",
        "tree": 3,
        "demand": "0.01",
        "what_if": "3",
        "in_service": 3,
    }


def test_s35_an_archived_item_is_hidden_greyed_when_included_and_keeps_its_history(
    money: Money,
) -> None:
    entry = money.entry()
    kept = money.item(entry, "FCW0000X001", lifecycle_state="Prod")
    gone = money.item(entry, "FCW0000X002", lifecycle_state="Prod")
    gone = money.move(gone, "Pending-Removal", "Released", "Archived")

    # Hidden by default.
    assert [item["hid"] for item in money.get("/items")["items"]] == [kept["hid"]]
    assert money.get("/reports/summary")["totals"]["items"] == 1
    # Shown when asked for, and told apart by its state, which a page greys.
    included = money.get("/items", include_archived=True, sort="serial_number")["items"]
    assert [item["hid"] for item in included] == [kept["hid"], gone["hid"]]
    assert [item["lifecycle_state"] for item in included] == ["Prod", "Archived"]
    # Still reachable by its HID, with nothing asked for.
    reached = money.get(f"/items/{gone['hid']}")
    assert reached["lifecycle_state"] == "Archived"
    assert reached["record_status"] == "active"
    # Its history is whole: created, and each of the three moves, with who made it.
    history = money.get(f"/items/{gone['hid']}/history", sort="at")["items"]
    assert [event["action"] for event in history] == ["create", *["transition"] * 3]
    moves = [
        (change["old"], change["new"])
        for event in history
        for change in event["changes"]
        if change["field"] == "lifecycle_state" and event["action"] == "transition"
    ]
    assert moves == [
        ("Prod", "Pending-Removal"),
        ("Pending-Removal", "Released"),
        ("Released", "Archived"),
    ]
    assert all(event["actor_name"] == IVY[0] for event in history)


def test_s39_the_worked_example_balances_at_minus_one_and_ninety_percent(money: Money) -> None:
    money.weigh("2400")
    money.worked_example()

    report = money.get("/reports/capacity")
    active = report["active"]
    assert report["weight_per_resource_unit"] == "300"
    assert active["support_weight"] == "2400"
    assert active["infrastructure_demand"] == "8"
    assert active["other_demand"] == "2"
    assert active["demand"] == "10"
    assert active["supply"] == "9"
    assert active["balance"] == "-1"
    assert active["coverage_pct"] == "90"
    by_category = {row["category"]: row["units"] for row in active["by_category"]}
    assert by_category == {
        "staff": "6",
        "professional_services": "1",
        "smart_hands": "0.5",
        "tools": "1.5",
        "services": "0",
    }
    # Two thirds of the supply is the team's own six positions.
    assert (active["own_units"], active["outside_units"]) == ("6", "3")
    assert active["own_share_pct"] == "66.67"


def test_s40_a_draft_line_balances_the_books_and_an_ended_line_drops_out(money: Money) -> None:
    money.weigh("2400")
    lines = money.worked_example()
    money.line("supply", "services", "AI assistant", "1", "1.0", record_status="draft")

    report = money.get("/reports/capacity")
    assert (report["active"]["supply"], report["active"]["balance"]) == ("9", "-1")
    assert (report["with_drafts"]["supply"], report["with_drafts"]["balance"]) == ("10", "0")
    assert report["with_drafts"]["coverage_pct"] == "100"

    partner = lines["Escalation partner"]
    money.patch(
        f"/capacity-lines/{partner['hid']}",
        {"row_version": partner["row_version"], "ends_on": LONG_AGO},
    )
    report = money.get("/reports/capacity")
    assert (report["active"]["supply"], report["active"]["balance"]) == ("8", "-2")
    assert (report["with_drafts"]["supply"], report["with_drafts"]["balance"]) == ("9", "-1")
    for view in ("active", "with_drafts"):
        by_category = {row["category"]: row["units"] for row in report[view]["by_category"]}
        assert by_category["professional_services"] == "0"
