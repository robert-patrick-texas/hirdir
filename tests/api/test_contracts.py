"""Support agreements, contracts and coverage: one record for many items, renewed in
one place, and what a contract has from the agreement it is grouped into."""

import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Agreement, Contract, ContractCoverage, Item
from hirdir.domain import contracts
from hirdir.io import fields
from tests.api.inventory import API, Maker, errors

TODAY = date.today()


def day(offset: int) -> str:
    """Return a day well clear of today, so that no time zone moves it across."""
    return (TODAY + timedelta(days=offset)).isoformat()


LAST_YEAR, NEXT_YEAR = day(-300), day(300)


class Desk(Maker):
    """A maker who also enters agreements and contracts and covers items."""

    def catalog(self) -> dict[str, Any]:
        self.cisco = self.vendor("Cisco")
        return self.entry(self.cisco, annual_support_cost="1200.00", support_weight="1")

    def switch(self, entry: dict[str, Any], serial: str, **more: Any) -> dict[str, Any]:
        more.setdefault("lifecycle_state", "Prod")
        return self.item(catalog_entry_hid=entry["hid"], serial_number=serial, **more)

    def agreement(self, name: str = "Cisco Enterprise Agreement", **more: Any) -> dict[str, Any]:
        more.setdefault("vendor_hid", self.cisco["hid"])
        return self.post("/agreements", {"name": name, **more})

    def contract(self, number: str, expect: int = 201, **more: Any) -> dict[str, Any]:
        if "agreement_hid" not in more:
            more.setdefault("vendor_hid", self.cisco["hid"])
        return self.post("/contracts", {"number": number, **more}, expect)

    def cover(self, contract: dict[str, Any], *items: dict[str, Any], expect: int = 201, **dates):
        body = {"items": [{"item_hid": item["hid"], **dates} for item in items]}
        response = self.client.post(
            f"{API}/contracts/{contract['hid']}/coverage", json=body, headers=self.headers
        )
        assert response.status_code == expect, response.text
        return response.json()

    def change(self, path: str, **fields_: Any) -> dict[str, Any]:
        now = self.get(path)
        return self.patch(path, {"row_version": now["row_version"], **fields_})

    def covered(self, item: dict[str, Any]) -> tuple[bool, str | None, list[str]]:
        found = self.get(f"/items/{item['hid']}")
        numbers = [one["contract"]["number"] for one in found["coverage"] if one["in_force"]]
        return found["covered"], found["covered_until"], numbers


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


def test_a_contract_is_one_record_for_the_many_items_it_covers(desk: Desk) -> None:
    entry = desk.catalog()
    switches = [desk.switch(entry, f"FCW-{number}") for number in range(3)]
    contract = desk.contract(
        "CON-2026-0001",
        starts_on=LAST_YEAR,
        ends_on=NEXT_YEAR,
        support_level="8x5",
        purchase_reference="RITM0010452",
        account_manager="Jordan Reyes, +1 555 0142",
        support_contact="Support desk, +1 555 0100",
        support_url="https://support.example.com/c",
        annual_cost="3600.00",
    )
    assert (contract["covers_today"], contract["covered_items"]) == (True, 0)
    assert contract["purchase_reference"] == "RITM0010452"
    assert contract["vendor"]["name"] == "Cisco"
    made = desk.cover(contract, *switches)
    # A coverage with no dates of its own is for the contract's period.
    assert {(one["starts_on"], one["ends_on"]) for one in made} == {(None, None)}
    assert {(one["effective_starts_on"], one["effective_ends_on"]) for one in made} == {
        (LAST_YEAR, NEXT_YEAR)
    }
    assert all(one["in_force"] for one in made)
    for switch in switches:
        assert desk.covered(switch) == (True, NEXT_YEAR, ["CON-2026-0001"])
    now = desk.get(f"/contracts/{contract['hid']}")
    assert (now["covered_items"], now["items_in_scope"]) == (3, 3)
    # Found, filtered and sorted by what covers it, on the item list.
    assert desk.get("/items", filter="covered:eq:true")["total"] == 3
    assert desk.get("/items", filter="contract.number:eq:con-2026-0001")["total"] == 3
    assert desk.get("/items", filter=f"covered_until:lte:{NEXT_YEAR}")["total"] == 3
    assert desk.get("/items", filter="contract.number:empty:true")["total"] == 0
    desk.get("/items", sort="contract.number,-covered_until")
    found = desk.get("/contracts", filter=f"coverage.item_hid:eq:{switches[0]['hid']}")
    assert [one["number"] for one in found["items"]] == ["CON-2026-0001"]
    desk.get("/contracts", sort="-covered_items,vendor")


def test_what_a_contract_must_be(desk: Desk) -> None:
    desk.catalog()
    desk.contract("CON-1")
    assert "number" in errors(desk.contract("con-1", expect=409))
    assert "number" in errors(desk.contract(" ", expect=422))
    juniper = desk.vendor("Juniper")
    # Two vendors may use one number.
    desk.contract("CON-1", vendor_hid=juniper["hid"])
    assert "vendor_hid" in errors(desk.post("/contracts", {"number": "CON-2"}, 422))
    assert "ends_on" in errors(
        desk.contract("CON-3", expect=422, starts_on=day(10), ends_on=day(5))
    )
    assert "support_url" in errors(desk.contract("CON-4", expect=422, support_url="ftp://x"))
    nobody = "01900000-0000-7000-8000-000000000000"
    assert "reseller_hid" in errors(desk.contract("CON-5", expect=422, reseller_hid=nobody))
    desk.post(
        "/contracts", {"number": "CON-6", "vendor_hid": desk.cisco["hid"], "status": "x"}, 422
    )


def test_a_contract_covers_only_while_it_is_active_and_in_date(desk: Desk) -> None:
    entry = desk.catalog()
    switch = desk.switch(entry, "FCW-1")
    contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    desk.cover(contract, switch)
    path = f"/contracts/{contract['hid']}"
    for change, covered in (
        ({"status": "pending"}, False),
        ({"status": "active"}, True),
        ({"ends_on": day(-5)}, False),
        ({"ends_on": None}, True),
        ({"starts_on": day(5)}, False),
        ({"starts_on": None}, True),
        ({"record_status": "draft"}, False),
        ({"record_status": "active"}, True),
    ):
        desk.change(path, **change)
        assert desk.covered(switch)[0] is covered, change
        assert desk.get("/items", filter="covered:eq:true")["total"] == int(covered), change
    # No end on the contract and none on the coverage: the cover never runs out.
    assert desk.covered(switch) == (True, None, ["CON-1"])
    retired = desk.post(f"{path}/retire", {"row_version": desk.get(path)["row_version"]}, 200)
    assert retired["record_status"] == "retired"
    assert desk.covered(switch)[0] is False
    assert "contract_hid" in errors(desk.cover(retired, desk.switch(entry, "FCW-2"), expect=422))


