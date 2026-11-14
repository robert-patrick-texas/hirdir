"""Minor items: what is installed in an item, and what it has from the item it is in."""

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors


def _switch(make: Maker, **more) -> dict:
    entry = make.entry(make.vendor())
    owner = make.owner()
    return make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW0000X001",
        hostname="site2-sw-access-01",
        owner_hid=owner["hid"],
        lifecycle_state="Prod",
        **more,
    )


def _part(make: Maker, parent: dict, name: str = "PS-A", **more) -> dict:
    return make.item(name=name, parent_item_hid=parent["hid"], position=name, **more)


def test_a_minor_item_has_the_owner_and_the_standing_of_the_item_it_is_in(make: Maker) -> None:
    switch = _switch(make)
    part = _part(make, switch)

    assert (part["is_major"], part["depth"], part["position"]) == (False, 1, "PS-A")
    assert part["parent"]["hid"] == switch["hid"]
    assert part["parent"]["serial_number"] == "FCW0000X001"
    assert (part["owner_hid"], part["lifecycle_state"], part["disposition"]) == (None, None, None)
    effective = part["effective"]
    assert effective["owner_hid"] == {
        "value": switch["owner_hid"],
        "label": "Network Engineering",
        "source": "parent_item",
        "source_hid": switch["hid"],
    }
    for name, value in (
        ("lifecycle_state", "Prod"),
        ("disposition", "Production"),
        ("expected_online", True),
    ):
        assert effective[name]["value"] == value
        assert effective[name]["source"] == "parent_item"
        assert effective[name]["source_hid"] == switch["hid"]
    again = make.get(f"/items/{switch['hid']}")
    assert (again["is_major"], again["depth"], again["minor_items"]) == (True, 0, 1)
    assert again["effective"]["owner_hid"]["source"] == "own"
    assert again["effective"]["lifecycle_state"]["source"] == "own"


def test_what_is_inherited_comes_from_the_nearest_item_that_has_it(make: Maker) -> None:
    chassis = _switch(make)
    other = make.owner("Voice Services")
    blade = _part(make, chassis, "Bay 1", owner_hid=other["hid"])
    module = _part(make, blade, "Slot 1")

    effective = module["effective"]
    assert module["depth"] == 2
    # The owner is the blade's, and the standing is the chassis's: the blade has none.
    assert (effective["owner_hid"]["label"], effective["owner_hid"]["source_hid"]) == (
        "Voice Services",
        blade["hid"],
    )
    assert (effective["lifecycle_state"]["value"], effective["lifecycle_state"]["source_hid"]) == (
        "Prod",
        chassis["hid"],
    )


def test_the_standing_is_taken_as_a_whole_from_one_item(make: Maker) -> None:
    switch = _switch(make)
    part = _part(make, switch)

    # With a state of its own, the minor item has its own disposition and intent too.
    moved = make.move(part, "Pending-Removal", reason="rma")
    effective = moved["effective"]
    assert moved["lifecycle_state"] == "Pending-Removal"
    assert effective["lifecycle_state"]["source"] == "own"
    assert effective["disposition"] == {"value": None, "source": "none", "source_hid": None}
    assert effective["expected_online"]["value"] is False
    assert effective["owner_hid"]["source"] == "parent_item"

    # Back to no state, it has the standing of its switch again, and the move is on record.
    back = make.move(moved, None, reason="found")
    assert back["lifecycle_state"] is None
    assert back["effective"]["lifecycle_state"]["value"] == "Prod"
    assert back["effective"]["lifecycle_state"]["source"] == "parent_item"
    event = make.audit(record_hid=part["hid"])[0]
    assert event["action"] == "transition"
    assert {"field": "lifecycle_state", "old": "Pending-Removal", "new": None} in event["changes"]
    assert {"field": "state_reason", "old": "rma", "new": "found"} in event["changes"]

    problem = make.move(back, None, expect=422)
    assert "already has the standing" in errors(problem)["to"]


def test_the_state_of_a_major_item_is_never_cleared(make: Maker) -> None:
    switch = _switch(make)
    problem = make.move(switch, None, expect=422)
    assert "leaves a state by moving to another" in errors(problem)["to"]


def test_moving_the_parent_writes_to_none_of_its_minor_items(make: Maker) -> None:
    switch = _switch(make)
    part = _part(make, switch)

    make.move(switch, "Down", reason="maintenance")

    after = make.get(f"/items/{part['hid']}")
    assert after["row_version"] == part["row_version"]
    assert after["updated_at"] == part["updated_at"]
    assert after["effective"]["lifecycle_state"]["value"] == "Down"
    assert make.audit(record_hid=part["hid"], action="transition") == []


def test_minor_items_nest_three_deep_and_no_deeper(make: Maker) -> None:
    chassis = _switch(make)
    blade = _part(make, chassis, "Bay 1")
    module = _part(make, blade, "Slot 1")
    optic = _part(make, module, "Port 1")
    assert optic["depth"] == 3

    problem = make.post("/items", {"name": "too deep", "parent_item_hid": optic["hid"]}, expect=422)
    assert "at most 3 deep" in errors(problem)["parent_item_hid"]

    # An item with minor items of its own is not put where they would end up too deep.
    other = make.item(name="another chassis")
    problem = make.patch(
        f"/items/{chassis['hid']}",
        {"row_version": chassis["row_version"], "parent_item_hid": other["hid"]},
        expect=422,
    )
    assert "at most 3 deep" in errors(problem)["parent_item_hid"]


def test_an_item_is_never_above_itself(make: Maker) -> None:
    chassis = _switch(make)
    blade = _part(make, chassis, "Bay 1")

    for parent in (chassis, blade):
        problem = make.patch(
            f"/items/{chassis['hid']}",
            {"row_version": chassis["row_version"], "parent_item_hid": parent["hid"]},
            expect=422,
        )
        assert "one of its own minor items" in errors(problem)["parent_item_hid"]


