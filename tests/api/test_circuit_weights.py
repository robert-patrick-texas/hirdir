"""The support weight of a circuit in force (P-141, P-155), as the merge of 0.8.0 wires
it into the circuit's record, its list and its files: its own, or the default of the
settings, raised to the minimum."""

from typing import Any

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker


def _setting(client: TestClient, admin: dict[str, str], key: str, value: Any) -> None:
    now = client.get(f"{API}/settings", headers=admin).json()
    (found,) = [one for one in now if one["key"] == key]
    response = client.put(
        f"{API}/settings/{key}",
        json={"row_version": found["row_version"], "value": value},
        headers=admin,
    )
    assert response.status_code == 200, response.text


def _circuit(make: Maker, name: str, **more: Any) -> dict[str, Any]:
    layout = make.layout()
    return make.post("/circuits", {"name": name, "a_location_hid": layout["room"]["hid"], **more})


def test_a_circuit_counts_at_the_default_and_is_raised_to_the_minimum(
    make: Maker, client: TestClient, admin: dict[str, str]
) -> None:
    circuit = _circuit(make, "Site-2 internet", z_note="carrier network")
    weight = make.get(f"/circuits/{circuit['hid']}")["effective"]["support_weight"]
    assert (weight["value"], weight["source"]) == (None, "none")
    _setting(client, admin, "default_circuit_weight", "2")
    weight = make.get(f"/circuits/{circuit['hid']}")["effective"]["support_weight"]
    assert (weight["value"], weight["source"], weight["raised_from"]) == ("2", "setting", None)
    # The list finds it by the weight it counts at.
    assert make.get("/circuits", filter="effective.support_weight:eq:2")["total"] == 1
    _setting(client, admin, "minimum_circuit_weight", "3")
    weight = make.get(f"/circuits/{circuit['hid']}")["effective"]["support_weight"]
    assert (weight["value"], weight["source"], weight["raised_from"]) == ("3", "setting", "2")
    # A weight of its own below the minimum is raised too, and says so.
    now = make.get(f"/circuits/{circuit['hid']}")
    make.patch(
        f"/circuits/{circuit['hid']}", {"row_version": now["row_version"], "support_weight": "1"}
    )
    weight = make.get(f"/circuits/{circuit['hid']}")["effective"]["support_weight"]
    assert (weight["value"], weight["source"], weight["raised_from"]) == ("3", "own", "1")


def test_a_file_that_holds_the_default_leaves_a_circuit_inheriting(
    make: Maker, client: TestClient, admin: dict[str, str]
) -> None:
    circuit = _circuit(make, "Site-2 internet", z_note="carrier network")
    _setting(client, admin, "default_circuit_weight", "2")
    exported = client.post(
        f"{API}/exports",
        json={"entity": "circuits", "format": "csv", "include_sources": True},
        headers=make.headers,
    )
    assert exported.status_code == 200, exported.text
    lines = exported.text.splitlines()
    header = lines[0].split(",")
    row = dict(zip(header, lines[1].split(","), strict=False))
    assert (row["support_weight"], row["support_weight_source"]) == ("2", "setting")
    preview = client.post(
        f"{API}/imports/preview",
        params={"entity": "circuits", "mode": "upsert", "file_name": "circuits.csv"},
        content=exported.text.encode(),
        headers={**make.headers, "Content-Type": "text/csv"},
    )
    assert preview.status_code == 201, preview.text
    assert preview.json()["job"]["unchanged"] == 1
    assert make.get(f"/circuits/{circuit['hid']}")["support_weight"] is None
