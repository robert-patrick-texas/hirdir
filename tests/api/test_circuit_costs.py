"""What circuits cost by fiscal year (P-151): a part month as the carrier bills it, and
the rows by carrier, site, region and group, each circuit once in the totals."""

import csv
import io
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy.orm import Session

from hirdir.db.models import Circuit, CircuitCarrier, CircuitCost, CircuitGroup, CircuitGroupMember
from hirdir.io.circuit_costs import billed, circuit_costs, rounded
from tests.api import test_cli
from tests.api.inventory import Maker

YEAR_2027 = (date(2027, 1, 1), date(2027, 12, 31))


def test_a_part_month_counts_for_its_days_as_the_carrier_bills_it() -> None:
    # Activated on 10 April 2027 at 1,000 a month: May to December in full, and 21 of
    # April's 30 days.
    assert rounded(billed(Decimal(1000), date(2027, 4, 10), YEAR_2027[1], None, None)) == Decimal(
        "8700.00"
    )
    # Disconnected on 20 September as well: 21 of 30 in April, 20 of 30 in September.
    assert rounded(billed(Decimal(1000), date(2027, 4, 10), date(2027, 9, 20), None, None)) == (
        Decimal("5366.67")
    )
    # A whole year is twelve months whatever their lengths, February of a leap year too.
    assert billed(Decimal(1000), date(2028, 1, 1), date(2028, 12, 31), None, None) == 12000
    assert billed(Decimal(1000), date(2028, 2, 1), date(2028, 2, 29), None, None) == 1000
    # A line's own dates bound it as the service does.
    assert billed(Decimal(300), *YEAR_2027, date(2027, 7, 1), date(2027, 7, 31)) == 300
    assert billed(Decimal(300), *YEAR_2027, date(2028, 1, 1), None) == 0
    # A credit is below zero, and is counted the same way.
    assert billed(Decimal(-100), date(2027, 12, 17), YEAR_2027[1], None, None) == Fraction(
        -1500, 31
    )


def test_every_sum_is_rounded_once_half_up() -> None:
    assert rounded(Fraction(1, 200)) == Decimal("0.01")
    assert rounded(Fraction(-1, 200)) == Decimal("-0.01")
    assert rounded(Fraction(1, 3) * 3) == Decimal("1.00")


def _circuit(db: Session, name: str, **fields: Any) -> Circuit:
    circuit = Circuit(name=name, name_key=name.casefold(), **fields)
    db.add(circuit)
    db.flush()
    return circuit


def _line(db: Session, circuit: Circuit, description: str, monthly: str, **more: Any) -> None:
    db.add(
        CircuitCost(
            circuit_hid=circuit.hid,
            description=description,
            description_key=description.casefold(),
            monthly_cost=Decimal(monthly),
            **more,
        )
    )


@pytest.fixture
def places(make: Maker) -> dict[str, Any]:
    americas = make.region("Americas")
    central = make.region("Central", americas)
    east = make.region("East", americas)
    hub = make.site("Hub", central)
    branch = make.site("Branch", east)
    return {
        "americas": americas,
        "central": central,
        "east": east,
        "hub": hub,
        "branch": branch,
        "hub_room": make.location("Room 1", hub),
        "branch_room": make.location("Room 2", branch),
        "carrier": make.vendor("Example Telecom"),
        "lec": make.vendor("Northwind Exchange"),
    }


def _rows(found: Any) -> dict[str | None, tuple[int, str, str, str]]:
    return {
        row.label: (row.circuits, str(row.cost), str(row.monthly_cost), str(row.annual_cost))
        for row in found.rows
    }


def test_the_rows_by_carrier_site_region_and_group(places: dict[str, Any], db: Session) -> None:
    carrier, lec = places["carrier"]["hid"], places["lec"]["hid"]
    # Between the hub and the branch, counted at its A side, the hub, with a local
    # loop that the local exchange carrier bills.
    wan = _circuit(
        db,
        "Hub to branch",
        a_location_hid=places["hub_room"]["hid"],
        z_location_hid=places["branch_room"]["hid"],
        carrier_hid=carrier,
        activated_on=date(2020, 1, 1),
    )
    db.add(CircuitCarrier(circuit_hid=wan.hid, vendor_hid=lec, role="local_exchange", priority=1))
    _line(db, wan, "Port", "800")
    _line(db, wan, "Local loop", "200", vendor_hid=lec)
    # The branch's internet, its far end in the carrier's network: it counts at the
    # branch, its Z side, though its cost side is A.
    internet = _circuit(
        db,
        "Branch internet",
        a_note="carrier network",
        z_location_hid=places["branch_room"]["hid"],
        carrier_hid=carrier,
    )
    _line(db, internet, "Access", "500")
    group = CircuitGroup(name="Internet access", name_key="internet access")
    db.add(group)
    db.flush()
    db.add(CircuitGroupMember(group_hid=group.hid, circuit_hid=internet.hid))
    # Taken out with no disconnection: it counts nowhere.
    _circuit(db, "Mistake", a_location_hid=places["hub_room"]["hid"], record_status="retired")
    db.commit()

    by_carrier = circuit_costs(db, fiscal_year=2027)
    assert by_carrier.by == "carrier"
    assert str(by_carrier.totals.annual_cost) == "18000.00"
    assert by_carrier.totals.circuits == 2
    assert _rows(by_carrier) == {
        "Example Telecom": (2, "15600.00", "1300.00", "15600.00"),
        "Northwind Exchange": (1, "2400.00", "200.00", "2400.00"),
    }
    assert by_carrier.rows[0].filter == {
        "field": "carriers.vendor_hid",
        "op": "eq",
        "value": carrier,
    }
    by_site = circuit_costs(db, fiscal_year=2027, by="site")
    assert _rows(by_site) == {
        "Americas > Central > Hub": (1, "12000.00", "1000.00", "12000.00"),
        "Americas > East > Branch": (1, "6000.00", "500.00", "6000.00"),
    }
    # A region holds what is beneath it; the totals count each circuit once.
    by_region = circuit_costs(db, fiscal_year=2027, by="region")
    assert _rows(by_region)["Americas"] == (2, "18000.00", "1500.00", "18000.00")
    assert _rows(by_region)["Americas > East"] == (1, "6000.00", "500.00", "6000.00")
    by_group = circuit_costs(db, fiscal_year=2027, by="group")
    assert _rows(by_group) == {
        "Internet access": (1, "6000.00", "500.00", "6000.00"),
        None: (1, "12000.00", "1000.00", "12000.00"),
    }
    # Switched to count at the far end, the circuit between them counts at the branch.
    wan.cost_side = "z"
    db.commit()
    assert _rows(circuit_costs(db, fiscal_year=2027, by="site")) == {
        "Americas > East > Branch": (2, "18000.00", "1500.00", "18000.00")
    }