def test_a_coverage_is_ended_with_a_date_and_never_overlaps_another(desk: Desk) -> None:
    entry = desk.catalog()
    switch = desk.switch(entry, "FCW-1")
    contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    (first,) = desk.cover(contract, switch)
    path = f"/contracts/{contract['hid']}/coverage"
    # The same item is not covered twice in the same days.
    assert "items.0.ends_on" in errors(desk.cover(contract, switch, expect=409))
    assert "items.0.ends_on" in errors(desk.cover(contract, switch, expect=409, starts_on=day(30)))
    ended = desk.patch(
        f"{path}/{first['hid']}", {"row_version": first["row_version"], "ends_on": day(-30)}
    )
    assert (ended["in_force"], ended["effective_ends_on"]) == (False, day(-30))
    assert desk.covered(switch) == (False, None, [])
    # It comes back: a second coverage, after the first.
    assert "items.0.ends_on" in errors(desk.cover(contract, switch, expect=409, starts_on=day(-40)))
    (second,) = desk.cover(contract, switch, starts_on=day(-10))
    assert second["in_force"] is True
    listed = desk.get(path, sort="starts_on")
    assert listed["total"] == 2
    assert desk.get(path, filter="in_force:eq:true")["total"] == 1
    # Its contract and its item are not changed, and its days stay a range.
    other = desk.switch(entry, "FCW-2")
    body = {"row_version": second["row_version"], "item_hid": other["hid"]}
    desk.patch(f"{path}/{second['hid']}", body, 422)
    assert "ends_on" in errors(
        desk.patch(
            f"{path}/{second['hid']}",
            {"row_version": second["row_version"], "ends_on": day(-20)},
            422,
        )
    )
    retired = desk.switch(entry, "FCW-3")
    desk.post(f"/items/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)
    assert "items.0.item_hid" in errors(desk.cover(contract, retired, expect=422))
    # All of them, or none.
    assert "items.1.item_hid" in errors(
        desk.post(path, {"items": [{"item_hid": other["hid"]}, {"item_hid": "no-such-item"}]}, 422)
    )
    assert desk.covered(other)[0] is False
    # One that was a mistake is removed outright, and the audit trail holds what it was.
    (mistake,) = desk.cover(contract, other, starts_on=day(-5))
    desk.delete(f"{path}/{mistake['hid']}")
    assert desk.get(path)["total"] == 2
    assert desk.covered(other)[0] is False
    removed = desk.audit(record_type="contract_coverage", record_hid=mistake["hid"])[0]
    assert removed["action"] == "delete"
    assert {change["field"]: change["old"] for change in removed["changes"]} == {
        "contract_hid": contract["hid"],
        "item_hid": other["hid"],
        "starts_on": day(-5),
    }
    desk.delete(f"{path}/{mistake['hid']}", 404)
    # Under a retired contract nothing of a coverage is changed.
    now = desk.get(f"/contracts/{contract['hid']}")
    desk.post(f"/contracts/{contract['hid']}/retire", {"row_version": now["row_version"]}, 200)
    again = {"row_version": ended["row_version"], "ends_on": None}
    assert "contract_hid" in errors(desk.patch(f"{path}/{first['hid']}", again, 422))


def test_coverage_ends_when_its_item_leaves_service(desk: Desk, db: Session) -> None:
    entry = desk.catalog()
    retired, archived, failing, staying = (desk.switch(entry, f"FCW-{n}") for n in range(4))
    contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    desk.cover(contract, retired, archived, failing, staying)
    today = desk.get("/reports/coverage")["as_of"]

    desk.post(f"/items/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)
    desk.move(desk.move(desk.move(archived, "Pending-Removal"), "Released"), "Archived")
    desk.move(failing, "Pending-Removal")

    # Retired, and released: the coverage ended that day, and says why.
    for item in (retired, archived):
        (its,) = desk.get(f"/items/{item['hid']}")["coverage"]
        assert (its["ends_on"], its["left_service"]) == (today, True)
        (event,) = desk.audit(
            record_type="contract_coverage", record_hid=its["hid"], action="update"
        )
        assert {change["field"]: change["new"] for change in event["changes"]} == {
            "ends_on": today,
            "left_service": True,
        }
    # On its way out is not out: it is still covered, and nothing was ended.
    (still,) = desk.get(f"/items/{failing['hid']}")["coverage"]
    assert (still["ends_on"], still["left_service"], still["in_force"]) == (NEXT_YEAR, False, True)
    # All three are what the vendor still counts and need not: the list to send.
    report = desk.get("/reports/coverage", section="out_of_service", sort="serial_number")
    assert [item["serial_number"] for item in report["items"]] == ["FCW-0", "FCW-1", "FCW-2"]
    assert report["totals"]["out_of_service"] == 3
    section = report["sections"]["out_of_service"]
    same = desk.post(
        "/items/query",
        {"filter": section["filter"], "include_archived": section["include_archived"]},
        200,
    )
    assert same["total"] == 3
    # The vendor is told: a person clears the mark, and the item leaves the list.
    (of_retired,) = desk.get(
        f"/contracts/{contract['hid']}/coverage", filter=f"item_hid:eq:{retired['hid']}"
    )["items"]
    cleared = desk.patch(
        f"/contracts/{contract['hid']}/coverage/{of_retired['hid']}",
        {"row_version": of_retired["row_version"], "left_service": False},
    )
    assert cleared["left_service"] is False
    assert desk.get("/reports/coverage")["totals"]["out_of_service"] == 2
    # A renewal into a new period ends the old term: what left in it leaves the list.
    # The archived switch is made to have left a month ago, which is before that period.
    for coverage in db.scalars(
        select(ContractCoverage).where(ContractCoverage.item_hid == archived["hid"])
    ):
        coverage.ends_on = TODAY - timedelta(days=30)
    db.commit()
    assert desk.get("/reports/coverage")["totals"]["out_of_service"] == 2
    desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": desk.get(f"/contracts/{contract['hid']}")["row_version"],
            "number": "CON-2",
            "starts_on": day(-1),
            "ends_on": day(700),
        },
        200,
    )
    left = desk.get("/reports/coverage", section="out_of_service")
    assert [item["serial_number"] for item in left["items"]] == ["FCW-2"]


def test_a_date_that_is_the_contracts_own_is_kept_blank_and_follows_a_renewal(desk: Desk) -> None:
    entry = desk.catalog()
    follows, joined_late, left = (desk.switch(entry, f"FCW-{number}") for number in range(3))
    contract = desk.contract(
        "CON-2026-0001", starts_on=LAST_YEAR, ends_on=day(20), purchase_reference="RITM0001"
    )
    (typed,) = desk.cover(contract, follows, starts_on=LAST_YEAR, ends_on=day(20))
    assert (typed["starts_on"], typed["ends_on"]) == (None, None)
    desk.cover(contract, joined_late, starts_on=day(-60))
    (gone,) = desk.cover(contract, left)
    desk.patch(
        f"/contracts/{contract['hid']}/coverage/{gone['hid']}",
        {"row_version": gone["row_version"], "ends_on": day(-30)},
    )
    assert desk.get(f"/contracts/{contract['hid']}")["items_in_scope"] == 2
    version = desk.get(f"/items/{follows['hid']}")["row_version"]

    renewed = desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": contract["row_version"],
            "number": "CON-2027-0001",
            "starts_on": day(-1),
            "ends_on": day(386),
            "purchase_reference": "RITM0002",
            "annual_cost": "4000.00",
        },
        200,
    )
    assert (renewed["number"], renewed["status"], renewed["next_term"]) == (
        "CON-2027-0001",
        "active",
        None,
    )
    # One change of one record: the items in scope show the new number and period at
    # once, and neither they nor their coverages were written to.
    listed = desk.get(f"/items/{follows['hid']}")
    assert listed["row_version"] == version
    assert [one["contract"]["number"] for one in listed["coverage"]] == ["CON-2027-0001"]
    assert (listed["covered"], listed["covered_until"]) == (True, day(386))
    late = desk.get(f"/items/{joined_late['hid']}")["coverage"][0]
    assert (late["starts_on"], late["ends_on"]) == (day(-1), day(386))
    # What was ended on a day of its own stays ended.
    assert desk.get(f"/items/{left['hid']}")["coverage"][0]["ends_on"] == day(-30)
    events = desk.audit(record_type="contract", record_hid=contract["hid"])
    assert [event["action"] for event in events] == ["renew", "create"]
    # The term it had is its purchase history.
    terms = desk.get(f"/contracts/{contract['hid']}/terms")
    assert [
        (term["number"], term["starts_on"], term["ends_on"], term["purchase_reference"])
        for term in terms
    ] == [("CON-2026-0001", LAST_YEAR, day(20), "RITM0001")]
    assert terms[0]["annual_cost"] is None
    assert terms[0]["renewed_by_name"] == "ivy"
    # A renewal says something new, and nothing it does not own.
    again = {"row_version": renewed["row_version"]}
    assert "ends_on" in errors(desk.post(f"/contracts/{contract['hid']}/renew", again, 422))
    desk.post(f"/contracts/{contract['hid']}/renew", {**again, "vendor_hid": "x"}, 422)
    second = desk.post(
        f"/contracts/{contract['hid']}/renew", {**again, "number": "CON-2028-0001"}, 200
    )
    assert [term["number"] for term in desk.get(f"/contracts/{second['hid']}/terms")] == [
        "CON-2027-0001",
        "CON-2026-0001",
    ]


