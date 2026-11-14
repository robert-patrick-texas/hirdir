"""Support agreements, contracts and coverage: one record for many items, renewed in
one place, and what a contract has from the agreement it is grouped into."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Contract, ContractCoverage, Item
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
    # Nothing removes a coverage, and its contract and item are not changed.
    assert (
        desk.client.delete(f"{API}{path}/{first['hid']}", headers=desk.headers).status_code == 405
    )
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
    versions = {
        item["hid"]: desk.get(f"/items/{item['hid']}")["row_version"] for item in (follows,)
    }

    renewed = desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": contract["row_version"],
            "number": "CON-2027-0001",
            "starts_on": day(21),
            "ends_on": day(386),
            "purchase_reference": "RITM0002",
            "annual_cost": "4000.00",
        },
        200,
    )
    assert (renewed["number"], renewed["status"]) == ("CON-2027-0001", "active")
    # One change of one record: the items in scope show the new number and period at
    # once, and neither they nor their coverages were written to.
    listed = desk.get(f"/items/{follows['hid']}")
    assert listed["row_version"] == versions[follows["hid"]]
    assert [one["contract"]["number"] for one in listed["coverage"]] == ["CON-2027-0001"]
    assert (listed["covered"], listed["covered_until"]) == (False, day(386))
    late = desk.get(f"/items/{joined_late['hid']}")["coverage"][0]
    assert (late["starts_on"], late["ends_on"]) == (day(21), day(386))
    # What was ended on a day of its own stays ended.
    assert desk.get(f"/items/{left['hid']}")["coverage"][0]["ends_on"] == day(-30)
    events = desk.audit(record_type="contract", record_hid=contract["hid"])
    assert [event["action"] for event in events] == ["renew", "create"]
    assert (
        desk.audit(record_type="contract_coverage", action="update", limit=10)[0]["record_hid"]
        == gone["hid"]
    )
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
        }
    assert in_force["reseller_hid"] == {
        "value": reseller["hid"],
        "label": "Example Reseller",
        "source": "agreement",
        "source_hid": agreement["hid"],
    }
    assert wireless["effective"]["support_level"] == {
        "value": "8x5",
        "source": "own",
        "source_hid": wireless["hid"],
    }
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
    # An override is cleared, and the agreement speaks again.
    cleared = desk.change(f"/contracts/{wireless['hid']}", support_level=None)
    assert cleared["effective"]["support_level"]["source"] == "agreement"
    # The agreement's period ends: so does the cover of what is co-termed with it.
    desk.change(f"/agreements/{agreement['hid']}", ends_on=day(-3))
    assert desk.covered(switch)[0] is False
    assert desk.get("/items", filter="covered:eq:true")["total"] == 0


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
    covered, bare, soon, parked, leaving = (desk.switch(entry, f"FCW-{n}") for n in range(5))
    supply = desk.item(
        catalog_entry_hid=desk.entry(desk.cisco, "PWR-1")["hid"],
        serial_number="LIT-1",
        parent_item_hid=bare["hid"],
        position="PS-A",
    )
    long_contract = desk.contract("CON-1", starts_on=LAST_YEAR, ends_on=NEXT_YEAR)
    short_contract = desk.contract("CON-2", starts_on=LAST_YEAR, ends_on=day(40))
    desk.cover(long_contract, covered, leaving)
    desk.cover(short_contract, soon)
    # Parked with the team: neither in service nor out of it.
    desk.move(desk.move(parked, "Down"), "Pending-Removal")
    desk.move(leaving, "Pending-Removal")

    report = desk.get("/reports/coverage")
    assert report["service_states"] == ["Test", "Prod", "Down"]
    assert report["totals"] == {
        "in_service": 3,
        "covered": 2,
        "uncovered": 1,
        "out_of_service": 1,
        "expiring": 1,
    }
    assert (report["section"], report["items"], report["total"]) == (None, [], 0)
    for name, expected in (
        ("uncovered", [bare]),
        ("out_of_service", [leaving]),
        ("expiring", [soon]),
    ):
        page = desk.get("/reports/coverage", section=name)
        assert [item["hid"] for item in page["items"]] == [one["hid"] for one in expected], name
        assert page["total"] == page["sections"][name]["count"] == len(expected)
        # The filter of a section lists the same items on the item list.
        section = page["sections"][name]
        same = desk.post(
            "/items/query",
            {"filter": section["filter"], "include_archived": section["include_archived"]},
            200,
        )
        assert [item["hid"] for item in same["items"]] == [one["hid"] for one in expected], name
    # A minor item is covered with its switch: it is not a gap of its own.
    assert supply["hid"] not in {
        item["hid"] for item in desk.get("/reports/coverage", section="uncovered")["items"]
    }
    # A longer horizon finds what runs out later, and a filter narrows the view.
    assert desk.get("/reports/coverage", within_days=400)["totals"]["expiring"] == 2
    narrowed = desk.get("/reports/coverage", filter="serial_number:eq:FCW-1")["totals"]
    assert (narrowed["in_service"], narrowed["uncovered"]) == (1, 1)
    assert "query.section" in errors(desk.get("/reports/coverage", 422, section="nonsense"))
    # What "in service" means is a setting.
    setting = desk.client.put(
        f"{API}/settings/service_states",
        json={"row_version": 0, "value": ["Prod"]},
        headers=admin,
    )
    assert setting.status_code == 200, setting.text
    assert desk.get("/reports/coverage")["service_states"] == ["Prod"]
    # A retired item that is still covered is cover that is paid for and not needed.
    now = desk.get(f"/items/{covered['hid']}")
    desk.post(f"/items/{covered['hid']}/retire", {"row_version": now["row_version"]}, 200)
    out = desk.get("/reports/coverage", section="out_of_service", sort="serial_number")
    assert [item["serial_number"] for item in out["items"]] == ["FCW-0", "FCW-4"]


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
            contract = desk.contract(f"CON-{number}", **case)
            switch = desk.switch(entry, f"FCW-{number}")
            response = desk.client.post(
                f"{API}/contracts/{contract['hid']}/coverage",
                json={"items": [{"item_hid": switch["hid"], **own}]},
                headers=desk.headers,
            )
            assert response.status_code in (201, 422), response.text
    today = contracts.today(db)
    by_item = contracts.of_items(db, list(db.scalars(select(Item.hid))))
    assert sum(len(found) for found in by_item.values()) > 30
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
        span = contracts.span(coverage, contract)
        assert (starts, ends) == (span.starts_on, span.ends_on)


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
