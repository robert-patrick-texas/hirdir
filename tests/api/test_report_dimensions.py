"""The summary and the management report by group and by model, and the items of each
model on the catalog (P-178, P-180)."""

import csv
import io
import json
from typing import Any

import pytest

from tests.api import test_cli
from tests.api.inventory import Maker, errors

# The fixture that runs `hirdir` against the test client.
run = test_cli.run

MONEY = {"est_value": "1000", "annual_support_cost": "100", "support_weight": "1"}


def _rows(make: Maker, report: str = "summary", **params: Any) -> dict[Any, dict[str, Any]]:
    """Return the rows of a report by their labels, in the order of the answer."""
    found = make.get(f"/reports/{report}", **params)["rows"]
    return {row["label"]: row for row in found}


@pytest.fixture
def campus(make: Maker) -> dict[str, Any]:
    """Groups nested three deep, with an item in two of them and a minor item in one.

    `Campus`, a custom group, holds the controller domain `east-wlc`, which holds the
    stack `site2-sw-stack1`. The domain has an access point; the stack two switches, the
    first with a power supply in it; and the custom group `lobby` has the first switch
    and a third. One more switch is in no group.
    """
    model = make.entry(make.vendor(), "C9300-48P", type="switch", **MONEY)
    switches = make.switches(model, "site2-sw", 4, lifecycle_state="Prod")
    supply = make.item(name="PS-A", parent_item_hid=switches[0]["hid"], position="PS-A")
    access_point = make.item(
        catalog_entry_hid=make.entry(make.vendor("Juniper"), "AP45", **MONEY)["hid"],
        hostname="site2-ap-01",
        lifecycle_state="Prod",
    )
    top = make.group("Campus", "custom")
    domain = make.group(
        "east-wlc", "controller_domain", [(access_point, "endpoint")], parent_group_hid=top["hid"]
    )
    stack = make.stack("site2-sw-stack1", switches[:2], parent_group_hid=domain["hid"])
    lobby = make.group("lobby", "custom", [(switches[0], "member"), (switches[2], "member")])
    return {
        "model": model,
        "switches": switches,
        "supply": supply,
        "access_point": access_point,
        "top": top,
        "domain": domain,
        "stack": stack,
        "lobby": lobby,
    }


def test_a_group_holds_its_members_those_of_the_groups_in_it_and_their_minor_items(
    make: Maker, campus: dict
) -> None:
    summary = make.get("/reports/summary", by="group")

    assert summary["by"] == "group"
    # By name without regard to case, and the blank row last.
    assert [row["label"] for row in summary["rows"]] == [
        "Campus",
        "east-wlc",
        "lobby",
        "site2-sw-stack1",
        None,
    ]
    rows = {row["label"]: row for row in summary["rows"]}
    shown = {
        label: (row["key"], row["type"], row["member_count"], row["nested_groups"], row["items"])
        for label, row in rows.items()
    }
    assert shown == {
        # The domain's access point, the stack's two switches and the power supply.
        "Campus": (campus["top"]["hid"], "custom", 0, 2, 4),
        "east-wlc": (campus["domain"]["hid"], "controller_domain", 1, 1, 4),
        "lobby": (campus["lobby"]["hid"], "custom", 2, 0, 3),
        "site2-sw-stack1": (campus["stack"]["hid"], "stack", 2, 0, 3),
        # The fourth switch, in no group.
        None: (None, None, None, None, 1),
    }
    # The power supply is no component, and the stack is one managed node wherever its
    # members are counted, each of them at the stack's discount, half, as everywhere.
    assert [
        (row["component_count"], row["managed_node_count"], row["support_weight"])
        for row in summary["rows"]
    ] == [(3, 2, "2"), (3, 2, "2"), (2, 2, "1.5"), (2, 1, "1"), (1, 1, "1")]
    # The first switch is in two rows of its own and two through the stack, and the
    # totals count it once.
    assert summary["totals"]["items"] == 6
    assert sum(row["items"] for row in summary["rows"]) == 15
    # A row of a group says nothing of a model.
    assert {
        (row["vendor"], row["pid"], row["model_name"], row["kind"]) for row in summary["rows"]
    } == {(None, None, None, None)}


def test_a_group_is_counted_by_the_view_with_its_operators_and_its_money(
    make: Maker, campus: dict
) -> None:
    by_group = _rows(make, by="group", filter="is_major:eq:true", operators="true")
    assert [(label, row["items"]) for label, row in by_group.items()] == [
        ("Campus", 3),
        ("east-wlc", 3),
        ("lobby", 2),
        ("site2-sw-stack1", 2),
        (None, 1),
    ]
    # Nobody is assigned to any of them.
    assert [(one["hid"], one["items"]) for one in by_group["lobby"]["operators"]] == [(None, 2)]

    money = make.get("/reports/management", by="group")
    assert money["by"] == "group"
    assert [
        (row["label"], row["type"], row["items"], row["est_value"], row["annual_support_cost"])
        for row in money["rows"]
    ] == [
        ("Campus", "custom", 4, "3000.00", "300.00"),
        ("east-wlc", "controller_domain", 4, "3000.00", "300.00"),
        ("lobby", "custom", 3, "2000.00", "200.00"),
        ("site2-sw-stack1", "stack", 3, "2000.00", "200.00"),
        (None, None, 1, "1000.00", "100.00"),
    ]
    assert money["totals"]["est_value"] == "5000.00"