def test_a_year_counts_the_days_in_service_and_the_figure_of_its_day(
    places: dict[str, Any], db: Session
) -> None:
    room = places["hub_room"]["hid"]
    april = _circuit(db, "From April", a_location_hid=room, activated_on=date(2027, 4, 10))
    _line(db, april, "Port", "1000")
    ended = _circuit(
        db,
        "Ended in September",
        a_location_hid=room,
        activated_on=date(2026, 1, 1),
        disconnected_on=date(2027, 9, 20),
        record_status="retired",
    )
    _line(db, ended, "Port", "1000")
    ordered = _circuit(db, "Ordered", a_location_hid=room, record_status="draft")
    _line(db, ordered, "Port", "1000")
    db.commit()
    found = circuit_costs(db, fiscal_year=2027)
    # The monthly figure is that of the day the report is of: the first day of a year to
    # come, the last of one that is past. On either, one of the two is in service.
    assert found.as_of in (date(2027, 1, 1), date(2027, 12, 31)) or (
        date(2027, 1, 1) < found.as_of < date(2027, 12, 31)
    )
    if found.as_of in (date(2027, 1, 1), date(2027, 12, 31)):
        assert str(found.totals.monthly_cost) == "1000.00"
    assert found.totals.circuits == 2
    assert str(found.totals.cost) == str(Decimal("8700.00") + Decimal("8666.67"))
    with_drafts = circuit_costs(db, fiscal_year=2027, include_drafts=True)
    assert with_drafts.totals.circuits == 3
    assert str(with_drafts.totals.cost) == "29366.67"
    # A fiscal year that begins in July is named for the year it ends in.
    from hirdir.db.models import Setting

    db.add(Setting(key="fiscal_year_start_month", value=7))
    db.commit()
    july = circuit_costs(db, fiscal_year=2028)
    assert (july.starts_on, july.ends_on) == (date(2027, 7, 1), date(2028, 6, 30))


def test_a_grouping_the_report_does_not_know_is_refused(db: Session) -> None:
    from hirdir.domain.errors import Invalid

    with pytest.raises(Invalid):
        circuit_costs(db, by="colour")


def test_the_route_answers_the_report_to_any_role(
    places: dict[str, Any], db: Session, client: Any, viewer: dict[str, str]
) -> None:
    from tests.api.inventory import API

    circuit = _circuit(db, "Hub link", a_location_hid=places["hub_room"]["hid"])
    _line(db, circuit, "Port", "1000")
    _line(db, circuit, "Promotional credit", "-100")
    db.commit()
    response = client.get(
        f"{API}/reports/circuit-costs", params={"fiscal_year": 2027, "by": "site"}, headers=viewer
    )
    assert response.status_code == 200, response.text
    found = response.json()
    assert (found["fiscal_year"], found["starts_on"], found["by"]) == (2027, "2027-01-01", "site")
    assert found["totals"]["annual_cost"] == "10800.00"
    assert found["rows"][0]["label"] == "Americas > Central > Hub"
    assert found["rows"][0]["filter"] == {
        "field": "cost_site_hid",
        "op": "eq",
        "value": places["hub"]["hid"],
    }
    refused = client.get(f"{API}/reports/circuit-costs", params={"by": "colour"}, headers=viewer)
    assert refused.status_code == 422


run = test_cli.run


def test_the_command_line_prints_the_report(places: dict[str, Any], db: Session, run: Any) -> None:
    circuit = _circuit(db, "Hub link", a_location_hid=places["hub_room"]["hid"])
    _line(db, circuit, "Port", "1000")
    db.commit()
    printed = run("report", "circuit-costs", "--year", "2027", "--by", "site", "--format", "csv")
    rows = list(csv.reader(io.StringIO(printed.stdout)))
    assert rows[0] == ["site", "circuits", "cost", "monthly_cost", "annual_cost"]
    assert rows[1:] == [
        ["Americas > Central > Hub", "1", "12000.00", "1000.00", "12000.00"],
        ["total", "1", "12000.00", "1000.00", "12000.00"],
    ]