def test_a_renewal_entered_early_leaves_the_old_term_running(desk: Desk, db: Session) -> None:
    entry = desk.catalog()
    switch = desk.switch(entry, "FCW-1")
    contract = desk.contract(
        "CON-2026-0001", starts_on=LAST_YEAR, ends_on=day(47), purchase_reference="RITM0001"
    )
    desk.cover(contract, switch)
    path = f"/contracts/{contract['hid']}"
    version = desk.get(f"/items/{switch['hid']}")["row_version"]
    ahead = {
        "row_version": contract["row_version"],
        "number": "CON-2027-0001",
        "starts_on": day(48),
        "ends_on": day(412),
        "purchase_reference": "RITM0002",
    }
    # A term that is still to begin says when it ends.
    without = {name: value for name, value in ahead.items() if name != "ends_on"}
    assert "ends_on" in errors(desk.post(f"{path}/renew", without, 422))
    renewed = desk.post(f"{path}/renew", ahead, 200)
    # The present number and period stay in force, and the new ones wait.
    assert (renewed["number"], renewed["starts_on"], renewed["ends_on"]) == (
        "CON-2026-0001",
        LAST_YEAR,
        day(47),
    )
    assert renewed["next_term"] == {
        "number": "CON-2027-0001",
        "starts_on": day(48),
        "ends_on": day(412),
        "annual_cost": None,
        "purchase_reference": "RITM0002",
        "with_agreement": False,
    }
    # The item is covered throughout, to the end of the term to come, and unwritten.
    item = desk.get(f"/items/{switch['hid']}")
    assert (item["covered"], item["covered_until"], item["row_version"]) == (
        True,
        day(412),
        version,
    )
    assert desk.get("/items", filter=f"covered_until:eq:{day(412)}")["total"] == 1
    report = desk.get("/reports/coverage")["totals"]
    assert (report["covered"], report["uncovered"], report["expiring"]) == (1, 0, 0)
    assert desk.get(f"{path}/terms") == []
    # It answers to both numbers, and no other contract of the vendor may take the new.
    for number in ("CON-2026-0001", "CON-2027-0001"):
        assert desk.get("/contracts", filter="next_starts_on:empty:false")["total"] == 1
        made = desk.contract(number, expect=409)
        assert "number" in errors(made)
    # Withdrawn, and entered again.
    withdrawn = desk.post(
        f"{path}/renew", {"row_version": renewed["row_version"], "withdraw": True}, 200
    )
    assert withdrawn["next_term"] is None
    assert desk.get(f"/items/{switch['hid']}")["covered_until"] == day(47)
    nothing = {"row_version": withdrawn["row_version"], "withdraw": True}
    assert "withdraw" in errors(desk.post(f"{path}/renew", nothing, 422))
    again = desk.post(f"{path}/renew", {**ahead, "row_version": withdrawn["row_version"]}, 200)

    # The day comes. Nothing is written by a clock: the record reads differently.
    held = db.get_one(Contract, contract["hid"])
    held.starts_on, held.ends_on = TODAY - timedelta(days=400), TODAY - timedelta(days=3)
    held.next_starts_on, held.next_ends_on = TODAY - timedelta(days=2), TODAY + timedelta(days=362)
    db.commit()
    now = desk.get(path)
    assert (now["number"], now["starts_on"], now["ends_on"], now["purchase_reference"]) == (
        "CON-2027-0001",
        day(-2),
        day(362),
        "RITM0002",
    )
    assert (now["next_term"], now["covers_today"], now["lapsed"]) == (None, True, False)
    # The version moved with the term: what was read before that day is stale, and an
    # edit that was meant for the old term is refused and not made to the new one.
    assert now["row_version"] == again["row_version"] + 1
    assert desk.get("/contracts", filter=f"row_version:eq:{now['row_version']}")["total"] == 1
    stale = {"row_version": again["row_version"], "annual_cost": "150.00"}
    assert desk.patch(path, stale, 409)["status"] == 409
    db.expire_all()
    assert db.get_one(Contract, contract["hid"]).next_starts_on is not None
    item = desk.get(f"/items/{switch['hid']}")
    assert (item["covered"], item["covered_until"]) == (True, day(362))
    assert [one["contract"]["number"] for one in item["coverage"]] == ["CON-2027-0001"]
    assert desk.get("/contracts", filter="number:eq:CON-2027-0001")["total"] == 1
    assert desk.get("/items", filter="contract.number:eq:con-2027-0001")["total"] == 1
    (before_it_was_written,) = desk.get(f"{path}/terms")
    # The first change after that day writes the term down, and is then made.
    changed = desk.patch(path, {"row_version": now["row_version"], "notes": "Renewed on time"})
    assert (changed["number"], changed["notes"]) == ("CON-2027-0001", "Renewed on time")
    assert changed["row_version"] == now["row_version"] + 1
    actions = [
        event["action"] for event in desk.audit(record_type="contract", record_hid=contract["hid"])
    ]
    assert actions[:2] == ["update", "renew"]
    # The term it had says when its renewal was entered and by whom, the same before
    # and after it was written down, whatever change did the writing.
    (earlier,) = desk.get(f"{path}/terms")
    assert earlier == before_it_was_written
    assert (earlier["number"], earlier["renewed_by_name"]) == ("CON-2026-0001", "ivy")
    entered = desk.audit(record_type="contract", record_hid=contract["hid"])[2]
    assert (entered["action"], earlier["renewed_at"]) == ("renew", entered["at"])


