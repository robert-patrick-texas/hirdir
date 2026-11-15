"""What the review of the server of 0.6.1 found, each held to what the documentation
says: the dates of an earlier term (D-163), an item with no state, a delivery file,
and what 0.6.0 left on a purchase line (D-161)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent, Contract, Item
from tests.api.inventory import Maker
from tests.api.test_contracts import Desk
from tests.api.test_files import Files, counts


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def moment(offset: int) -> datetime:
    """Noon UTC of a day, well clear of any zone's midnight."""
    return datetime.combine(TODAY + timedelta(days=offset), time(12), tzinfo=UTC)


def _events(db: Session, record_type: str, hid: str) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.record_type == record_type, AuditEvent.record_hid == hid)
            .order_by(AuditEvent.at, AuditEvent.hid)
        )
    )


def _timeline(desk: Desk, db: Session, fold: bool) -> tuple[list[dict[str, Any]], dict]:
    """A contract that shares its agreement's period, whose own renewal was entered early
    and has begun, and an agreement renewed late after the contract's earlier term had
    ended."""
    desk.catalog()
    agreement = desk.agreement(number="EA-1", starts_on=day(-700), ends_on=day(-30))
    contract = desk.contract("CON-1", agreement_hid=agreement["hid"])
    # Entered early: the next term, with dates of its own.
    desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": contract["row_version"],
            "number": "CON-2",
            "starts_on": day(10),
            "ends_on": day(375),
        },
        200,
    )
    # ... and it began five days ago: the earlier term's last day is day(-6).
    held = db.get_one(Contract, contract["hid"])
    held.next_starts_on = TODAY - timedelta(days=5)
    db.commit()
    # The agreement's 0.6.0-style late renewal, entered two days ago.
    now = desk.get(f"/agreements/{agreement['hid']}")
    desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {
            "row_version": now["row_version"],
            "number": "EA-2",
            "starts_on": day(-29),
            "ends_on": day(335),
        },
        200,
    )
    # A real timeline: created long ago, renewed early 100 days ago, the agreement
    # renewed two days ago.
    a_events = _events(db, "agreement", agreement["hid"])
    c_events = _events(db, "contract", contract["hid"])
    a_events[0].at = moment(-800)
    a_events[-1].at = moment(-2)
    c_events[0].at = moment(-800)
    c_events[-1].at = moment(-100)
    # The record was made when its first event says.
    db.get_one(Contract, contract["hid"]).created_at = moment(-800)
    db.commit()
    if fold:
        desk.change(f"/contracts/{contract['hid']}", notes="written down")
    return desk.get(f"/contracts/{contract['hid']}/terms"), agreement


@pytest.mark.parametrize("written_down", [False, True])
def test_an_earlier_term_has_the_agreement_term_it_began_in(
    desk: Desk, db: Session, written_down: bool
) -> None:
    terms, agreement = _timeline(desk, db, fold=written_down)
    (earlier,) = terms
    assert earlier["number"] == "CON-1"
    # CON-1 began when it was made, when the agreement ran from day(-700) to day(-30):
    # its later renewal does not move the term that has ended, before it is written
    # down or after.
    assert (earlier["starts_on"], earlier["ends_on"]) == (day(-700), day(-30)), earlier
    assert (earlier["starts_on_source"], earlier["agreement_hid"]) == (
        "agreement",
        agreement["hid"],
    )


# --- purchase lines -------------------------------------------------------------------


def _line(make: Maker, entry: dict[str, Any], quantity: int = 4) -> dict[str, Any]:
    body = {
        "reference": "RITM0012345",
        "lines": [{"catalog_entry_hid": entry["hid"], "quantity": quantity}],
    }
    return make.post("/purchase-requests", body)["lines"][0]


def test_a_row_made_by_the_lines_model_keeps_what_it_inherits(make: Maker, files: Files) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", annual_support_cost="1200.00", support_weight="1")
    _line(make, entry)
    # The same file, once with the model named and once with only the line.
    named = (
        "vendor,pid,serial_number,lifecycle_state,purchase_line,annual_support_cost\n"
        "Cisco,C9300-48P,FCW-1,Delivered,RITM0012345/1,1200.00\n"
    )
    bare = (
        "serial_number,lifecycle_state,purchase_line,annual_support_cost\n"
        "FCW-2,Delivered,RITM0012345/1,1200.00\n"
    )
    assert counts(files.load("items", named)) == (1, 0, 0, 0)
    assert counts(files.load("items", bare)) == (1, 0, 0, 0)
    by_serial = {one["serial_number"]: one for one in make.get("/items")["items"]}
    assert by_serial["FCW-1"]["effective"]["annual_support_cost"]["source"] != "own"
    # The row held the very value the item has from its model: it should inherit.
    assert by_serial["FCW-2"]["catalog_entry_hid"] == entry["hid"]
    assert by_serial["FCW-2"]["annual_support_cost"] is None, by_serial["FCW-2"]["effective"][
        "annual_support_cost"
    ]


