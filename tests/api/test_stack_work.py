"""Working a stack: a switch that joins takes the stack's name and place (P-217), one that
leaves is given what becomes of it (P-218), and a position is held by one member (P-219).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files, counts, table

STACK = "cw07-idf03-acc1"


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
