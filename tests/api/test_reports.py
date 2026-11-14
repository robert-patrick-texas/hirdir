"""The summary report: components, managed nodes, support weight, value and cost."""

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors


def _model(make: Maker, pid: str = "C9300-48P", **more) -> dict:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    values = {"est_value": "18000", "support_weight": "1", "annual_support_cost": "1450"}
    return make.entry(vendor, pid, **{**values, **more})


def _measures(found: dict) -> tuple:
    return (
        found["items"],
        found["component_count"],
        found["managed_node_count"],
        Decimal(found["support_weight"]),
    )


def _money(make: Maker, **params) -> tuple:
    found = make.get("/reports/management", **params)["totals"]
    return Decimal(found["est_value"]), Decimal(found["annual_support_cost"])


def test_an_empty_inventory_counts_nothing(make: Maker) -> None:
    summary = make.get("/reports/summary")
    assert summary["by"] is None
    assert summary["rows"] == []
    assert summary["totals"] == {
        "items": 0,
        "component_count": 0,
        "managed_node_count": 0,
        "support_weight": "0",
        "by_health": {"good": 0, "degraded": 0, "failed": 0, "unknown": 0},
        "by_condition": [],
        "by_kind": [],
    }
    assert make.get("/reports/management")["totals"] == {
        "items": 0,
        "component_count": 0,
        "est_value": "0.00",
        "annual_support_cost": "0.00",
    }


def test_components_are_major_items_in_hand_and_weight_is_carried_in_service(make: Maker) -> None:
    model = _model(make)
    states = ("Purchased", "Delivered", "Assigned", "Test", "Prod", None)
    switches = [
        make.item(
            catalog_entry_hid=model["hid"],
            serial_number=f"FCW0000X00{number}",
            **({"lifecycle_state": state} if state else {}),
        )
        for number, state in enumerate(states, start=1)
    ]
    make.item(name="PS-A", parent_item_hid=switches[4]["hid"], est_value="900")

    totals = make.totals()

    # Seven records. Purchased and Delivered are not yet in hand; a blank state counts.
    # The minor item is not a component, and its value is in the sum.
    assert _measures(totals) == (7, 4, 4, Decimal("2"))
    assert _money(make) == (Decimal("108900"), Decimal("8700"))
    assert make.get("/reports/management")["totals"]["est_value"] == "108900.00"
    assert totals["by_kind"] == [
        {"key": "hardware", "label": "hardware", "items": 7, "component_count": 4}
    ]


def test_quantity_multiplies_and_an_override_is_what_counts(make: Maker) -> None:
    licence = _model(make, "NETCONFIG-MANAGER", kind="software", support_weight="0.01")
    make.item(
        catalog_entry_hid=licence["hid"],
        name="NetConfig Manager",
        quantity=250,
        lifecycle_state="Prod",
    )
    switch = _model(make)
    make.item(
        catalog_entry_hid=switch["hid"],
        serial_number="FCW0000X001",
        lifecycle_state="Prod",
        support_weight="2.5",
        est_value="20000",
    )

    totals = make.totals()

    # Software carries weight and cost, and stands beside the headline count, not in it.
    assert _measures(totals) == (2, 1, 1, Decimal("5"))
    assert _money(make) == (Decimal("4520000"), Decimal("363950"))
    assert [(one["key"], one["items"], one["component_count"]) for one in totals["by_kind"]] == [
        ("hardware", 1, 1),
        ("software", 1, 1),
    ]


def test_a_stack_is_one_managed_node_and_its_members_earn_the_discount(
    make: Maker, admin: dict
) -> None:
    plain = _model(make)
    own = _model(make, "EX4400-48P", stack_discount_pct="30")
    first = make.switches(plain, "site2-sw-stack1", 4, lifecycle_state="Prod")
    second = make.switches(own, "site2-sw-stack2", 4, lifecycle_state="Prod")
    make.switches(plain, "site2-sw-alone", 4, lifecycle_state="Prod")
    make.stack("site2-sw-stack1", first)
    make.stack("site2-sw-stack2", second)

    # The worked example of the data model page: 2.0, 2.8, and 4.0 for four alone.
    assert _measures(make.totals(filter="group.name:eq:site2-sw-stack1"))[1:4] == (
        4,
        1,
        Decimal("2"),
    )
    assert _measures(make.totals(filter="group.name:eq:site2-sw-stack2"))[1:4] == (
        4,
        1,
        Decimal("2.8"),
    )
    assert _measures(make.totals(filter="hostname:prefix:site2-sw-alone"))[1:4] == (
        4,
        4,
        Decimal("4"),
    )
    everything = make.totals()
    assert _measures(everything)[1:4] == (12, 6, Decimal("8.8"))
    # The discount never touches the cost: twelve switches cost twelve times one.
    assert _money(make)[1] == 12 * Decimal("1450")

    # The global discount reaches the model that sets none, and not the one that does.
    setting = Maker(make.client, admin)
    setting.client.put(
        f"{API}/settings/stack_discount_pct", json={"row_version": 0, "value": 25}, headers=admin
    ).raise_for_status()
    assert Decimal(make.totals(filter="group.name:eq:site2-sw-stack1")["support_weight"]) == 3
    assert Decimal(
        make.totals(filter="group.name:eq:site2-sw-stack2")["support_weight"]
    ) == Decimal("2.8")