def test_a_late_renewal_is_pending_and_a_silent_one_has_lapsed(desk: Desk) -> None:
    entry = desk.catalog()
    switch = desk.switch(entry, "FCW-1")
    contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=day(-10))
    desk.cover(contract, switch)
    path = f"/contracts/{contract['hid']}"
    # Its period has ended and it still says active: it has lapsed, and covers nothing.
    now = desk.get(path)
    assert (now["lapsed"], now["covers_today"]) == (True, False)
    assert desk.covered(switch)[0] is False
    report = desk.get("/reports/coverage")
    assert report["lapsed_contracts"]["count"] == 1
    listed = desk.get("/contracts", filter=json.dumps(report["lapsed_contracts"]["filter"]))
    assert [one["number"] for one in listed["items"]] == ["CON-1"]
    assert (report["totals"]["uncovered"], report["totals"]["renewal_pending"]) == (1, 0)
    # Procurement is slow, and the vendor still supports it by escalation.
    pending = desk.patch(path, {"row_version": now["row_version"], "status": "renewal_pending"})
    assert (pending["lapsed"], pending["covers_today"], pending["covered_items"]) == (
        False,
        True,
        1,
    )
    assert desk.covered(switch) == (True, None, ["CON-1"])
    item = desk.get(f"/items/{switch['hid']}")
    assert item["coverage"][0]["contract"]["status"] == "renewal_pending"
    report = desk.get("/reports/coverage", section="renewal_pending")
    assert report["lapsed_contracts"]["count"] == 0
    assert (report["totals"]["uncovered"], report["totals"]["renewal_pending"]) == (0, 1)
    assert [one["hid"] for one in report["items"]] == [switch["hid"]]
    assert desk.get("/items", filter="contract.status:eq:renewal_pending")["total"] == 1
    # The renewal arrives at last: active again, in its new period.
    renewed = desk.post(
        f"{path}/renew",
        {
            "row_version": pending["row_version"],
            "number": "CON-2",
            "starts_on": day(-9),
            "ends_on": day(355),
        },
        200,
    )
    assert (renewed["status"], renewed["lapsed"]) == ("active", False)
    assert desk.covered(switch) == (True, day(355), ["CON-2"])
    assert desk.get("/reports/coverage")["totals"]["renewal_pending"] == 0
    # An agreement lapses in the same way, and is renewed in the same way.
    agreement = desk.agreement(starts_on=LAST_YEAR, ends_on=day(-2))
    assert agreement["lapsed"] is True
    assert desk.get("/agreements", filter="lapsed:eq:true")["total"] == 1
    inside = desk.contract("CON-9", agreement_hid=agreement["hid"])
    assert (inside["lapsed"], inside["covers_today"]) == (True, False)
    ahead = desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {"row_version": agreement["row_version"], "starts_on": day(30), "ends_on": day(394)},
        200,
    )
    assert ahead["next_term"]["starts_on"] == day(30)
    at_once = desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {"row_version": ahead["row_version"], "starts_on": day(-1), "ends_on": day(364)},
        200,
    )
    assert (at_once["lapsed"], at_once["next_term"], at_once["ends_on"]) == (False, None, day(364))
    assert desk.get(f"/contracts/{inside['hid']}")["covers_today"] is True


def test_a_contract_has_from_its_agreement_what_it_leaves_blank(desk: Desk) -> None:
    entry = desk.catalog()
    reseller = desk.vendor("Example Reseller")
    agreement = desk.agreement(
        number="EA-0004417",
        reseller_hid=reseller["hid"],
        starts_on=LAST_YEAR,
        ends_on=NEXT_YEAR,
        support_level="24x7",
        account_manager="Jordan Reyes, +1 555 0142",
        support_contact="Enterprise desk, +1 555 0100",
        support_url="https://support.example.com/ea",
    )
    assert agreement["contracts"] == 0
    # In an agreement, a new contract needs no vendor of its own.
    campus = desk.contract("CON-1", agreement_hid=agreement["hid"])
    wireless = desk.contract("CON-2", agreement_hid=agreement["hid"], support_level="8x5")
    assert campus["vendor_hid"] == desk.cisco["hid"]
    assert campus["agreement"] == {
        "hid": agreement["hid"],
        "name": "Cisco Enterprise Agreement",
        "number": "EA-0004417",
    }
    assert campus["starts_on"] is None
    in_force = campus["effective"]
    for name, value in (
        ("starts_on", LAST_YEAR),
        ("ends_on", NEXT_YEAR),
        ("support_level", "24x7"),
        ("account_manager", "Jordan Reyes, +1 555 0142"),
        ("support_contact", "Enterprise desk, +1 555 0100"),
        ("support_url", "https://support.example.com/ea"),
    ):
        assert in_force[name] == {
            "value": value,
            "source": "agreement",
            "source_hid": agreement["hid"],
            "from_agreement": value,
        }
    assert in_force["reseller_hid"] == {
        "value": reseller["hid"],
        "label": "Example Reseller",
        "source": "agreement",
        "source_hid": agreement["hid"],
        "from_agreement": reseller["hid"],
        "from_agreement_label": "Example Reseller",
    }
    # An override says what it is in place of: the server says it, not the page.
    assert wireless["effective"]["support_level"] == {
        "value": "8x5",
        "source": "own",
        "source_hid": wireless["hid"],
        "from_agreement": "24x7",
    }
    # The same value as the agreement's, said of its own, is still an override.
    same = desk.change(f"/contracts/{wireless['hid']}", support_url=agreement["support_url"])
    assert same["effective"]["support_url"]["source"] == "own"
    assert same["effective"]["support_url"]["from_agreement"] == agreement["support_url"]
    desk.change(f"/contracts/{wireless['hid']}", support_url=None)
    assert campus["covers_today"] is True
    switch = desk.switch(entry, "FCW-1")
    desk.cover(campus, switch)
    assert desk.covered(switch) == (True, NEXT_YEAR, ["CON-1"])
    assert desk.get(f"/agreements/{agreement['hid']}")["contracts"] == 2
    listed = desk.get("/contracts", filter="agreement.name:eq:cisco enterprise agreement")
    assert listed["total"] == 2
    assert desk.get("/contracts", filter=f"effective.ends_on:eq:{NEXT_YEAR}")["total"] == 2
    assert desk.get("/contracts", filter="effective.support_level:eq:8x5")["total"] == 1
    desk.get("/contracts", sort="agreement.name,-effective.ends_on")

    # Said once on the agreement: every contract that says nothing of its own follows,
    # and so does every item under those contracts. Nothing beneath is written to.
    before = (desk.get(f"/contracts/{campus['hid']}")["row_version"], switch["row_version"])
    desk.change(
        f"/agreements/{agreement['hid']}",
        ends_on=day(500),
        account_manager="Sam Whitlock, +1 555 0155",
        support_level="24x7, four-hour response",
    )
    campus_now = desk.get(f"/contracts/{campus['hid']}")
    assert campus_now["effective"]["account_manager"]["value"] == "Sam Whitlock, +1 555 0155"
    assert campus_now["effective"]["ends_on"]["value"] == day(500)
    assert desk.get(f"/contracts/{wireless['hid']}")["effective"]["support_level"]["value"] == "8x5"
    assert desk.covered(switch)[1] == day(500)
    after = (campus_now["row_version"], desk.get(f"/items/{switch['hid']}")["row_version"])
    assert after == before
    assert (
        desk.get(f"/contracts/{wireless['hid']}")["effective"]["support_level"]["from_agreement"]
        == "24x7, four-hour response"
    )
    # An override is cleared, and the agreement speaks again.
    cleared = desk.change(f"/contracts/{wireless['hid']}", support_level=None)
    assert cleared["effective"]["support_level"]["source"] == "agreement"
    # The agreement's period ends: so does the cover of what is co-termed with it.
    desk.change(f"/agreements/{agreement['hid']}", ends_on=day(-3))
    assert desk.covered(switch)[0] is False
    assert desk.get("/items", filter="covered:eq:true")["total"] == 0
    # A contract in no agreement has nothing from one.
    alone = desk.contract("CON-3", support_level="8x5")
    # The contact records in force are lists, and say only where they came from.
    lists = ("account_managers", "support_contacts")
    texts = [its for name, its in alone["effective"].items() if name not in lists]
    assert {its["from_agreement"] for its in texts} == {None}
    assert alone["effective"]["account_managers"] == {
        "value": [],
        "source": "none",
        "source_hid": None,
    }
    assert alone["effective"]["reseller_hid"]["from_agreement_label"] is None


