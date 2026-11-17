"""Why an item and a group have each value: the walk, step by step (P-176)."""

from typing import Any

from tests.api.inventory import Maker
from tests.api.test_operators import _named, _patch, _team


def _walk(make: Maker, path: str, field: str) -> dict[str, Any]:
    found = make.get(f"{path}/resolution")["fields"]
    return next(one for one in found if one["field"] == field)


def _steps(walk: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(step["level"], step["name"], step["label"], step["outcome"]) for step in walk["steps"]]


def test_the_walk_of_an_optic_says_which_step_decides_and_what_is_passed_over(
    make: Maker,
) -> None:
    marks = _team(make)
    places = make.layout()
    _patch(make, f"/sites/{places['site']['hid']}", operator_hid=marks["DW"]["hid"])
    entry = make.entry(make.vendor(), est_value="18000.00")
    switch = make.switches(entry, "sw", 1)[0]
    _patch(make, f"/items/{switch['hid']}", location_hid=places["room"]["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=switch["hid"])
    make.stack("site2-sw", [switch], operator_hid=marks["PR"]["hid"])
    make.group("optics-pool", "custom", [(optic, "member")], operator_hid=marks["RA"]["hid"])
    make.group("aaa-pool", "custom", [(optic, "member")])
    _patch(make, f"/items/{switch['hid']}", operator_hid=marks["LM"]["hid"])

    walk = _walk(make, f"/items/{optic['hid']}", "operator_hid")
    assert (walk["label"], walk["source"]) == ("RA", "device_group")
    assert _steps(walk) == [
        ("own", "SFP-1", None, "nothing"),
        ("device_group", "aaa-pool", None, "nothing"),
        ("device_group", "optics-pool", "RA", "decides"),
        ("parent_item", switch["hostname"], "LM", "passed_over"),
        ("device_group", "site2-sw", "PR", "passed_over"),
        ("location", "Americas > Central > Site-2 > Building 1 > Room 102", None, "nothing"),
        ("location", "Americas > Central > Site-2 > Building 1", None, "nothing"),
        ("site", "Americas > Central > Site-2", "DW", "passed_over"),
        ("region", "Americas > Central", None, "nothing"),
        ("region", "Americas", None, "nothing"),
    ]
    ranks = [(step["name"], step["rank"]) for step in walk["steps"] if step["rank"]]
    assert ranks == [("aaa-pool", 1), ("optics-pool", 2), ("site2-sw", 1)]

    # A value of its own decides, and says what it replaces.
    _patch(make, f"/items/{optic['hid']}", operator_hid=marks["DW"]["hid"])
    walk = _walk(make, f"/items/{optic['hid']}", "operator_hid")
    assert (walk["label"], walk["source"], walk["overrides_label"]) == ("DW", "own", "RA")
    # The model's values: its own, then the catalog's.
    walk = _walk(make, f"/items/{switch['hid']}", "est_value")
    assert [(s["level"], s["value"], s["outcome"]) for s in walk["steps"]] == [
        ("own", None, "nothing"),
        ("catalog", "18000.00", "decides"),
    ]


def test_a_group_walks_up_the_groups_it_is_nested_in(make: Maker) -> None:
    marks = _team(make)
    domain = make.group("east-wlc", "controller_domain", operator_hid=marks["LM"]["hid"])
    cluster = make.group("wlc-pair", "cluster", parent_group_hid=domain["hid"])
    walk = _walk(make, f"/device-groups/{cluster['hid']}", "operator_hid")
    assert _steps(walk) == [
        ("own", "wlc-pair", None, "nothing"),
        ("device_group", "east-wlc", "LM", "decides"),
    ]
    # A retired operator is passed over as retired.
    _patch(make, f"/device-groups/{cluster['hid']}", operator_hid=marks["RA"]["hid"])
    ra = make.get(f"/operators/{marks['RA']['hid']}")
    make.post(f"/operators/{ra['hid']}/retire", {"row_version": ra["row_version"]}, 200)
    walk = _walk(make, f"/device-groups/{cluster['hid']}", "operator_hid")
    assert [step["outcome"] for step in walk["steps"]] == ["retired", "decides"]


def test_the_walk_agrees_with_the_value_in_force_of_every_item(make: Maker) -> None:
    """The value in force and its walk are worked out by the same rules; for every item
    of a varied inventory, each walk ends where the record says the value comes from."""
    marks = _team(make)
    places = make.layout()
    _patch(make, f"/locations/{places['building']['hid']}", operator_hid=marks["RA"]["hid"])
    owner = make.owner("Network Engineering")
    entry = make.entry(make.vendor(), est_value="1000.00", support_weight="2")
    switches = make.switches(entry, "sw", 6)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    module = make.item(name="MOD-1", parent_item_hid=switches[1]["hid"], est_value="5.00")
    make.item(name="SFP-1", parent_item_hid=module["hid"])
    make.stack("stack-b", switches[:2], operator_hid=marks["LM"]["hid"], owner_hid=owner["hid"])
    outer = make.group("domain", "controller_domain", location_hid=places["room"]["hid"])
    make.group("cluster-a", "cluster", [(switches[2], "active")], parent_group_hid=outer["hid"])
    make.group("custom-a", "custom", [(switches[3], "member")], operator_hid=marks["DW"]["hid"])
    make.group(
        "pool", "custom", [({"hid": _named(make, "SFP-1")}, "member")], owner_hid=owner["hid"]
    )
    _patch(make, f"/items/{switches[4]['hid']}", location_hid=places["room"]["hid"])

    everything = make.get("/items", minor=1, limit=1000)["items"]
    assert len(everything) == 9
    for item in everything:
        walks = {
            one["field"]: one for one in make.get(f"/items/{item['hid']}/resolution")["fields"]
        }
        for field in ("location_hid", "planned_location_hid", "operator_hid", "owner_hid"):
            shown, walk = item["effective"][field], walks[field]
            assert (walk["value"], walk["source"], walk["source_hid"]) == (
                shown["value"],
                shown["source"],
                shown["source_hid"],
            ), (item["name"], field)
        for field in ("est_value", "ldos", "do_not_renew"):
            assert walks[field]["value"] == item["effective"][field]["value"], (item["name"], field)