def test_only_an_active_stack_is_one_node_and_earns_the_discount(make: Maker) -> None:
    model = _model(make)
    switches = make.switches(model, "site2-sw-stack1", 2, lifecycle_state="Prod")
    stack = make.group(
        "site2-sw-stack1",
        "stack",
        [(switches[0], "master"), (switches[1], "member")],
        record_status="draft",
    )

    assert _measures(make.totals())[1:4] == (2, 2, Decimal("2"))
    make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "record_status": "active"},
    )
    assert _measures(make.totals())[1:4] == (2, 1, Decimal("1"))
    again = make.get(f"/device-groups/{stack['hid']}")
    make.post(f"/device-groups/{stack['hid']}/retire", {"row_version": again["row_version"]}, 200)
    assert _measures(make.totals())[1:4] == (2, 2, Decimal("2"))


def test_a_cluster_is_one_node_and_comes_before_a_stack(make: Maker) -> None:
    model = _model(make)
    switches = make.switches(model, "site2-sw-core", 4, lifecycle_state="Prod")
    make.stack("site2-sw-core-a", switches[:2])
    make.stack("site2-sw-core-b", switches[2:])
    assert _measures(make.totals())[1:3] == (4, 2)

    # Two stacks behind one management address are one managed node.
    make.group("site2-sw-core", "cluster", [(switch, "member") for switch in switches])
    totals = make.totals()
    assert _measures(totals)[1:3] == (4, 1)
    # Each member is still in its stack, and the discount is the stack's to give.
    assert Decimal(totals["support_weight"]) == 2


