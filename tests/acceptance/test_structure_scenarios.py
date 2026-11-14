"""Scenarios S18 to S23 of docs/build-plan.md, against a real server process."""

from decimal import Decimal
from typing import Any

import httpx2
import pytest

from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_item_scenarios import IVY, Inventory


class Structure(Inventory):
    """A signed-in Inventory user who builds stacks, clusters and domains, beside an Admin."""

    def __init__(self, client: httpx2.Client, admin: httpx2.Client) -> None:
        super().__init__(client)
        self.admin = admin

    def switches(self, entry: dict[str, Any], prefix: str, count: int, **more: Any) -> list[dict]:
        return [
            self.post(
                "/items",
                {
                    "catalog_entry_hid": entry["hid"],
                    "serial_number": f"{prefix.upper()}{number:03d}",
                    "hostname": f"{prefix}-{number:02d}",
                    **more,
                },
            )
            for number in range(1, count + 1)
        ]

    def stack(self, name: str, members: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a stack whose first member is the master."""
        return self.post(
            "/device-groups",
            {
                "type": "stack",
                "name": name,
                "hostname": name,
                "members": [
                    {
                        "item_hid": member["hid"],
                        "role": "master" if place == 1 else "member",
                        "position": place,
                    }
                    for place, member in enumerate(members, start=1)
                ],
            },
        )

    def members(self, group: dict[str, Any], **params: Any) -> list[dict[str, Any]]:
        return self.get(f"/device-groups/{group['hid']}/members", **params)["items"]

    def totals(self, **params: Any) -> dict[str, Any]:
        return self.get("/reports/summary", **params)["totals"]

    def cost(self, **params: Any) -> Decimal:
        """Return the annual support cost of a view, from the management report."""
        return Decimal(self.get("/reports/management", **params)["totals"]["annual_support_cost"])


@pytest.fixture
def structure(server: Server) -> Structure:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Structure(server.sign_in(*IVY), admin)


def test_s18_minor_items_follow_their_switch_and_are_not_counted(structure: Structure) -> None:
    switch_model = structure.entry(support_weight="1.0")
    supply_model = structure.entry("PWR-C1-715WAC-P", type="power-supply")
    module_model = structure.entry("C9300-NM-8X", type="module")
    first = structure.post("/owners", {"label": "Network Engineering"})
    second = structure.post("/owners", {"label": "Campus Networks"})
    before = structure.totals()

    switch = structure.post(
        "/items",
        {
            "catalog_entry_hid": switch_model["hid"],
            "serial_number": "FCW0000X001",
            "hostname": "site2-sw-access-01",
            "owner_hid": first["hid"],
            "lifecycle_state": "Assigned",
        },
    )
    parts = (
        (supply_model, "LIT0000X001", "PS-A"),
        (supply_model, "LIT0000X002", "PS-B"),
        (module_model, "FOC0000X001", "Slot 1"),
    )
    for model, serial, position in parts:
        made = structure.post(
            "/items",
            {
                "catalog_entry_hid": model["hid"],
                "serial_number": serial,
                "parent_item_hid": switch["hid"],
                "position": position,
            },
        )
        assert made["is_major"] is False
        assert made["effective"]["owner_hid"] == {
            "value": first["hid"],
            "label": "Network Engineering",
            "source": "parent_item",
            "source_hid": switch["hid"],
        }
        assert made["effective"]["lifecycle_state"]["value"] == "Assigned"

    # Four records more, and one component more: the minor items are not counted.
    after = structure.totals()
    assert after["items"] == before["items"] + 4
    assert after["component_count"] == before["component_count"] + 1

    switch = structure.patch(
        f"/items/{switch['hid']}",
        {"row_version": switch["row_version"], "owner_hid": second["hid"]},
    )
    for to in ("Test", "Prod"):
        switch = structure.post(
            f"/items/{switch['hid']}/transition",
            {"row_version": switch["row_version"], "to": to},
            200,
        )

    children = structure.get(f"/items/{switch['hid']}/children")["items"]
    assert [child["position"] for child in children] == ["PS-A", "PS-B", "Slot 1"]
    for child in children:
        effective = child["effective"]
        assert effective["owner_hid"]["value"] == second["hid"]
        assert effective["owner_hid"]["source"] == "parent_item"
        assert effective["lifecycle_state"] == {
            "value": "Prod",
            "source": "parent_item",
            "source_hid": switch["hid"],
        }
        assert effective["disposition"]["value"] == "Production"
        assert effective["expected_online"]["value"] is True
        # Nothing was copied down: the minor items were not written to.
        assert child["owner_hid"] is None
        assert child["lifecycle_state"] is None
        assert child["row_version"] == 1
    assert structure.totals()["component_count"] == before["component_count"] + 1


def test_s19_a_stack_shows_the_serial_number_of_the_master_that_is_seen(
    structure: Structure,
) -> None:
    switches = structure.switches(structure.entry(), "site2-sw-stack1", 4)
    stack = structure.stack("site2-sw-stack1", switches)
    assert stack["type"] == "stack"
    assert stack["member_count"] == 4
    # One member is marked as the master that is intended, and the stack shows its serial.
    assert (stack["serial_number"], stack["serial_source"]) == (
        switches[0]["serial_number"],
        "intended",
    )

    # The stack booted and made its third switch master. That is recorded as seen.
    again = structure.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "observed_master_hid": switches[2]["hid"]},
    )

    # The serial number is read from the master that is seen, so it is right at once.
    assert (again["serial_number"], again["serial_source"]) == (
        switches[2]["serial_number"],
        "observed",
    )
    assert again["hid"] == stack["hid"]
    assert again["master_as_intended"] is False
    # What is intended is as it was: one member is marked, and it is the first.
    roles = {member["item_hid"]: member["role"] for member in structure.members(stack)}
    assert roles[switches[0]["hid"]] == "master"
    assert list(roles.values()).count("master") == 1
    # The stack is found by the serial number of any of its members.
    for switch in switches:
        found = structure.get(
            "/device-groups", filter=f"member.serial_number:eq:{switch['serial_number']}"
        )["items"]
        assert [group["hid"] for group in found] == [stack["hid"]]


def test_s20_the_stack_discount_lowers_the_weight_and_never_the_cost(structure: Structure) -> None:
    setting = structure.get("/settings")
    discount = next(entry for entry in setting if entry["key"] == "stack_discount_pct")
    assert discount["value"] == 50
    model = structure.entry(support_weight="1.0", annual_support_cost="1450.00")
    switches = structure.switches(model, "site2-sw-stack1", 4, lifecycle_state="Prod")
    one = f"hid:eq:{switches[0]['hid']}"
    assert Decimal(structure.totals(filter=one)["support_weight"]) == Decimal("1.0")
    cost_of_one = structure.cost(filter=one)
    stack = structure.stack("site2-sw-stack1", switches)
    in_stack = "group.name:eq:site2-sw-stack1"

    totals = structure.totals(filter=in_stack)
    assert Decimal(totals["support_weight"]) == Decimal("2.0")
    assert (totals["component_count"], totals["managed_node_count"]) == (4, 1)
    assert structure.cost(filter=in_stack) == 4 * cost_of_one

    structure.patch(
        f"/catalog-entries/{model['hid']}",
        {"row_version": model["row_version"], "stack_discount_pct": "30"},
    )
    totals = structure.totals(filter=in_stack)
    assert Decimal(totals["support_weight"]) == Decimal("2.8")
    assert (totals["component_count"], totals["managed_node_count"]) == (4, 1)
    assert structure.cost(filter=in_stack) == Decimal("5800.00")
    assert structure.get(f"/device-groups/{stack['hid']}")["member_count"] == 4


def test_s21_the_master_of_a_stack_is_replaced_for_an_rma(structure: Structure) -> None:
    model = structure.entry()
    switches = structure.switches(model, "site2-sw-stack1", 4)
    stack = structure.stack("site2-sw-stack1", switches)
    master = switches[0]

    replacement = structure.post(
        f"/items/{master['hid']}/replace",
        {
            "row_version": master["row_version"],
            "reason": "rma",
            "reference": "RMA-0000-001",
            "new_item": {"catalog_entry_hid": model["hid"], "serial_number": "FCW0000X999"},
        },
    )

    # Two item records, linked by the replacement.
    old = structure.get(f"/items/{master['hid']}")
    new = structure.get(f"/items/{replacement['new_item']['hid']}")
    assert old["hid"] != new["hid"]
    assert old["replaced_by"]["item_hid"] == new["hid"]
    assert new["replaces"]["item_hid"] == old["hid"]
    assert new["replaces"]["reason"] == "rma"
    assert new["replaces"]["reference"] == "RMA-0000-001"

    # The departed switch's membership has an end date, and the new one has its place.
    every = structure.members(stack, include_past="true")
    departed = next(member for member in every if member["item_hid"] == old["hid"])
    arrived = next(member for member in every if member["item_hid"] == new["hid"])
    day = replacement["replaced_on"]
    assert day is not None
    assert departed["left_on"] == day
    assert arrived["left_on"] is None
    assert (arrived["role"], arrived["position"], arrived["joined_on"]) == ("master", 1, day)
    assert old["groups"] == []
    assert [group["group_hid"] for group in new["groups"]] == [stack["hid"]]

    # The stack is the same record, and reads its serial number from the new master.
    again = structure.get(f"/device-groups/{stack['hid']}")
    assert again["hid"] == stack["hid"]
    assert again["member_count"] == 4
    assert again["serial_number"] == "FCW0000X999"


def test_s22_a_controller_domain_of_a_cluster_and_forty_access_points(
    structure: Structure,
) -> None:
    controller_model = structure.entry("C9800-40-K9", type="wireless-controller")
    access_point_model = structure.entry("C9130AXI-B", type="access-point")
    controllers = structure.switches(controller_model, "site2-wlc", 2)
    access_points = structure.switches(access_point_model, "site2-ap", 40)

    domain = structure.post(
        "/device-groups",
        {
            "type": "controller_domain",
            "name": "site2-wireless",
            "members": [{"item_hid": point["hid"], "role": "endpoint"} for point in access_points],
        },
    )
    structure.post(
        "/device-groups",
        {
            "type": "cluster",
            "name": "site2-wlc-ha",
            "hostname": "site2-wlc",
            "parent_group_hid": domain["hid"],
            "members": [
                {"item_hid": controllers[0]["hid"], "role": "active"},
                {"item_hid": controllers[1]["hid"], "role": "standby"},
            ],
        },
    )

    totals = structure.totals()
    assert totals["component_count"] == 42
    # The cluster is one managed node, and each access point is one.
    assert totals["managed_node_count"] == 41
    in_cluster = structure.totals(filter="group.name:eq:site2-wlc-ha")
    assert (in_cluster["component_count"], in_cluster["managed_node_count"]) == (2, 1)

    wanted = sorted(controller["hid"] for controller in controllers)
    points = structure.get("/items", filter="catalog.type:eq:access-point", limit=100)["items"]
    assert len(points) == 40
    for point in points:
        assert sorted(controller["hid"] for controller in point["controllers"]) == wanted


def test_s23_one_address_under_two_networks_and_twice_under_one(structure: Structure) -> None:
    red = structure.post("/networks", {"label": "Red", "kind": "vrf"})
    black = structure.post("/networks", {"label": "Black", "kind": "vrf"})
    first, second = structure.switches(structure.entry(), "site2-sw-access", 2)

    def address(item: dict[str, Any], network: dict[str, Any]) -> dict[str, Any]:
        return structure.post(
            "/addresses",
            {"item_hid": item["hid"], "address": "192.0.2.10", "network_hid": network["hid"]},
        )

    address(first, red)
    address(first, black)
    # The same address under two networks is two different addresses.
    assert structure.get("/reports/duplicates")["items"] == []

    address(second, red)
    duplicates = structure.get("/reports/duplicates")["items"]
    assert len(duplicates) == 1
    pair = duplicates[0]
    assert (pair["address"], pair["network"], pair["count"]) == ("192.0.2.10", "Red", 2)
    assert sorted(holder["item_hid"] for holder in pair["holders"]) == sorted(
        [first["hid"], second["hid"]]
    )
    assert structure.get("/addresses", filter="address:eq:192.0.2.10")["total"] == 3