def test_the_contracts_that_still_count_an_item_out_of_service_are_a_field(
    desk: Desk, client: TestClient, inventory: dict[str, str]
) -> None:
    entry = desk.catalog()
    first = desk.contract("CON-B-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    second = desk.contract("CON-A-2", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    leaving = desk.switch(entry, "FCW-1")
    archived = desk.switch(entry, "FCW-2")
    staying = desk.switch(entry, "FCW-3")
    desk.cover(first, leaving, archived, staying)
    desk.cover(second, leaving)
    desk.move(leaving, "Pending-Removal")
    desk.move(desk.move(desk.move(archived, "Pending-Removal"), "Released"), "Archived")
    # Pending-Removal ends nothing: both still cover it. Archived ended its coverage, and
    # the vendor still counts it while the term runs.
    record = desk.get(f"/items/{leaving['hid']}")
    assert [ref["number"] for ref in record["out_of_service_contracts"]] == ["CON-A-2", "CON-B-1"]
    gone = desk.get(f"/items/{archived['hid']}")
    assert [ref["number"] for ref in gone["out_of_service_contracts"]] == ["CON-B-1"]
    assert desk.get(f"/items/{staying['hid']}")["out_of_service_contracts"] == []
    found = desk.get(
        "/items", filter="out_of_service_contract.number:eq:con-b-1", include_archived="true"
    )
    assert {one["hid"] for one in found["items"]} == {leaving["hid"], archived["hid"]}
    found = desk.get(
        "/items", filter=f"out_of_service_contract.hid:eq:{second['hid']}", include_archived="true"
    )
    assert [one["hid"] for one in found["items"]] == [leaving["hid"]]
    ordered = desk.get(
        "/items", sort="out_of_service_contract.number,serial_number", include_archived="true"
    )
    assert [one["serial_number"] for one in ordered["items"]] == ["FCW-1", "FCW-2", "FCW-3"]
    # The vendor is told: the archived item is no longer counted.
    (ended,) = [one for one in gone["coverage"] if one["left_service"]]
    held = desk.get("/contract-coverage", filter=f"hid:eq:{ended['hid']}")["items"][0]
    desk.patch(
        f"/contracts/{first['hid']}/coverage/{ended['hid']}",
        {"row_version": held["row_version"], "left_service": False},
    )
    assert desk.get(f"/items/{archived['hid']}")["out_of_service_contracts"] == []
    # In a file, as the numbers, and not loaded.
    response = client.post(
        f"{API}/exports",
        json={
            "entity": "items",
            "columns": ["serial_number", "out_of_service_contracts"],
            "sort": ["serial_number"],
            "include_archived": True,
        },
        headers=desk.headers,
    )
    assert response.status_code == 200, response.text
    lines = response.text.strip().splitlines()
    assert lines[0] == "hid,serial_number,out_of_service_contracts"
    assert [line.split(",", 2)[2] for line in lines[1:]] == ["CON-A-2;CON-B-1", "", ""]


def test_an_earlier_term_of_a_co_termed_contract_has_the_dates_it_had(
    desk: Desk, db: Session
) -> None:
    desk.catalog()
    agreement = desk.agreement(number="EA-1", starts_on=day(-700), ends_on=day(-340))
    path = f"/agreements/{agreement['hid']}"
    co_termed = desk.contract("CON-10", agreement_hid=agreement["hid"])
    half = desk.contract("CON-11", agreement_hid=agreement["hid"], starts_on=day(-650))
    # The agreement is renewed, and the contracts with it: each takes a new number.
    renewed = desk.post(
        f"{path}/renew",
        {
            "row_version": agreement["row_version"],
            "number": "EA-2",
            "starts_on": day(-339),
            "ends_on": day(20),
        },
        200,
    )
    assert renewed["starts_on"] == day(-339)
    for contract, number in ((co_termed, "CON-20"), (half, "CON-21")):
        now = desk.get(f"/contracts/{contract['hid']}")
        body = {"row_version": now["row_version"], "number": number}
        desk.post(f"/contracts/{contract['hid']}/renew", body, 200)
    # The agreement is changed again after: what the term had is what stood then. Each
    # contract was given its new number after the agreement was renewed, and its
    # earlier term still has the agreement's term it began in, EA-1's (D-163).
    desk.change(path, starts_on=day(-330))
    (earlier,) = desk.get(f"/contracts/{co_termed['hid']}/terms")
    assert (earlier["number"], earlier["agreement_hid"]) == ("CON-10", agreement["hid"])
    assert (earlier["starts_on"], earlier["starts_on_source"]) == (day(-700), "agreement")
    assert (earlier["ends_on"], earlier["ends_on_source"]) == (day(-340), "agreement")
    # Each date by itself: its own where it had one, the agreement's where it had none.
    (other,) = desk.get(f"/contracts/{half['hid']}/terms")
    assert (other["starts_on"], other["starts_on_source"]) == (day(-650), "own")
    assert (other["ends_on"], other["ends_on_source"]) == (day(-340), "agreement")
    # A contract that stands by itself has nothing from an agreement.
    alone = desk.contract("CON-30", starts_on=day(-100))
    desk.post(f"/contracts/{alone['hid']}/renew", {"row_version": 1, "number": "CON-31"}, 200)
    (its,) = desk.get(f"/contracts/{alone['hid']}/terms")
    assert (its["agreement_hid"], its["starts_on_source"], its["ends_on_source"]) == (
        None,
        "own",
        "none",
    )
    # The agreement has a purchase history of its own.
    (term,) = desk.get(f"{path}/terms")
    assert (term["number"], term["starts_on"], term["ends_on"]) == ("EA-1", day(-700), day(-340))
    assert term["renewed_by_name"] == "ivy"
    assert "starts_on_source" not in term
    assert desk.client.get(f"{API}/agreements/AGR-0/terms", headers=desk.headers).status_code == 404


def test_an_agreement_with_no_number_has_its_terms_too(desk: Desk) -> None:
    desk.catalog()
    agreement = desk.agreement(starts_on=day(-400), ends_on=day(-35))
    desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {"row_version": agreement["row_version"], "starts_on": day(-34), "ends_on": day(330)},
        200,
    )
    (term,) = desk.get(f"/agreements/{agreement['hid']}/terms")
    assert (term["number"], term["starts_on"], term["ends_on"]) == (None, day(-400), day(-35))


def test_a_standalone_contract_is_rolled_into_an_agreement_by_one_change(desk: Desk) -> None:
    entry = desk.catalog()
    agreement = desk.agreement(
        starts_on=LAST_YEAR, ends_on=NEXT_YEAR, account_manager="Jordan Reyes"
    )
    alone = desk.contract(
        "CON-2026-0107", starts_on=day(-60), ends_on=day(200), account_manager="Riley Lindqvist"
    )
    assert alone["agreement"] is None
    assert alone["effective"]["account_manager"]["source"] == "own"
    switch = desk.switch(entry, "FCW-1")
    desk.cover(alone, switch)
    rolled = desk.change(f"/contracts/{alone['hid']}", agreement_hid=agreement["hid"])
    # What it says of its own stays, as overrides.
    assert rolled["agreement"]["name"] == "Cisco Enterprise Agreement"
    assert rolled["effective"]["ends_on"] == {
        "value": day(200),
        "source": "own",
        "source_hid": alone["hid"],
        "from_agreement": NEXT_YEAR,
    }
    assert desk.covered(switch)[1] == day(200)
    # Cleared, it is co-termed with the agreement.
    desk.change(f"/contracts/{alone['hid']}", starts_on=None, ends_on=None, account_manager=None)
    assert desk.covered(switch) == (True, NEXT_YEAR, ["CON-2026-0107"])
    out = desk.change(f"/contracts/{alone['hid']}", agreement_hid=None)
    assert (out["agreement"], out["effective"]["ends_on"]["source"]) == (None, "none")
    assert desk.covered(switch) == (True, None, ["CON-2026-0107"])


