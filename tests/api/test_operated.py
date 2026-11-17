"""What an operator is on, and how (P-177): each place and group given it, the items
that have it from each, what beneath each has it too and what is another's."""

import json
from typing import Any

from tests.api.inventory import Maker
from tests.api.test_operators import _patch, _team


def _listed(make: Maker, count: dict[str, Any]) -> int:
    """Return how many items the filter of a count lists: what a link from it shows."""
    return make.get("/items", filter=json.dumps(count["filter"]), minor=1, limit=1)["total"]


def test_what_an_operator_is_on_is_counted_by_the_filters_it_links_to(make: Maker) -> None:
    marks = _team(make)
    ra = marks["RA"]["hid"]
    places = make.layout()
    _patch(make, f"/locations/{places['building']['hid']}", operator_hid=ra)
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 6)
    for switch in switches[:3]:
        _patch(make, f"/items/{switch['hid']}", location_hid=places["room"]["hid"])
    # One in the room is someone else's: an exception under the building.
    _patch(make, f"/items/{switches[2]['hid']}", operator_hid=marks["LM"]["hid"])
    pool = make.group(
        "custom-a",
        "custom",
        [(switches[3], "member"), (switches[4], "member")],
        operator_hid=ra,
    )
    make.group("inner", "custom", parent_group_hid=pool["hid"])
    _patch(make, f"/items/{switches[4]['hid']}", operator_hid=marks["DW"]["hid"])
    _patch(make, f"/items/{switches[5]['hid']}", operator_hid=ra)
    make.item(name="PS-A", parent_item_hid=switches[5]["hid"])

    found = make.get(f"/operators/{ra}/assignments")
    (building,) = found["places"]
    assert (building["level"], building["path"]) == (
        "location",
        "Americas > Central > Site-2 > Building 1",
    )
    assert building["items"]["count"] == 2
    assert building["exceptions"]["count"] == 1
    assert [one["path"] for one in building["places_beneath"]["shown"]] == [
        "Americas > Central > Site-2 > Building 1 > Room 102"
    ]
    (group,) = found["groups"]
    assert (group["name"], group["items"]["count"], group["exceptions"]["count"]) == (
        "custom-a",
        1,
        1,
    )
    assert [one["name"] for one in group["groups_beneath"]["shown"]] == ["inner"]
    assert (found["own"]["count"], found["from_item"]["count"]) == (1, 1)
    assert found["totals"]["count"] == 5
    assert (
        building["items"]["count"]
        + group["items"]["count"]
        + found["own"]["count"]
        + found["from_item"]["count"]
        == found["totals"]["count"]
    )
    for count in (
        building["items"],
        building["exceptions"],
        group["items"],
        group["exceptions"],
        found["own"],
        found["from_item"],
        found["totals"],
    ):
        assert _listed(make, count) == count["count"], count["filter"]


def test_the_summary_by_operator_says_how_its_items_have_it(make: Maker) -> None:
    """The leaderboard of operators: how the items of each have it, which add up to its
    items, and the groups and places given it (P-178)."""
    marks = _team(make)
    ra = marks["RA"]["hid"]
    places = make.layout()
    _patch(make, f"/locations/{places['building']['hid']}", operator_hid=ra)
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 4)
    _patch(make, f"/items/{switches[0]['hid']}", location_hid=places["room"]["hid"])
    make.group("custom-a", "custom", [(switches[1], "member")], operator_hid=ra)
    _patch(make, f"/items/{switches[2]['hid']}", operator_hid=ra)
    make.item(name="PS-A", parent_item_hid=switches[2]["hid"])

    rows = {row["label"]: row for row in make.get("/reports/summary", by="operator")["rows"]}
    mine = rows["RA"]
    split = {name: mine[name] for name in ("own", "from_item", "from_group", "from_place")}
    assert split == {"own": 1, "from_item": 1, "from_group": 1, "from_place": 1}
    assert sum(split.values()) == mine["items"]
    assert (mine["groups_given"], mine["places_given"]) == (1, 1)
    # The blank row, and a row by anything else, say none of it.
    assert rows[None]["own"] is None
    by_vendor = make.get("/reports/summary", by="vendor")["rows"][0]
    assert by_vendor["groups_given"] is None