def test_an_unrelated_edit_of_a_060_item_with_no_model_leaves_its_model(
    make: Maker, db: Session
) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    line = _line(make, entry)
    # 0.6.0 let an item with no model onto a line: known by its name.
    probe = make.item(name="probe-1", serial_number="FCW-9")
    held = db.get_one(Item, probe["hid"])
    held.purchase_line_hid = line["hid"]
    db.commit()
    before = make.get(f"/items/{probe['hid']}")
    assert before["purchase_line_mismatch"] is True
    after = make.patch(
        f"/items/{probe['hid']}", {"row_version": before["row_version"], "comments": "seen"}
    )
    # "What 0.6.0 let in is left as it is" (D-161).
    assert after["catalog_entry_hid"] is None, "the edit of a comment gave it a model"


def test_an_unrelated_edit_of_a_060_item_with_no_model_is_not_refused(
    make: Maker, db: Session
) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    line = _line(make, entry)
    make.item(catalog_entry_hid=entry["hid"], serial_number="FCW-9")
    probe = make.item(name="probe-1", serial_number="FCW-9")
    held = db.get_one(Item, probe["hid"])
    held.purchase_line_hid = line["hid"]
    db.commit()
    before = make.get(f"/items/{probe['hid']}")
    response = make.client.patch(
        f"/api/v1/items/{probe['hid']}",
        json={"row_version": before["row_version"], "comments": "seen"},
        headers=make.headers,
    )
    # "... and is not held against an edit of anything else" (D-161).
    assert response.status_code == 200, response.text


# --- the contracts that still count an item ---------------------------------------------


def test_a_coverage_that_ends_today_asks_nothing_more_of_the_vendor(desk: Desk) -> None:
    entry = desk.catalog()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(300))
    switch = desk.switch(entry, "FCW-1")
    desk.cover(contract, switch, ends_on=day(0))
    moved = desk.move(desk.get(f"/items/{switch['hid']}"), "Pending-Removal")
    record = desk.get(f"/items/{moved['hid']}")
    assert [one["in_force"] for one in record["coverage"]] == [True]
    assert record["covered"] is True
    # D-162: a contract counts the item when it covers it past today.
    assert record["out_of_service_contracts"] == []
    assert desk.get("/items", filter="out_of_service_cover:eq:true")["total"] == 0


def test_an_item_with_no_state_is_blank_and_so_not_equal_to_a_contract(desk: Desk) -> None:
    entry = desk.catalog()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(300))
    # An item with no state: neither in service nor out of it (D-142).
    bare = desk.item(catalog_entry_hid=entry["hid"], serial_number="FCW-0")
    assert bare["lifecycle_state"] is None
    desk.cover(contract, bare)
    record = desk.get(f"/items/{bare['hid']}")
    assert record["out_of_service_contracts"] == []
    # Blank is not CON-1, as `contract.number:ne:` finds an item with none.
    found = desk.get("/items", filter="out_of_service_contract.number:ne:CON-1")
    assert [one["hid"] for one in found["items"]] == [bare["hid"]], "ne leaves it out"


def test_an_item_with_no_state_is_not_out_of_service_cover(desk: Desk) -> None:
    entry = desk.catalog()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(300))
    bare = desk.item(catalog_entry_hid=entry["hid"], serial_number="FCW-0")
    desk.cover(contract, bare)
    found = desk.get("/items", filter="out_of_service_contract.number:empty:true")
    assert [one["hid"] for one in found["items"]] == [bare["hid"]], "empty true leaves it out"
    found = desk.get("/items", filter="out_of_service_cover:eq:false")
    assert [one["hid"] for one in found["items"]] == [bare["hid"]], "eq false leaves it out"


def test_a_bare_delivery_row_with_an_asset_tag_finds_the_item_of_that_tag(
    make: Maker, files: Files
) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    _line(make, entry)
    # Entered before its request was, known by its asset tag.
    early = make.item(catalog_entry_hid=entry["hid"], asset_tag="TAG-0001")
    row = "serial_number,asset_tag,purchase_line\nFCW-1,TAG-0001,RITM0012345/1\n"
    preview = files.preview("items", row)
    # Matched by the asset tag (rule 3), as in 0.6.0, and given its serial number and
    # its line.
    assert preview["rows"][0]["record_hid"] == early["hid"], preview["rows"][0]
    files.apply(preview)
    found = make.get(f"/items/{early['hid']}")
    assert (found["serial_number"], found["purchase_line"]["name"]) == ("FCW-1", "RITM0012345/1")


def test_a_bulk_edit_holds_items_to_the_lines_model(make: Maker) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    line = _line(make, entry)
    on = make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW-1",
        hostname="h-on",
        purchase_line_hid=line["hid"],
    )
    off = make.item(catalog_entry_hid=other["hid"], serial_number="X-1", hostname="h-off")
    for filter_, set_ in (
        ("hostname:eq:h-on", {"vendor": "Juniper", "pid": "EX4400-48P"}),
        ("hostname:eq:h-off", {"purchase_line": "RITM0012345/1"}),
    ):
        preview = make.post("/items/bulk-update", {"filter": filter_, "set": set_})
        assert preview["job"]["rejected"] == 1, preview["rows"]
    assert make.get(f"/items/{on['hid']}")["catalog_entry_hid"] == entry["hid"]
    assert make.get(f"/items/{off['hid']}")["purchase_line"] is None