def test_what_an_agreement_must_be(desk: Desk) -> None:
    desk.catalog()
    juniper = desk.vendor("Juniper")
    agreement = desk.agreement()
    assert "name" in errors(
        desk.post(
            "/agreements", {"name": "cisco enterprise agreement", "vendor_hid": juniper["hid"]}, 409
        )
    )
    assert "vendor_hid" in errors(desk.post("/agreements", {"name": "Another"}, 422))
    # A contract is grouped into an agreement with its own vendor.
    assert "agreement_hid" in errors(
        desk.contract(
            "JNP-1", expect=422, vendor_hid=juniper["hid"], agreement_hid=agreement["hid"]
        )
    )
    inside = desk.contract("CON-1", agreement_hid=agreement["hid"])
    assert "vendor_hid" in errors(
        desk.patch(
            f"/agreements/{agreement['hid']}",
            {"row_version": agreement["row_version"], "vendor_hid": juniper["hid"]},
            422,
        )
    )
    # Its period, with the contract's own start, must still be a period.
    assert "ends_on" in errors(
        desk.patch(
            f"/contracts/{inside['hid']}",
            {"row_version": inside["row_version"], "starts_on": day(10)},
        )
        and desk.patch(
            f"/agreements/{agreement['hid']}",
            {"row_version": agreement["row_version"], "starts_on": day(9), "ends_on": day(5)},
            422,
        )
    )
    # Retired only when no contract that is not retired is in it.
    path = f"/agreements/{agreement['hid']}"
    version = {"row_version": desk.get(path)["row_version"]}
    assert "record_status" in errors(desk.post(f"{path}/retire", version, 409))
    now = desk.get(f"/contracts/{inside['hid']}")
    desk.post(f"/contracts/{inside['hid']}/retire", {"row_version": now["row_version"]}, 200)
    assert desk.post(f"{path}/retire", version, 200)["record_status"] == "retired"
    assert desk.get("/agreements")["total"] == 0
    assert desk.get("/agreements", include_archived="true")["total"] == 1
    assert "agreement_hid" in errors(
        desk.contract("CON-9", expect=422, agreement_hid=agreement["hid"])
    )


def test_the_reports_are_by_contract_and_the_blank_row_is_what_none_covers(desk: Desk) -> None:
    entry = desk.catalog()
    both, one, bare = (desk.switch(entry, f"FCW-{number}") for number in range(3))
    first = desk.contract("CON-1", ends_on=NEXT_YEAR)
    second = desk.contract("CON-2", ends_on=NEXT_YEAR)
    desk.cover(first, both, one)
    desk.cover(second, both)
    summary = desk.get("/reports/summary", by="contract")
    assert [(row["label"], row["items"], row["component_count"]) for row in summary["rows"]] == [
        ("CON-1 (Cisco)", 2, 2),
        ("CON-2 (Cisco)", 1, 1),
        (None, 1, 1),
    ]
    assert summary["rows"][0]["key"] == first["hid"]
    # An item under two contracts is in the row of each, and the totals count it once.
    assert summary["totals"]["items"] == 3
    money = desk.get("/reports/management", by="contract")
    assert [(row["label"], row["annual_support_cost"]) for row in money["rows"]] == [
        ("CON-1 (Cisco)", "2400.00"),
        ("CON-2 (Cisco)", "1200.00"),
        (None, "1200.00"),
    ]
    assert money["totals"]["annual_support_cost"] == "3600.00"
    assert bare["hid"] not in {row["key"] for row in summary["rows"]}


def test_the_coverage_report_counts_what_its_filters_list(desk: Desk, admin: dict) -> None:
    entry = desk.catalog()
    covered, bare, soon, spare, leaving, twice = (desk.switch(entry, f"FCW-{n}") for n in range(6))
    arriving = desk.switch(entry, "FCW-9", lifecycle_state="Delivered")
    supply = desk.item(
        catalog_entry_hid=desk.entry(desk.cisco, "PWR-1")["hid"],
        serial_number="LIT-1",
        parent_item_hid=bare["hid"],
        position="PS-A",
    )
    long_contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    short_contract = desk.contract("CON-2", starts_on=LAST_YEAR, ends_on=day(40))
    desk.cover(long_contract, covered, leaving, twice)
    desk.cover(short_contract, soon, twice)
    # Handed to the team and parked: in service, and a gap when nothing covers it.
    desk.move(desk.move(spare, "Down"), "Pending-Removal")
    spare = desk.move(desk.get(f"/items/{spare['hid']}"), "Assigned")
    desk.move(leaving, "Pending-Removal")

    report = desk.get("/reports/coverage")
    assert report["service_states"] == ["Assigned", "Test", "Prod", "Down"]
    assert report["totals"] == {
        "in_service": 5,
        "covered": 3,
        "uncovered": 2,
        "out_of_service": 1,
        "expiring": 1,
        "overlapping": 1,
        "renewal_pending": 0,
        "not_renewed": 0,
    }
    assert (report["section"], report["items"], report["total"]) == (None, [], 0)
    assert report["lapsed_contracts"]["count"] == 0
    for name, expected in (
        ("uncovered", [bare, spare]),
        ("out_of_service", [leaving]),
        ("expiring", [soon]),
        ("overlapping", [twice]),
        ("renewal_pending", []),
    ):
        page = desk.get("/reports/coverage", section=name, sort="serial_number")
        assert [item["hid"] for item in page["items"]] == [one["hid"] for one in expected], name
        assert page["total"] == page["sections"][name]["count"] == len(expected)
        # The filter of a section lists the same items on the item list.
        section = page["sections"][name]
        same = desk.post(
            "/items/query",
            {"filter": section["filter"], "include_archived": section["include_archived"]},
            200,
        )
        assert {item["hid"] for item in same["items"]} == {one["hid"] for one in expected}, name
    # A minor item is covered with its switch, and what has only been delivered is not
    # in service yet: neither is a gap of its own.
    gaps = {item["hid"] for item in desk.get("/reports/coverage", section="uncovered")["items"]}
    assert not gaps & {supply["hid"], arriving["hid"]}
    # The item under two contracts says so, and is found and sorted by it.
    doubled = desk.get(f"/items/{twice['hid']}")
    assert (doubled["contract_count"], doubled["covered_until"]) == (2, NEXT_YEAR)
    assert desk.get("/items", filter="contract_count:gt:1")["total"] == 1
    assert desk.get("/items", sort="-contract_count")["items"][0]["hid"] == twice["hid"]
    # A longer horizon finds what runs out later, and a filter narrows the view.
    assert desk.get("/reports/coverage", within_days=400)["totals"]["expiring"] == 3
    narrowed = desk.get("/reports/coverage", filter="serial_number:eq:FCW-1")["totals"]
    assert (narrowed["in_service"], narrowed["uncovered"]) == (1, 1)
    assert "query.section" in errors(desk.get("/reports/coverage", 422, section="nonsense"))
    # A filter at the limits of the grammar is still counted: the section then has no
    # filter to hand back, and is read with `section`.
    widest = {
        "or": [{"field": "serial_number", "op": "eq", "value": f"FCW-{n}"} for n in range(100)]
    }
    at_limit = desk.get("/reports/coverage", filter=json.dumps(widest), section="uncovered")
    assert (at_limit["totals"]["uncovered"], at_limit["total"]) == (2, 2)
    assert at_limit["sections"]["uncovered"]["filter"] is None
    # What "in service" means is a setting.
    setting = desk.client.put(
        f"{API}/settings/service_states",
        json={"row_version": 0, "value": ["Prod"]},
        headers=admin,
    )
    assert setting.status_code == 200, setting.text
    narrower = desk.get("/reports/coverage")
    assert (narrower["service_states"], narrower["totals"]["uncovered"]) == (["Prod"], 1)


