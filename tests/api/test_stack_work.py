"""Working a stack: a switch that joins takes the stack's name and place (P-217), one that
leaves is given what becomes of it (P-218), and a position is held by one member (P-219).
"""

import threading
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from hirdir.db.models import DeviceGroupMember
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, counts, table
from tests.api.test_hardening import _together

STACK = "cw07-idf03-acc1"
# A day after whichever day the test runs on, when a member joins "today".
LATER = "2099-01-01"


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _model(make: Maker) -> dict[str, Any]:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    return entries[0] if entries else make.entry(vendor)


def _places(make: Maker) -> dict[str, dict[str, Any]]:
    """The stack's room, and a depot where the spares are kept."""
    places = make.layout()
    places["depot"] = make.location("Spares Depot", places["site"], kind="room")
    return places


def _switch(make: Maker, number: int, **more: Any) -> dict[str, Any]:
    """A switch in service in a stack, known by its serial number alone."""
    fields = {"lifecycle_state": "Prod", **more}
    return make.item(
        catalog_entry_hid=_model(make)["hid"], serial_number=f"FCW9000{number:04d}", **fields
    )


def _spare(make: Maker, number: int, depot: dict[str, Any] | None = None, **more: Any) -> dict:
    """A spare in the pool: a name of its own, Prod, Spare and expected offline."""
    fields: dict[str, Any] = {
        "hostname": f"spare-sw-{number:03d}",
        "fqdn": f"spare-sw-{number:03d}.example.net",
        "disposition": "Spare",
        "expected_online": False,
        **more,
    }
    if depot is not None:
        fields["location_hid"] = depot["hid"]
    return _switch(make, 500 + number, **fields)


def _stack(make: Maker, room: dict[str, Any], *members: dict[str, Any], **more: Any) -> dict:
    return make.group(
        more.pop("name", STACK),
        "stack",
        [(member, "master" if place == 0 else "member") for place, member in enumerate(members)],
        hostname=STACK,
        fqdn=f"{STACK}.example.net",
        location_hid=room["hid"],
        **more,
    )


def _item(make: Maker, item: dict[str, Any]) -> dict[str, Any]:
    return make.get(f"/items/{item['hid']}")


