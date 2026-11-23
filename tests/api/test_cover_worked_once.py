"""What covers an item, as the item list filters and sorts by it, is worked out once for
a statement from what is in force for each contract today (D-166, P-326): one table of
the contracts, read by every coverage of every item. It answers as each item's record
does, item by item, in the terms that turn and the cover that ends on the day, and on
the day in the application's time zone."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import Agreement, Contract, ContractCoverage, Item
from hirdir.domain import contracts
from hirdir.io import fields, hosted, listing
from tests.api.inventory import API
from tests.api.test_contracts import Desk

# Two zones, of which one always has another day than New York's: Kiritimati is a day
# ahead from five or six in the morning there, and the zone of twelve hours behind
# Greenwich a day behind until seven or eight.
FAR_ZONES = ("Pacific/Kiritimati", "Etc/GMT+12")


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


def _held(db: Session, model: Any, hid: str, **values: Any) -> None:
    """Write what the API would not let a test enter at once: a term that has run, a
    status that a day gave it, an item that has left."""
    record = db.get_one(model, hid)
    for name, value in values.items():
        setattr(record, name, value)
    db.commit()


def _inventory(desk: Desk, db: Session) -> None:
    """Contracts in each of the ways a day decides what covers, and items under them."""
    today = contracts.today(db)

    def on(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    def at(offset: int) -> date:
        return today + timedelta(days=offset)

    entry = desk.catalog()
    agreement = desk.agreement(starts_on=on(-100), ends_on=on(100))
    made = {
        number: desk.contract(number, starts_on=on(-300), ends_on=on(300))
        for number in (
            "CON-ALPHA",
            "con-aardvark",
            "CON-LAPSED",
            "CON-PENDING",
            "CON-TURNED",
            "CON-NEXT",
            "CON-DRAFT",
            "CON-EXPIRED",
            "CON-LATER",
        )
    }
    made["CON-AGREED"] = desk.contract("CON-AGREED", agreement_hid=agreement["hid"])
    items: dict[str, dict[str, Any]] = {}
    under = {
        "two": ("CON-ALPHA", "CON-PENDING"),
        "lapsed": ("CON-LAPSED",),
        "turned": ("CON-TURNED",),
        "ends-today": ("CON-NEXT",),
        "own-end-today": ("CON-ALPHA",),
        "agreed": ("CON-AGREED",),
        "aardvark": ("con-aardvark", "CON-ALPHA"),
        "nothing": (),
        "draft-and-expired": ("CON-DRAFT", "CON-EXPIRED"),
        "not-yet": ("CON-LATER",),
        "starts-tomorrow": ("CON-ALPHA",),
        "released": ("CON-ALPHA",),
        "released-ends-today": ("CON-ALPHA",),
        "leaving": ("CON-ALPHA",),
        "left-a-lapsed-one": ("CON-LAPSED",),
        "archived": ("CON-ALPHA", "con-aardvark"),
        "retired": ("CON-TURNED",),
    }
    for serial, numbers in under.items():
        items[serial] = desk.switch(entry, f"FCW-{serial}")
        for number in numbers:
            desk.cover(made[number], items[serial])
    hid = {number: one["hid"] for number, one in made.items()}

    def coverage(serial: str, number: str) -> str:
        return next(
            one["hid"]
            for one in desk.get(f"/items/{items[serial]['hid']}")["coverage"]
            if one["contract_hid"] == hid[number]
        )

    _held(db, Contract, hid["CON-ALPHA"], starts_on=at(-50), ends_on=at(50))
    _held(db, Contract, hid["con-aardvark"], starts_on=at(-50), ends_on=at(80))
    # Still active by its status, its period over: it has lapsed, and covers nothing.
    _held(db, Contract, hid["CON-LAPSED"], starts_on=at(-200), ends_on=at(-10))
    # Past its period with its renewal pending: it covers, and no day ends it.
    _held(
        db,
        Contract,
        hid["CON-PENDING"],
        status="renewal_pending",
        starts_on=at(-90),
        ends_on=at(-5),
    )
    # Expired yesterday, its next term begun today under a number of its own.
    _held(
        db,
        Contract,
        hid["CON-TURNED"],
        status="expired",
        starts_on=at(-300),
        ends_on=at(-1),
        next_starts_on=at(0),
        next_ends_on=at(200),
        next_number="CON-TURNED-2",
    )
    # Its term ends today, and the next begins tomorrow.
    _held(
        db,
        Contract,
        hid["CON-NEXT"],
        starts_on=at(-300),
        ends_on=at(0),
        next_starts_on=at(1),
        next_ends_on=at(300),
        next_number="CON-NEXT-2",
    )
    _held(db, Contract, hid["CON-DRAFT"], record_status="draft")
    _held(db, Contract, hid["CON-EXPIRED"], status="expired", starts_on=at(-300), ends_on=at(30))
    _held(db, Contract, hid["CON-LATER"], starts_on=at(10), ends_on=at(400))
    # The agreement's next term began yesterday: its contract has its days from it.
    _held(db, Agreement, agreement["hid"], next_starts_on=at(-1), next_ends_on=at(250))
    _held(db, ContractCoverage, coverage("own-end-today", "CON-ALPHA"), ends_on=at(0))
    _held(db, ContractCoverage, coverage("starts-tomorrow", "CON-ALPHA"), starts_on=at(1))
    # Out of service: its cover goes on; it left while the term runs; it left one that
    # lapsed; it is archived; it is retired, having left while the term runs.
    _held(db, Item, items["released"]["hid"], lifecycle_state="Released")
    # Out of service with its cover ending today: nothing more is asked of the vendor.
    _held(db, Item, items["released-ends-today"]["hid"], lifecycle_state="Released")
    _held(db, ContractCoverage, coverage("released-ends-today", "CON-ALPHA"), ends_on=at(0))
    _held(db, Item, items["leaving"]["hid"], lifecycle_state="Pending-Removal")
    _held(
        db,
        ContractCoverage,
        coverage("leaving", "CON-ALPHA"),
        ends_on=at(-1),
        left_service=True,
    )
    _held(db, Item, items["left-a-lapsed-one"]["hid"], lifecycle_state="Pending-Removal")
    _held(
        db,
        ContractCoverage,
        coverage("left-a-lapsed-one", "CON-LAPSED"),
        ends_on=at(-12),
        left_service=True,
    )
    _held(db, Item, items["archived"]["hid"], lifecycle_state="Archived")
    _held(db, Item, items["retired"]["hid"], record_status="retired")
    _held(db, ContractCoverage, coverage("retired", "CON-TURNED"), ends_on=at(0), left_service=True)


def _fold(text: str) -> str:
    # As the database compares text when case does not count (`dialect.folded`).
    return text.lower()


def _least(values: list[Any]) -> Any:
    return min(values) if values else None


def _order(values: dict[str, Any], descending: bool) -> list[str]:
    """Return the HIDs in the order of their values, blank values last and a tie in the
    order of the HIDs, as a page of a list is sorted."""
    present = sorted(hid for hid, value in values.items() if value is not None)
    present.sort(key=lambda hid: values[hid], reverse=descending)
    return present + sorted(hid for hid, value in values.items() if value is None)


def _agree(desk: Desk) -> int:
    """Hold every filter and sort of what covers an item to what each item's record
    says, and return how many conditions were held."""
    every: dict[str, Any] = {"include_archived": "true", "include_drafts": "true", "limit": 1000}
    records = {one["hid"]: one for one in desk.get("/items", **every)["items"]}
    in_force = {
        hid: [one for one in record["coverage"] if one["in_force"]]
        for hid, record in records.items()
    }
    counting = {hid: record["out_of_service_contracts"] for hid, record in records.items()}

    def found(filter_: str) -> set[str]:
        return {one["hid"] for one in desk.get("/items", filter=filter_, **every)["items"]}

    def having(test: Callable[[str], bool]) -> set[str]:
        return {hid for hid in records if test(hid)}

    expected: dict[str, set[str]] = {
        "covered:eq:true": having(lambda hid: records[hid]["covered"]),
        "covered:eq:false": having(lambda hid: not records[hid]["covered"]),
        "contract_count:gt:1": having(lambda hid: records[hid]["contract_count"] > 1),
        "covered_until:empty:true": having(lambda hid: records[hid]["covered_until"] is None),
        "out_of_service_cover:eq:true": having(lambda hid: bool(counting[hid])),
        "contract.number:empty:true": having(lambda hid: not in_force[hid]),
    }
    for count in (0, 1, 2):
        expected[f"contract_count:eq:{count}"] = having(
            lambda hid, count=count: records[hid]["contract_count"] == count
        )
    for until in {record["covered_until"] for record in records.values()} - {None}:
        expected[f"covered_until:eq:{until}"] = having(
            lambda hid, until=until: records[hid]["covered_until"] == until
        )
    refs = {
        (one["contract"]["hid"], one["contract"]["number"], one["contract"]["status"])
        for record in records.values()
        for one in record["coverage"]
    }
    for contract_hid, number, status in refs:
        expected[f"contract.hid:eq:{contract_hid}"] = having(
            lambda hid, of=contract_hid: of in [one["contract_hid"] for one in in_force[hid]]
        )
        expected[f"contract.number:eq:{number.upper()}"] = having(
            lambda hid, of=number: of in [one["contract"]["number"] for one in in_force[hid]]
        )
        expected[f"contract.number:ne:{number}"] = having(
            lambda hid, of=number: of not in [one["contract"]["number"] for one in in_force[hid]]
        )
        expected[f"contract.status:eq:{status}"] = having(
            lambda hid, of=status: of in [one["contract"]["status"] for one in in_force[hid]]
        )
        expected[f"out_of_service_contract.hid:eq:{contract_hid}"] = having(
            lambda hid, of=contract_hid: of in [one["hid"] for one in counting[hid]]
        )
        expected[f"out_of_service_contract.number:eq:{number}"] = having(
            lambda hid, of=number: of in [one["number"] for one in counting[hid]]
        )
    for filter_, items in expected.items():
        assert found(filter_) == items, filter_

    sorts = {
        "contract.number": {
            hid: _least([_fold(one["contract"]["number"]) for one in its])
            for hid, its in in_force.items()
        },
        "contract.status": {
            hid: _least([one["contract"]["status"] for one in its]) for hid, its in in_force.items()
        },
        "contract_count": {hid: record["contract_count"] for hid, record in records.items()},
        "covered_until": {hid: record["covered_until"] for hid, record in records.items()},
        "out_of_service_contract.number": {
            hid: _least([_fold(one["number"]) for one in its]) for hid, its in counting.items()
        },
    }
    for name, values in sorts.items():
        for way in ("", "-"):
            listed = [one["hid"] for one in desk.get("/items", sort=way + name, **every)["items"]]
            assert listed == _order(values, way == "-"), way + name
    return len(expected) + 2 * len(sorts)


def _zone(desk: Desk, admin: dict[str, str], zone: str | None) -> None:
    now = {one["key"]: one for one in desk.get("/settings")}
    response = desk.client.put(
        f"{API}/settings/time_zone",
        json={"row_version": now["time_zone"]["row_version"], "value": zone},
        headers=admin,
    )
    assert response.status_code == 200, response.text


def test_the_list_finds_and_sorts_what_covers_an_item_as_its_record_says(
    desk: Desk, db: Session, admin: dict[str, str]
) -> None:
    _inventory(desk, db)
    records = {
        one["serial_number"]: one for one in desk.get("/items", include_archived="true")["items"]
    }
    # The ways a day decides, as the record says them, so that each is held below.
    assert records["FCW-two"]["contract_count"] == 2
    assert not records["FCW-lapsed"]["covered"]
    turned = records["FCW-turned"]["coverage"][0]
    assert (turned["in_force"], turned["contract"]["number"]) == (True, "CON-TURNED-2")
    assert turned["contract"]["status"] == "active"
    assert records["FCW-ends-today"]["coverage"][0]["contract"]["number"] == "CON-NEXT"
    assert records["FCW-ends-today"]["covered"]
    assert records["FCW-own-end-today"]["covered"]
    assert not records["FCW-starts-tomorrow"]["covered"]
    assert [one["number"] for one in records["FCW-leaving"]["out_of_service_contracts"]] == [
        "CON-ALPHA"
    ]
    assert records["FCW-left-a-lapsed-one"]["out_of_service_contracts"] == []
    assert records["FCW-released-ends-today"]["out_of_service_contracts"] == []
    held = _agree(desk)
    assert held > 40

    # On another day than New York's, by the application's time zone, the list and the
    # records move together.
    zone = next(one for one in FAR_ZONES if clock.today(one) != contracts.today(db))
    _zone(desk, admin, zone)
    db.rollback()
    assert contracts.today(db) == clock.today(zone)
    _agree(desk)
    _zone(desk, admin, None)


def test_the_contracts_are_worked_out_once_and_the_page_and_its_total_together(
    desk: Desk, db: Session
) -> None:
    _inventory(desk, db)
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        # Not the question, once for a session, whether anything runs on a host (P-246).
        if "FROM items" in statement and hosted.MARK not in statement:
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", note)
    try:
        rows, total = listing.page(
            db, fields.ITEMS, filter_="covered:eq:true", sort=["-covered_until"], limit=3
        )
        sent = list(statements)
        statements.clear()
        past, past_total = listing.page(db, fields.ITEMS, filter_="covered:eq:true", offset=100)
        after_the_last = list(statements)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", note)
    # One statement reads the page and the total, from the records matched once.
    (one,) = sent
    assert len(rows) == 3 < total
    assert total == listing.count(db, fields.ITEMS, filter_="covered:eq:true")
    # What is in force for each contract is a table of the statement's own, which the
    # filter and the sort both read: the contracts are read once, for the table.
    assert one.count("contract_today AS MATERIALIZED") == 1
    assert one.count("FROM contracts") == 1
    assert "JOIN contracts" not in one
    # A page past the last record still says how many there are.
    assert (past, past_total) == ([], total)
    assert len(after_the_last) == 2