def test_the_database_and_the_record_agree_on_what_is_in_force(desk: Desk, db: Session) -> None:
    """`hirdir.domain.contracts` works out what covers an item for a record, and
    `hirdir.io.fields` for the database to filter by. This holds the two together."""
    entry = desk.catalog()
    agreement = desk.agreement(starts_on=day(-100), ends_on=day(100))
    cases: tuple[dict[str, Any], ...] = (
        {},
        {"starts_on": day(-10)},
        {"starts_on": day(10)},
        {"ends_on": day(-10)},
        {"ends_on": day(10)},
        {"starts_on": day(-50), "ends_on": day(50)},
        {"status": "expired", "ends_on": day(50)},
        {"record_status": "draft"},
        {"agreement_hid": agreement["hid"]},
        {"agreement_hid": agreement["hid"], "ends_on": day(20)},
        {"agreement_hid": agreement["hid"], "starts_on": day(20)},
        {"status": "renewal_pending", "starts_on": day(-90), "ends_on": day(-5)},
        {"status": "renewal_pending", "starts_on": day(5)},
        {"starts_on": day(-90), "ends_on": day(-5), "note": "next term has begun"},
        {"starts_on": day(-90), "ends_on": day(8), "note": "next term is to begin"},
        {"agreement_hid": agreement["hid"], "note": "next term has begun"},
        {"status": "renewal_pending", "ends_on": day(-5), "note": "next term has begun"},
    )
    spans: tuple[dict[str, Any], ...] = (
        {},
        {"starts_on": day(-5)},
        {"ends_on": day(5)},
        {"starts_on": day(5)},
    )
    number = 0
    for case in cases:
        for own in spans:
            number += 1
            given = {name: value for name, value in case.items() if name != "note"}
            contract = desk.contract(f"CON-{number}", **given)
            if "note" in case:
                # A term that follows: begun two days ago, or to begin in nine.
                held = db.get_one(Contract, contract["hid"])
                begins = -2 if "has begun" in case["note"] else 9
                held.next_starts_on = TODAY + timedelta(days=begins)
                held.next_ends_on = TODAY + timedelta(days=begins + 60)
                held.next_number = f"CON-{number}-R"
                db.commit()
            switch = desk.switch(entry, f"FCW-{number}")
            response = desk.client.post(
                f"{API}/contracts/{contract['hid']}/coverage",
                json={"items": [{"item_hid": switch["hid"], **own}]},
                headers=desk.headers,
            )
            assert response.status_code in (201, 422), response.text
    # The agreement, too, has a term that follows, which has begun.
    above = db.get_one(Agreement, agreement["hid"])
    above.next_starts_on = TODAY - timedelta(days=1)
    above.next_ends_on = TODAY + timedelta(days=200)
    db.commit()
    db.expire_all()
    today = contracts.today(db)
    by_item = contracts.of_items(db, list(db.scalars(select(Item.hid))))
    assert sum(len(found) for found in by_item.values()) > 50
    reading: Any = select(Item.hid, fields.COVERED_UNTIL).select_from(Item)
    listed = dict(db.execute(fields.ITEMS.joined(reading).where(fields.COVERED)).all())
    for hid, found in by_item.items():
        expected = any(
            contracts.in_force(coverage, contract, today) for coverage, contract in found
        )
        assert (hid in listed) is expected, found
        if expected:
            assert listed[hid] == contracts.covered_until(found, today)
    # And for each coverage: the days in force.
    rows = db.execute(
        select(ContractCoverage, Contract, contracts.starts(), contracts.ends()).join(
            Contract, Contract.hid == ContractCoverage.contract_hid
        )
    )
    for coverage, contract, starts, ends in rows:
        span = contracts.span(coverage, contract, today)
        assert (starts, ends) == (span.starts_on, span.ends_on)
    # And for each contract: what the record says of it, and what its list finds.
    listed_contracts = {one["hid"]: one for one in desk.get("/contracts", limit=1000)["items"]}
    for name in ("covers_today", "lapsed"):
        found = desk.get("/contracts", filter=f"{name}:eq:true", limit=1000)["items"]
        assert {one["hid"] for one in found} == {
            hid for hid, one in listed_contracts.items() if one[name]
        }, name
    for hid, one in listed_contracts.items():
        by_number = desk.get("/contracts", filter=f"number:eq:{one['number']}")["items"]
        assert [found["hid"] for found in by_number] == [hid]
    # And for an item that is out of service: the contracts that still count it, those
    # whose cover goes on and those whose coverage ended because it left.
    for place, item in enumerate(db.scalars(select(Item).order_by(Item.hid))):
        item.lifecycle_state = ("Pending-Removal", "Archived", "Prod")[place % 3]
    for place, coverage in enumerate(db.scalars(select(ContractCoverage))):
        if place % 4 == 1:
            coverage.left_service = True
            coverage.ends_on = TODAY - timedelta(days=place % 7)
        elif place % 4 == 2:
            coverage.ends_on = TODAY
    db.commit()

    def every(**more: Any) -> list[dict[str, Any]]:
        return desk.get(
            "/items", limit=1000, include_archived="true", include_drafts="true", **more
        )["items"]

    records = {one["hid"]: one for one in every()}
    counted = {hid for hid, one in records.items() if one["out_of_service_contracts"]}
    assert 10 < len(counted) < len(records)
    found = every(filter="out_of_service_cover:eq:true")
    assert {one["hid"] for one in found} == counted
    for contract_hid in listed_contracts:
        found = every(filter=f"out_of_service_contract.hid:eq:{contract_hid}")
        assert {one["hid"] for one in found} == {
            hid
            for hid, one in records.items()
            if contract_hid in [ref["hid"] for ref in one["out_of_service_contracts"]]
        }, contract_hid
    in_service = {hid for hid, one in records.items() if one["lifecycle_state"] == "Prod"}
    assert in_service
    assert not counted & in_service


WRITES = (
    ("post", "/agreements"),
    ("patch", "/agreements/x"),
    ("post", "/agreements/x/retire"),
    ("post", "/contracts"),
    ("patch", "/contracts/x"),
    ("post", "/contracts/x/renew"),
    ("post", "/contracts/x/retire"),
    ("post", "/contracts/x/coverage"),
    ("patch", "/contracts/x/coverage/y"),
    ("delete", "/contracts/x/coverage/y"),
    ("post", "/agreements/x/renew"),
)


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_every_write_needs_the_inventory_role(
    client: TestClient, viewer: dict[str, str], method: str, path: str
) -> None:
    assert client.request(method, API + path, json={}, headers=viewer).status_code == 403
    assert client.request(method, API + path, json={}).status_code == 401


def test_a_viewer_reads_contracts_and_every_change_is_audited(
    desk: Desk, client: TestClient, viewer: dict[str, str]
) -> None:
    entry = desk.catalog()
    agreement = desk.agreement()
    contract = desk.contract("CON-1", agreement_hid=agreement["hid"], tags=[])
    (coverage,) = desk.cover(contract, desk.switch(entry, "FCW-1"))
    for path in (
        "/agreements",
        f"/agreements/{agreement['hid']}",
        "/contracts",
        f"/contracts/{contract['hid']}",
        f"/contracts/{contract['hid']}/coverage",
        f"/contracts/{contract['hid']}/terms",
        "/contract-coverage",
        "/reports/coverage",
    ):
        assert client.get(API + path, headers=viewer).status_code == 200, path
    for record_type, hid in (
        ("agreement", agreement["hid"]),
        ("contract", contract["hid"]),
        ("contract_coverage", coverage["hid"]),
    ):
        (event,) = desk.audit(record_type=record_type, record_hid=hid)
        assert (event["action"], event["actor_name"]) == ("create", "ivy")
    created = desk.audit(record_type="contract_coverage")[0]
    assert {change["field"] for change in created["changes"]} == {"contract_hid", "item_hid"}
    assert client.get(f"{API}/contracts/nope", headers=viewer).status_code == 404
    assert client.get(f"{API}/agreements/nope", headers=viewer).status_code == 404
    # A stale edit is refused.
    stale = {"row_version": contract["row_version"] + 5, "notes": "x"}
    assert desk.patch(f"/contracts/{contract['hid']}", stale, 409)["status"] == 409


