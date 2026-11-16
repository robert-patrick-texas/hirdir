"""What the review of 0.8.0's server found: each defect as a test that failed before its
correction."""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hirdir.db.models import Circuit, CircuitCarrier, CircuitCost, CircuitGroup, CircuitGroupMember
from tests.api.inventory import API, Maker
from tests.api.test_circuit_costs import _circuit, _line, places

_ = places


def _report(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = client.get(f"{API}/reports/circuit-costs", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _listed(client: TestClient, headers: dict[str, str], found: dict[str, Any], row: Any) -> set:
    response = client.post(
        f"{API}/circuits/query",
        json={
            "filter": row["filter"],
            "include_archived": found["include_archived"],
            "include_drafts": found["include_drafts"],
            "limit": 1000,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {one["name"] for one in response.json()["items"]}


def test_each_rows_filter_lists_the_circuits_the_row_counted(
    places: dict[str, Any], db: Session, client: TestClient, viewer: dict[str, str]
) -> None:
    room = places["hub_room"]["hid"]
    for name, more in (
        ("Since 2020", {"activated_on": date(2020, 1, 1)}),
        ("From 2028", {"activated_on": date(2028, 3, 1)}),
        (
            "Ended in 2027",
            {
                "activated_on": date(2020, 1, 1),
                "disconnected_on": date(2027, 6, 30),
                "record_status": "retired",
            },
        ),
        ("Ended in 2026", {"disconnected_on": date(2026, 6, 30)}),
    ):
        _line(db, _circuit(db, name, a_location_hid=room, **more), "Port", "100")
    db.commit()
    found = _report(client, viewer, fiscal_year=2027, by="site")
    (row,) = found["rows"]
    assert row["circuits"] == 2
    assert _listed(client, viewer, found, row) == {"Since 2020", "Ended in 2027"}
    assert _listed(client, viewer, found, found["totals"]) == {"Since 2020", "Ended in 2027"}


def test_a_carrier_that_bills_nothing_of_the_year_has_no_row(
    places: dict[str, Any], db: Session, client: TestClient, viewer: dict[str, str]
) -> None:
    carrier, lec = places["carrier"]["hid"], places["lec"]["hid"]
    circuit = _circuit(
        db, "Hub link", a_location_hid=places["hub_room"]["hid"], carrier_hid=carrier
    )
    db.add(
        CircuitCarrier(circuit_hid=circuit.hid, vendor_hid=lec, role="local_exchange", priority=1)
    )
    _line(db, circuit, "Port", "800")
    _line(db, circuit, "Old loop", "200", vendor_hid=lec, ends_on=date(2025, 12, 31))
    # Named as a carrier of another circuit, and billing nothing of it.
    named = _circuit(db, "Resold", a_location_hid=places["hub_room"]["hid"], carrier_hid=carrier)
    db.add(CircuitCarrier(circuit_hid=named.hid, vendor_hid=lec, role="local_exchange", priority=1))
    _line(db, named, "Port", "100")
    db.commit()
    found = _report(client, viewer, fiscal_year=2027, by="carrier")
    assert [(row["label"], row["circuits"]) for row in found["rows"]] == [("Example Telecom", 2)]
    assert _listed(client, viewer, found, found["rows"][0]) == {"Hub link", "Resold"}
    # In 2025 the local exchange carrier billed its loop, and only on the one circuit.
    earlier = _report(client, viewer, fiscal_year=2025, by="carrier")
    (lec_row,) = [row for row in earlier["rows"] if row["key"] == lec]
    assert (lec_row["circuits"], lec_row["cost"], lec_row["monthly_cost"]) == (
        1,
        "2400.00",
        "200.00",
    )
    assert _listed(client, viewer, earlier, lec_row) == {"Hub link"}


def test_a_retired_group_keeps_its_row_and_the_blank_row_lists_what_it_counted(
    places: dict[str, Any], db: Session, client: TestClient, viewer: dict[str, str]
) -> None:
    room = places["hub_room"]["hid"]
    grouped = _circuit(db, "Grouped", a_location_hid=room)
    loose = _circuit(db, "Loose", a_location_hid=room)
    for one in (grouped, loose):
        _line(db, one, "Port", "100")
    group = CircuitGroup(name="Old ring", name_key="old ring", record_status="retired")
    db.add(group)
    db.flush()
    db.add(CircuitGroupMember(group_hid=group.hid, circuit_hid=grouped.hid))
    db.commit()
    found = _report(client, viewer, fiscal_year=2027, by="group")
    rows = {row["label"]: row for row in found["rows"]}
    assert rows["Old ring"]["circuits"] == 1
    assert _listed(client, viewer, found, rows["Old ring"]) == {"Grouped"}
    assert _listed(client, viewer, found, rows[None]) == {"Loose"}


def test_a_draft_is_in_service_in_a_view_of_drafts(
    places: dict[str, Any], db: Session, make: Maker
) -> None:
    draft = _circuit(db, "Ordered", a_location_hid=places["hub_room"]["hid"], record_status="draft")
    _line(db, draft, "Port", "100")
    db.commit()
    listed = make.get("/circuits", include_drafts=True, filter="in_service:eq:true")
    assert [(one["name"], one["in_service"], one["monthly_cost"]) for one in listed["items"]] == [
        ("Ordered", True, "100.00")
    ]
    # Read by itself, in no view of drafts, it is not in service, and costs nothing yet.
    alone = make.get(f"/circuits/{draft.hid}")
    assert (alone["in_service"], alone["monthly_cost"]) == (False, "0.00")
    assert alone["costs"][0]["monthly_cost"] == "100.00"


def test_a_disconnected_circuit_costs_nothing_today(
    places: dict[str, Any], db: Session, make: Maker
) -> None:
    gone = _circuit(
        db,
        "Gone",
        a_location_hid=places["hub_room"]["hid"],
        activated_on=date(2019, 1, 1),
        disconnected_on=date(2021, 1, 31),
    )
    db.add(
        CircuitCost(
            circuit_hid=gone.hid,
            description="Port",
            description_key="port",
            monthly_cost=Decimal(1000),
        )
    )
    db.commit()
    record = make.get(f"/circuits/{gone.hid}")
    assert (record["in_service"], record["monthly_cost"], record["annual_cost"]) == (
        False,
        "0.00",
        "0.00",
    )
    assert make.get("/circuits", filter="monthly_cost:gt:0")["total"] == 0


def test_a_file_row_finds_a_circuit_by_its_primary_carriers_number_only(
    places: dict[str, Any], db: Session, make: Maker, client: TestClient
) -> None:
    carrier, lec = places["carrier"], places["lec"]
    circuit = _circuit(
        db,
        "Hub link",
        a_location_hid=places["hub_room"]["hid"],
        carrier_hid=carrier["hid"],
        carrier_circuit_number="EXT-1",
        carrier_number_key="ext-1",
        z_note="carrier network",
    )
    db.add(
        CircuitCarrier(
            circuit_hid=circuit.hid,
            vendor_hid=lec["hid"],
            role="local_exchange",
            circuit_number="LEC-1",
            circuit_number_key="lec-1",
            priority=1,
        )
    )
    db.commit()

    def preview(text: str) -> dict[str, Any]:
        response = client.post(
            f"{API}/imports/preview",
            params={"entity": "circuits", "mode": "upsert", "file_name": "circuits.csv"},
            content=text.encode(),
            headers={**make.headers, "Content-Type": "text/csv"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    found = preview("name,carrier,carrier_circuit_number,notes\nHub link,Example Telecom,EXT-1,x\n")
    assert (found["job"]["updated"], found["job"]["rejected"]) == (1, 0), found["rows"][0][
        "reasons"
    ]
    # The local exchange carrier's number, in the primary carrier's columns, finds nothing:
    # the row would be a new circuit, and is refused for the number the other one has.
    other = preview(
        "name,carrier,carrier_circuit_number,a_location,z_note\n"
        "Hub link,Northwind Exchange,LEC-1,Americas > Central > Hub > Room 1,carrier network\n"
    )
    assert (other["job"]["created"], other["job"]["rejected"]) == (0, 1)
    assert other["rows"][0]["record_hid"] is None, other["rows"][0]
    assert [reason["field"] for reason in other["rows"][0]["reasons"]] == ["carrier_circuit_number"]
    assert db.get(Circuit, circuit.hid) is not None