def _cause(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the entries of an event that say what made the change."""
    return [
        entry for entry in event["changes"] if entry["field"] in ("joining_group", "leaving_group")
    ]


def _changed(event: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in event["changes"]}


# --- joining with the stack's name and place (P-217) ---------------------------------


def test_a_spare_that_joins_takes_the_stacks_name_and_place_in_one_change(make: Maker) -> None:
    places = _places(make)
    owner = make.owner()
    stack = _stack(make, places["room"], _switch(make, 1))
    spare = _spare(make, 17, places["depot"], owner_hid=owner["hid"])
    first = make.address(spare, "192.0.2.17", is_primary=True)
    second = make.address(spare, "2001:db8::17")

    made = make.add(
        stack,
        [
            {
                "item_hid": spare["hid"],
                "position": 2,
                "drop_identity": True,
                "disposition": "Production",
                "expected_online": True,
            }
        ],
    )

    assert [(member["item_hid"], member["position"]) for member in made] == [(spare["hid"], 2)]
    joined = _item(make, spare)
    assert (joined["hostname"], joined["fqdn"], joined["location_hid"]) == (None, None, None)
    assert joined["addresses"] == []
    # The stack's room is in force, read from the stack and copied to nothing.
    where = joined["effective"]["location_hid"]
    assert (where["value"], where["source_hid"]) == (places["room"]["hid"], stack["hid"])
    assert (joined["disposition"], joined["expected_online"]) == ("Production", True)
    # What is not its name or its place stays.
    assert (joined["owner_hid"], joined["serial_number"]) == (owner["hid"], spare["serial_number"])
    # The stack has nothing of the spare's.
    after = make.get(f"/device-groups/{stack['hid']}")
    assert (after["hostname"], after["member_count"], after["addresses"]) == (STACK, 2, [])

    # Each change is audited as the item's, or as the removal of its address, and says it
    # was made by joining the stack, with what was given up (O-02).
    membership = make.audit(record_type="device_group_member", record_hid=made[0]["hid"])[0]
    event = make.audit(record_type="item", record_hid=spare["hid"])[0]
    assert event["action"] == "update"
    assert _changed(event) == {
        "hostname": ("spare-sw-017", None),
        "fqdn": ("spare-sw-017.example.net", None),
        "location_hid": (places["depot"]["hid"], None),
        "disposition": ("Spare", "Production"),
        "expected_online": (False, True),
        "joining_group": (None, stack["hid"]),
    }
    removed = {one["record_hid"]: one for one in make.audit(record_type="address", action="delete")}
    assert set(removed) == {first["hid"], second["hid"]}
    for address, held in ((first, "192.0.2.17"), (second, "2001:db8::17")):
        gone = _changed(removed[address["hid"]])
        assert gone["address"] == (held, None)
        assert gone["item_hid"] == (spare["hid"], None)
        assert gone["joining_group"] == (None, stack["hid"])
    assert {event["request_id"], *(one["request_id"] for one in removed.values())} == {
        membership["request_id"]
    }
    assert _cause(membership) == []


def test_a_member_that_keeps_its_name_or_has_nothing_to_give_up(make: Maker) -> None:
    places = _places(make)
    stack = _stack(make, places["room"], _switch(make, 1))
    named = _spare(make, 18, places["depot"])
    bare = _switch(make, 2)

    # Without drop_identity, and with nothing else, the item is not changed at all.
    make.add(stack, [{"item_hid": named["hid"], "position": 2}])
    kept = _item(make, named)
    assert (kept["hostname"], kept["location_hid"], kept["row_version"]) == (
        "spare-sw-018",
        places["depot"]["hid"],
        named["row_version"],
    )
    assert make.audit(record_type="item", record_hid=named["hid"])[0]["action"] == "create"

    # A switch with no name, no address and no place of its own gives up nothing, and
    # is not changed either.
    make.add(stack, [{"item_hid": bare["hid"], "position": 3, "drop_identity": True}])
    assert _item(make, bare)["row_version"] == bare["row_version"]
    assert make.audit(record_type="address", action="delete") == []


def test_a_new_stack_takes_its_first_members_name_and_place(make: Maker) -> None:
    places = _places(make)
    spare = _spare(make, 19, places["depot"])
    make.address(spare, "192.0.2.19", is_primary=True)

    stack = make.post(
        "/device-groups",
        {
            "type": "stack",
            "name": "cw05-lab-sw1",
            "hostname": "cw05-lab-sw1",
            "location_hid": places["room"]["hid"],
            "members": [{"item_hid": spare["hid"], "position": 1, "drop_identity": True}],
        },
    )

    joined = _item(make, spare)
    assert (joined["hostname"], joined["fqdn"], joined["location_hid"]) == (None, None, None)
    assert (joined["addresses"], joined["disposition"]) == ([], "Spare")
    assert joined["effective"]["location_hid"]["source_hid"] == stack["hid"]


def test_what_a_member_brings_is_refused_by_the_items_rules_and_nothing_is_added(
    make: Maker,
) -> None:
    places = _places(make)
    stack = _stack(make, places["room"], _switch(make, 1))
    first, second = _spare(make, 20, places["depot"]), _spare(make, 21, places["depot"])
    make.address(first, "192.0.2.20", is_primary=True)

    # Production is expected online in Prod: nothing follows from the disposition alone.
    problem = make.add(
        stack,
        [
            {"item_hid": first["hid"], "position": 2, "drop_identity": True},
            {"item_hid": second["hid"], "position": 3, "disposition": "Production"},
        ],
        expect=422,
    )
    assert errors(problem) == {
        "members.1.expected_online": "a Production item in Prod is expected online"
    }
    # A disposition its state does not allow.
    problem = make.add(
        stack, [{"item_hid": second["hid"], "disposition": "Excess", "expected_online": False}], 422
    )
    assert set(errors(problem)) == {"members.0.disposition"}
    assert "not Excess" in errors(problem)["members.0.disposition"]

    # All or nothing: neither member was added, and the first switch kept its name.
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 1
    kept = _item(make, first)
    assert (kept["hostname"], kept["location_hid"]) == ("spare-sw-020", places["depot"]["hid"])
    assert [one["address"] for one in kept["addresses"]] == ["192.0.2.20"]
    assert make.audit(record_type="address", action="delete") == []
    assert len(make.audit(record_type="device_group_member")) == 1


def test_only_a_member_of_a_stack_takes_the_groups_name(make: Maker) -> None:
    places = _places(make)
    cluster = make.group("site2-fw-edge", "cluster", location_hid=places["room"]["hid"])
    domain = make.group("site2-wireless", "controller_domain")
    firewall = _spare(make, 22, places["depot"])

    for group, kind in ((cluster, "cluster"), (domain, "controller domain")):
        problem = make.add(group, [{"item_hid": firewall["hid"], "drop_identity": True}], 422)
        assert errors(problem) == {
            "members.0.drop_identity": f"the members of a {kind} keep their own names"
        }
    # A cluster's member may still be given a standing with it.
    make.add(
        cluster,
        [{"item_hid": firewall["hid"], "disposition": "Production", "expected_online": True}],
    )
    kept = _item(make, firewall)
    assert (kept["hostname"], kept["disposition"]) == ("spare-sw-022", "Production")
    event = make.audit(record_type="item", record_hid=firewall["hid"])[0]
    assert _cause(event) == [{"field": "joining_group", "old": None, "new": cluster["hid"]}]


def test_the_refusal_of_a_switch_in_another_stack_does_not_begin_with_its_name(
    make: Maker,
) -> None:
    places = _places(make)
    spare = _spare(make, 19, places["depot"])
    _stack(make, places["room"], spare)
    other = _stack(make, places["room"], _switch(make, 1), name="cw07-idf03-acc2")

    problem = make.add(other, [{"item_hid": spare["hid"]}], 409)
    assert problem["detail"] == f"the item spare-sw-019 is a member of the stack {STACK}"


def test_a_file_of_members_says_what_each_switch_gives_up(make: Maker, files: Files) -> None:
    places = _places(make)
    stack = _stack(make, places["room"], _switch(make, 1))
    spare = _spare(make, 30, places["depot"])
    make.address(spare, "192.0.2.30", is_primary=True)
    kept = _spare(make, 31, places["depot"])
    text = (
        "group,item,position,drop_identity,disposition,expected_online\n"
        f"{STACK},spare-sw-030,2,true,Production,true\n"
        f"{STACK},spare-sw-031,3,,,\n"
    )

    preview = files.preview("device_group_members", text)

    assert counts(preview["job"]) == (2, 0, 0, 0)
    assert preview["rows"][0]["notes"] == [
        "takes the stack's name and place: its host name spare-sw-030 is cleared; its FQDN "
        "spare-sw-030.example.net is cleared; its address 192.0.2.30 is removed; its own "
        "location Americas > Central > Site-2 > Spares Depot is cleared",
        "is given disposition Production and expected_online true",
    ]
    assert preview["rows"][1]["notes"] == []
    # Nothing is done by a preview.
    assert _item(make, spare)["hostname"] == "spare-sw-030"

    files.apply(preview)
    joined = _item(make, spare)
    assert (joined["hostname"], joined["fqdn"], joined["location_hid"]) == (None, None, None)
    assert (joined["addresses"], joined["disposition"]) == ([], "Production")
    assert _item(make, kept)["hostname"] == "spare-sw-031"
    event = make.audit(record_type="item", record_hid=spare["hid"])[0]
    assert (event["via"], _cause(event)) == (
        "import",
        [{"field": "joining_group", "old": None, "new": stack["hid"]}],
    )

    # A row of a membership that is there already is not given it again.
    again = files.preview(
        "device_group_members", f"group,item,drop_identity\n{STACK},spare-sw-031,true\n"
    )
    assert counts(again["job"]) == (0, 0, 1, 0)
    assert again["rows"][0]["notes"] == [
        "a membership that is there already: drop_identity, disposition and expected_online "
        "are for a member that joins, and are passed over"
    ]
    # A refusal of a row names the column of the file, and a membership entered for the
    # record, which has ended, changes nothing of its item.
    other = _switch(make, 2)
    refused = files.preview(
        "device_group_members",
        "group,item,joined_on,left_on,drop_identity,disposition\n"
        f"{STACK},{other['hid']},,,,Excess\n"
        f"{STACK},{spare['hid']},2025-01-01,2025-06-30,true,\n",
    )
    assert [[one["field"] for one in row["reasons"]] for row in refused["rows"]] == [
        ["disposition"],
        ["drop_identity"],
    ]
    # An export writes the three only when they are asked for, and blank.
    assert "drop_identity" not in files.export("device_group_members").splitlines()[0]
    rows = table(files.export("device_group_members", columns=["item", "drop_identity"]))
    assert {row["drop_identity"] for row in rows} == {""}


# --- leaving with what becomes of it (P-218) -----------------------------------------


def _end(
    make: Maker, stack: dict[str, Any], whose: dict[str, Any], expect: int = 200, **body: Any
) -> dict[str, Any]:
    """Change the current membership of an item in a stack as the body says: end it."""
    member = next(one for one in make.members(stack) if one["item_hid"] == whose["hid"])
    return make.patch(
        f"/device-groups/{stack['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], **body},
        expect,
    )


def _in_service(make: Maker, room: dict[str, Any]) -> tuple[dict, list[dict]]:
    """A stack of three switches in service, which have nothing of their own."""
    switches = [
        _switch(make, number, disposition="Production", expected_online=True)
        for number in (1, 2, 3)
    ]
    return _stack(make, room, *switches), switches


def test_a_member_pulled_to_the_spare_pool_is_given_a_name_and_a_place_with_the_end(
    make: Maker,
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    pulled = switches[2]
    assert _item(make, pulled)["effective"]["location_hid"]["source_hid"] == stack["hid"]

    ended = _end(
        make,
        stack,
        pulled,
        left_on=LATER,
        item={
            "hostname": "spare-sw-901",
            "fqdn": "spare-sw-901.example.net",
            "location_hid": places["depot"]["hid"],
            "disposition": "Spare",
            "expected_online": False,
        },
    )

    assert ended["left_on"] == LATER
    spare = _item(make, pulled)
    assert (spare["hostname"], spare["fqdn"], spare["location_hid"]) == (
        "spare-sw-901",
        "spare-sw-901.example.net",
        places["depot"]["hid"],
    )
    assert (spare["lifecycle_state"], spare["disposition"], spare["expected_online"]) == (
        "Prod",
        "Spare",
        False,
    )
    assert spare["groups"] == []
    # One change of the item, audited as its own and as made by leaving the stack, with
    # the request of the end.
    event = make.audit(record_type="item", record_hid=pulled["hid"])[0]
    end = make.audit(record_type="device_group_member", record_hid=ended["hid"])[0]
    assert (event["action"], event["request_id"]) == ("update", end["request_id"])
    assert _changed(event)["location_hid"] == (None, places["depot"]["hid"])
    assert _cause(event) == [{"field": "leaving_group", "old": stack["hid"], "new": None}]
    assert _cause(end) == []


def test_a_failed_member_is_moved_for_return_or_as_excess_with_the_end(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed, worn = switches[1], switches[2]

    _end(
        make,
        stack,
        failed,
        left_on=LATER,
        item={"lifecycle_state": "Pending-Removal", "state_reason": "rma"},
    )
    returned = _item(make, failed)
    assert (returned["lifecycle_state"], returned["state_reason"]) == ("Pending-Removal", "rma")
    # Pending-Removal keeps the disposition it came with, and is not expected online.
    assert (returned["disposition"], returned["expected_online"]) == ("Production", False)
    move = make.audit(record_type="item", record_hid=failed["hid"])[0]
    assert move["action"] == "transition"
    assert _changed(move)["lifecycle_state"] == ("Prod", "Pending-Removal")
    assert _cause(move) == [{"field": "leaving_group", "old": stack["hid"], "new": None}]

    _end(
        make,
        stack,
        worn,
        left_on=LATER,
        item={
            "lifecycle_state": "Pending-Removal",
            "state_reason": "retired",
            "disposition": "Excess",
        },
    )
    excess = _item(make, worn)
    assert (excess["lifecycle_state"], excess["disposition"]) == ("Pending-Removal", "Excess")
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 1


def test_an_item_that_leaves_for_good_does_not_collide_with_its_other_groups(
    make: Maker,
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed = switches[1]
    lab = make.group("lab-kit", "custom", [(failed, "member")])
    make.move(_item(make, failed), "Pending-Removal", reason="rma")

    # A move to Released ends the memberships the item has: the stack's has ended first,
    # on its own day, and the other group's ends today, as any such move ends it.
    _end(
        make,
        stack,
        failed,
        left_on=LATER,
        item={"lifecycle_state": "Released", "state_reason": "returned"},
    )
    gone = _item(make, failed)
    assert (gone["lifecycle_state"], gone["groups"]) == ("Released", [])
    past = make.members(stack, include_past="true")
    assert [one["left_on"] for one in past if one["item_hid"] == failed["hid"]] == [LATER]
    assert make.members(lab) == []
    assert make.get(f"/device-groups/{lab['hid']}")["member_count"] == 0


def test_a_refused_part_of_what_becomes_of_it_leaves_the_membership_and_the_item(
    make: Maker,
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    member = switches[2]
    day = LATER

    refusals = [
        # A disposition its state does not allow, given with a name that would be taken.
        ({"hostname": "spare-sw-902", "disposition": "Excess"}, "item.disposition"),
        # Production in Prod is expected online.
        ({"disposition": "Production", "expected_online": False}, "item.expected_online"),
        # A move the rules do not list, which is never forced here.
        ({"lifecycle_state": "Delivered"}, "item.lifecycle_state"),
        ({"lifecycle_state": "Nowhere"}, "item.lifecycle_state"),
        # A reason is taken with a move.
        ({"state_reason": "rma"}, "item.state_reason"),
        (
            {"lifecycle_state": "Pending-Removal", "state_reason": "no-such-reason"},
            "item.state_reason",
        ),
        ({"location_hid": "01900000-0000-7000-8000-000000000000"}, "item.location_hid"),
    ]
    for given, field in refusals:
        problem = _end(make, stack, member, 422, left_on=day, item=given)
        assert set(errors(problem)) == {field}, given
    # What becomes of the item is given with the end of a current membership.
    problem = _end(make, stack, member, 422, item={"hostname": "spare-sw-902"})
    assert set(errors(problem)) == {"item"}

    still = _item(make, member)
    assert (still["hostname"], still["disposition"], still["lifecycle_state"]) == (
        None,
        "Production",
        "Prod",
    )
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 3
    assert make.audit(record_type="item", record_hid=member["hid"])[0]["action"] == "create"

    # Once it has ended, the item is changed on its own page.
    _end(make, stack, member, left_on=day)
    ended = make.members(stack, include_past="true")[-1]
    problem = make.patch(
        f"/device-groups/{stack['hid']}/members/{ended['hid']}",
        {"row_version": ended["row_version"], "left_on": day, "item": {"hostname": "late"}},
        422,
    )
    assert set(errors(problem)) == {"item"}


# --- a position is held by one member (P-219) ----------------------------------------


def _positions(make: Maker, stack: dict[str, Any]) -> list[tuple[int | None, str]]:
    """Return the current members of a stack by position, each as its serial number."""
    return [(member["position"], member["item"]["serial_number"]) for member in make.members(stack)]


def _next(make: Maker, group: dict[str, Any]) -> int | None:
    return make.get(f"/device-groups/{group['hid']}")["next_position"]


def test_a_position_is_held_by_one_current_member_and_freed_by_its_end(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    first, second, third = switches
    assert (stack["next_position"], _next(make, stack)) == (4, 4)

    # A position another current member holds is refused, naming that member's item.
    taken = make.add(stack, [{"item_hid": _switch(make, 4)["hid"], "position": 2}], 409)
    assert taken["existing"] == {
        "hid": second["hid"],
        "record_type": "item",
        "label": second["serial_number"],
    }
    assert errors(taken) == {
        "members.0.position": f"another current member holds position 2: {second['serial_number']}"
    }
    assert taken["detail"] == f"position 2 of {STACK} is held by {second['serial_number']}"
    # So is one that two members of one request are given.
    doubled = make.add(
        stack,
        [
            {"item_hid": _switch(make, 5)["hid"], "position": 4},
            {"item_hid": _switch(make, 6)["hid"], "position": 4},
        ],
        expect=422,
    )
    assert set(errors(doubled)) == {"members.1.position"}
    # And a member moved to a position another holds.
    member = make.members(stack)[2]
    moved = make.patch(
        f"/device-groups/{stack['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "position": 1},
        409,
    )
    assert (set(errors(moved)), moved["existing"]["hid"]) == ({"position"}, first["hid"])
    assert _positions(make, stack) == [
        (1, first["serial_number"]),
        (2, second["serial_number"]),
        (3, third["serial_number"]),
    ]

    # A member that has left keeps its number and holds nothing: the lowest free one is
    # offered, and a member added with none takes it.
    _end(make, stack, second, left_on=LATER)
    assert _next(make, stack) == 2
    spare = _spare(make, 18, places["depot"])
    assert make.add(stack, [{"item_hid": spare["hid"]}])[0]["position"] == 2
    past = make.members(stack, include_past="true")
    assert [
        (one["position"], one["left_on"]) for one in past if one["item_hid"] == second["hid"]
    ] == [(2, LATER)]
    assert _next(make, stack) == 4


def test_members_given_no_position_take_the_lowest_free_ones(make: Maker) -> None:
    places = _places(make)
    stack = make.group(STACK, "stack")
    assert stack["next_position"] == 1
    made = make.add(stack, [{"item_hid": _switch(make, number)["hid"]} for number in (1, 2)])
    assert [member["position"] for member in made] == [1, 2]
    # A position given in the request is not taken by a member given none before it.
    made = make.add(
        stack,
        [
            {"item_hid": _switch(make, 3)["hid"]},
            {"item_hid": _switch(make, 4)["hid"], "position": 3},
            {"item_hid": _switch(make, 5)["hid"]},
        ],
    )
    assert [member["position"] for member in made] == [4, 3, 5]
    # The members of another kind of group are not numbered.
    cluster = make.group("site2-fw-edge", "cluster", location_hid=places["room"]["hid"])
    assert cluster["next_position"] is None
    made = make.add(
        cluster,
        [
            {"item_hid": _switch(make, 6)["hid"]},
            {"item_hid": _switch(make, 7)["hid"], "position": 1},
            {"item_hid": _switch(make, 8)["hid"], "position": 1},
        ],
    )
    assert [member["position"] for member in made] == [None, 1, 1]


def test_two_members_that_held_one_position_from_before_stay_and_may_be_worked(
    make: Maker, client: TestClient
) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    _, second, third = make.members(stack)
    # As 0.9.5 let two members take one position.
    app = cast(Any, client.app)
    with app.state.sessions() as db:
        db.execute(
            update(DeviceGroupMember)
            .where(DeviceGroupMember.hid == third["hid"])
            .values(position=1)
        )
        db.commit()

    # Other changes of the stack go through, and the two stay as they are.
    renamed = make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "expected_members": 4},
    )
    assert renamed["expected_members"] == 4
    assert _role_of(make, stack, second, "master")["role"] == "master"
    assert make.add(stack, [{"item_hid": _switch(make, 4)["hid"]}])[0]["position"] == 3
    assert [position for position, _ in _positions(make, stack)] == [1, 1, 2, 3]
    # A replacement of one of the two hands the position over as it is.
    spare = _spare(make, 19, places["depot"])
    old = _item(make, switches[0])
    make.post(
        f"/items/{old['hid']}/replace",
        {"row_version": old["row_version"], "reason": "rma", "new_item_hid": spare["hid"]},
    )
    held = {member["item_hid"]: member["position"] for member in make.members(stack)}
    assert (held[spare["hid"]], held[switches[2]["hid"]]) == (1, 1)
    # Either of the two is moved to a free position.
    doubled = next(one for one in make.members(stack) if one["item_hid"] == switches[2]["hid"])
    make.patch(
        f"/device-groups/{stack['hid']}/members/{doubled['hid']}",
        {"row_version": doubled["row_version"], "position": 5},
    )
    assert [position for position, _ in _positions(make, stack)] == [1, 2, 3, 5]


def _role_of(make: Maker, stack: dict, member: dict, role: str) -> dict[str, Any]:
    now = next(one for one in make.members(stack) if one["hid"] == member["hid"])
    return make.patch(
        f"/device-groups/{stack['hid']}/members/{now['hid']}",
        {"row_version": now["row_version"], "role": role},
    )


def test_a_replacement_takes_the_position_of_the_member_it_replaces(make: Maker) -> None:
    places = _places(make)
    stack, switches = _in_service(make, places["room"])
    failed = _item(make, switches[1])
    spare = _spare(make, 18, places["depot"])

    make.post(
        f"/items/{failed['hid']}/replace",
        {"row_version": failed["row_version"], "reason": "rma", "new_item_hid": spare["hid"]},
    )

    assert _positions(make, stack) == [
        (1, switches[0]["serial_number"]),
        (2, spare["serial_number"]),
        (3, switches[2]["serial_number"]),
    ]
    assert _next(make, stack) == 4


def test_two_requests_at_one_moment_do_not_both_take_a_position(
    make: Maker, client: TestClient
) -> None:
    places = _places(make)
    stack, _ = _in_service(make, places["room"])
    gate = threading.Barrier(2, timeout=5)

    def add(member: dict[str, Any]) -> Any:
        def call(caller: TestClient) -> Any:
            gate.wait()
            return caller.post(
                f"{API}/device-groups/{stack['hid']}/members",
                json={"members": [member]},
                headers=make.headers,
            )

        return call

    asked = [{"item_hid": _switch(make, number)["hid"], "position": 4} for number in (4, 5)]
    assert _together(client, [add(one) for one in asked]) == [201, 409]
    gate.reset()
    blank = [{"item_hid": _switch(make, number)["hid"]} for number in (6, 7)]
    assert _together(client, [add(one) for one in blank]) == [201, 201]
    assert [position for position, _ in _positions(make, stack)] == [1, 2, 3, 4, 5, 6]


def test_a_file_numbers_the_members_it_gives_no_position(make: Maker, files: Files) -> None:
    places = _places(make)
    stack, _ = _in_service(make, places["room"])
    for number in (4, 5, 6, 7):
        _switch(make, number)
    text = (
        "group,item,position\n"
        f"{STACK},FCW90000004,\n"
        f"{STACK},FCW90000005,4\n"
        f"{STACK},FCW90000006,\n"
        f"{STACK},FCW90000007,2\n"
    )

    preview = files.preview("device_group_members", text)

    assert counts(preview["job"]) == (3, 0, 0, 1)
    assert [entry["field"] for entry in preview["rows"][3]["reasons"]] == ["position"]
    files.apply(preview, skip_rejected="true")
    assert _positions(make, stack)[3:] == [
        (4, "FCW90000005"),
        (5, "FCW90000004"),
        (6, "FCW90000006"),
    ]