def test_a_term_that_begins_ends_what_was_said_of_the_one_before(desk: Desk, db: Session) -> None:
    entry = desk.catalog()
    switches = [desk.switch(entry, f"FCW-{number}") for number in range(3)]
    said = ("renewal_pending", "expired", "cancelled")
    held = [
        desk.contract(f"CON-{number}", starts_on=LAST_YEAR, ends_on=day(-10), status=status)
        for number, status in enumerate(said)
    ]
    for contract, switch in zip(held, switches, strict=True):
        desk.cover(contract, switch)
        ahead = {"row_version": contract["row_version"], "starts_on": day(10), "ends_on": day(374)}
        renewed = desk.post(f"/contracts/{contract['hid']}/renew", ahead, 200)
        # The status is of the present term, and is left as it is.
        assert renewed["status"] == contract["status"]
    # While the term waits: what a pending renewal covers is covered to the end of the
    # term to come, what has expired is to be covered again, and what was cancelled
    # is not.
    assert desk.covered(switches[0]) == (True, day(374), ["CON-0"])
    assert desk.covered(switches[1]) == (False, day(374), [])
    assert desk.covered(switches[2]) == (False, None, [])

    for contract in held:
        stored = db.get_one(Contract, contract["hid"])
        stored.next_starts_on = TODAY - timedelta(days=1)
        stored.next_ends_on = TODAY + timedelta(days=363)
    db.commit()

    def read() -> list[tuple[Any, ...]]:
        found = []
        for contract, switch in zip(held, switches, strict=True):
            now = desk.get(f"/contracts/{contract['hid']}")
            found.append((now["status"], now["covers_today"], now["lapsed"], desk.covered(switch)))
        found.append(desk.get("/reports/coverage", within_days=400)["totals"]["expiring"])
        found.append(desk.get("/items", filter="covered_until:empty:true")["total"])
        return found

    # The day comes: active again, as after a renewal that is in force at once. What
    # was cancelled stays so: that was said of the contract, and not of a term.
    begun = read()
    assert begun == [
        ("active", True, False, (True, day(363), ["CON-0"])),
        ("active", True, False, (True, day(363), ["CON-1"])),
        ("cancelled", False, False, (False, None, [])),
        2,
        1,
    ]
    # And nothing reads differently once the term is written down.
    for contract in held:
        now = desk.get(f"/contracts/{contract['hid']}")
        desk.patch(
            f"/contracts/{contract['hid']}", {"row_version": now["row_version"], "notes": "x"}
        )
    assert read() == begun


def test_a_contract_and_its_agreement_fit_in_every_term_to_come(desk: Desk, db: Session) -> None:
    desk.catalog()
    agreement = desk.agreement(starts_on=LAST_YEAR, ends_on=day(100))
    path = f"/agreements/{agreement['hid']}"
    ahead = {"row_version": agreement["row_version"], "starts_on": day(101), "ends_on": day(465)}
    desk.post(f"{path}/renew", ahead, 200)
    # It fits today, and would not once the agreement's next term has begun: from that
    # day it would start, with the agreement, after its own end.
    short: dict[str, Any] = {"agreement_hid": agreement["hid"], "ends_on": day(50)}
    assert "ends_on" in errors(desk.contract("CON-1", expect=422, **short))
    desk.contract("CON-1", starts_on=day(-5), **short)
    # Two terms that are never in force together are not held against one another: a
    # co-termed contract whose own next term has no end, and the agreement's present end.
    together = desk.contract("CON-2", agreement_hid=agreement["hid"])
    desk.post(
        f"/contracts/{together['hid']}/renew",
        {"row_version": together["row_version"], "starts_on": day(120), "ends_on": None},
        200,
    )
    now = desk.get(path)
    earlier = desk.patch(path, {"row_version": now["row_version"], "ends_on": day(99)})
    # What would leave a contract the wrong way round is refused, and names it.
    late = desk.contract("CON-3", agreement_hid=agreement["hid"], starts_on=day(90))
    refused = desk.patch(path, {"row_version": earlier["row_version"], "ends_on": day(80)}, 422)
    assert "CON-3" in errors(refused)["ends_on"]
    assert "CON-2" not in errors(refused)["ends_on"]
    # A contract that is wrong already is not held against a change, and can itself
    # still be given a note, and be put right.
    stored = db.get_one(Contract, late["hid"])
    stored.starts_on = TODAY + timedelta(days=200)
    db.commit()
    noted = desk.patch(
        f"/contracts/{late['hid']}", {"row_version": late["row_version"], "notes": "x"}
    )
    desk.patch(path, {"row_version": earlier["row_version"], "ends_on": day(98)})
    wrong = {"row_version": noted["row_version"], "starts_on": day(210)}
    assert "ends_on" in errors(desk.patch(f"/contracts/{late['hid']}", wrong, 422))
    desk.patch(
        f"/contracts/{late['hid']}", {"row_version": noted["row_version"], "starts_on": day(1)}
    )
    # A next number is held to what a number is held to, and compared as one.
    sharp = desk.contract("CON-4", vendor_hid=agreement["vendor"]["hid"], ends_on=day(30))
    desk.post(
        f"/contracts/{sharp['hid']}/renew",
        {
            "row_version": sharp["row_version"],
            "number": "Stra\u00dfe-7",
            "starts_on": day(31),
            "ends_on": day(395),
        },
        200,
    )
    taken = desk.contract("STRASSE-7", expect=409, vendor_hid=agreement["vendor"]["hid"])
    assert "number" in errors(taken)


def test_an_item_that_comes_back_is_in_service_again(desk: Desk) -> None:
    entry = desk.catalog()
    switch = desk.switch(entry, "FCW-1")
    running = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    to_come = desk.contract("CON-2", starts_on=day(20), ends_on=day(400), status="pending")
    (present,) = desk.cover(running, switch)
    (future,) = desk.cover(to_come, switch)
    retired = desk.post(
        f"/items/{switch['hid']}/retire", {"row_version": switch["row_version"]}, 200
    )
    # The coverage that was in force ended today. The one that had not begun never
    # was in force: it is removed, and the audit trail holds what it was.
    (its,) = desk.get(f"/items/{switch['hid']}")["coverage"]
    assert (its["hid"], its["left_service"]) == (present["hid"], True)
    gone = desk.audit(record_type="contract_coverage", record_hid=future["hid"])[0]
    assert gone["action"] == "delete"
    assert desk.get("/reports/coverage")["totals"]["out_of_service"] == 1
    # Brought back, it is in service, and on no list of what has left.
    desk.patch(
        f"/items/{switch['hid']}",
        {"row_version": retired["row_version"], "record_status": "active"},
    )
    totals = desk.get("/reports/coverage")["totals"]
    assert (totals["in_service"], totals["out_of_service"]) == (1, 0)
    # Its coverage does not come back by itself: a person opens it again.
    (ended,) = desk.get(f"/contracts/{running['hid']}/coverage")["items"]
    reopened = desk.patch(
        f"/contracts/{running['hid']}/coverage/{present['hid']}",
        {"row_version": ended["row_version"], "ends_on": None, "left_service": False},
    )
    assert (reopened["in_force"], reopened["left_service"]) == (True, False)
    assert desk.covered(switch) == (True, NEXT_YEAR, ["CON-1"])
