"""What the review of the server of 0.9.4 found, put right."""

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_operators import _patch, _team
from tests.api.test_weights import put


def _walk(make: Maker, path: str, field: str) -> dict[str, Any]:
    found = make.get(f"{path}/resolution")["fields"]
    return next(one for one in found if one["field"] == field)


def test_a_report_by_group_takes_a_filter_on_the_groups_an_item_is_under(make: Maker) -> None:
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 3)
    domain = make.group("east-wlc", "controller_domain", [(switches[0], "controller")])
    make.group("wlc-pair", "cluster", [(switches[1], "active")], parent_group_hid=domain["hid"])
    for path in ("/reports/summary", "/reports/management"):
        rows = make.get(path, by="group", filter=f"group:within:{domain['hid']}")["rows"]
        assert {row["label"]: row["items"] for row in rows} == {"east-wlc": 2, "wlc-pair": 1}
        assert make.get(path, by="group", filter="group:empty:false")["totals"]["items"] == 2


def test_the_management_report_by_operator_says_how_its_items_have_it(make: Maker) -> None:
    marks = _team(make)
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 2)
    make.group("custom-a", "custom", [(switches[0], "member")], operator_hid=marks["RA"]["hid"])
    _patch(make, f"/items/{switches[1]['hid']}", operator_hid=marks["RA"]["hid"])
    (row,) = [
        r for r in make.get("/reports/management", by="operator")["rows"] if r["label"] == "RA"
    ]
    assert (row["own"], row["from_group"], row["groups_given"]) == (1, 1, 1)


def test_a_member_that_has_the_groups_owner_from_the_group_does_not_disagree(
    make: Maker,
) -> None:
    network = make.owner("Network Engineering")
    facilities = make.owner("Facilities", is_external=True, exception_reason="the building's")
    entry = make.entry(make.vendor())
    switch = make.switches(entry, "sw", 1)[0]
    _patch(make, f"/items/{switch['hid']}", owner_hid=network["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=switch["hid"])
    pool = make.group("optics-pool", "custom", [(optic, "member")], owner_hid=facilities["hid"])
    assert make.get(f"/device-groups/{pool['hid']}")["members_disagree"] == []
    # A member with another owner of its own does.
    _patch(make, f"/items/{optic['hid']}", owner_hid=network["hid"])
    assert make.get(f"/device-groups/{pool['hid']}")["members_disagree"] == ["owner_hid"]


def test_the_walk_of_a_raised_weight_says_what_the_record_says(
    client: TestClient, admin: dict, make: Maker
) -> None:
    put(client, admin, "minimum_item_weight", 1)
    entry = make.entry(make.vendor(), support_weight="0.5")
    switch = make.switches(entry, "sw", 1)[0]
    shown = make.get(f"/items/{switch['hid']}")["effective"]["support_weight"]
    walk = _walk(make, f"/items/{switch['hid']}", "support_weight")
    assert (walk["value"], walk["source"], walk["source_hid"]) == (
        shown["value"],
        shown["source"],
        shown["source_hid"],
    )
    assert [step["outcome"] for step in walk["steps"]] == [
        "nothing",
        "decides",
        "nothing",
        "raises",
    ]
    _patch(make, f"/items/{switch['hid']}", support_weight="0.25")
    walk = _walk(make, f"/items/{switch['hid']}", "support_weight")
    # Without its own it would have the catalog's, raised to the minimum as well.
    assert (walk["value"], walk["source"], walk["overrides"]) == ("1", "own", "1")
    assert walk["steps"][0]["outcome"] == "decides"


def test_a_walk_says_retired_of_a_retired_group_and_a_retired_operator(make: Maker) -> None:
    marks = _team(make)
    top = make.group("top", "controller_domain", operator_hid=marks["LM"]["hid"])
    middle = make.group("middle", "controller_domain", parent_group_hid=top["hid"])
    bottom = make.group("bottom", "cluster", parent_group_hid=middle["hid"])
    now = make.get(f"/device-groups/{middle['hid']}")
    make.post(f"/device-groups/{middle['hid']}/retire", {"row_version": now["row_version"]}, 200)
    walk = _walk(make, f"/device-groups/{bottom['hid']}", "operator_hid")
    assert [(s["name"], s["outcome"]) for s in walk["steps"]] == [
        ("bottom", "nothing"),
        ("middle", "retired"),
    ]
    # In a member's walk, a stack whose operator is retired says so.
    entry = make.entry(make.vendor())
    switch = make.switches(entry, "sw", 1)[0]
    make.stack("stack-a", [switch], operator_hid=marks["RA"]["hid"])
    ra = make.get(f"/operators/{marks['RA']['hid']}")
    make.post(f"/operators/{ra['hid']}/retire", {"row_version": ra["row_version"]}, 200)
    walk = _walk(make, f"/items/{switch['hid']}", "operator_hid")
    assert [(s["name"], s["outcome"]) for s in walk["steps"][:2]] == [
        ("sw-01", "nothing"),
        ("stack-a", "retired"),
    ]


def test_the_exceptions_of_a_group_are_everything_under_it_that_is_anothers(
    make: Maker,
) -> None:
    marks = _team(make)
    ra = marks["RA"]["hid"]
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 2)
    top = make.group("top", "custom", [(switches[0], "member")], operator_hid=ra)
    make.group("inner", "custom", [(switches[1], "member")], parent_group_hid=top["hid"])
    _patch(make, f"/items/{switches[1]['hid']}", operator_hid=marks["LM"]["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=switches[0]["hid"])
    _patch(make, f"/items/{optic['hid']}", operator_hid=marks["LM"]["hid"])
    (group,) = make.get(f"/operators/{ra}/assignments")["groups"]
    assert (group["items"]["count"], group["exceptions"]["count"]) == (1, 2)
    listed = make.get(
        "/items", filter=json.dumps(group["exceptions"]["filter"]), minor=1, limit=10
    )["total"]
    assert listed == 2


def test_a_row_that_names_the_operator_of_its_new_place_leaves_it_inheriting(
    client: TestClient, inventory: dict, make: Maker
) -> None:
    from tests.api.test_files import Files

    marks = _team(make)
    places = make.layout()
    _patch(make, f"/locations/{places['building']['hid']}", operator_hid=marks["RA"]["hid"])
    Files(client, inventory).load(
        "items",
        "name,location,operator\nNEW-SW,Americas > Central > Site-2 > Building 1 > Room 102,RA\n",
    )
    made = make.get("/items", filter="name:eq:NEW-SW")["items"][0]
    assert made["operator_hid"] is None
    assert made["effective"]["operator_hid"]["source"] == "location"


def test_a_large_group_says_which_members_disagree_in_one_statement(make: Maker) -> None:
    network = make.owner("Network Engineering")
    facilities = make.owner("Facilities", is_external=True, exception_reason="the building's")
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 3)
    pool = make.group(
        "pool", "custom", [(one, "member") for one in switches], owner_hid=network["hid"]
    )
    assert make.get(f"/device-groups/{pool['hid']}")["members_disagree"] == []
    _patch(make, f"/items/{switches[2]['hid']}", owner_hid=facilities["hid"])
    assert make.get(f"/device-groups/{pool['hid']}")["members_disagree"] == ["owner_hid"]
    listed = make.get("/device-groups", filter="name:eq:pool")["items"][0]
    assert listed["members_disagree"] == ["owner_hid"]
