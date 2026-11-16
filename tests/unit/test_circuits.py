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
