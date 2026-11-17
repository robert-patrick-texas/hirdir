"""A minor item's own groups before the item it is in (P-175): the location, the planned
location and the owner, in the record and in the list, which filters by the same walk."""

from typing import Any

from tests.api.inventory import Maker


def _patch(make: Maker, path: str, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields})


def _in_force(make: Maker, item: dict[str, Any], field: str) -> tuple[Any, str, Any]:
    found = make.get(f"/items/{item['hid']}")["effective"][field]
    return found["value"], found["source"], found["source_hid"]


def _listed(make: Maker, condition: str) -> set[str]:
    page = make.get("/items", filter=condition, minor=1, limit=1000)
    return {row["hid"] for row in page["items"]}


def test_a_minor_items_own_group_comes_before_the_item_it_is_in(make: Maker) -> None:
    places = make.layout()
    lab = make.location("Lab", make.site("Site-3", places["central"]))
    facilities = make.owner("Facilities", is_external=True, exception_reason="the building's")
    network = make.owner("Network Engineering")
    entry = make.entry(make.vendor())
    switch = make.switches(entry, "sw", 1)[0]
    _patch(make, f"/items/{switch['hid']}", location_hid=places["room"]["hid"])
    _patch(make, f"/items/{switch['hid']}", owner_hid=network["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=switch["hid"])
    module = make.item(name="MOD-1", parent_item_hid=switch["hid"])
    pool = make.group(
        "optics-pool",
        "custom",
        [(optic, "member")],
        location_hid=lab["hid"],
        owner_hid=facilities["hid"],
    )

    # The optic's own group decides; the module, in no group, has its switch's.
    assert _in_force(make, optic, "location_hid") == (lab["hid"], "device_group", pool["hid"])
    assert _in_force(make, optic, "owner_hid") == (facilities["hid"], "device_group", pool["hid"])
    assert _in_force(make, module, "location_hid") == (
        places["room"]["hid"],
        "parent_item",
        switch["hid"],
    )
    # The list filters by the same walk.
    assert _listed(make, f"effective.location_hid:eq:{lab['hid']}") == {optic["hid"]}
    assert _listed(make, f"effective.owner_hid:eq:{facilities['hid']}") == {optic["hid"]}
    assert _listed(make, f"effective.location_hid:eq:{places['room']['hid']}") == {
        switch["hid"],
        module["hid"],
    }
    # A value of its own still decides, and an ended membership counts for nothing.
    _patch(make, f"/items/{optic['hid']}", owner_hid=network["hid"])
    assert _in_force(make, optic, "owner_hid")[:2] == (network["hid"], "own")
    member = make.get(f"/device-groups/{pool['hid']}/members")["items"][0]
    make.patch(
        f"/device-groups/{pool['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "left_on": member["joined_on"]},
    )
    assert _in_force(make, optic, "location_hid")[:2] == (places["room"]["hid"], "parent_item")
    assert _listed(make, f"effective.location_hid:eq:{lab['hid']}") == set()
