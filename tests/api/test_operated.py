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
