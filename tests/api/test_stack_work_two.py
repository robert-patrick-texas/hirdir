"""Working a stack, part two: a member replaced in one press (P-242), the condition given
with an end (P-245), a stack made of a switch that stands alone (P-243), and a
replacement that was a mistake removed by an Admin (P-238)."""

from typing import Any

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.api.test_stack_work import (
    LATER,
    STACK,
    _changed,
    _day,
    _end,
    _in_service,
    _item,
    _places,
    _spare,
)

NOBODY = "01900000-0000-7000-8000-000000000000"


def _replace(make: Maker, old: dict[str, Any], expect: int = 201, **body: Any) -> dict[str, Any]:
    now = _item(make, old)
    return make.post(
        f"/items/{old['hid']}/replace",
        {"row_version": now["row_version"], "reason": "rma", **body},
        expect,
    )


def _replacing(event: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in event["changes"] if entry["field"] == "replacing"]


# --- a member replaced in one press (P-242) ------------------------------------------


def test_a_failed_member_is_replaced_by_a_spare_in_one_request(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed = switches[1]
    spare = _spare(make, 21, places["depot"])
    address = make.address(spare, "192.0.2.21", is_primary=True)

    made = _replace(
        make,
        failed,
        new_item_hid=spare["hid"],
        reference="RMA-0000-021",
        drop_identity=True,
        disposition="Production",
        expected_online=True,
        old_item={
            "lifecycle_state": "Pending-Removal",
            "state_reason": "rma",
            "condition": "failed",
        },
    )

    # The spare is in the failed member's position, with the stack's name and place.
    came = _item(make, spare)
    assert (came["hostname"], came["fqdn"], came["location_hid"], came["addresses"]) == (
        None,
        None,
        None,
        [],
    )
    assert came["effective"]["location_hid"]["source_hid"] == stack["hid"]
    assert (came["disposition"], came["expected_online"]) == ("Production", True)
    assert [(one["position"], one["role"]) for one in came["groups"]] == [(2, "member")]
    # The failed member left, waits to go back to the manufacturer, and is marked failed.
    left = _item(make, failed)
    assert (left["groups"], left["lifecycle_state"], left["state_reason"]) == (
        [],
        "Pending-Removal",
        "rma",
    )
    assert left["condition"] == "failed"
    # Each change is the item's own, in the request of the replacement, and says it.
    replacement = make.audit(record_type="item_replacement")[0]
    events = make.audit(request_id=replacement["request_id"])
    spare_change = next(
        one
        for one in events
        if (one["record_hid"], one["action"]) == (spare["hid"], "update")
        and "replacing" in _changed(one)
    )
    assert _changed(spare_change)["hostname"] == ("spare-sw-021", None)
    assert _replacing(spare_change) == [{"field": "replacing", "old": None, "new": made["hid"]}]
    gone = next(one for one in events if one["record_hid"] == address["hid"])
    assert (gone["action"], _changed(gone)["replacing"]) == ("delete", (None, made["hid"]))
    by_old = [one for one in events if one["record_hid"] == failed["hid"]]
    assert {one["action"] for one in by_old} >= {"update", "transition", "replace"}
    for one in by_old:
        if one["action"] in ("update", "transition"):
            assert _replacing(one) == [{"field": "replacing", "old": None, "new": made["hid"]}]
    # The answer has both items as they are now.
    assert made["old_item"]["lifecycle_state"] == "Pending-Removal"
    assert made["new_item"]["hostname"] is None


def test_a_new_item_created_by_the_replacement_takes_the_stacks_name(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    made = _replace(
        make,
        switches[0],
        new_item={
            "catalog_entry_hid": switches[0]["catalog_entry_hid"],
            "serial_number": "FCW9000X0099",
            "hostname": "new-sw-099",
            "lifecycle_state": "Prod",
            "disposition": "Spare",
            "expected_online": False,
        },
        drop_identity=True,
        disposition="Production",
        expected_online=True,
    )
    new = made["new_item"]
    assert (new["hostname"], new["disposition"], new["expected_online"]) == (
        None,
        "Production",
        True,
    )
    assert [one["group_hid"] for one in new["groups"]] == [stack["hid"]]


def test_what_a_replacement_carries_is_refused_and_nothing_is_done(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed = switches[1]
    spare = _spare(make, 22, places["depot"])
    loose = _spare(make, 23, places["depot"])
    retired = make.location("Old Room", places["site"], kind="room")
    make.post(f"/locations/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)
    day = _day(make, stack)

    refusals = [
        # A disposition the spare's state does not allow.
        ({"disposition": "Nowhere"}, "disposition"),
        # Production in Prod is expected online.
        ({"disposition": "Production", "expected_online": False}, "expected_online"),
        # What becomes of the old item, by its own rules.
        ({"old_item": {"lifecycle_state": "Delivered"}}, "old_item.lifecycle_state"),
        ({"old_item": {"condition": "shiny"}}, "old_item.condition"),
        ({"old_item": {"state_reason": "rma"}}, "old_item.state_reason"),
        ({"old_item": {"location_hid": retired["hid"]}}, "old_item.location_hid"),
        # And on a day to come.
        ({"old_item": {"hostname": "x"}, "replaced_on": LATER}, "replaced_on"),
    ]
    for given, field in refusals:
        problem = _replace(make, failed, 422, new_item_hid=spare["hid"], **given)
        assert set(errors(problem)) == {field}, given
    # The name and place of a stack, where the item that leaves is in none.
    problem = _replace(make, loose, 422, new_item_hid=spare["hid"], drop_identity=True)
    assert set(errors(problem)) == {"drop_identity"}

    # Nothing was done: no replacement, no membership ended, neither item changed.
    assert make.audit(record_type="item_replacement") == []
    assert [one["item_hid"] for one in make.members(stack)] == [
        switch["hid"] for switch in switches
    ]
    assert _item(make, spare)["hostname"] == "spare-sw-022"
    assert _item(make, spare)["row_version"] == spare["row_version"]
    assert _item(make, failed)["row_version"] == failed["row_version"]
    assert make.members(stack, include_past="true")[-1]["left_on"] is None
    assert day == make.members(stack)[0]["joined_on"]


# --- the condition with an end (P-245) -----------------------------------------------


def test_a_member_that_leaves_is_given_its_condition_with_the_end(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed, worn = switches[1], switches[2]
    make.patch(
        f"/items/{worn['hid']}",
        {"row_version": _item(make, worn)["row_version"], "condition": "degraded"},
    )

    _end(
        make,
        stack,
        failed,
        left_on=_day(make, stack),
        item={"lifecycle_state": "Pending-Removal", "state_reason": "rma", "condition": "failed"},
    )
    marked = _item(make, failed)
    assert (marked["lifecycle_state"], marked["condition"]) == ("Pending-Removal", "failed")
    event = next(
        one
        for one in make.audit(record_type="item", record_hid=failed["hid"])
        if "condition" in _changed(one)
    )
    assert _changed(event)["condition"] == (None, "failed")
    assert _changed(event)["leaving_group"] == (stack["hid"], None)

    # Null clears it, and a value not of the list is refused with the end.
    problem = _end(make, stack, worn, 422, left_on=_day(make, stack), item={"condition": "shiny"})
    assert set(errors(problem)) == {"item.condition"}
    _end(make, stack, worn, left_on=_day(make, stack), item={"condition": None})
    assert _item(make, worn)["condition"] is None


def test_the_end_of_a_membership_sets_no_condition_by_a_rule(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    _end(
        make,
        stack,
        switches[1],
        left_on=_day(make, stack),
        item={"lifecycle_state": "Pending-Removal", "state_reason": "rma"},
    )
    assert _item(make, switches[1])["condition"] is None


def test_replacing_with_what_each_carries_needs_the_inventory_role(
    client: TestClient, make: Maker, viewer: dict
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    response = client.post(
        f"{API}/items/{switches[0]['hid']}/replace",
        json={
            "row_version": 1,
            "reason": "rma",
            "new_item_hid": NOBODY,
            "drop_identity": True,
        },
        headers=viewer,
    )
    assert response.status_code == 403
    assert make.get(f"/device-groups/{stack['hid']}")["hostname"] == STACK
