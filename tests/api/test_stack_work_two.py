"""Working a stack, part two: a member replaced in one press (P-242), the condition given
with an end (P-245), a stack made of a switch that stands alone (P-243), and a
replacement that was a mistake removed by an Admin (P-238)."""

from typing import Any

from fastapi.testclient import TestClient

from tests.api import test_cli
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
# The fixture that runs `hirdir` against the test client.
run = test_cli.run


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
        # And on a day to come, for either item: what a replacement changes of either is
        # done with the request, and a spare dated ahead is not stripped today.
        ({"old_item": {"hostname": "x"}, "replaced_on": LATER}, "replaced_on"),
        ({"drop_identity": True, "replaced_on": LATER}, "replaced_on"),
        ({"disposition": "Production", "replaced_on": LATER}, "replaced_on"),
        ({"expected_online": True, "replaced_on": LATER}, "replaced_on"),
    ]
    for given, field in refusals:
        problem = _replace(make, failed, 422, new_item_hid=spare["hid"], **given)
        assert set(errors(problem)) == {field}, given
    # The name and place of a stack, where the item that leaves is in none.
    problem = _replace(make, loose, 422, new_item_hid=spare["hid"], drop_identity=True)
    assert set(errors(problem)) == {"drop_identity"}
    # A spare with an address gives it up, and the old item is then refused a disposition
    # its state does not allow: the address the spare gave up is there again.
    address = make.address(spare, "192.0.2.22", is_primary=True)
    spare = _item(make, spare)
    problem = _replace(
        make,
        failed,
        422,
        new_item_hid=spare["hid"],
        drop_identity=True,
        disposition="Production",
        expected_online=True,
        old_item={"disposition": "Excess"},
    )
    assert set(errors(problem)) == {"old_item.disposition"}
    kept = _item(make, spare)
    assert [one["hid"] for one in kept["addresses"]] == [address["hid"]]
    assert (kept["location_hid"], kept["disposition"]) == (places["depot"]["hid"], "Spare")
    assert make.audit(record_type="address", action="delete") == []

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


# --- a stack made of a switch that stands alone (P-243) ------------------------------


def _alone(make: Maker, places: dict[str, Any]) -> dict[str, Any]:
    """A switch in service that stands alone, with a name, a place and addresses of its own."""
    owner = make.owner()
    operator = make.post("/operators", {"label": "LM"})
    plan = make.site("Site-3", places["central"], record_status="draft")
    places["suite"] = make.location("Suite 300", plan, kind="room")
    return _spare(
        make,
        31,
        places["room"],
        hostname="cw07-idf04-acc1",
        fqdn="cw07-idf04-acc1.example.net",
        name="cw07-idf04-acc1",
        disposition="Production",
        expected_online=True,
        owner_hid=owner["hid"],
        operator_hid=operator["hid"],
        planned_location_hid=places["suite"]["hid"],
        condition="good",
    )


def _make_stack(make: Maker, item: dict[str, Any], expect: int = 201, **body: Any) -> dict:
    now = _item(make, item)
    return make.post(
        f"/items/{item['hid']}/make-stack", {"row_version": now["row_version"], **body}, expect
    )


STACK_HOLDS = (
    "hostname",
    "fqdn",
    "location_hid",
    "planned_location_hid",
    "owner_hid",
    "operator_hid",
)


