"""Circuits and their parts (P-145 to P-148, P-150): the record, its sides and its speed,
its carriers and their numbers, its cost lines, the devices it connects, and the rules
that hold them together."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

NOBODY = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"


class Desk(Maker):
    """Makes circuits and what they name, as one signed-in user."""

    def places(self) -> dict[str, dict[str, Any]]:
        """Make `Americas > Central` with Site-2 and Site-3, a building in each, and a
        room in the building of Site-2."""
        found = self.layout()
        found["site3"] = self.site("Site-3", found["central"])
        found["annex"] = self.location("Annex", found["site3"], kind="building")
        return found

    def circuit(self, name: str, expect: int = 201, **fields: Any) -> dict[str, Any]:
        return self.post("/circuits", {"name": name, **fields}, expect)

    def part(
        self, circuit: dict[str, Any], kind: str, body: dict[str, Any], expect: int = 201
    ) -> Any:
        return self.post(f"/circuits/{circuit['hid']}/{kind}", body, expect)

    def again(self, circuit: dict[str, Any]) -> dict[str, Any]:
        return self.get(f"/circuits/{circuit['hid']}")

    def names(self, path: str = "/circuits", **params: Any) -> list[str]:
        return [row["name"] for row in self.get(path, **params)["items"]]

    def refused_delete(self, path: str, expect: int) -> dict[str, Any]:
        response = self.client.delete(API + path, headers=self.headers)
        assert response.status_code == expect, response.text
        return response.json()


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def places(desk: Desk) -> dict[str, dict[str, Any]]:
    return desk.places()


def test_a_circuit_answers_its_sides_its_speed_and_the_site_it_counts_at(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    telecom = desk.vendor("Example Telecom")
    made = desk.circuit(
        "Site-2 internet",
        enterprise_circuit_id="EC-0042",
        circuit_type="internet",
        port_mbps="1000",
        down_mbps="200",
        up_mbps="20",
        a_note="carrier network",
        z_location_hid=places["building"]["hid"],
        carrier_hid=telecom["hid"],
        carrier_circuit_number="EXT/12345/000/EXTL",
        billing_account="BA-0001",
        tags=[],
    )
    assert made["speed"] == "1G / 200M / 20M"
    assert (made["port_mbps"], made["down_mbps"], made["up_mbps"]) == ("1000.00", "200.00", "20.00")
    assert made["effective"]["down_mbps"] == {
        "value": "200.00",
        "source": "own",
        "source_hid": None,
    }
    assert made["a_side"] is None
    assert made["z_side"]["path"] == "Americas > Central > Site-2 > Building 1"
    assert made["z_side"]["site_hid"] == places["site"]["hid"]
    assert made["z_side"]["region_hid"] == places["central"]["hid"]
    # It counts at its A side unless switched, and the A side has no location: the other.
    assert made["cost_side"] == "a"
    assert made["cost_site_hid"] == places["site"]["hid"]
    assert made["cost_site_path"] == "Americas > Central > Site-2"
    assert made["carrier"] == {"hid": telecom["hid"], "name": "Example Telecom"}
    assert made["production"] is True
    assert made["in_service"] is True
    assert (made["monthly_cost"], made["annual_cost"]) == ("0.00", "0.00")
    assert made["effective"]["support_weight"] == {
        "value": None,
        "source": "none",
        "source_hid": None,
        "raised_from": None,
    }
    assert (made["carriers"], made["costs"], made["devices"], made["groups"]) == ([], [], [], [])
    assert desk.audit(record_type="circuit", record_hid=made["hid"])[0]["action"] == "create"

    # A rate left blank is the full rate of the port, and says so.
    full = desk.circuit(
        "Site-3 uplink",
        port_mbps="10000",
        a_location_hid=places["annex"]["hid"],
        z_note="cloud on-ramp",
        support_weight="1.5",
    )
    assert full["speed"] == "10G"
    assert full["effective"]["up_mbps"] == {
        "value": "10000.00",
        "source": "port",
        "source_hid": None,
    }
    assert full["effective"]["support_weight"]["value"] == "1.5"
    one_way = desk.patch(
        f"/circuits/{full['hid']}", {"row_version": full["row_version"], "down_mbps": "500"}
    )
    assert one_way["speed"] == "10G / 500M / 10G"
    both = desk.patch(
        f"/circuits/{full['hid']}", {"row_version": one_way["row_version"], "up_mbps": "500"}
    )
    assert both["speed"] == "10G / 500M"
    slow = desk.patch(
        f"/circuits/{full['hid']}",
        {
            "row_version": both["row_version"],
            "port_mbps": "0.5",
            "down_mbps": None,
            "up_mbps": None,
        },
    )
    assert slow["speed"] == "500k"


def test_what_a_circuit_refuses(desk: Desk, places: dict[str, dict[str, Any]]) -> None:
    room = places["room"]["hid"]
    telecom = desk.vendor("Example Telecom")
    # At least one side is a location, and a side with none says where it ends.
    both = errors(desk.circuit("Nowhere", 422, a_note="carrier network", z_note="cloud"))
    assert set(both) >= {"a_location_hid", "z_location_hid"}
    assert "z_note" in errors(desk.circuit("No note", 422, a_location_hid=room))
    # A rate needs a port speed and is not above it.
    assert "down_mbps" in errors(
        desk.circuit("No port", 422, a_location_hid=room, z_note="x", down_mbps="100")
    )
    assert "up_mbps" in errors(
        desk.circuit(
            "Too fast", 422, a_location_hid=room, z_note="x", port_mbps="100", up_mbps="200"
        )
    )
    assert "port_mbps" in errors(
        desk.circuit("Stopped", 422, a_location_hid=room, z_note="x", port_mbps="0")
    )
    # No activation before the installation, no disconnection before the activation.
    assert "a_activated_on" in errors(
        desk.circuit(
            "Early",
            422,
            a_location_hid=room,
            z_note="x",
            a_installed_on="2027-04-10",
            a_activated_on="2027-04-01",
        )
    )
    assert "a_disconnected_on" in errors(
        desk.circuit(
            "Gone early",
            422,
            a_location_hid=room,
            z_note="x",
            a_activated_on="2027-04-10",
            a_disconnected_on="2027-04-09",
        )
    )
    # A carrier's number needs its carrier.
    assert "carrier_circuit_number" in errors(
        desk.circuit("Numbered", 422, a_location_hid=room, z_note="x", carrier_circuit_number="N1")
    )
    # The type is a value of its list.
    assert "circuit_type" in errors(
        desk.circuit("Typed", 422, a_location_hid=room, z_note="x", circuit_type="satellite")
    )
    assert "a_location_hid" in errors(desk.circuit("Lost", 422, a_location_hid=NOBODY, z_note="x"))
    # The enterprise's ID is unique without regard to case, and so is a carrier's number
    # with its carrier.
    first = desk.circuit(
        "First",
        a_location_hid=room,
        z_note="x",
        enterprise_circuit_id="EC-0001",
        carrier_hid=telecom["hid"],
        carrier_circuit_number="ABC-1",
    )
    assert "enterprise_circuit_id" in errors(
        desk.circuit(
            "Second", 409, a_location_hid=room, z_note="x", enterprise_circuit_id="ec-0001"
        )
    )
    assert "carrier_circuit_number" in errors(
        desk.circuit(
            "Third",
            409,
            a_location_hid=room,
            z_note="x",
            carrier_hid=telecom["hid"],
            carrier_circuit_number="abc-1",
        )
    )
    # Another carrier may give the same number.
    other = desk.vendor("Northwind Fiber")
    desk.circuit(
        "Fourth",
        a_location_hid=room,
        z_note="x",
        carrier_hid=other["hid"],
        carrier_circuit_number="ABC-1",
    )
    # A stale copy is refused.
    desk.patch(f"/circuits/{first['hid']}", {"row_version": first["row_version"], "notes": "a"})
    desk.patch(
        f"/circuits/{first['hid']}", {"row_version": first["row_version"], "notes": "b"}, 409
    )


def test_a_side_is_not_given_a_retired_location_and_a_location_with_a_circuit_stays(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    annex = places["annex"]
    shed = desk.location("Shed", places["site3"], kind="building")
    desk.post(f"/locations/{shed['hid']}/retire", {"row_version": shed["row_version"]}, 200)
    assert "z_location_hid" in errors(
        desk.circuit("To the shed", 422, a_location_hid=annex["hid"], z_location_hid=shed["hid"])
    )
    made = desk.circuit("Annex uplink", a_location_hid=annex["hid"], z_note="carrier network")
    # The location is not retired while a circuit that is not retired has a side there.
    refused = desk.post(
        f"/locations/{annex['hid']}/retire", {"row_version": annex["row_version"]}, 409
    )
    assert "1 circuit" in refused["detail"]
    retired = desk.post(
        f"/circuits/{made['hid']}/retire", {"row_version": made["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    assert retired["in_service"] is False
    gone = desk.post(
        f"/locations/{annex['hid']}/retire", {"row_version": annex["row_version"]}, 200
    )
    assert gone["record_status"] == "retired"
    # Nor is a circuit brought back to a side whose location has been retired since.
    assert "record_status" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": retired["row_version"], "record_status": "active"},
            422,
        )
    )
    assert desk.names() == []
    assert desk.names(include_archived=True) == ["Annex uplink"]


def test_a_new_circuit_counts_at_the_side_the_setting_gives_and_keeps_it(
    desk: Desk, places: dict[str, dict[str, Any]], client: TestClient, admin: dict[str, str]
) -> None:
    room, annex = places["room"]["hid"], places["annex"]["hid"]
    before = desk.circuit("Before", a_location_hid=room, z_location_hid=annex)
    assert (before["cost_side"], before["cost_site_hid"]) == ("a", places["site"]["hid"])
    setting = next(
        one for one in Maker(client, admin).get("/settings") if one["key"] == "circuit_cost_side"
    )
    assert (setting["value"], setting["default"]) == ("a", "a")
    Maker(client, admin).client.put(
        f"{API}/settings/circuit_cost_side",
        json={"row_version": setting["row_version"], "value": "z"},
        headers=admin,
    ).raise_for_status()
    after = desk.circuit("After", a_location_hid=room, z_location_hid=annex)
    assert (after["cost_side"], after["cost_site_hid"]) == ("z", places["site3"]["hid"])
    # A circuit that exists keeps its own, and any may be switched.
    assert desk.again(before)["cost_side"] == "a"
    named = desk.circuit("Named", a_location_hid=room, z_location_hid=annex, cost_side="a")
    assert named["cost_side"] == "a"
    switched = desk.patch(
        f"/circuits/{before['hid']}", {"row_version": before["row_version"], "cost_side": "z"}
    )
    assert switched["cost_site_hid"] == places["site3"]["hid"]
    assert "cost_side" in errors(
        desk.patch(
            f"/circuits/{before['hid']}",
            {"row_version": switched["row_version"], "cost_side": None},
            422,
        )
    )


def test_an_owner_outside_the_team_marks_the_circuit(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    owner = desk.owner("Example Partner", is_external=True, exception_reason="Run by the partner")
    made = desk.circuit(
        "Partner fiber", a_location_hid=places["room"]["hid"], z_note="x", owner_hid=owner["hid"]
    )
    assert made["owner"]["label"] == "Example Partner"
    assert (made["owner_exception"], made["owner_exception_reason"]) == (True, "Run by the partner")
    assert desk.names(filter="owner_exception:eq:true") == ["Partner fiber"]
    assert desk.names(filter="owner.label:eq:example partner") == ["Partner fiber"]


def test_carriers_beside_the_primary_one_each_once_with_a_number_unique_with_its_carrier(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    xconnect = desk.vendor("Example Colocation")
    made = desk.circuit(
        "Site-2 to Site-3",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
        carrier_circuit_number="T-100",
    )
    lec = desk.part(
        made,
        "carriers",
        {"vendor_hid": exchange["hid"], "role": "local_exchange", "circuit_number": "LEC-778-0001"},
    )
    assert (lec["vendor"], lec["role"], lec["priority"]) == (
        "Example Local Exchange",
        "local_exchange",
        1,
    )
    colo = desk.part(made, "carriers", {"vendor_hid": xconnect["hid"], "role": "cross_connect"})
    assert colo["priority"] == 2
    # A vendor is named once on a circuit, the primary among them.
    assert "vendor_hid" in errors(
        desk.part(made, "carriers", {"vendor_hid": telecom["hid"], "role": "other"}, 409)
    )
    assert "vendor_hid" in errors(
        desk.part(made, "carriers", {"vendor_hid": exchange["hid"], "role": "other"}, 409)
    )
    assert "role" in errors(
        desk.part(
            made, "carriers", {"vendor_hid": desk.vendor("Spare")["hid"], "role": "boss"}, 422
        )
    )
    # A carrier's number is unique with that carrier, in both places.
    second = desk.circuit("Second", a_location_hid=places["room"]["hid"], z_note="x")
    assert "circuit_number" in errors(
        desk.part(
            second,
            "carriers",
            {
                "vendor_hid": exchange["hid"],
                "role": "local_exchange",
                "circuit_number": "lec-778-0001",
            },
            409,
        )
    )
    assert "circuit_number" in errors(
        desk.part(
            second,
            "carriers",
            {"vendor_hid": telecom["hid"], "role": "last_mile", "circuit_number": "t-100"},
            409,
        )
    )
    assert "carrier_circuit_number" in errors(
        desk.patch(
            f"/circuits/{second['hid']}",
            {
                "row_version": second["row_version"],
                "carrier_hid": exchange["hid"],
                "carrier_circuit_number": "LEC-778-0001",
            },
            409,
        )
    )
    # Nor is the primary carrier one of the others.
    again = desk.again(made)
    assert "carrier_hid" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": again["row_version"], "carrier_hid": exchange["hid"]},
            409,
        )
    )
    assert [one["vendor"] for one in again["carriers"]] == [
        "Example Local Exchange",
        "Example Colocation",
    ]
    listed = desk.get(f"/circuits/{made['hid']}/carriers")
    assert listed["total"] == 2
    moved = desk.patch(
        f"/circuits/{made['hid']}/carriers/{colo['hid']}",
        {"row_version": colo["row_version"], "priority": 1},
    )
    assert moved["priority"] == 1
    assert moved["row_version"] == colo["row_version"] + 1
    # One that was a mistake is removed outright, and the audit event holds what it was.
    desk.delete(f"/circuits/{made['hid']}/carriers/{colo['hid']}")
    removed = desk.audit(record_type="circuit_carrier", record_hid=colo["hid"])[0]
    assert removed["action"] == "delete"
    assert {"field": "vendor_hid", "old": xconnect["hid"], "new": None} in removed["changes"]
    desk.delete(f"/circuits/{made['hid']}/carriers/{colo['hid']}", 404)
    # A retired circuit takes no new part.
    retired = desk.post(
        f"/circuits/{second['hid']}/retire", {"row_version": desk.again(second)["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    assert "circuit_hid" in errors(
        desk.part(second, "carriers", {"vendor_hid": xconnect["hid"], "role": "cross_connect"}, 422)
    )


def test_the_monthly_cost_is_the_sum_of_the_lines_in_date_and_the_annual_twelve_times(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    stranger = desk.vendor("Somebody Else")
    made = desk.circuit(
        "Site-2 internet",
        a_location_hid=places["room"]["hid"],
        z_note="carrier network",
        carrier_hid=telecom["hid"],
    )
    desk.part(made, "carriers", {"vendor_hid": exchange["hid"], "role": "local_exchange"})
    port = desk.part(made, "costs", {"description": "Port", "monthly_cost": "850.00"})
    assert (port["vendor_hid"], port["in_date"]) == (None, True)
    loop = desk.part(
        made,
        "costs",
        {"description": "Local loop", "monthly_cost": "200", "vendor_hid": exchange["hid"]},
    )
    assert loop["vendor"] == "Example Local Exchange"
    desk.part(made, "costs", {"description": "Promotional credit", "monthly_cost": "-50.00"})
    # A line that ended, or begins later, is not billed today.
    desk.part(
        made, "costs", {"description": "Old rate", "monthly_cost": "999", "ends_on": "2020-01-31"}
    )
    desk.part(
        made,
        "costs",
        {"description": "Next rate", "monthly_cost": "999", "starts_on": "2999-01-01"},
    )
    shown = desk.again(made)
    assert (shown["monthly_cost"], shown["annual_cost"]) == ("1000.00", "12000.00")
    assert [line["description"] for line in shown["costs"]] == [
        "Local loop",
        "Next rate",
        "Old rate",
        "Port",
        "Promotional credit",
    ]
    assert desk.names(filter="monthly_cost:eq:1000") == ["Site-2 internet"]
    assert desk.names(filter="annual_cost:gt:11999") == ["Site-2 internet"]
    # The description is unique within the circuit, and a line is billed by a carrier of it.
    assert "description" in errors(
        desk.part(made, "costs", {"description": "port", "monthly_cost": "1"}, 409)
    )
    assert "vendor_hid" in errors(
        desk.part(
            made,
            "costs",
            {"description": "Access", "monthly_cost": "1", "vendor_hid": stranger["hid"]},
            422,
        )
    )
    assert "ends_on" in errors(
        desk.part(
            made,
            "costs",
            {
                "description": "Backwards",
                "monthly_cost": "1",
                "starts_on": "2027-02-01",
                "ends_on": "2027-01-01",
            },
            422,
        )
    )
    # A carrier that a line names is not removed, nor the primary replaced, while it does.
    lec = shown["carriers"][0]
    assert "vendor_hid" in errors(
        desk.refused_delete(f"/circuits/{made['hid']}/carriers/{lec['hid']}", 409)
    )
    named = desk.patch(
        f"/circuits/{made['hid']}/costs/{port['hid']}",
        {"row_version": port["row_version"], "vendor_hid": telecom["hid"]},
    )
    assert named["vendor"] == "Example Telecom"
    assert "carrier_hid" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": shown["row_version"], "carrier_hid": stranger["hid"]},
            422,
        )
    )
    # A new rate is a line that ends and one that begins.
    ended = desk.patch(
        f"/circuits/{made['hid']}/costs/{loop['hid']}",
        {"row_version": loop["row_version"], "ends_on": "2021-12-31"},
    )
    assert ended["in_date"] is False
    assert desk.again(made)["monthly_cost"] == "800.00"
    desk.delete(f"/circuits/{made['hid']}/costs/{loop['hid']}")
    desk.delete(f"/circuits/{made['hid']}/carriers/{lec['hid']}")
    removed = desk.audit(record_type="circuit_cost", record_hid=loop["hid"])[0]
    assert {"field": "monthly_cost", "old": "200", "new": None} in removed["changes"]


def test_the_devices_of_a_circuit_and_the_circuits_of_a_device(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    entry = desk.entry(desk.vendor("Cisco"), pid="C8300-1N1S-6T")
    router_a = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R001", hostname="site2-rtr-01"
    )
    router_z = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R002", hostname="site3-rtr-01"
    )
    pair = desk.group("site3-rtr-pair", "cluster", [(router_z, "active")])
    made = desk.circuit(
        "Site-2 to Site-3",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
    )
    connected = desk.part(
        made,
        "devices",
        {
            "devices": [
                {"item_hid": router_a["hid"], "side": "a"},
                {"group_hid": pair["hid"], "side": "z", "notes": "both routers"},
            ]
        },
    )
    assert [(one["name"], one["side"], one["record_status"]) for one in connected] == [
        ("site2-rtr-01", "a", "active"),
        ("site3-rtr-pair", "z", "active"),
    ]
    shown = desk.get(f"/items/{router_a['hid']}")["circuits"]
    assert shown == [
        {
            "hid": made["hid"],
            "name": "Site-2 to Site-3",
            "enterprise_circuit_id": None,
            "side": "a",
            "link_hid": connected[0]["hid"],
            "record_status": "active",
        }
    ]
    assert [one["side"] for one in desk.get(f"/device-groups/{pair['hid']}")["circuits"]] == ["z"]
    # A device is connected to a circuit once, and is one item or one group.
    assert "item_hid" in errors(
        desk.part(made, "devices", {"devices": [{"item_hid": router_a["hid"], "side": "z"}]}, 409)
    )
    assert set(errors(desk.part(made, "devices", {"devices": [{"side": "z"}]}, 422))) == {
        "item_hid",
        "group_hid",
    }
    # The side is changed, the device is not.
    link = connected[0]
    desk.patch(
        f"/circuits/{made['hid']}/devices/{link['hid']}",
        {"row_version": link["row_version"], "item_hid": router_z["hid"]},
        422,
    )
    moved = desk.patch(
        f"/circuits/{made['hid']}/devices/{link['hid']}",
        {"row_version": link["row_version"], "side": "z"},
    )
    assert moved["side"] == "z"
    # A retired item stays listed where it was connected, marked so, and is connected to
    # nothing new.
    spare = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R003", hostname="spare-rtr"
    )
    desk.post(f"/items/{spare['hid']}/retire", {"row_version": spare["row_version"]}, 200)
    assert "item_hid" in errors(
        desk.part(made, "devices", {"devices": [{"item_hid": spare["hid"], "side": "a"}]}, 422)
    )
    desk.post(
        f"/items/{router_a['hid']}/retire",
        {"row_version": desk.get(f"/items/{router_a['hid']}")["row_version"]},
        200,
    )
    listed = desk.get(f"/circuits/{made['hid']}/devices")["items"]
    assert sorted((one["name"], one["side"], one["record_status"]) for one in listed) == [
        ("site2-rtr-01", "z", "retired"),
        ("site3-rtr-pair", "z", "active"),
    ]
    desk.delete(f"/circuits/{made['hid']}/devices/{link['hid']}")
    assert desk.get(f"/items/{router_a['hid']}")["circuits"] == []
    removed = desk.audit(record_type="circuit_device", record_hid=link["hid"])[0]
    assert {"field": "item_hid", "old": router_a["hid"], "new": None} in removed["changes"]


def test_a_replacement_hands_the_circuits_of_the_old_item_to_the_new_one(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    entry = desk.entry(desk.vendor("Cisco"), pid="C8300-1N1S-6T")
    old = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R001", hostname="site2-rtr-01"
    )
    new = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FDO0000R009", hostname="site2-rtr-01b"
    )
    made = desk.circuit(
        "Site-2 internet", a_location_hid=places["room"]["hid"], z_note="carrier network"
    )
    desk.part(made, "devices", {"devices": [{"item_hid": old["hid"], "side": "a"}]})
    desk.post(
        f"/items/{old['hid']}/replace",
        {"row_version": old["row_version"], "reason": "rma", "new_item_hid": new["hid"]},
    )
    assert desk.get(f"/items/{old['hid']}")["circuits"] == []
    handed = desk.get(f"/items/{new['hid']}")["circuits"]
    assert [(one["name"], one["side"]) for one in handed] == [("Site-2 internet", "a")]


def test_the_list_of_circuits_filters_and_sorts_by_what_it_answers(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    room, annex = places["room"]["hid"], places["annex"]["hid"]
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    desk.circuit(
        "Broadband",
        circuit_type="internet",
        port_mbps="50",
        a_location_hid=annex,
        z_note="carrier network",
    )
    desk.circuit(
        "Limited",
        circuit_type="internet",
        port_mbps="1000",
        down_mbps="80",
        a_location_hid=room,
        z_note="carrier network",
        carrier_hid=telecom["hid"],
        carrier_circuit_number="T-1",
    )
    fast = desk.circuit(
        "Backbone",
        circuit_type="point_to_point",
        port_mbps="10000",
        a_location_hid=room,
        z_location_hid=annex,
        cost_side="z",
    )
    desk.part(
        fast,
        "carriers",
        {"vendor_hid": exchange["hid"], "role": "local_exchange", "circuit_number": "LEC-9"},
    )
    desk.circuit("Draft", a_location_hid=room, z_note="x", record_status="draft")
    # The rate in force: a full-rate circuit of 50 is below 100 too.
    assert desk.names(filter="circuit_type:eq:internet effective.down_mbps:lt:100") == [
        "Broadband",
        "Limited",
    ]
    assert desk.names(filter="effective.up_mbps:lt:100") == ["Broadband"]
    # A side at a location, or at or beneath a site or a region.
    assert desk.names(filter="location:within:Americas > Central > Site-3") == [
        "Backbone",
        "Broadband",
    ]
    assert desk.names(filter=f"location:within:{places['building']['hid']}") == [
        "Backbone",
        "Limited",
    ]
    assert desk.names(filter="location:within:Americas") == ["Backbone", "Broadband", "Limited"]
    # Where it counts.
    assert desk.names(filter=f"cost_site_hid:eq:{places['site3']['hid']}") == [
        "Backbone",
        "Broadband",
    ]
    assert desk.names(filter="cost_location:within:Americas > Central > Site-2") == ["Limited"]
    # Any of its carriers, the primary one among them, and the number any gives it.
    assert desk.names(filter=f"carriers.vendor_hid:eq:{telecom['hid']}") == ["Limited"]
    assert desk.names(filter=f"carriers.vendor_hid:eq:{exchange['hid']}") == ["Backbone"]
    assert desk.names(filter="carriers.circuit_number:eq:lec-9") == ["Backbone"]
    assert desk.names(filter="carriers.circuit_number:eq:T-1") == ["Limited"]
    assert desk.names(filter="carrier.name:eq:Example Telecom") == ["Limited"]
    assert desk.names(filter="in_service:eq:true") == ["Backbone", "Broadband", "Limited"]
    assert desk.names(include_drafts=True) == ["Backbone", "Broadband", "Draft", "Limited"]
    # Sorted by the port, and by the name of a side's location, a side with none last.
    assert desk.names(sort="-port_mbps") == ["Backbone", "Limited", "Broadband"]
    assert desk.names(sort="z_location.name,name") == ["Backbone", "Broadband", "Limited"]
    assert desk.names(sort="-effective.down_mbps") == ["Backbone", "Limited", "Broadband"]
    assert desk.names(sort="carriers.circuit_number,name") == ["Backbone", "Limited", "Broadband"]
    # A list leaves the parts out unless they are asked for.
    rows = desk.get("/circuits")["items"]
    assert all(row["carriers"] is None and row["costs"] is None for row in rows)
    asked = desk.get("/circuits", fields="name,carriers", filter="name:eq:Backbone")["items"][0]
    assert [one["vendor"] for one in asked["carriers"]] == ["Example Local Exchange"]
    assert set(asked) == {"hid", "row_version", "name", "carriers"}
    queried = desk.post(
        "/circuits/query", {"filter": {"field": "speed", "op": "eq", "value": "1G"}}, 422
    )
    assert "filter" in errors(queried)
    assert (
        desk.post("/circuits/query", {"sort": ["-annual_cost", "name"], "limit": 2}, 200)["total"]
        == 3
    )
    assert "sort" in errors(desk.get("/circuits", 422, sort="location"))


def test_any_role_reads_circuits_and_only_inventory_changes_them(
    desk: Desk, places: dict[str, dict[str, Any]], client: TestClient, viewer: dict[str, str]
) -> None:
    made = desk.circuit(
        "Site-2 internet", a_location_hid=places["room"]["hid"], z_note="carrier network"
    )
    reader = Maker(client, viewer)
    assert reader.get(f"/circuits/{made['hid']}")["name"] == "Site-2 internet"
    assert reader.get("/circuits")["total"] == 1
    reader.post(
        "/circuits", {"name": "Mine", "a_location_hid": places["room"]["hid"], "z_note": "x"}, 403
    )
    reader.patch(
        f"/circuits/{made['hid']}", {"row_version": made["row_version"], "notes": "x"}, 403
    )
    reader.post(f"/circuits/{made['hid']}/costs", {"description": "Port", "monthly_cost": "1"}, 403)
    reader.post(f"/circuits/{made['hid']}/retire", {"row_version": made["row_version"]}, 403)