def test_a_retired_group_and_an_ended_membership_leave_no_trace(make: Maker, campus: dict) -> None:
    # The second switch leaves the stack, and so the domain and Campus with it.
    second = next(
        one
        for one in make.members(campus["stack"])
        if one["item_hid"] == campus["switches"][1]["hid"]
    )
    make.patch(
        f"/device-groups/{campus['stack']['hid']}/members/{second['hid']}",
        {"row_version": second["row_version"], "left_on": second["joined_on"]},
    )
    # A group nested in Campus with a group in it, retired: neither it nor what is
    # nested in it is under Campus any more, and the group in it stands by itself.
    middle = make.group("annex", "custom", [(campus["switches"][3], "member")])
    make.patch(
        f"/device-groups/{middle['hid']}",
        {"row_version": middle["row_version"], "parent_group_hid": campus["top"]["hid"]},
    )
    make.group("annex-aps", "custom", parent_group_hid=middle["hid"])
    held = make.group("annex-spares", "custom", parent_group_hid=middle["hid"])
    make.add(held, [{"item_hid": campus["switches"][1]["hid"], "role": "member"}])
    before = _rows(make, by="group")
    assert (before["Campus"]["items"], before["Campus"]["nested_groups"]) == (5, 5)
    middle = make.get(f"/device-groups/{middle['hid']}")
    make.post(f"/device-groups/{middle['hid']}/retire", {"row_version": middle["row_version"]}, 200)
    # A retired group with what was in it.
    gone = make.group("old-pool", "custom", [(campus["switches"][2], "member")])
    gone = make.get(f"/device-groups/{gone['hid']}")
    make.post(f"/device-groups/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)

    rows = _rows(make, by="group")

    # A group with nothing under it, `annex-aps`, has no row, as a tag on nothing has
    # none.
    assert [
        (label, row["items"], row["member_count"], row["nested_groups"])
        for label, row in rows.items()
    ] == [
        ("annex-spares", 1, 1, 0),
        ("Campus", 3, 0, 2),
        ("east-wlc", 3, 1, 1),
        ("lobby", 3, 2, 0),
        ("site2-sw-stack1", 2, 1, 0),
        (None, 1, None, None),
    ]
    # The fourth switch was in the retired group alone, and is in no group now.
    assert rows[None]["component_count"] == 1
    assert make.totals()["items"] == 6


def test_a_model_is_a_vendors_product_ranked_against_every_other(make: Maker) -> None:
    cisco, juniper = make.vendor(), make.vendor("Juniper")
    catalyst = make.entry(
        cisco, "C9300-48P", model_name="Catalyst 9300 48-port PoE+", type="switch", **MONEY
    )
    router = make.entry(cisco, "ISR4331/K9", type="router", **MONEY)
    ex = make.entry(juniper, "EX4400-48P", type="switch", **MONEY)
    licence = make.entry(cisco, "DNA-E-48-3Y", kind="software")
    make.switches(catalyst, "site2-sw", 2, lifecycle_state="Prod")
    make.switches(ex, "site3-sw", 1, lifecycle_state="Prod")
    make.switches(router, "site2-rtr", 1, lifecycle_state="Prod")
    make.item(catalog_entry_hid=licence["hid"], name="DNA licences", quantity=48)
    make.item(name="unknown", lifecycle_state="Prod")

    summary = make.get("/reports/summary", by="model")

    assert summary["by"] == "model"
    assert [
        (
            row["label"],
            row["key"],
            row["vendor"],
            row["pid"],
            row["model_name"],
            row["kind"],
            row["type"],
            row["items"],
            row["component_count"],
        )
        for row in summary["rows"]
    ] == [
        (
            "Cisco C9300-48P",
            catalyst["hid"],
            "Cisco",
            "C9300-48P",
            "Catalyst 9300 48-port PoE+",
            "hardware",
            "switch",
            2,
            2,
        ),
        ("Cisco DNA-E-48-3Y", licence["hid"], "Cisco", "DNA-E-48-3Y", None, "software", None, 1, 0),
        (
            "Cisco ISR4331/K9",
            router["hid"],
            "Cisco",
            "ISR4331/K9",
            None,
            "hardware",
            "router",
            1,
            1,
        ),
        (
            "Juniper EX4400-48P",
            ex["hid"],
            "Juniper",
            "EX4400-48P",
            None,
            "hardware",
            "switch",
            1,
            1,
        ),
        # The item with no catalog entry.
        (None, None, None, None, None, None, None, 1, 1),
    ]
    # A row of a model says nothing of a group.
    assert {(row["member_count"], row["nested_groups"]) for row in summary["rows"]} == {
        (None, None)
    }
    # The models of switch of every vendor, ranked against each other.
    switches = _rows(make, by="model", filter="catalog.type:eq:switch")
    assert [(label, row["support_weight"]) for label, row in switches.items()] == [
        ("Cisco C9300-48P", "2"),
        ("Juniper EX4400-48P", "1"),
    ]
    # By type is what is of one type whatever its vendor, as before.
    by_type = _rows(make, by="type", filter="catalog.type:eq:switch")
    assert [(label, row["items"], row["type"]) for label, row in by_type.items()] == [
        ("Switch", 3, None)
    ]

    money = make.get("/reports/management", by="model", filter="catalog.type:eq:switch")
    assert [
        (row["label"], row["vendor"], row["pid"], row["est_value"]) for row in money["rows"]
    ] == [
        ("Cisco C9300-48P", "Cisco", "C9300-48P", "2000.00"),
        ("Juniper EX4400-48P", "Juniper", "EX4400-48P", "1000.00"),
    ]
    assert money["totals"]["annual_support_cost"] == "300.00"


def test_the_reports_refuse_what_they_are_not_by(make: Maker) -> None:
    problem = make.get("/reports/management", expect=422, by="health")
    assert problem["status"] == 422
    # A report by anything else says nothing of a group or of a model.
    make.item(catalog_entry_hid=make.entry(make.vendor())["hid"], serial_number="A1")
    (row,) = make.get("/reports/management", by="vendor")["rows"]
    assert (row["label"], row["type"], row["member_count"], row["pid"]) == (
        "Cisco",
        None,
        None,
        None,
    )


def test_a_catalog_entry_says_how_many_items_are_of_it_and_is_sorted_by_it(
    make: Maker,
) -> None:
    cisco = make.vendor()
    busy = make.entry(cisco, "C9300-48P")
    quiet = make.entry(cisco, "C9200L-24P-4G")
    idle = make.entry(make.vendor("Juniper"), "EX4400-48P")
    first, _, retired, archived = make.switches(busy, "site2-sw", 4, lifecycle_state="Prod")
    # A minor item of the model is counted; a draft, a retired item and one in Archived
    # are not (D-152).
    make.item(
        catalog_entry_hid=busy["hid"],
        serial_number="FCW0000Z001",
        parent_item_hid=first["hid"],
        position="1",
    )
    make.item(catalog_entry_hid=busy["hid"], serial_number="DRAFT-1", record_status="draft")
    make.post(f"/items/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)
    make.move(make.move(make.move(archived, "Pending-Removal"), "Released"), "Archived")
    make.item(catalog_entry_hid=quiet["hid"], serial_number="FOC0000Y001")

    listed = make.get("/catalog-entries")["items"]
    assert [(entry["pid"], entry["items"]) for entry in listed] == [
        ("C9200L-24P-4G", 1),
        ("C9300-48P", 3),
        ("EX4400-48P", 0),
    ]
    # The number leads to as many rows of the item list.
    assert make.get("/items", filter=f"catalog_entry_hid:eq:{busy['hid']}")["total"] == 3
    assert make.get(f"/catalog-entries/{busy['hid']}")["items"] == 3
    by_items = make.get("/catalog-entries", sort="-items")["items"]
    assert [entry["pid"] for entry in by_items] == ["C9300-48P", "C9200L-24P-4G", "EX4400-48P"]
    fewest = make.get("/catalog-entries", sort="items,vendor")["items"]
    assert [entry["pid"] for entry in fewest] == ["EX4400-48P", "C9200L-24P-4G", "C9300-48P"]
    assert [
        entry["items"] for entry in make.get("/catalog-entries", fields="pid,items")["items"]
    ] == [1, 3, 0]
    # It is a count to sort by, and not a field to filter by.
    problem = make.get("/catalog-entries", expect=422, filter="items:eq:3")
    assert "filter" in errors(problem)
    assert by_items[-1]["hid"] == idle["hid"]


def test_the_reports_are_printed_by_group_and_by_model(run, make: Maker, campus: dict) -> None:
    table = run("report", "summary", "--by", "group").stdout.splitlines()
    assert table[0].split()[:3] == ["GROUP", "ITEMS", "COMPONENT_COUNT"]
    assert [(line.split()[0], line.split()[1]) for line in table[1:]] == [
        ("Campus", "4"),
        ("east-wlc", "4"),
        ("lobby", "3"),
        ("site2-sw-stack1", "3"),
        ("(none)", "1"),
        ("(all)", "6"),
    ]
    found = json.loads(run("report", "summary", "--by", "group", "--format", "json").stdout)
    assert [(row["label"], row["nested_groups"]) for row in found["rows"]][:2] == [
        ("Campus", 2),
        ("east-wlc", 1),
    ]

    by_model = csv.DictReader(
        io.StringIO(run("report", "management", "--by", "model", "--format", "csv").stdout)
    )
    assert [(row["model"], row["items"], row["est_value"]) for row in by_model] == [
        ("Cisco C9300-48P", "4", "4000.00"),
        ("Juniper AP45", "1", "1000.00"),
        ("(none)", "1", "0.00"),
        ("(all)", "6", "5000.00"),
    ]
    assert "Cisco C9300-48P" in run("report", "summary", "--by", "model").stdout
    run("report", "management", "--by", "condition", expect=4)
