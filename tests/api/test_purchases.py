"""Purchases, external systems and capacity: requests and receiving, registrations, and
the balance of demand against supply."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hirdir.db.models import Item
from tests.api.inventory import API, Maker, errors

TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _change(make: Maker, path: str, expect: int = 200, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields}, expect)


@pytest.fixture
def entry(make: Maker) -> dict[str, Any]:
    return make.entry(make.vendor(), support_weight="1")


# --- purchases -----------------------------------------------------------------------


def _request(make: Maker, entry: dict[str, Any], quantity: int = 4, **more: Any) -> dict:
    body = {
        "reference": "RITM0012345",
        "lines": [{"catalog_entry_hid": entry["hid"], "quantity": quantity}],
        **more,
    }
    return make.post("/purchase-requests", body)


def _receive(make: Maker, line: dict[str, Any], *serials: str, expect: int = 201, **more: Any):
    now = make.get(f"/purchase-lines/{line['hid']}")
    body = {
        "row_version": now["row_version"],
        "items": [{"serial_number": serial} for serial in serials],
        **more,
    }
    return make.post(f"/purchase-lines/{line['hid']}/receive", body, expect)


def test_a_request_has_numbered_lines_and_is_no_inventory(make: Maker, entry: dict) -> None:
    request = _request(make, entry, requested_on="2026-10-05", notes="Access switches")
    assert (request["status"], request["quantity"], request["pending_quantity"]) == (
        "pending",
        4,
        4,
    )
    (first,) = request["lines"]
    assert (first["name"], first["line"], first["catalog"]["pid"]) == (
        "RITM0012345/1",
        1,
        "C9300-48P",
    )
    site = make.site("Site-3", make.region("Americas"), record_status="draft")
    second = make.post(
        f"/purchase-requests/{request['hid']}/lines",
        {
            "catalog_entry_hid": entry["hid"],
            "quantity": 2,
            "destination_site_hid": site["hid"],
            "expected_on": "2026-12-01",
        },
    )
    assert (second["line"], second["destination_site"]["path"]) == (2, "Americas > Site-3")
    assert "line" in errors(
        make.post(
            f"/purchase-requests/{request['hid']}/lines",
            {"catalog_entry_hid": entry["hid"], "quantity": 1, "line": 2},
            409,
        )
    )
    assert "reference" in errors(make.post("/purchase-requests", {"reference": "ritm0012345"}, 409))
    assert "reference" in errors(make.post("/purchase-requests", {"reference": "A/B"}, 422))
    # Nothing of a request is in any list or count of items.
    assert make.get("/items", include_drafts="true")["total"] == 0
    assert make.totals(include_drafts="true")["items"] == 0
    lines = make.get(f"/purchase-requests/{request['hid']}/lines", sort="-line")
    assert [line["line"] for line in lines["items"]] == [2, 1]
    listed = make.get("/purchase-requests", sort="-pending_quantity,line_count")
    assert [(one["reference"], one["pending_quantity"]) for one in listed["items"]] == [
        ("RITM0012345", 6)
    ]
    assert make.get("/purchase-requests", filter="pending_quantity:gt:0")["total"] == 1
    assert make.get("/purchase-lines", filter="site:eq:Site-3 pending_quantity:gte:2")["total"] == 1


def test_receiving_creates_the_items_that_arrived_and_never_more_than_the_line(
    make: Maker, entry: dict
) -> None:
    request = _request(make, entry)
    (line,) = request["lines"]
    room = make.layout()["room"]
    received = _receive(
        make, line, "FCW-1", "FCW-2", delivered_on="2026-11-02", location_hid=room["hid"]
    )
    assert (received["received_quantity"], received["pending_quantity"]) == (2, 2)
    assert [item["serial_number"] for item in received["items"]] == ["FCW-1", "FCW-2"]
    items = make.get("/items", filter=f"purchase_line_hid:eq:{line['hid']}", sort="serial_number")
    for item in items["items"]:
        assert (item["lifecycle_state"], item["delivered_on"]) == ("Delivered", "2026-11-02")
        assert item["purchase_line"] == {
            "hid": line["hid"],
            "name": "RITM0012345/1",
            "request_hid": request["hid"],
            "reference": "RITM0012345",
            "line": 1,
            "catalog_entry_hid": entry["hid"],
        }
        assert item["location"]["path"].endswith("Room 102")
        (created,) = make.audit(record_type="item", record_hid=item["hid"])
        assert created["action"] == "create"
    events = make.audit(record_type="purchase_line", record_hid=line["hid"])
    assert [event["action"] for event in events] == ["receive", "create"]
    assert events[0]["changes"] == [{"field": "received_quantity", "old": 0, "new": 2}]
    # Each item that arrives needs something to know it by, and all arrive or none.
    body = {"row_version": received["row_version"], "items": [{"serial_number": "FCW-3"}, {}]}
    refused = make.post(f"/purchase-lines/{line['hid']}/receive", body, 422)
    assert "items.1.serial_number" in errors(refused)
    body["items"] = [{"serial_number": "FCW-3"}, {"serial_number": "FCW-1"}]
    refused = make.post(f"/purchase-lines/{line['hid']}/receive", body, 409)
    assert "items.1.serial_number" in errors(refused)
    assert make.get("/items")["total"] == 2
    # More than is still to come is refused, until the line is given more.
    assert "items" in errors(_receive(make, line, "FCW-3", "FCW-4", "FCW-5", expect=422))
    _change(make, f"/purchase-lines/{line['hid']}", quantity=5)
    _receive(make, line, "FCW-3", "FCW-4", "FCW-5")
    assert make.get(f"/purchase-requests/{request['hid']}")["pending_quantity"] == 0
    # A line is never below what has arrived on it, and is taken back by lowering it.
    assert "quantity" in errors(_change(make, f"/purchase-lines/{line['hid']}", 422, quantity=4))
    # The model of a line is corrected at any time, but where items have arrived on it,
    # the change says what becomes of them.
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    assert "items" in errors(
        _change(make, f"/purchase-lines/{line['hid']}", 422, catalog_entry_hid=other["hid"])
    )
    # Every line has arrived in full: the request says so by itself, and it is on record.
    assert make.get(f"/purchase-requests/{request['hid']}")["status"] == "received"
    said = make.audit(record_type="purchase_request", record_hid=request["hid"])[0]
    assert said["changes"] == [{"field": "status", "old": "pending", "new": "received"}]


def test_a_delivery_is_received_as_a_count_and_named_for_its_line(make: Maker, entry: dict) -> None:
    request = _request(make, entry, quantity=5)
    (line,) = request["lines"]
    now = make.get(f"/purchase-lines/{line['hid']}")
    received = make.post(
        f"/purchase-lines/{line['hid']}/receive",
        {"row_version": now["row_version"], "items": [{"serial_number": "FCW-1"}], "quantity": 2},
    )
    assert [item["name"] for item in received["items"]] == [
        None,
        "RITM0012345/1-002",
        "RITM0012345/1-003",
    ]
    assert (received["received_quantity"], received["pending_quantity"]) == (3, 2)
    # Nothing arrived: neither an item nor a count.
    empty = {"row_version": received["row_version"]}
    assert "items" in errors(make.post(f"/purchase-lines/{line['hid']}/receive", empty, 422))
    # Not all has arrived: the request is still what a person said of it.
    assert make.get(f"/purchase-requests/{request['hid']}")["status"] == "pending"
    # A person may say received early: a request may hold lines that are not followed here.
    early = _change(make, f"/purchase-requests/{request['hid']}", status="received")
    assert early["status"] == "received"
    _change(make, f"/purchase-requests/{request['hid']}", status="ordered")
    # The serial number is given later, to the item that is known by its name.
    named = make.get("/items", filter="name:eq:RITM0012345/1-002")["items"][0]
    make.patch(
        f"/items/{named['hid']}", {"row_version": named["row_version"], "serial_number": "FCW-2"}
    )
    more = make.post(
        f"/purchase-lines/{line['hid']}/receive",
        {"row_version": received["row_version"], "quantity": 2},
    )
    assert [item["name"] for item in more["items"]] == ["RITM0012345/1-004", "RITM0012345/1-005"]
    assert make.get(f"/purchase-requests/{request['hid']}")["status"] == "received"
    too_many = {"row_version": more["row_version"], "quantity": 1}
    assert "items" in errors(make.post(f"/purchase-lines/{line['hid']}/receive", too_many, 422))
    # A line that is lowered to what has arrived has arrived in full.
    second = _request_two(make, entry)
    assert second["status"] == "received"


def test_a_place_on_a_line_is_given_once(make: Maker, entry: dict) -> None:
    (line,) = _request(make, entry, quantity=5)["lines"]
    now = make.get(f"/purchase-lines/{line['hid']}")
    path = f"/purchase-lines/{line['hid']}/receive"
    first = make.post(path, {"row_version": now["row_version"], "quantity": 3})
    # One is taken off the line by hand, and keeps the name it was given.
    second = make.get(f"/items/{first['items'][1]['hid']}")
    make.patch(
        f"/items/{second['hid']}",
        {"row_version": second["row_version"], "purchase_line_hid": None},
    )
    more = make.post(path, {"row_version": first["row_version"], "quantity": 2})
    assert [item["name"] for item in more["items"]] == ["RITM0012345/1-004", "RITM0012345/1-005"]
    assert make.get("/items", filter="name:prefix:RITM0012345/1-")["total"] == 5


def _request_two(make: Maker, entry: dict[str, Any]) -> dict[str, Any]:
    request = make.post(
        "/purchase-requests",
        {"reference": "RITM0012400", "lines": [{"catalog_entry_hid": entry["hid"], "quantity": 4}]},
    )
    (line,) = request["lines"]
    _receive(make, line, "FCW-91")
    _change(make, f"/purchase-lines/{line['hid']}", quantity=1)
    return make.get(f"/purchase-requests/{request['hid']}")


def test_a_request_that_is_a_draft_or_cancelled_receives_nothing(make: Maker, entry: dict) -> None:
    request = _request(make, entry, status="draft")
    (line,) = request["lines"]
    assert "status" in errors(_receive(make, line, "FCW-1", expect=422))
    _change(make, f"/purchase-requests/{request['hid']}", status="ordered")
    _receive(make, line, "FCW-1")
    _change(make, f"/purchase-requests/{request['hid']}", status="cancelled")
    assert "status" in errors(_receive(make, line, "FCW-2", expect=422))
    # Nor is an item put on a line of it by hand.
    by_hand = {"name": "by hand", "purchase_line_hid": line["hid"]}
    assert "purchase_line_hid" in errors(make.post("/items", by_hand, 422))
    assert "status" in errors(
        _change(make, f"/purchase-requests/{request['hid']}", 422, status="lost")
    )


def test_an_item_is_put_on_a_line_by_hand_and_the_line_counts_it(make: Maker, entry: dict) -> None:
    (line,) = _request(make, entry, quantity=1)["lines"]
    early = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW-1")
    linked = make.patch(
        f"/items/{early['hid']}",
        {"row_version": early["row_version"], "purchase_line_hid": line["hid"]},
    )
    assert linked["purchase_line"]["name"] == "RITM0012345/1"
    assert make.get(f"/purchase-lines/{line['hid']}")["received_quantity"] == 1
    # The line has nothing still to come.
    refused = make.post(
        "/items",
        {
            "catalog_entry_hid": entry["hid"],
            "serial_number": "FCW-2",
            "purchase_line_hid": line["hid"],
        },
        422,
    )
    assert "purchase_line_hid" in errors(refused)
    assert "purchase_line_hid" in errors(
        make.post("/items", {"name": "x", "purchase_line_hid": "no-such-line"}, 422)
    )
    cleared = make.patch(
        f"/items/{early['hid']}", {"row_version": linked["row_version"], "purchase_line_hid": None}
    )
    assert cleared["purchase_line"] is None
    assert make.get(f"/purchase-lines/{line['hid']}")["pending_quantity"] == 1


def test_an_item_on_a_line_is_of_the_lines_model(make: Maker, entry: dict, db: Session) -> None:
    (line,) = _request(make, entry, quantity=4)["lines"]
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    # One that names no model takes the line's.
    taken = make.post("/items", {"serial_number": "FCW-1", "purchase_line_hid": line["hid"]})
    assert (taken["catalog_entry_hid"], taken["purchase_line_mismatch"]) == (entry["hid"], False)
    # One that names another is refused, and the answer says the line's model.
    refused = make.post(
        "/items",
        {
            "catalog_entry_hid": other["hid"],
            "serial_number": "X-2",
            "purchase_line_hid": line["hid"],
        },
        422,
    )
    assert "C9300-48P" in errors(refused)["catalog_entry_hid"]
    early = make.item(catalog_entry_hid=other["hid"], serial_number="X-3")
    put_on = {"row_version": early["row_version"], "purchase_line_hid": line["hid"]}
    assert "catalog_entry_hid" in errors(make.patch(f"/items/{early['hid']}", put_on, 422))
    # While it is on the line its model is not changed; taken off, it may be.
    remodel = {"row_version": taken["row_version"], "catalog_entry_hid": other["hid"]}
    assert "catalog_entry_hid" in errors(make.patch(f"/items/{taken['hid']}", remodel, 422))
    off = make.patch(f"/items/{taken['hid']}", {**remodel, "purchase_line_hid": None})
    assert (off["catalog_entry_hid"], off["purchase_line"]) == (other["hid"], None)
    assert make.get(f"/purchase-lines/{line['hid']}")["mismatched_items"] == 0

    # What 0.6.0 let in is left as it is, is not held against another change, and is
    # reported to be put right.
    astray = make.post("/items", {"serial_number": "FCW-4", "purchase_line_hid": line["hid"]})
    held = db.get_one(Item, astray["hid"])
    held.catalog_entry_hid = other["hid"]
    db.commit()
    renamed = _change(make, f"/items/{astray['hid']}", name="site2-sw4")
    assert (renamed["name"], renamed["purchase_line_mismatch"]) == ("site2-sw4", True)
    assert make.get(f"/purchase-lines/{line['hid']}")["mismatched_items"] == 1
    found = make.get("/items", filter="purchase_line_mismatch:eq:true")["items"]
    assert [one["hid"] for one in found] == [astray["hid"]]
    assert make.get("/purchase-lines", filter="mismatched_items:gt:0")["total"] == 1
    # Put right by giving it the line's model.
    _change(make, f"/items/{astray['hid']}", catalog_entry_hid=entry["hid"])
    assert make.get("/items", filter="purchase_line_mismatch:eq:true")["total"] == 0
    assert make.get(f"/purchase-lines/{line['hid']}")["mismatched_items"] == 0


def test_a_line_that_is_not_tracked_takes_no_item_and_is_waited_for_by_nobody(
    make: Maker, entry: dict
) -> None:
    request = make.post(
        "/purchase-requests",
        {
            "reference": "RITM0012345",
            "lines": [
                {"catalog_entry_hid": entry["hid"], "quantity": 2},
                {"part_number": "HLT-100", "description": "Cable ties, 100", "quantity": 50},
            ],
        },
    )
    switches, ties = request["lines"]
    assert (switches["tracked"], ties["tracked"]) == (True, False)
    assert (ties["catalog_entry_hid"], ties["catalog"], ties["part_number"]) == (
        None,
        None,
        "HLT-100",
    )
    assert (ties["description"], ties["quantity"], ties["pending_quantity"]) == (
        "Cable ties, 100",
        50,
        0,
    )
    # It is in no count of its request, and not on the list of what is still to come.
    assert (request["quantity"], request["pending_quantity"]) == (2, 2)
    assert make.get("/purchase-requests", filter="pending_quantity:eq:2")["total"] == 1
    assert make.get("/purchase-lines", filter="tracked:eq:false")["total"] == 1
    assert make.get("/purchase-lines", filter="part_number:eq:hlt-100")["total"] == 1
    assert make.get("/purchase-lines", filter="pending_quantity:gt:0")["total"] == 1
    listed = make.get("/purchase-lines", sort="-tracked,catalog.pid")["items"]
    assert [line["name"] for line in listed] == ["RITM0012345/1", "RITM0012345/2"]
    # It takes no item, by a receipt or by hand.
    refused = _receive(make, ties, "TIE-1", expect=422)
    assert "match it to a model" in errors(refused)["items"]
    by_hand = {"name": "ties", "purchase_line_hid": ties["hid"]}
    assert "purchase_line_hid" in errors(make.post("/items", by_hand, 422))
    # A line has a model or a part number.
    lines = f"/purchase-requests/{request['hid']}/lines"
    assert "catalog_entry_hid" in errors(make.post(lines, {"quantity": 1}, 422))
    assert "catalog_entry_hid" in errors(
        _change(make, f"/purchase-lines/{ties['hid']}", 422, part_number=None)
    )
    # Every line that is tracked has arrived: the request is received.
    _receive(make, switches, "FCW-1", "FCW-2")
    assert make.get(f"/purchase-requests/{request['hid']}")["status"] == "received"

    # A line that is not tracked is matched to a model at any time, which makes it
    # tracked, and its model is taken off while nothing has arrived on it.
    other = make.post(
        "/purchase-requests",
        {"reference": "RITM0012400", "lines": [{"part_number": "C9300-48P=", "quantity": 1}]},
    )
    (late,) = other["lines"]
    matched = _change(make, f"/purchase-lines/{late['hid']}", catalog_entry_hid=entry["hid"])
    assert (matched["tracked"], matched["pending_quantity"], matched["part_number"]) == (
        True,
        1,
        "C9300-48P=",
    )
    assert make.get(f"/purchase-requests/{other['hid']}")["pending_quantity"] == 1
    off = _change(make, f"/purchase-lines/{late['hid']}", catalog_entry_hid=None)
    assert (off["tracked"], off["pending_quantity"]) == (False, 0)
    # Not tracked any more, it is waited for no more: nothing of the request is.
    assert make.get(f"/purchase-requests/{other['hid']}")["status"] == "pending"
    assert "catalog_entry_hid" in errors(
        _change(make, f"/purchase-lines/{switches['hid']}", 422, catalog_entry_hid=None)
    )


def test_a_line_corrected_after_items_arrived_says_what_becomes_of_them(
    make: Maker, entry: dict
) -> None:
    right = make.entry({"hid": entry["vendor_hid"]}, "C9300-48T", support_weight="3")
    follow = _request(make, entry, quantity=3)["lines"][0]
    kept, plain, gone = _receive(make, follow, "FCW-1", "FCW-2", "FCW-3")["items"]
    _change(make, f"/items/{kept['hid']}", support_weight="7")
    now = make.get(f"/items/{gone['hid']}")
    make.post(f"/items/{gone['hid']}/retire", {"row_version": now["row_version"]}, 200)
    path = f"/purchase-lines/{follow['hid']}"
    assert "follow" in errors(_change(make, path, 422, catalog_entry_hid=right["hid"]))["items"]
    assert "items" in errors(
        _change(make, path, 422, catalog_entry_hid=right["hid"], items="maybe")
    )
    corrected = _change(make, path, catalog_entry_hid=right["hid"], items="follow")
    assert (corrected["catalog"]["pid"], corrected["mismatched_items"]) == ("C9300-48T", 0)
    # Each item that is not retired has the corrected model, with an event of its own.
    for item, weight, source in ((kept, "7", "own"), (plain, "3", "catalog")):
        now = make.get(f"/items/{item['hid']}")
        assert (now["catalog_entry_hid"], now["purchase_line_mismatch"]) == (right["hid"], False)
        assert Decimal(now["effective"]["support_weight"]["value"]) == Decimal(weight)
        assert now["effective"]["support_weight"]["source"] == source
        (event, *_) = make.audit(record_type="item", record_hid=item["hid"])
        assert {"field": "catalog_entry_hid", "old": entry["hid"], "new": right["hid"]} in event[
            "changes"
        ]
    assert make.get(f"/items/{gone['hid']}")["catalog_entry_hid"] == entry["hid"]
    line_events = make.audit(record_type="purchase_line", record_hid=follow["hid"])
    assert line_events[0]["changes"] == [
        {"field": "catalog_entry_hid", "old": entry["hid"], "new": right["hid"]}
    ]

    # Left as they are, they are reported, one by one.
    stay = _request(make, entry, quantity=2, reference="RITM0012400")["lines"][0]
    left = _receive(make, stay, "FCW-11", "FCW-12")["items"]
    stayed = _change(
        make, f"/purchase-lines/{stay['hid']}", catalog_entry_hid=right["hid"], items="stay"
    )
    assert stayed["mismatched_items"] == 2
    for item in left:
        now = make.get(f"/items/{item['hid']}")
        assert (now["catalog_entry_hid"], now["purchase_line_mismatch"]) == (entry["hid"], True)
    # An item on a line is still not given another model by itself (D-161).
    alone = make.get(f"/items/{left[0]['hid']}")
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    remodel = {"row_version": alone["row_version"], "catalog_entry_hid": other["hid"]}
    assert "catalog_entry_hid" in errors(make.patch(f"/items/{alone['hid']}", remodel, 422))
    # Put right by its line's model, it is no longer reported.
    _change(make, f"/items/{alone['hid']}", catalog_entry_hid=right["hid"])
    assert make.get(f"/purchase-lines/{stay['hid']}")["mismatched_items"] == 1


# --- external systems ----------------------------------------------------------------


def test_a_registration_is_of_one_record_with_one_system_once(make: Maker, entry: dict) -> None:
    watch = make.post(
        "/external-systems",
        {"name": "NetWatch", "kind": "monitoring", "url": "https://netwatch.example.net"},
    )
    assert (watch["kind"], watch["registrations"]) == ("monitoring", 0)
    assert "name" in errors(make.post("/external-systems", {"name": "netwatch"}, 409))
    assert "url" in errors(make.post("/external-systems", {"name": "X", "url": "netwatch"}, 422))
    make.post("/external-systems", {"name": "Y", "kind": "telepathy"}, 422)
    switches = make.switches(entry, "sw", 4)
    stack = make.stack("site2-sw-stack1", switches[:2])
    of_stack = make.post(
        "/registrations",
        {"system_hid": watch["hid"], "group_hid": stack["hid"], "external_id": "node-1"},
    )
    assert (of_stack["status"], of_stack["group"]["name"], of_stack["item"]) == (
        "registered",
        "site2-sw-stack1",
        None,
    )
    body = {"system_hid": watch["hid"], "group_hid": stack["hid"]}
    assert "group_hid" in errors(make.post("/registrations", body, 409))
    both = {"system_hid": watch["hid"], "group_hid": stack["hid"], "item_hid": switches[0]["hid"]}
    assert "item_hid" in errors(make.post("/registrations", both, 422))
    assert "item_hid" in errors(make.post("/registrations", {"system_hid": watch["hid"]}, 422))
    # On the stack, and not one of the registrations of its members: but a member says
    # what its stack is registered with, so that nobody takes it for unknown.
    of_group = make.get(f"/device-groups/{stack['hid']}")["registrations"]
    assert [one["system"]["name"] for one in of_group] == ["NetWatch"]
    member = make.get(f"/items/{switches[0]['hid']}")
    assert member["registrations"] == []
    assert [
        (one["system"]["name"], one["group"]["name"], one["external_id"])
        for one in member["group_registrations"]
    ] == [("NetWatch", "site2-sw-stack1", "node-1")]
    assert make.get(f"/items/{switches[2]['hid']}")["group_registrations"] == []
    of_item = make.post(
        "/registrations",
        {
            "system_hid": watch["hid"],
            "item_hid": switches[2]["hid"],
            "confirmed_at": "2026-11-02T10:00:00",
        },
    )
    # A moment with no zone is in the application's time zone: New York, in winter.
    assert of_item["confirmed_at"] == "2026-11-02T15:00:00Z"
    ahead = {"row_version": of_item["row_version"], "confirmed_at": day(3) + "T00:00:00Z"}
    assert "confirmed_at" in errors(make.patch(f"/registrations/{of_item['hid']}", ahead, 422))
    # What a system knows: by a registration of its own, or of the stack it is in.
    assert make.found(filter="registration.system:eq:netwatch") == ["sw-01", "sw-02", "sw-03"]
    assert make.found(filter="registration.system:ne:NetWatch") == ["sw-04"]
    assert make.found(filter="registration.system:empty:true") == ["sw-04"]
    assert make.get("/device-groups", filter="registration.system:eq:NetWatch")["total"] == 1
    make.get("/items", sort="registration.system")
    assert make.get(f"/external-systems/{watch['hid']}")["registrations"] == 2
    # One that ends is given the status removed, and is the same record when it begins again.
    removed = _change(make, f"/registrations/{of_item['hid']}", status="removed")
    assert removed["status"] == "removed"
    assert make.found(filter="registration.system:eq:NetWatch") == ["sw-01", "sw-02"]
    assert make.get(f"/external-systems/{watch['hid']}")["registrations"] == 1
    assert make.get("/registrations", filter="status:eq:removed")["total"] == 1
    back = _change(make, f"/registrations/{of_item['hid']}", status="registered")
    assert back["hid"] == of_item["hid"]
    # A draft or retired record is not counted, as in every other count.
    draft = make.item(name="draft", record_status="draft")
    make.post("/registrations", {"system_hid": watch["hid"], "item_hid": draft["hid"]})
    assert make.get(f"/external-systems/{watch['hid']}")["registrations"] == 2
    # One that was a mistake is removed outright, and the audit trail holds what it was.
    mistake = make.post(
        "/registrations",
        {"system_hid": watch["hid"], "item_hid": switches[3]["hid"], "external_id": "wrong"},
    )
    make.delete(f"/registrations/{mistake['hid']}")
    make.get(f"/registrations/{mistake['hid']}", 404)
    gone = make.audit(record_type="registration", record_hid=mistake["hid"])[0]
    assert gone["action"] == "delete"
    assert {change["field"]: change["old"] for change in gone["changes"]}["external_id"] == "wrong"
    # A retired system takes no new registration, and none that begins again.
    _change(make, f"/registrations/{of_item['hid']}", status="removed")
    system = make.get(f"/external-systems/{watch['hid']}")
    make.post(
        f"/external-systems/{watch['hid']}/retire", {"row_version": system["row_version"]}, 200
    )
    assert "system_hid" in errors(
        make.post(
            "/registrations", {"system_hid": watch["hid"], "item_hid": switches[3]["hid"]}, 422
        )
    )
    assert "status" in errors(
        _change(make, f"/registrations/{of_item['hid']}", 422, status="registered")
    )
    assert make.get("/registrations", sort="holder,-system.name")["total"] == 3
    actions = [
        event["action"]
        for event in make.audit(record_type="registration", record_hid=of_item["hid"])
    ]
    assert actions == ["update", "update", "update", "create"]


# --- capacity ------------------------------------------------------------------------


def _line(
    make: Maker,
    side: str,
    category: str | None,
    name: str,
    quantity: str,
    units: str,
    expect: int = 201,
    **more: Any,
):
    body = {"side": side, "name": name, "quantity": quantity, "units_each": units, **more}
    if category is not None:
        body["category"] = category
    return make.post("/capacity-lines", body, expect)


def test_what_a_capacity_line_must_be(make: Maker) -> None:
    staff = _line(make, "supply", "staff", "Network engineer", "3", "1.0", annual_cost="1.50")
    assert (staff["units"], staff["category_label"], staff["in_date"]) == ("3", "Staff", True)
    # A demand line is other work, whether or not it says so.
    project = _line(make, "demand", None, "Site consolidation", "1", "1.5")
    assert project["category"] == "other_work"
    assert "category" in errors(_line(make, "supply", None, "No category", "1", "1", 422))
    assert "category" in errors(_line(make, "supply", "other_work", "Wrong side", "1", "1", 422))
    assert "category" in errors(_line(make, "demand", "staff", "Wrong side", "1", "1", 422))
    assert "category" in errors(_line(make, "supply", "magic", "No such", "1", "1", 422))
    # The name is unique on its side.
    assert "name" in errors(_line(make, "supply", "tools", "network engineer", "1", "1", 409))
    _line(make, "demand", None, "Network engineer", "1", "1")
    assert "ends_on" in errors(
        _line(make, "supply", "tools", "Dates", "1", "1", 422, starts_on=day(5), ends_on=day(1))
    )
    region = make.region("Americas")
    site = make.site("Site-2", region)
    assert "site_hid" in errors(
        _line(
            make,
            "supply",
            "tools",
            "Both",
            "1",
            "1",
            422,
            region_hid=region["hid"],
            site_hid=site["hid"],
        )
    )
    served = _line(make, "supply", "smart_hands", "Smart hands", "1", "0.5", site_hid=site["hid"])
    assert served["site"]["path"] == "Americas > Site-2"
    assert (
        make.patch(
            f"/capacity-lines/{staff['hid']}",
            {"row_version": staff["row_version"], "units_each": "0.25"},
        )["units"]
        == "0.75"
    )
    listed = make.get("/capacity-lines", sort="-units", filter="side:eq:supply")
    assert [line["name"] for line in listed["items"]] == ["Network engineer", "Smart hands"]
    assert make.get("/capacity-lines", filter="units:gte:0.75 in_date:eq:true")["total"] == 3
    retired = make.post(
        f"/capacity-lines/{project['hid']}/retire", {"row_version": project["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    assert make.get("/capacity-lines", filter="side:eq:demand")["total"] == 1
    # A category in use is not removed from its list.
    staff_choice = next(
        c for c in make.get("/choices", list="capacity_category") if c["value"] == "staff"
    )
    assert (
        make.client.delete(f"{API}/choices/{staff_choice['hid']}", headers=make.headers).status_code
        == 409
    )


def test_the_balance_is_exact_and_counts_what_is_in_date(
    make: Maker, entry: dict, admin: dict
) -> None:
    empty = make.get("/reports/capacity")["active"]
    assert (empty["demand"], empty["supply"], empty["balance"]) == ("0", "0", "0")
    assert (empty["coverage_pct"], empty["own_share_pct"]) == (None, None)
    assert [row["category"] for row in empty["by_category"]] == [
        "staff",
        "professional_services",
        "smart_hands",
        "tools",
        "services",
    ]
    # A support weight of 1,000 at 300 to the unit is three and a third units.
    heavy = make.entry(make.vendor("Juniper"), "MX960", support_weight="1000")
    make.item(catalog_entry_hid=heavy["hid"], serial_number="JN-1", lifecycle_state="Prod")
    make.item(
        catalog_entry_hid=heavy["hid"],
        serial_number="JN-2",
        lifecycle_state="Prod",
        record_status="draft",
    )
    _line(make, "supply", "staff", "Engineer", "3", "1.0", annual_cost="300000.00")
    _line(make, "supply", "tools", "Tooling", "1", "0.33")
    _line(
        make,
        "supply",
        "services",
        "What-if",
        "2",
        "1.5",
        record_status="draft",
        annual_cost="10.00",
    )
    _line(make, "supply", "tools", "Not yet", "1", "5", starts_on=day(5))
    _line(make, "supply", "tools", "No longer", "1", "5", ends_on=day(-5))
    report = make.get("/reports/capacity")
    active, drafts = report["active"], report["with_drafts"]
    assert (active["support_weight"], active["infrastructure_demand"]) == ("1000", "3.33")
    assert (active["supply"], active["balance"], active["coverage_pct"]) == ("3.33", "0", "99.9")
    assert (active["own_units"], active["outside_units"], active["own_share_pct"]) == (
        "3",
        "0.33",
        "90.09",
    )
    assert active["annual_cost"] == "300000.00"
    assert (drafts["support_weight"], drafts["infrastructure_demand"]) == ("2000", "6.67")
    assert (drafts["supply"], drafts["balance"], drafts["annual_cost"]) == (
        "6.33",
        "-0.34",
        "300010.00",
    )
    # The setting decides how much weight one unit carries.
    set_ = make.client.put(
        f"{API}/settings/weight_per_resource_unit",
        json={"row_version": 0, "value": 500},
        headers=admin,
    )
    assert set_.status_code == 200, set_.text
    assert make.get("/reports/capacity")["active"]["infrastructure_demand"] == "2"


WRITES = (
    ("post", "/purchase-requests"),
    ("patch", "/purchase-requests/x"),
    ("post", "/purchase-requests/x/lines"),
    ("patch", "/purchase-lines/x"),
    ("post", "/purchase-lines/x/receive"),
    ("post", "/external-systems"),
    ("patch", "/external-systems/x"),
    ("post", "/external-systems/x/retire"),
    ("post", "/registrations"),
    ("patch", "/registrations/x"),
    ("delete", "/registrations/x"),
    ("post", "/capacity-lines"),
    ("patch", "/capacity-lines/x"),
    ("post", "/capacity-lines/x/retire"),
)


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_every_write_needs_the_inventory_role(
    client: TestClient, viewer: dict[str, str], method: str, path: str
) -> None:
    assert client.request(method, API + path, json={}, headers=viewer).status_code == 403
    assert client.request(method, API + path, json={}).status_code == 401


def test_a_viewer_reads_all_of_it(client: TestClient, viewer: dict[str, str]) -> None:
    for path in (
        "/purchase-requests",
        "/purchase-lines",
        "/external-systems",
        "/registrations",
        "/capacity-lines",
        "/reports/capacity",
        "/reports/end-of-life",
        "/reports/replacements",
    ):
        assert client.get(API + path, headers=viewer).status_code == 200, path