def test_a_switch_that_stands_alone_is_made_a_stack_in_one_request(make: Maker) -> None:
    places = _places(make)
    switch = _alone(make, places)
    network = make.network("CORP-MGMT")
    primary = make.address(switch, "192.0.2.31", network, is_primary=True)
    loopback = make.address(switch, "198.51.100.31", role="loopback")
    before = _item(make, switch)

    stack = _make_stack(make, switch)

    # The stack has the switch's own name, and what a stack holds for its members.
    assert (stack["type"], stack["name"], stack["hostname"], stack["fqdn"]) == (
        "stack",
        "cw07-idf04-acc1",
        "cw07-idf04-acc1",
        "cw07-idf04-acc1.example.net",
    )
    # An active item makes an active stack.
    assert stack["record_status"] == "active"
    for field in ("location_hid", "planned_location_hid", "owner_hid", "operator_hid"):
        assert stack[field] == before[field], field
    # Each address moved as it is: its HID, network, role and primary mark.
    moved = {one["hid"]: one for one in stack["addresses"]}
    assert set(moved) == {primary["hid"], loopback["hid"]}
    assert (moved[primary["hid"]]["is_primary"], moved[primary["hid"]]["network"]) == (
        True,
        "CORP-MGMT",
    )
    assert moved[loopback["hid"]]["role"] == "loopback"
    # The switch gave each up, has them from the stack, and kept the rest.
    after = _item(make, switch)
    for field in STACK_HOLDS:
        assert after[field] is None, field
    assert after["addresses"] == []
    for field in ("location_hid", "owner_hid", "operator_hid", "planned_location_hid"):
        assert after["effective"][field]["source_hid"] == stack["hid"], field
    for field in ("name", "serial_number", "lifecycle_state", "disposition", "condition"):
        assert after[field] == before[field], field
    assert [(one["group_hid"], one["position"]) for one in after["groups"]] == [(stack["hid"], 1)]

    # Every part is audited, and each but the stack's making names the stack.
    events = make.audit(request_id=make.audit(record_hid=stack["hid"])[0]["request_id"])
    by_kind = {(one["record_type"], one["action"]) for one in events}
    assert by_kind >= {
        ("device_group", "create"),
        ("device_group_member", "create"),
        ("item", "update"),
        ("address", "update"),
    }
    joined = {"field": "joining_group", "old": None, "new": stack["hid"]}
    for one in events:
        if one["record_type"] != "device_group":
            assert joined in one["changes"], one
    change = next(one for one in events if one["record_type"] == "item")
    assert _changed(change)["hostname"] == ("cw07-idf04-acc1", None)
    assert _changed(change)["owner_hid"] == (before["owner_hid"], None)
    address_event = next(one for one in events if one["record_hid"] == primary["hid"])
    assert _changed(address_event)["item_hid"] == (switch["hid"], None)
    assert _changed(address_event)["group_hid"] == (None, stack["hid"])
    assert make.audit(record_hid=primary["hid"])[0]["hid"] == address_event["hid"]


def test_a_stack_made_of_a_draft_is_a_draft(make: Maker) -> None:
    places = _places(make)
    draft = _spare(make, 37, places["depot"], record_status="draft")
    stack = _make_stack(make, draft)
    assert (stack["name"], stack["record_status"]) == ("spare-sw-037", "draft")
    assert [one["item_hid"] for one in make.members(stack)] == [draft["hid"]]
    assert _item(make, draft)["record_status"] == "draft"


def test_a_stack_made_with_a_name_and_a_second_switch(make: Maker) -> None:
    places = _places(make)
    switch = _alone(make, places)
    spare = _spare(make, 32, places["depot"])
    make.address(spare, "192.0.2.32")

    stack = _make_stack(
        make,
        switch,
        name="cw07-idf04-stack",
        members=[
            {
                "item_hid": spare["hid"],
                "drop_identity": True,
                "disposition": "Production",
                "expected_online": True,
            }
        ],
    )

    assert (stack["name"], stack["member_count"]) == ("cw07-idf04-stack", 2)
    assert [(one["position"], one["item_hid"]) for one in make.members(stack)] == [
        (1, switch["hid"]),
        (2, spare["hid"]),
    ]
    second = _item(make, spare)
    assert (second["hostname"], second["addresses"], second["disposition"]) == (
        None,
        [],
        "Production",
    )


def test_a_stack_is_not_made_of_what_may_not_be_in_one(make: Maker) -> None:
    places = _places(make)
    switch = _alone(make, places)
    others, _ = _in_service(make, places["room"])
    member = make.members(others)[0]["item"]
    part = make.item(name="PS-A", parent_item_hid=switch["hid"])
    gone = _spare(make, 33)
    make.move(_item(make, gone), "Pending-Removal", reason="rma")
    make.move(_item(make, gone), "Released", reason="returned")
    retired = _spare(make, 34)
    make.post(f"/items/{retired['hid']}/retire", {"row_version": retired["row_version"]}, 200)
    model = switch["catalog_entry_hid"]
    unnamed = make.item(serial_number="FCW9000X0035", catalog_entry_hid=model)
    make.group("cw07-idf05-acc1", "custom")

    problem = _make_stack(make, part, 422)
    assert set(errors(problem)) == {"item_hid"}
    for item in (gone, retired):
        assert set(errors(_make_stack(make, item, 422))) == {"item_hid"}
    in_one = _make_stack(make, member, 409)
    assert in_one["existing"]["hid"] == others["hid"]
    taken = _make_stack(make, switch, 409, name="cw07-idf05-acc1")
    assert set(errors(taken)) == {"name"}
    assert set(errors(_make_stack(make, unnamed, 422))) == {"name"}
    # A refusal of a further member leaves no stack made and the switch as it was.
    problem = _make_stack(make, switch, 422, members=[{"item_hid": NOBODY}])
    assert set(errors(problem)) == {"members.item_hid"}
    problem = _make_stack(
        make, switch, 422, members=[{"item_hid": gone["hid"], "disposition": "Production"}]
    )
    assert set(errors(problem)) == {"members.item_hid"}
    stale = make.post(
        f"/items/{switch['hid']}/make-stack", {"row_version": switch["row_version"] + 9}, 409
    )
    assert stale["title"] == "Stale version"
    assert make.get("/device-groups", filter="name:eq:cw07-idf04-acc1")["total"] == 0
    assert _item(make, switch)["hostname"] == "cw07-idf04-acc1"


