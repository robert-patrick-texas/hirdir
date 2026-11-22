"""Groups of circuits (P-152): circuits that may land at different sites, looked at and
costed together, each circuit once."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import errors
from tests.api.test_circuits import Desk


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def three(desk: Desk) -> dict[str, dict[str, Any]]:
    """Three circuits at two sites, each with a line of cost, one not in service yet."""
    places = desk.places()
    made = {
        "internet": desk.circuit(
            "Site-2 internet", a_location_hid=places["room"]["hid"], z_note="carrier network"
        ),
        "cloud": desk.circuit(
            "Site-3 cloud on-ramp", a_location_hid=places["annex"]["hid"], z_note="cloud on-ramp"
        ),
        "later": desk.circuit(
            "Site-3 internet",
            a_location_hid=places["annex"]["hid"],
            z_note="carrier network",
            a_activated_on="2999-01-01",
        ),
    }
    for name, cost in (("internet", "1000.00"), ("cloud", "250.50"), ("later", "400.00")):
        desk.part(made[name], "costs", {"description": "Port", "monthly_cost": cost})
    return made


def _add(desk: Desk, group: dict[str, Any], *circuits: dict[str, Any], expect: int = 201) -> Any:
    return desk.post(
        f"/circuit-groups/{group['hid']}/members",
        {"circuit_hids": [one["hid"] for one in circuits]},
        expect,
    )


def test_a_group_holds_circuits_each_once_and_costs_them_as_one_sum(
    desk: Desk, three: dict[str, dict[str, Any]]
) -> None:
    owner = desk.owner("Network Engineering")
    group = desk.post(
        "/circuit-groups",
        {"name": "Internet access", "description": "Every way out", "owner_hid": owner["hid"]},
    )
    assert (group["circuits"], group["in_service"], group["monthly_cost"]) == (0, 0, "0.00")
    added = _add(desk, group, three["internet"], three["cloud"], three["later"])
    assert [one["circuit"]["name"] for one in added] == [
        "Site-2 internet",
        "Site-3 cloud on-ramp",
        "Site-3 internet",
    ]
    shown = desk.get(f"/circuit-groups/{group['hid']}")
    # What those in service cost today, each once: the one that is not active yet is not.
    assert (shown["circuits"], shown["in_service"]) == (3, 2)
    assert (shown["monthly_cost"], shown["annual_cost"]) == ("1250.50", "15006.00")
    assert shown["owner"]["label"] == "Network Engineering"
    # A circuit is in one group once, and in any number of groups.
    assert "circuit_hids" in errors(_add(desk, group, three["cloud"], expect=409))
    assert "circuit_hids" in errors(_add(desk, group, three["cloud"], three["cloud"], expect=422))
    cloud = desk.post("/circuit-groups", {"name": "Cloud on-ramps"})
    _add(desk, cloud, three["cloud"])
    assert [one["name"] for one in desk.again(three["cloud"])["groups"]] == [
        "Cloud on-ramps",
        "Internet access",
    ]
    assert "name" in errors(desk.post("/circuit-groups", {"name": "internet ACCESS"}, 409))
    members = desk.get(f"/circuit-groups/{group['hid']}/members", limit=2)
    assert (members["total"], len(members["items"])) == (3, 2)
    assert members["items"][0]["circuit"]["monthly_cost"] == "1000.00"
    # The list finds a circuit by any of its groups, and sorts by the first of them.
    assert desk.names(filter="groups.name:eq:cloud on-ramps") == ["Site-3 cloud on-ramp"]
    assert desk.names(filter=f"groups.hid:eq:{group['hid']}") == [
        "Site-2 internet",
        "Site-3 cloud on-ramp",
        "Site-3 internet",
    ]
    assert desk.names(filter="groups.name:empty:true") == []
    # The list of groups filters and sorts by how many circuits each has and their cost.
    assert desk.names("/circuit-groups", sort="-monthly_cost") == [
        "Internet access",
        "Cloud on-ramps",
    ]
    assert desk.names("/circuit-groups", filter="circuits:gt:1") == ["Internet access"]
    assert desk.names("/circuit-groups", filter="owner.label:eq:network engineering") == [
        "Internet access"
    ]
    assert desk.names("/circuit-groups", sort="annual_cost") == [
        "Cloud on-ramps",
        "Internet access",
    ]
    # A membership is removed outright, with an audit event that holds what it was.
    internet = next(one for one in members["items"] if one["circuit"]["name"] == "Site-2 internet")
    desk.delete(f"/circuit-groups/{group['hid']}/members/{internet['hid']}")
    removed = desk.audit(record_type="circuit_group_member", record_hid=internet["hid"])[0]
    assert removed["action"] == "delete"
    assert {"field": "circuit_hid", "old": three["internet"]["hid"], "new": None} in removed[
        "changes"
    ]
    assert desk.get(f"/circuit-groups/{group['hid']}")["monthly_cost"] == "250.50"


def test_a_retired_circuit_stays_in_its_groups_and_is_added_to_none(
    desk: Desk, three: dict[str, dict[str, Any]]
) -> None:
    group = desk.post("/circuit-groups", {"name": "Internet access"})
    _add(desk, group, three["internet"])
    circuit = desk.again(three["internet"])
    desk.post(f"/circuits/{circuit['hid']}/retire", {"row_version": circuit["row_version"]}, 200)
    listed = desk.get(f"/circuit-groups/{group['hid']}/members")["items"]
    assert [(one["circuit"]["name"], one["circuit"]["record_status"]) for one in listed] == [
        ("Site-2 internet", "retired")
    ]
    assert desk.get(f"/circuit-groups/{group['hid']}")["in_service"] == 0
    other = desk.post("/circuit-groups", {"name": "Everything"})
    assert "circuit_hids" in errors(_add(desk, other, three["internet"], expect=422))
    # A retired group takes no new circuit, and stays readable.
    retired = desk.post(
        f"/circuit-groups/{other['hid']}/retire", {"row_version": other["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    assert "circuit_hids" in errors(_add(desk, other, three["cloud"], expect=422))
    assert desk.names("/circuit-groups") == ["Internet access"]
    assert desk.names("/circuit-groups", include_archived=True) == ["Everything", "Internet access"]
    back = desk.patch(
        f"/circuit-groups/{other['hid']}",
        {"row_version": retired["row_version"], "record_status": "active", "tags": []},
    )
    assert back["record_status"] == "active"
    assert desk.audit(record_type="circuit_group", record_hid=other["hid"])[0]["action"] == "update"