def test_a_late_renewal_at_once_leaves_the_earlier_term_its_own_period(
    desk: Desk, db: Session
) -> None:
    desk.catalog()
    agreement = desk.agreement(number="EA-1", starts_on=day(-700), ends_on=day(-30))
    contract = desk.contract("CON-1", agreement_hid=agreement["hid"])
    now = desk.get(f"/agreements/{agreement['hid']}")
    desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {
            "row_version": now["row_version"],
            "number": "EA-2",
            "starts_on": day(-29),
            "ends_on": day(335),
        },
        200,
    )
    # The contract, renewed late as well, with a period of its own from day(-29).
    now = desk.get(f"/contracts/{contract['hid']}")
    desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": now["row_version"],
            "number": "CON-2",
            "starts_on": day(-29),
            "ends_on": day(335),
        },
        200,
    )
    a_events = _events(db, "agreement", agreement["hid"])
    c_events = _events(db, "contract", contract["hid"])
    a_events[0].at, a_events[-1].at = moment(-800), moment(-3)
    c_events[0].at, c_events[-1].at = moment(-800), moment(-1)
    db.get_one(Contract, contract["hid"]).created_at = moment(-800)
    db.commit()
    (earlier,) = desk.get(f"/contracts/{contract['hid']}/terms")
    # CON-1 began when the agreement ran from day(-700) to day(-30), and that is its
    # period, though the agreement was renewed before CON-1 was.
    assert (earlier["starts_on"], earlier["ends_on"]) == (day(-700), day(-30)), earlier


def test_the_count_of_another_model_leads_to_as_many_rows(make: Maker, db: Session) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    line = _line(make, entry)
    astray = []
    for serial, status in (("X-1", "active"), ("X-2", "draft"), ("X-3", "active")):
        made = make.item(serial_number=serial, purchase_line_hid=line["hid"], record_status=status)
        astray.append(made)
        held = db.get_one(Item, made["hid"])
        held.catalog_entry_hid = other["hid"]
        db.commit()
    # One is retired: the list leaves it out, and so does the count (D-152).
    now = make.get(f"/items/{astray[2]['hid']}")
    make.post(f"/items/{now['hid']}/retire", {"row_version": now["row_version"]}, 200)
    listed = make.get(
        "/items", filter=f"purchase_line_hid:eq:{line['hid']} purchase_line_mismatch:eq:true"
    )
    assert make.get(f"/purchase-lines/{line['hid']}")["mismatched_items"] == listed["total"] == 1
    assert make.get("/purchase-lines", filter="mismatched_items:eq:1")["total"] == 1


def test_a_coverage_that_ends_today_with_its_contract_asks_nothing_more(desk: Desk) -> None:
    entry = desk.catalog()
    # The contract's period ends today, and no renewal is entered.
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(0))
    switch = desk.switch(entry, "FCW-1")
    desk.cover(contract, switch)
    moved = desk.move(desk.get(f"/items/{switch['hid']}"), "Pending-Removal")
    record = desk.get(f"/items/{moved['hid']}")
    assert record["covered"] is True
    # Its coverage ends today by its contract's end, as surely as by its own (D-162).
    assert record["out_of_service_contracts"] == []
    assert desk.get("/items", filter="out_of_service_cover:eq:true")["total"] == 0
    # A renewal to come carries the cover on, and the vendor counts the item again.
    now = desk.get(f"/contracts/{contract['hid']}")
    desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": now["row_version"],
            "number": "CON-2",
            "starts_on": day(1),
            "ends_on": day(366),
        },
        200,
    )
    record = desk.get(f"/items/{moved['hid']}")
    assert [ref["number"] for ref in record["out_of_service_contracts"]] == ["CON-1"]
    assert desk.get("/items", filter="out_of_service_cover:eq:true")["total"] == 1


def test_a_delivery_row_finds_the_device_060_left_on_its_line(
    make: Maker, files: Files, db: Session
) -> None:
    cisco = make.vendor("Cisco")
    entry = make.entry(cisco, "C9300-48P", support_weight="1")
    line = _line(make, entry, quantity=4)
    # 0.6.0 let it onto the line with no model.
    probe = make.item(name="probe-1", serial_number="FCW-9")
    held = db.get_one(Item, probe["hid"])
    held.purchase_line_hid = line["hid"]
    db.commit()
    row = "serial_number,purchase_line,comments\nFCW-9,RITM0012345/1,seen\n"
    assert counts(files.load("items", row)) == (0, 1, 0, 0)
    on_line = make.get("/items", filter=f"purchase_line_hid:eq:{line['hid']}")
    assert [one["hid"] for one in on_line["items"]] == [probe["hid"]]
    assert on_line["items"][0]["comments"] == "seen"
