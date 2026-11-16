"""The circuit commands of the command line (P-154), run against the application itself."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api import test_cli
from tests.api.test_circuits import Desk

# The fixture that runs `hirdir` against the test client.
run = test_cli.run


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def wired(desk: Desk) -> dict[str, Any]:
    """A circuit between two sites with a carrier, a local exchange carrier, two cost
    lines and a router, in a group, and a second circuit."""
    places = desk.places()
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    desk.owner("Network Engineering")
    entry = desk.entry(desk.vendor("Cisco"), pid="C8300-1N1S-6T")
    router = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R001", hostname="site2-rtr-01"
    )
    made = desk.circuit(
        "Site-2 to Site-3",
        enterprise_circuit_id="EC-0042",
        circuit_type="point_to_point",
        port_mbps="1000",
        down_mbps="200",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
        carrier_circuit_number="EXT/12345",
    )
    desk.part(
        made,
        "carriers",
        {"vendor_hid": exchange["hid"], "role": "local_exchange", "circuit_number": "LEC-1"},
    )
    desk.part(made, "costs", {"description": "Port", "monthly_cost": "850"})
    desk.part(
        made,
        "costs",
        {"description": "Local loop", "monthly_cost": "150", "vendor_hid": exchange["hid"]},
    )
    desk.part(made, "devices", {"devices": [{"item_hid": router["hid"], "side": "a"}]})
    second = desk.circuit(
        "Site-3 internet", a_location_hid=places["annex"]["hid"], z_note="carrier network"
    )
    group = desk.post("/circuit-groups", {"name": "Inter-site links"})
    return {"circuit": made, "second": second, "group": group, "places": places}


def test_a_circuit_is_shown_by_what_it_is_known_by_with_its_parts(run, wired: dict) -> None:
    for known_by in ("EC-0042", "Site-2 to Site-3", wired["circuit"]["hid"]):
        assert "EC-0042" in run("circuits", "show", known_by).output
    shown = run("circuits", "show", "ec-0042").output
    assert "speed:               1G / 200M / 1G" in shown
    assert "a_side:              Americas > Central > Site-2 > Building 1 > Room 102" in shown
    assert "counts_at:           Americas > Central > Site-2 (the A side)" in shown
    assert "carrier:             Example Telecom EXT/12345" in shown
    assert "carrier:             Example Local Exchange (local_exchange) LEC-1" in shown
    assert "device:              site2-rtr-01 on the A side" in shown
    assert "cost:                Local loop: 150.00 a month, billed by Example Local" in shown
    assert "monthly_cost:        1000.00" in shown
    assert "annual_cost:         12000.00" in shown
    run("circuits", "show", "EC-9999", expect=4)


def test_a_circuit_is_set_listed_retired_and_put_into_a_group(run, desk: Desk, wired: dict) -> None:
    said = run(
        "circuits", "set", "EC-0042", "cost_side=z", "owner=Network Engineering", "down_mbps="
    ).output
    assert "1G, counted at Americas > Central > Site-3 (the Z side), 1000.00 a month" in said
    changed = desk.again(wired["circuit"])
    assert (changed["cost_side"], changed["owner"]["label"], changed["down_mbps"]) == (
        "z",
        "Network Engineering",
        None,
    )
    run("circuits", "set", "EC-0042", "colour=blue", expect=2)
    run("circuits", "set", "EC-0042", "up_mbps=5000", expect=4)
    listed = run("circuits", "list", "--filter", "circuit_type:eq:point_to_point").output
    assert "Site-2 to Site-3" in listed
    assert "Site-3 internet" not in listed
    as_csv = run("circuits", "list", "--format", "csv", "--columns", "name,speed").output
    assert as_csv.splitlines()[1:] == [
        f"{wired['circuit']['hid']},Site-2 to Site-3,1G",
        f"{wired['second']['hid']},Site-3 internet,",
    ]

    added = run("circuit-groups", "add", "Inter-site links", "EC-0042", "Site-3 internet").output
    assert "Inter-site links: 2 added, 2 circuits in all" in added
    run("circuit-groups", "add", "Inter-site links", "EC-0042", expect=5)
    group = run("circuit-groups", "show", "Inter-site links").output
    assert "monthly_cost:        1000.00" in group
    assert "Site-3 internet" in group
    assert "Inter-site links" in run("circuit-groups", "list").output
    taken = run("circuit-groups", "remove", "Inter-site links", "Site-3 internet").output
    assert "1 taken out, 1 circuits in all" in taken
    run("circuit-groups", "remove", "Inter-site links", "Site-3 internet", expect=4)

    assert "Site-3 internet: retired" in run("circuits", "retire", "Site-3 internet").output
    assert "Site-3 internet" not in run("circuits", "list").output