def test_making_a_stack_needs_the_inventory_role(
    client: TestClient, make: Maker, viewer: dict
) -> None:
    switch = make.item(name="cw07-idf06-acc1")
    response = client.post(
        f"{API}/items/{switch['hid']}/make-stack", json={"row_version": 1}, headers=viewer
    )
    assert response.status_code == 403


def test_the_command_makes_a_stack_of_a_switch(run: Any, make: Maker) -> None:
    places = _places(make)
    switch = _alone(make, places)
    spare = _spare(make, 36, places["depot"])

    said = run(
        "items", "make-stack", "cw07-idf04-acc1", "--name", "cw07-idf04-stack",
        "--member", spare["serial_number"],
    ).stdout.splitlines()  # fmt: skip

    stack = make.get("/device-groups", filter="name:eq:cw07-idf04-stack")["items"][0]
    assert said[0] == f"made the stack cw07-idf04-stack  {stack['hid']}"
    assert said[1:] == ["  1: cw07-idf04-acc1", f"  2: {spare['serial_number']}"]
    # The member that joins takes the stack's name and place.
    assert _item(make, spare)["hostname"] is None
    assert _item(make, switch)["hostname"] is None
    run("items", "make-stack", "cw07-idf04-acc1", expect=5)


# --- a replacement that was a mistake, removed by an Admin (P-238) -------------------


def _remove(
    client: TestClient, headers: dict[str, str], hid: str, expect: int = 204, **body: Any
) -> Any:
    response = client.post(f"{API}/item-replacements/{hid}/remove", json=body, headers=headers)
    assert response.status_code == expect, response.text
    return response.json() if response.content else None


