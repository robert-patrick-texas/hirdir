"""Replacing an item: two records linked, and the place in a group handed over."""

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

NOBODY = "01900000-0000-7000-8000-000000000000"


def _switches(make: Maker, count: int = 3) -> tuple[dict, list[dict]]:
    entry = make.entry(make.vendor())
    return entry, make.switches(entry, "site2-sw-stack1", count)


def _replace(make: Maker, item: dict, expect: int = 201, **body) -> dict:
    return make.post(
        f"/items/{item['hid']}/replace",
        {"row_version": item["row_version"], "reason": "rma", **body},
        expect,
    )


def test_a_replacement_links_two_items_and_creates_the_new_one(make: Maker) -> None:
    entry, switches = _switches(make, 1)
    old = switches[0]

    made = _replace(
        make,
        old,
        reference="RMA-0000-001",
        replaced_on="2026-11-02",
        new_item={"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X999"},
    )

    assert (made["reason"], made["reference"], made["replaced_on"]) == (
        "rma",
        "RMA-0000-001",
        "2026-11-02",
    )
    new = made["new_item"]
    assert (made["old_item_hid"], made["new_item_hid"]) == (old["hid"], new["hid"])
    assert new["serial_number"] == "FCW0000X999"
    assert new["replaces"] == {
        "hid": made["hid"],
        "item_hid": old["hid"],
        "name": "site2-sw-stack1-01",
        "serial_number": old["serial_number"],
        "reason": "rma",
        "reference": "RMA-0000-001",
        "replaced_on": "2026-11-02",
    }
    assert made["old_item"]["replaced_by"]["item_hid"] == new["hid"]
    assert (made["old_item"]["replaces"], new["replaced_by"]) == (None, None)
    # Neither item is moved in the lifecycle by it.
    assert (made["old_item"]["lifecycle_state"], new["lifecycle_state"]) == (None, None)
    # Both items say so in their own history, and the copy read before is stale.
    for item, field, other in ((old, "replaced_by", new), (new, "replaces", old)):
        event = make.get(f"/items/{item['hid']}/history")["items"][0]
        assert event["action"] == "replace"
        assert {"field": field, "old": None, "new": other["hid"]} in event["changes"]
    assert make.audit(record_type="item_replacement")[0]["action"] == "create"
    assert make.get(f"/items/{old['hid']}")["row_version"] == old["row_version"] + 1


def test_the_new_item_takes_the_place_of_the_old_one_in_its_groups(make: Maker) -> None:
    entry, switches = _switches(make)
    spare = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X999")
    stack = make.stack("site2-sw-stack1", switches)
    domain = make.group("site2-campus", "custom", [(switches[0], "member")])

    made = _replace(make, switches[0], new_item_hid=spare["hid"])
    day = made["replaced_on"]

    again = make.get(f"/device-groups/{stack['hid']}")
    assert (again["hid"], again["member_count"], again["serial_number"]) == (
        stack["hid"],
        3,
        "FCW0000X999",
    )
    every = make.members(stack, include_past="true")
    departed = next(member for member in every if member["item_hid"] == switches[0]["hid"])
    arrived = next(member for member in every if member["item_hid"] == spare["hid"])
    # Left out, the day of the replacement is today, where the application is.
    assert departed["left_on"] == day
    assert (arrived["role"], arrived["position"], arrived["joined_on"], arrived["left_on"]) == (
        "master",
        1,
        day,
        None,
    )
    assert [member["item_hid"] for member in make.members(domain)] == [spare["hid"]]
    assert make.get(f"/items/{switches[0]['hid']}")["groups"] == []
    assert len(make.get(f"/items/{spare['hid']}")["groups"]) == 2