def test_a_parent_must_exist_and_not_be_retired(make: Maker) -> None:
    problem = make.post(
        "/items",
        {"name": "PS-A", "parent_item_hid": "01900000-0000-7000-8000-000000000000"},
        expect=422,
    )
    assert "there is no item" in errors(problem)["parent_item_hid"]

    switch = _switch(make)
    make.post(f"/items/{switch['hid']}/retire", {"row_version": switch["row_version"]}, 200)
    problem = make.post("/items", {"name": "PS-A", "parent_item_hid": switch["hid"]}, expect=422)
    assert errors(problem) == {"parent_item_hid": "this item is retired"}


def test_only_a_minor_item_has_a_position(make: Maker) -> None:
    problem = make.post("/items", {"name": "loose supply", "position": "PS-A"}, expect=422)
    assert "name the item it is in" in errors(problem)["position"]

    switch = _switch(make)
    part = _part(make, switch)
    # Taken out of its parent, the item keeps its record and its history, is a major
    # item with what is its own, and has no place in the parent any more.
    out = make.patch(
        f"/items/{part['hid']}", {"row_version": part["row_version"], "parent_item_hid": None}
    )
    assert (out["is_major"], out["parent"], out["position"]) == (True, None, None)
    assert out["effective"]["owner_hid"]["source"] == "none"
    assert out["effective"]["lifecycle_state"]["value"] is None
    changed = {change["field"] for change in make.audit(record_hid=part["hid"])[0]["changes"]}
    assert changed == {"parent_item_hid", "position"}
    assert make.get(f"/items/{part['hid']}/history")["total"] == 2


def test_the_children_of_an_item_are_listed_by_position(make: Maker) -> None:
    switch = _switch(make)
    for name in ("Slot 1", "PS-B", "PS-A"):
        _part(make, switch, name)
    _part(make, make.item(name="another switch"), "PS-A")

    page = make.get(f"/items/{switch['hid']}/children")
    assert page["total"] == 3
    assert [child["position"] for child in page["items"]] == ["PS-A", "PS-B", "Slot 1"]
    assert (
        make.get(f"/items/{switch['hid']}/children", limit=1, offset=1)["items"][0]["position"]
        == "PS-B"
    )
    make.get("/items/01900000-0000-7000-8000-000000000000/children", expect=404)


def test_the_list_tells_major_items_from_minor_ones(make: Maker) -> None:
    chassis = _switch(make)
    blade = _part(make, chassis, "Bay 1")
    _part(make, blade, "Slot 1")

    assert make.found(filter="is_major:eq:true") == ["site2-sw-access-01"]
    assert make.found(filter="is_major:eq:false") == ["Bay 1", "Slot 1"]
    assert make.found(filter="depth:eq:2") == ["Slot 1"]
    assert make.found(filter="depth:gte:1", sort="-depth") == ["Slot 1", "Bay 1"]
    assert make.found(filter=f"parent_item_hid:eq:{chassis['hid']}") == ["Bay 1"]
    assert make.found(filter="position:prefix:slot") == ["Slot 1"]
    assert make.found(filter="parent.name:eq:bay 1") == ["Slot 1"]
    assert make.found(filter="parent.name:empty:false", sort="-parent.name") == ["Bay 1", "Slot 1"]
    assert make.found(sort="depth,name") == ["site2-sw-access-01", "Bay 1", "Slot 1"]


def test_filters_see_what_a_minor_item_has_in_force(make: Maker) -> None:
    switch = _switch(make)
    _part(make, switch)
    make.item(name="loose supply")

    # Its own state is blank, and the state in force is its switch's.
    assert make.found(filter="lifecycle_state:eq:Prod") == ["site2-sw-access-01"]
    assert make.found(filter="effective.lifecycle_state:eq:Prod") == [
        "PS-A",
        "site2-sw-access-01",
    ]
    assert make.found(filter="effective.disposition:eq:Production is_major:eq:false") == ["PS-A"]
    assert make.found(filter="effective.expected_online:eq:true is_major:eq:false") == ["PS-A"]
    assert make.found(filter=f"effective.owner_hid:eq:{switch['owner_hid']}") == [
        "PS-A",
        "site2-sw-access-01",
    ]
    # The owner a list names and sorts by is the owner in force.
    assert make.found(filter="owner.label:eq:network engineering") == [
        "PS-A",
        "site2-sw-access-01",
    ]
    assert make.found(filter="owner.label:empty:true") == ["loose supply"]


def test_a_minor_item_of_an_archived_item_is_left_out_with_it(make: Maker, admin: dict) -> None:
    switch = _switch(make)
    _part(make, switch)
    forced = Maker(make.client, admin)
    forced.move(make.get(f"/items/{switch['hid']}"), "Archived", reason="disposed", force=True)

    assert make.found() == []
    assert make.found(include_archived="true") == ["PS-A", "site2-sw-access-01"]


def test_a_minor_item_is_made_and_changed_by_the_inventory_role_only(
    client: TestClient, make: Maker, viewer: dict
) -> None:
    switch = _switch(make)
    part = _part(make, switch)
    refused = client.patch(
        f"{API}/items/{part['hid']}",
        json={"row_version": part["row_version"], "position": "PS-B"},
        headers=viewer,
    )
    assert refused.status_code == 403
    listed = client.get(f"{API}/items/{switch['hid']}/children", headers=viewer)
    assert listed.status_code == 200
    created = make.audit(record_hid=part["hid"])[0]
    assert created["action"] == "create"
    assert {"field": "parent_item_hid", "old": None, "new": switch["hid"]} in created["changes"]