def test_an_admin_removes_a_replacement_and_what_it_handed_over_stays(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    wrong = switches[1]
    spare = _spare(make, 41, places["depot"])
    made = _replace(make, wrong, new_item_hid=spare["hid"], reference="RMA-0000-041")
    before = (_item(make, wrong), _item(make, spare))

    assert _remove(client, admin, made["hid"], reason="recorded on the wrong switch") is None

    # The audit event of the removal holds the replacement as it was, and the reason.
    (event,) = make.audit(record_type="item_replacement", action="delete")
    assert (event["record_hid"], _changed(event)["removal_reason"]) == (
        made["hid"],
        (None, "recorded on the wrong switch"),
    )
    assert _changed(event)["old_item_hid"] == (wrong["hid"], None)
    assert _changed(event)["reference"] == ("RMA-0000-041", None)
    # Each item has an event of it, its version moved, and lists no replacement.
    for item, field, other in (
        (before[0], "replaced_by", spare),
        (before[1], "replaces", wrong),
    ):
        now = _item(make, item)
        assert (now["replacements"], now[field]) == ([], None)
        assert now["row_version"] == item["row_version"] + 1
        latest = make.get(f"/items/{item['hid']}/history")["items"][0]
        assert latest["action"] == "replacement_removed"
        assert _changed(latest)[field] == (other["hid"], None)
        assert _changed(latest)["replacement"] == (made["hid"], None)
    # What it handed over stays: the spare is still the stack's member at position 2.
    assert [(one["position"], one["item_hid"]) for one in make.members(stack)][1] == (
        2,
        spare["hid"],
    )
    _remove(client, admin, made["hid"], 404, reason="again")


def test_an_item_whose_only_tie_was_the_replacement_is_then_deleted(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    old = make.item(name="ex-wrong-old")
    new = make.item(name="ex-wrong-new")
    made = _replace(make, old, new_item_hid=new["hid"])

    def delete(hids: list[str]) -> dict[str, Any]:
        body = {"hids": hids, "reason": "a wrong press"}
        response = client.post(f"{API}/items/delete", json=body, headers=admin)
        assert response.status_code == 200, response.text
        return response.json()

    # An item in several replacements is refused naming each (P-241).
    third = make.item(name="ex-wrong-third")
    other = _replace(make, new, new_item_hid=third["hid"])
    ties = delete([new["hid"]])["refused"][0]["depends_on"]
    assert sorted(tie["hid"] for tie in ties) == sorted([made["hid"], other["hid"]])
    _remove(client, admin, other["hid"], reason="a wrong press")
    refused = delete([old["hid"]])["refused"]
    assert [tie["hid"] for tie in refused[0]["depends_on"]] == [made["hid"]]
    _remove(client, admin, made["hid"], reason="a wrong press")
    assert [one["hid"] for one in delete([old["hid"], new["hid"]])["deleted"]] == [
        old["hid"],
        new["hid"],
    ]


def test_removing_a_replacement_is_for_an_admin_with_a_reason(
    client: TestClient, make: Maker, admin: dict[str, str], inventory: dict[str, str]
) -> None:
    old, new = make.item(name="ex-kept-old"), make.item(name="ex-kept-new")
    made = _replace(make, old, new_item_hid=new["hid"])
    _remove(client, inventory, made["hid"], 403, reason="no")
    for blank in ("", "   "):
        problem = _remove(client, admin, made["hid"], 422, reason=blank)
        assert set(errors(problem)) == {"reason"}
    _remove(client, admin, made["hid"], 422)
    _remove(client, admin, NOBODY, 404, reason="none such")
    assert len(_item(make, old)["replacements"]) == 1
    assert make.audit(record_type="item_replacement", action="delete") == []


def test_the_command_removes_a_replacement_and_asks_first(
    run: Any, make: Maker, admin: dict[str, str], monkeypatch: Any
) -> None:
    old, new = make.item(name="ex-cli-old"), make.item(name="ex-cli-new")
    made = _replace(make, old, new_item_hid=new["hid"])
    hid = made["hid"]
    refused = run("replacements", "remove", hid, "--reason", "wrong", "--yes", expect=3)
    assert "admin role" in refused.output
    monkeypatch.setenv("HIRDIR_TOKEN", admin["Authorization"].removeprefix("Bearer "))
    assert "--reason" in run("replacements", "remove", hid, expect=2).output
    declined = run("replacements", "remove", hid, "--reason", "wrong", expect=1)
    assert "Remove this replacement?" in declined.output
    assert declined.stdout.startswith("ex-cli-old replaced by ex-cli-new on ")
    assert len(_item(make, old)["replacements"]) == 1
    done = run("replacements", "remove", hid, "--reason", "wrong", "--yes")
    assert done.stdout.splitlines()[-1].startswith("removed: ex-cli-old replaced by ex-cli-new")
    assert _item(make, old)["replacements"] == []
    run("replacements", "remove", hid, "--reason", "wrong", "--yes", expect=4)


# --- an item known by its host name alone ---------------------------------------------

ALONE_SAID = "give it a name, a serial number with its model, or an asset tag first"


def test_a_switch_known_by_its_host_name_alone_is_not_made_a_stack(make: Maker) -> None:
    places = _places(make)
    bare = make.item(hostname="cw07-idf07-acc1", location_hid=places["room"]["hid"])
    problem = _make_stack(make, bare, 422, name="cw07-idf07-stack")
    assert problem["detail"] == (
        "cw07-idf07-acc1 is known by its host name alone, which the stack takes"
    )
    assert errors(problem) == {"item_hid": ALONE_SAID}
    # Nothing was changed: no stack, and the switch as it was.
    assert make.get("/device-groups")["total"] == 0
    assert _item(make, bare)["row_version"] == bare["row_version"]
    # Given a name of its own first, it is made one.
    named = make.patch(f"/items/{bare['hid']}", {"row_version": bare["row_version"], "name": "x1"})
    assert _make_stack(make, named)["name"] == "x1"


def test_a_member_known_by_its_host_name_alone_does_not_take_the_stacks_name(
    make: Maker,
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    bare = make.item(hostname="spare-sw-099", lifecycle_state="Prod")
    # Joining a stack.
    problem = make.add(stack, [{"item_hid": bare["hid"], "drop_identity": True}], 422)
    assert errors(problem) == {"members.0.item_hid": ALONE_SAID}
    assert "known by its host name alone" in problem["detail"]
    # Taking a member's place by a replacement.
    problem = _replace(make, switches[1], 422, new_item_hid=bare["hid"], drop_identity=True)
    assert errors(problem) == {"new_item_hid": ALONE_SAID}
    # And as a further member of a stack made of a switch.
    switch = _alone(make, places)
    problem = _make_stack(
        make, switch, 422, members=[{"item_hid": bare["hid"], "drop_identity": True}]
    )
    assert errors(problem) == {"members.0.item_hid": ALONE_SAID}
    # Nothing was done: the stack has its three, and the spare keeps its host name.
    assert len(make.members(stack)) == 3
    assert make.audit(record_type="item_replacement") == []
    assert _item(make, bare)["hostname"] == "spare-sw-099"
    # Without drop_identity it joins and keeps its name.
    make.add(stack, [{"item_hid": bare["hid"]}])
    assert _item(make, bare)["hostname"] == "spare-sw-099"
