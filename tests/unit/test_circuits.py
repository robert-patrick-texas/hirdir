"""What is worked out when a circuit is read (P-146, P-150): its speed written short, the
rate in force each way, the cost of its lines on a day, and the side it counts at."""

from datetime import date
from decimal import Decimal

import pytest

from hirdir.db.models import Circuit, CircuitCost
from hirdir.domain import circuit_records, circuits, weights


def _circuit(**fields: object) -> Circuit:
    return Circuit(name="A circuit", cost_side="a", record_status="active", **fields)


@pytest.mark.parametrize(
    ("port", "down", "up", "shown"),
    [
        ("1000", None, None, "1G"),
        ("1000", "200", "200", "1G / 200M"),
        ("1000", "200", "20", "1G / 200M / 20M"),
        ("1000", "200", None, "1G / 200M / 1G"),
        ("10000", None, None, "10G"),
        ("1500", None, None, "1500M"),
        ("100", "2.5", "2.5", "100M / 2.5M"),
        ("0.5", None, None, "500k"),
        ("1", "0.25", "0.06", "1M / 250k / 60k"),
    ],
)
def test_the_speed_is_written_short(
    port: str, down: str | None, up: str | None, shown: str
) -> None:
    circuit = _circuit(
        port_mbps=Decimal(port),
        down_mbps=Decimal(down) if down else None,
        up_mbps=Decimal(up) if up else None,
    )
    assert circuit_records.speed(circuit) == shown


def test_a_circuit_with_no_port_has_no_speed_and_no_rate() -> None:
    circuit = _circuit()
    assert circuit_records.speed(circuit) is None
    assert {name: one.source for name, one in circuit_records.rates_in_force(circuit).items()} == {
        "down_mbps": "none",
        "up_mbps": "none",
    }


def test_a_blank_rate_is_the_full_rate_of_the_port() -> None:
    rates = circuit_records.rates_in_force(
        _circuit(port_mbps=Decimal(1000), down_mbps=Decimal(200))
    )
    assert (rates["down_mbps"].value, rates["down_mbps"].source) == (Decimal(200), "own")
    assert (rates["up_mbps"].value, rates["up_mbps"].source) == (Decimal(1000), "port")


def test_the_monthly_cost_is_the_sum_of_the_lines_billed_that_day() -> None:
    lines = [
        CircuitCost(description="Port", monthly_cost=Decimal("850.00")),
        CircuitCost(
            description="Credit", monthly_cost=Decimal("-50.00"), ends_on=date(2027, 3, 31)
        ),
        CircuitCost(
            description="New rate", monthly_cost=Decimal("100"), starts_on=date(2027, 4, 1)
        ),
    ]
    assert circuit_records.monthly_cost(lines, date(2027, 3, 31)) == Decimal("800.00")
    assert circuit_records.monthly_cost(lines, date(2027, 4, 1)) == Decimal("950.00")
    assert circuit_records.monthly_cost([], date(2027, 4, 1)) == Decimal("0.00")


def test_a_circuit_counts_at_the_side_it_names_or_at_the_other_where_that_has_no_location() -> None:
    both = _circuit(a_location_hid="a-place", z_location_hid="z-place")
    assert circuits.cost_location_hid(both) == "a-place"
    both.cost_side = "z"
    assert circuits.cost_location_hid(both) == "z-place"
    far_end = _circuit(a_location_hid=None, z_location_hid="z-place")
    assert circuits.cost_location_hid(far_end) == "z-place"


def test_a_weight_of_its_own_is_in_force_and_none_is_none() -> None:
    figures = weights.Figures()
    weighed = weights.of_circuit(_circuit(support_weight=Decimal("1.5")), figures)
    assert (weighed.value, weighed.source) == (Decimal("1.5"), "own")
    assert weights.of_circuit(_circuit(), figures).source == "none"


# --- the dates of each side (P-317, P-320) -------------------------------------------


def test_a_blank_date_of_the_z_side_is_read_as_the_a_sides_never_copied() -> None:
    circuit = _circuit(
        a_installed_on=date(2027, 3, 29),
        a_activated_on=date(2027, 4, 10),
        z_installed_on=date(2027, 4, 2),
    )
    found = circuits.z_dates_in_force(circuit)
    assert {name: (one.value, one.source) for name, one in found.items()} == {
        "z_installed_on": (date(2027, 4, 2), "own"),
        "z_activated_on": (date(2027, 4, 10), "a_side"),
        "z_disconnected_on": (None, "none"),
    }
    # Nothing is written: the Z side's own activation stays blank.
    assert circuit.z_activated_on is None
    assert circuits.side_dates(circuit, "z") == (date(2027, 4, 2), date(2027, 4, 10), None)
    assert circuits.side_dates(circuit, "a") == (date(2027, 3, 29), date(2027, 4, 10), None)


def test_the_side_cost_side_names_decides_whether_a_circuit_is_in_service() -> None:
    # The A side is activated on 10 April and the Z side, of its own, on 17 April.
    dates = {"a_activated_on": date(2027, 4, 10), "z_activated_on": date(2027, 4, 17)}
    by_a, by_z = _circuit(**dates), _circuit(**dates)
    by_z.cost_side = "z"
    assert circuits.in_service_on(by_a, date(2027, 4, 12)) is True
    assert circuits.in_service_on(by_z, date(2027, 4, 12)) is False
    assert circuits.in_service_on(by_z, date(2027, 4, 17)) is True
    # The Z side's disconnection, blank, is the A side's: both end on 30 June.
    by_a.a_disconnected_on = by_z.a_disconnected_on = date(2027, 6, 30)
    assert circuits.in_service_on(by_z, date(2027, 7, 1)) is False
    assert circuits.deciding_dates(by_z) == (date(2027, 4, 17), date(2027, 6, 30))
    # A Z side that ends later keeps a circuit counted by it in service after the A side.
    by_z.z_disconnected_on = date(2027, 7, 15)
    assert circuits.in_service_on(by_z, date(2027, 7, 1)) is True
    assert circuits.in_service_on(by_a, date(2027, 7, 1)) is False
    # Retired, it was in service until the disconnection of the side that decides.
    by_z.record_status = "retired"
    assert circuits.in_service_on(by_z, date(2027, 7, 10)) is True
    assert circuits.in_service_on(by_z, date(2027, 7, 16)) is False


def test_a_circuit_counted_at_its_z_side_with_no_dates_there_is_read_as_before() -> None:
    # As every circuit of cost_side z was before 0.9.18, which gave the Z side none.
    circuit = _circuit(a_activated_on=date(2027, 4, 10), a_disconnected_on=date(2027, 9, 20))
    circuit.cost_side = "z"
    assert circuits.deciding_dates(circuit) == (date(2027, 4, 10), date(2027, 9, 20))
    assert circuits.in_service_on(circuit, date(2027, 4, 9)) is False
    assert circuits.in_service_on(circuit, date(2027, 9, 20)) is True