def test_the_summary_is_of_the_view_the_list_shows(make: Maker) -> None:
    model = _model(make)
    owner = make.owner()
    make.item(
        catalog_entry_hid=model["hid"],
        serial_number="A1",
        lifecycle_state="Prod",
        owner_hid=owner["hid"],
    )
    draft = make.item(catalog_entry_hid=model["hid"], serial_number="A2", record_status="draft")
    retired = make.item(catalog_entry_hid=model["hid"], serial_number="A3", lifecycle_state="Prod")
    make.post(f"/items/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)

    assert make.totals()["component_count"] == 1
    assert make.totals(include_drafts="true")["component_count"] == 2
    assert make.totals(include_archived="true")["component_count"] == 2
    assert make.totals(include_drafts="true", include_archived="true")["items"] == 3
    assert make.totals(filter="owner.label:eq:Network Engineering")["items"] == 1
    assert make.totals(filter=f"hid:eq:{draft['hid']}")["items"] == 0
    as_json = make.totals(filter='{"field": "serial_number", "op": "in", "value": ["A1", "A3"]}')
    assert as_json["items"] == 1

    problem = make.get("/reports/summary", expect=422, filter="colour:eq:red")
    assert "not a field" in errors(problem)["filter"]
    problem = make.get("/reports/summary", expect=422, by="contract")
    assert problem["status"] == 422


def test_the_summary_by_owner_puts_a_minor_item_under_the_owner_in_force(make: Maker) -> None:
    model = _model(make)
    ours, theirs = make.owner(), make.owner("Voice Services")
    switch = make.item(
        catalog_entry_hid=model["hid"],
        serial_number="A1",
        lifecycle_state="Prod",
        owner_hid=ours["hid"],
    )
    make.item(name="PS-A", parent_item_hid=switch["hid"])
    make.item(
        catalog_entry_hid=model["hid"],
        serial_number="A2",
        lifecycle_state="Test",
        owner_hid=theirs["hid"],
    )
    make.item(name="nobody's")

    summary = make.get("/reports/summary", by="owner")

    assert summary["by"] == "owner"
    rows = {row["label"]: row for row in summary["rows"]}
    assert [row["label"] for row in summary["rows"]] == [
        "Network Engineering",
        "Voice Services",
        None,
    ]
    assert rows["Network Engineering"]["key"] == ours["hid"]
    assert (
        rows["Network Engineering"]["items"],
        rows["Network Engineering"]["component_count"],
    ) == (2, 1)
    assert (rows["Voice Services"]["items"], rows["Voice Services"]["support_weight"]) == (1, "1")
    assert (rows[None]["key"], rows[None]["items"], rows[None]["component_count"]) == (None, 1, 1)
    assert sum(row["items"] for row in summary["rows"]) == summary["totals"]["items"] == 4


def test_the_summary_by_what_items_share(make: Maker) -> None:
    switch = _model(make, type="switch", function="access")
    router = _model(make, "ISR4331/K9", type="router", function="wan")
    juniper = make.entry(make.vendor("Juniper"), "EX4400-48P", kind="virtual_machine")
    for label in ("critical", "lab"):
        make.tag(label)
    make.item(
        catalog_entry_hid=switch["hid"],
        serial_number="A1",
        lifecycle_state="Prod",
        tags=["critical", "lab"],
    )
    make.item(
        catalog_entry_hid=router["hid"],
        serial_number="B1",
        lifecycle_state="Assigned",
        tags=["critical"],
    )
    make.item(
        catalog_entry_hid=juniper["hid"],
        serial_number="C1",
        lifecycle_state="Prod",
        disposition="Spare",
    )
    make.item(name="unknown")

    def rows(by: str) -> list[tuple]:
        found = make.get("/reports/summary", by=by)["rows"]
        return [(row["label"], row["items"], row["component_count"]) for row in found]

    assert rows("vendor") == [("Cisco", 2, 2), ("Juniper", 1, 1), (None, 1, 1)]
    # An item with no catalog entry is counted as hardware.
    assert rows("kind") == [("hardware", 3, 3), ("virtual_machine", 1, 1)]
    # A type and a function are called what their lists of choices call them.
    assert rows("type") == [("Router", 1, 1), ("Switch", 1, 1), (None, 2, 2)]
    assert rows("function") == [("Access", 1, 1), ("WAN", 1, 1), (None, 2, 2)]
    by_type = make.get("/reports/summary", by="type")["rows"]
    assert [row["key"] for row in by_type] == ["router", "switch", None]
    assert rows("lifecycle_state") == [("Assigned", 1, 1), ("Prod", 2, 2), (None, 1, 1)]
    assert rows("disposition") == [
        ("Production", 1, 1),
        ("Spare", 1, 1),
        ("Staging", 1, 1),
        (None, 1, 1),
    ]
    # An item with two tags is in the row of each, and the totals count it once.
    by_tag = make.get("/reports/summary", by="tag")
    assert [(row["label"], row["items"]) for row in by_tag["rows"]] == [
        ("critical", 2),
        ("lab", 1),
        (None, 2),
    ]
    assert by_tag["totals"]["items"] == 4


def test_a_stack_split_between_two_rows_is_a_node_in_both_and_one_in_all(make: Maker) -> None:
    model = _model(make)
    ours, theirs = make.owner(), make.owner("Voice Services")
    switches = make.switches(model, "site2-sw-stack1", 2, lifecycle_state="Prod")
    make.patch(f"/items/{switches[0]['hid']}", {"row_version": 1, "owner_hid": ours["hid"]})
    make.patch(f"/items/{switches[1]['hid']}", {"row_version": 1, "owner_hid": theirs["hid"]})
    make.stack("site2-sw-stack1", switches)

    summary = make.get("/reports/summary", by="owner")

    assert [row["managed_node_count"] for row in summary["rows"]] == [1, 1]
    assert summary["totals"]["managed_node_count"] == 1


def test_support_weight_is_rounded_once_after_it_is_summed(make: Maker) -> None:
    model = _model(make, support_weight="0.01", stack_discount_pct="50")
    switches = make.switches(model, "site2-sw-stack1", 3, lifecycle_state="Prod")
    make.stack("site2-sw-stack1", switches)

    # Three times half a hundredth is 0.015: rounded each, it would be 0.03 or nothing.
    assert make.totals()["support_weight"] == "0.02"


def test_the_summary_is_read_by_every_role_and_by_nobody_else(
    client: TestClient, viewer: dict
) -> None:
    assert client.get(f"{API}/reports/summary", headers=viewer).status_code == 200
    assert client.get(f"{API}/reports/summary").status_code == 401
