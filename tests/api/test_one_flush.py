"""A new item and its audit event stored by one flush of the session (P-324).

The item is given beforehand what its first flush gave it: its HID, given or made, its
moments, and the default of each field not given, so that its event says what it is
stored with, as when it was stored first and its event after it. Then the session's next
flush stores the two at once. What the event says, the order of the events of a row, the
HID a row gives, and a row refused for a twin are as they were.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db.models import AuditEvent, Item
from hirdir.domain import audit, catalog, items
from tests.api.inventory import API, Maker
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def test_a_new_item_and_its_event_are_stored_by_one_flush(db: Session) -> None:
    vendor = catalog.create_vendor(db, audit.SYSTEM, {"name": "Cisco"})
    model = catalog.create_entry(db, audit.SYSTEM, {"vendor_hid": vendor.hid, "pid": "C9300-48P"})
    db.flush()
    flushed: list[set[str]] = []

    @event.listens_for(db, "before_flush")
    def _seen(session: Session, *_: Any) -> None:
        flushed.append({type(one).__name__ for one in session.new})

    hid = ids.new_hid()
    with ids.given(items.RECORD_TYPE, hid):
        item = items.create_item(
            db, audit.SYSTEM, {"catalog_entry_hid": model.hid, "serial_number": "FLUSH001"}
        )
    db.flush()
    assert flushed[0] == {"Item", "AuditEvent"}
    assert item.hid == hid
    made = db.scalars(select(AuditEvent).where(AuditEvent.record_hid == hid)).one()
    # The event says what the item is stored with, its defaults among them.
    said = {entry["field"]: entry["new"] for entry in made.changes}
    assert said == {
        "catalog_entry_hid": model.hid,
        "serial_number": "FLUSH001",
        "quantity": 1,
        "record_status": "active",
    }
    stored = db.get_one(Item, hid)
    db.refresh(stored)
    assert (stored.quantity, stored.record_status, stored.row_version) == (1, "active", 1)
    assert stored.created_at == stored.updated_at
    assert stored.created_at <= made.at


def test_the_events_of_a_row_come_in_the_order_they_did(
    make: Maker, files: Files, client: TestClient
) -> None:
    make.entry(make.vendor("Cisco"), "C9300-48P")
    make.tag("lab")
    network = make.network("Management")
    hid = ids.new_hid()
    text = (
        "hid,vendor,pid,serial_number,asset_tag,tags,mgmt_address,mgmt_network\n"
        f"{hid},Cisco,C9300-48P,ORDER001,AT-ORDER-1,lab,198.51.100.21,{network['label']}\n"
        ",Cisco,C9300-48P,ORDER002,AT-ORDER-1,,,\n"
        ",Cisco,C9300-48P,ORDER003,,,198.51.100.22,\n"
    )
    preview = files.preview("items", text)
    rows = preview["rows"]
    assert [row["outcome"] for row in rows] == ["create", "rejected", "create"]
    # The second gives the asset tag the first gave: refused as a twin, on its column.
    assert rows[1]["reasons"] == [
        {"field": "asset_tag", "message": "another item has this asset tag"}
    ]
    job = files.apply(preview, skip_rejected=True)
    assert (job["status"], job["applied"]) == ("applied", 2)
    started = make.audit(record_type="import_job", action="apply_started")[0]
    events = make.audit(request_id=started["request_id"], limit=100)
    made = [
        (one["record_type"], one["action"])
        for one in reversed(events)
        if one["record_type"] != "import_job"
    ]
    # Each item's event first, then its address's, row by row.
    assert made == [
        ("item", "create"),
        ("address", "create"),
        ("item", "create"),
        ("address", "create"),
    ]
    first = make.get(f"/items/{hid}")
    assert first["serial_number"] == "ORDER001"
    tagged = next(one for one in events if one["record_hid"] == hid)
    assert {"field": "tags", "old": [], "new": ["lab"]} in tagged["changes"]
    response = client.get(
        f"{API}/items", params={"filter": "serial_number:eq:ORDER002"}, headers=files.headers
    )
    assert response.json()["total"] == 0