def test_a_replacement_that_would_break_a_group_changes_nothing(make: Maker) -> None:
    entry, switches = _switches(make)
    stack = make.stack("site2-sw-stack1", switches[:2])
    other = make.stack("site2-sw-stack2", [switches[2], make.item(name="fourth")])

    # The item that is to take the place is in another stack already.
    problem = _replace(make, switches[0], new_item_hid=switches[2]["hid"], expect=409)
    assert "one stack at a time" in errors(problem)["item_hid"]
    # A minor item is not a member of a stack.
    part = make.item(name="PS-A", parent_item_hid=switches[2]["hid"])
    problem = _replace(make, switches[0], new_item_hid=part["hid"], expect=422)
    assert "major items" in errors(problem)["item_hid"]
    # The day is before the day the item joined.
    problem = _replace(
        make,
        switches[0],
        replaced_on="2001-01-01",
        new_item={"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X999"},
        expect=422,
    )
    assert "after this day" in errors(problem)["replaced_on"]

    assert make.audit(record_type="item_replacement") == []
    assert make.get("/items", filter="serial_number:eq:FCW0000X999")["total"] == 0
    assert [member["item_hid"] for member in make.members(stack)] == [
        switches[0]["hid"],
        switches[1]["hid"],
    ]
    assert make.get(f"/device-groups/{other['hid']}")["member_count"] == 2
    assert make.get(f"/items/{switches[0]['hid']}")["row_version"] == switches[0]["row_version"]


def test_an_item_is_replaced_once_and_takes_the_place_of_one(make: Maker) -> None:
    _, switches = _switches(make)
    first, second, third = switches
    _replace(make, first, new_item_hid=second["hid"])

    current = make.get(f"/items/{first['hid']}")
    problem = _replace(make, current, new_item_hid=third["hid"], expect=409)
    assert "replaced already" in problem["detail"]
    problem = _replace(make, third, new_item_hid=second["hid"], expect=409)
    assert "took the place of another already" in problem["detail"]
    # A chain is fine: the one that took a place is itself replaced later.
    second = make.get(f"/items/{second['hid']}")
    _replace(make, second, new_item_hid=third["hid"], reason="refresh")
    middle = make.get(f"/items/{second['hid']}")
    assert (middle["replaces"]["item_hid"], middle["replaced_by"]["item_hid"]) == (
        first["hid"],
        third["hid"],
    )


def test_what_a_replacement_needs(make: Maker) -> None:
    entry, switches = _switches(make, 2)
    old, other = switches
    new_item = {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X999"}

    problem = _replace(make, old, expect=422)
    assert "and not both" in errors(problem)["new_item_hid"]
    problem = _replace(make, old, new_item_hid=other["hid"], new_item=new_item, expect=422)
    assert "and not both" in errors(problem)["new_item_hid"]
    problem = _replace(make, old, new_item_hid=old["hid"], expect=422)
    assert errors(problem) == {"new_item_hid": "name another item"}
    problem = _replace(make, old, new_item_hid=NOBODY, expect=422)
    assert "there is no item" in errors(problem)["new_item_hid"]
    problem = _replace(make, old, new_item_hid=other["hid"], reason="whim", expect=422)
    assert "reason" in errors(problem)
    problem = _replace(make, old, new_item={"serial_number": "no model"}, expect=422)
    assert "serial_number" in errors(problem)
    stale = make.post(
        f"/items/{old['hid']}/replace",
        {"row_version": old["row_version"] + 5, "reason": "rma", "new_item_hid": other["hid"]},
        expect=409,
    )
    assert stale["status"] == 409
    make.post(
        f"/items/{NOBODY}/replace",
        {"row_version": 1, "reason": "rma", "new_item_hid": other["hid"]},
        expect=404,
    )
    assert make.audit(record_type="item_replacement") == []


def test_a_reason_in_use_is_not_removed_from_its_list(make: Maker) -> None:
    _, switches = _switches(make, 2)
    _replace(make, switches[0], new_item_hid=switches[1]["hid"], reason="RMA")
    choice = next(
        one for one in make.get("/choices", list="replacement_reason") if one["value"] == "rma"
    )
    response = make.client.delete(f"{API}/choices/{choice['hid']}", headers=make.headers)
    assert response.status_code == 409


def test_replacing_needs_the_inventory_role(client: TestClient, make: Maker, viewer: dict) -> None:
    _, switches = _switches(make, 2)
    response = client.post(
        f"{API}/items/{switches[0]['hid']}/replace",
        json={"row_version": 1, "reason": "rma", "new_item_hid": switches[1]["hid"]},
        headers=viewer,
    )
    assert response.status_code == 403
