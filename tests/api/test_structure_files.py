"""Files of release 0.4.0: minor items, device groups, memberships, networks and addresses."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files, changes, counts, table


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def reasons(row: dict[str, Any]) -> dict[str, str]:
    return {entry["field"]: entry["message"] for entry in row["reasons"]}


def _switch(make: Maker, **more: Any) -> dict:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    entry = entries[0] if entries else make.entry(vendor)
    fields = {"serial_number": "FCW0000X001", "asset_tag": "AT-000101", "lifecycle_state": "Prod"}
    return make.item(catalog_entry_hid=entry["hid"], **{**fields, **more})


# --- minor items ---------------------------------------------------------------------


def test_a_file_puts_minor_items_in_the_item_it_names(make: Maker, files: Files) -> None:
    switch = _switch(make, hostname="site2-sw-access-01")
    text = (
        "name,parent,position\n"
        "PS-A,AT-000101,PS-A\n"  # by its asset tag
        "PS-B,FCW0000X001,PS-B\n"  # by its serial number
        "Slot 1,site2-sw-access-01,Slot 1\n"  # by its name
        f"Slot 2,{switch['hid']},Slot 2\n"  # by its HID
        "Port 1,Slot 1,Port 1\n"  # in an item that this file made
        "lost,no-such-switch,\n"
    )

    preview = files.preview("items", text)

    assert counts(preview["job"]) == (5, 0, 0, 1)
    assert reasons(preview["rows"][5]) == {"parent": "there is no item no-such-switch"}
    assert changes(preview["rows"][0])["parent"] == (None, "AT-000101")
    files.apply(preview, skip_rejected="true")
    children = make.get(f"/items/{switch['hid']}/children")["items"]
    assert [child["position"] for child in children] == ["PS-A", "PS-B", "Slot 1", "Slot 2"]
    assert make.found(filter="depth:eq:2") == ["Port 1"]


def test_a_minor_item_stands_after_its_parent_in_a_file(make: Maker, files: Files) -> None:
    text = "name,parent,position\nPS-A,chassis-1,PS-A\nchassis-1,,\n"
    preview = files.preview("items", text)
    assert counts(preview["job"]) == (1, 0, 0, 1)
    assert reasons(preview["rows"][0]) == {"parent": "there is no item chassis-1"}

    # An export sorted by depth writes every parent before what is in it.
    chassis = make.item(name="chassis-1")
    blade = make.item(name="a-blade", parent_item_hid=chassis["hid"], position="Bay 1")
    make.item(name="a-module", parent_item_hid=blade["hid"], position="Slot 1")
    rows = table(files.export("items", sort=["depth", "name"], columns=["name", "parent", "depth"]))
    assert [(row["name"], row["parent"], row["depth"]) for row in rows] == [
        ("chassis-1", "", "0"),
        ("a-blade", "chassis-1", "1"),
        ("a-module", "a-blade", "2"),
    ]


def test_a_name_that_two_items_have_names_no_parent(make: Maker, files: Files) -> None:
    make.item(name="twin")
    make.item(name="twin", asset_tag="AT-000900")
    preview = files.preview("items", "name,parent\nPS-A,twin\nPS-B,AT-000900\n")
    assert counts(preview["job"]) == (1, 0, 0, 1)
    assert "more than one item answers to twin" in reasons(preview["rows"][0])["parent"]


def test_clear_takes_a_minor_item_out_of_its_parent(make: Maker, files: Files) -> None:
    switch = _switch(make)
    part = make.item(name="PS-A", parent_item_hid=switch["hid"], position="PS-A")

    preview = files.preview("items", f"hid,parent\n{part['hid']},!clear\n")

    assert changes(preview["rows"][0]) == {
        "parent": ("AT-000101", None),
        "position": ("PS-A", None),
    }
    files.apply(preview)
    after = make.get(f"/items/{part['hid']}")
    assert (after["is_major"], after["position"]) == (True, None)


def test_an_import_does_not_turn_what_a_minor_item_inherits_into_its_own(
    make: Maker, files: Files
) -> None:
    owner = make.owner()
    switch = _switch(make, owner_hid=owner["hid"])
    part = make.item(name="PS-A", parent_item_hid=switch["hid"], position="PS-A")

    # An export writes the values in force, with where each came from.
    text = files.export("items", filter="is_major:eq:false", include_sources=True)
    row = table(text)[0]
    assert (row["owner"], row["lifecycle_state"], row["disposition"], row["expected_online"]) == (
        "Network Engineering",
        "Prod",
        "Production",
        "true",
    )
    assert (row["owner_source"], row["lifecycle_state_source"]) == ("parent_item", "parent_item")
    # Imported back, the row says nothing new, and the item still inherits.
    preview = files.preview("items", text)
    assert counts(preview["job"]) == (0, 0, 1, 0)
    after = make.get(f"/items/{part['hid']}")
    assert (after["owner_hid"], after["lifecycle_state"], after["row_version"]) == (None, None, 1)
    # The stored values are blank, and that is what a file to import back holds.
    own = table(files.export("items", filter="is_major:eq:false", own_values=True))[0]
    assert (own["owner"], own["lifecycle_state"], own["disposition"]) == ("", "", "")

    # A new minor item described with what its parent has anyway inherits as well.
    text = "name,parent,owner,lifecycle_state,disposition,expected_online\n"
    text += "PS-B,AT-000101,Network Engineering,Prod,Production,true\n"
    files.load("items", text)
    made = make.get("/items", filter="name:eq:PS-B")["items"][0]
    assert (made["owner_hid"], made["lifecycle_state"]) == (None, None)
    assert made["effective"]["lifecycle_state"]["source"] == "parent_item"


def test_a_file_gives_a_minor_item_a_state_of_its_own_and_takes_it_back(
    make: Maker, files: Files
) -> None:
    switch = _switch(make)
    part = make.item(name="PS-A", parent_item_hid=switch["hid"])
    head = "hid,lifecycle_state,state_reason\n"

    files.load("items", f"{head}{part['hid']},Pending-Removal,rma\n")
    moved = make.get(f"/items/{part['hid']}")
    assert (moved["lifecycle_state"], moved["state_reason"]) == ("Pending-Removal", "rma")

    preview = files.preview("items", f"{head}{part['hid']},!clear,found\n")
    assert changes(preview["rows"][0])["lifecycle_state"] == ("Pending-Removal", None)
    files.apply(preview)
    back = make.get(f"/items/{part['hid']}")
    assert (back["lifecycle_state"], back["effective"]["lifecycle_state"]["value"]) == (
        None,
        "Prod",
    )
    assert make.audit(record_hid=part["hid"])[0]["action"] == "transition"

    # The state of a major item is not cleared.
    preview = files.preview("items", f"hid,lifecycle_state\n{switch['hid']},!clear\n")
    assert "leaves a state by moving to another" in reasons(preview["rows"][0])["lifecycle_state"]


# --- the management address ----------------------------------------------------------


def test_a_file_sets_changes_and_removes_the_management_address(make: Maker, files: Files) -> None:
    switch = _switch(make)
    make.network("Red")
    make.network("Black")
    head = "asset_tag,mgmt_address,mgmt_network\n"

    preview = files.preview("items", f"{head}AT-000101,192.0.2.10,Red\n")
    assert changes(preview["rows"][0]) == {
        "mgmt_address": (None, "192.0.2.10"),
        "mgmt_network": (None, "Red"),
    }
    files.apply(preview)
    held = make.get(f"/items/{switch['hid']}")["addresses"]
    assert [(one["address"], one["network"], one["role"], one["is_primary"]) for one in held] == [
        ("192.0.2.10", "Red", "management", True)
    ]

    # The same row again changes nothing. Another address changes the one there is.
    assert counts(files.preview("items", f"{head}AT-000101,192.0.2.10,Red\n")["job"]) == (
        0,
        0,
        1,
        0,
    )
    files.load("items", f"{head}AT-000101,192.0.2.20,Black\n")
    again = make.get(f"/items/{switch['hid']}")["addresses"]
    assert [(one["hid"], one["address"], one["network"]) for one in again] == [
        (held[0]["hid"], "192.0.2.20", "Black")
    ]
    # Without the network column the network is left as it is, and `!clear` takes it off.
    files.load("items", "asset_tag,mgmt_address\nAT-000101,192.0.2.21\n")
    assert make.get(f"/items/{switch['hid']}")["addresses"][0]["network"] == "Black"
    files.load("items", f"{head}AT-000101,192.0.2.21,!clear\n")
    assert make.get(f"/items/{switch['hid']}")["addresses"][0]["network"] is None
    files.load("items", f"{head}AT-000101,!clear,\n")
    assert make.get(f"/items/{switch['hid']}")["addresses"] == []
    assert make.audit(record_type="address")[0]["via"] == "import"


def test_what_a_management_address_in_a_file_must_be(make: Maker, files: Files) -> None:
    _switch(make)
    make.network("Red")
    head = "asset_tag,mgmt_address,mgmt_network\n"
    for line, field, expected in (
        ("AT-000101,192.0.2.0/24,", "mgmt_address", "no prefix length"),
        ("AT-000101,192.0.2.10,Blue", "mgmt_network", "there is no network Blue"),
        ("AT-000101,,Red", "mgmt_network", "give mgmt_address with it"),
    ):
        preview = files.preview("items", head + line + "\n")
        assert counts(preview["job"]) == (0, 0, 0, 1), line
        assert expected in reasons(preview["rows"][0])[field], line
    assert make.audit(record_type="address") == []


def test_the_management_columns_are_written_when_they_are_asked_for(
    make: Maker, files: Files
) -> None:
    switch = _switch(make)
    make.address(switch, "192.0.2.10", make.network("Red"), is_primary=True)
    make.address(switch, "2001:db8::10", role="loopback")

    # Every address is in a file of its own, so a plain export of items leaves them out.
    assert "mgmt_address" not in files.export("items").splitlines()[0]
    rows = table(files.export("items", columns=["asset_tag", "mgmt_address", "mgmt_network"]))
    assert rows == [
        {
            "hid": switch["hid"],
            "asset_tag": "AT-000101",
            "mgmt_address": "192.0.2.10",
            "mgmt_network": "Red",
        }
    ]
    addresses = table(files.export("addresses"))
    assert [
        (row["item"], row["address"], row["network"], row["is_primary"]) for row in addresses
    ] == [
        ("AT-000101", "192.0.2.10", "Red", "true"),
        ("AT-000101", "2001:db8::10", "", "false"),
    ]


# --- networks and addresses ----------------------------------------------------------


def test_networks_and_addresses_load_and_load_again_unchanged(make: Maker, files: Files) -> None:
    _switch(make)
    stack = make.group("site2-sw-stack1", "stack")
    networks = "label,kind\nRed,vrf\nBlack,vrf\nLab,\n"
    addresses = (
        "item,group,address,network,role,is_primary\n"
        "AT-000101,,192.0.2.10,Red,management,true\n"
        "AT-000101,,192.0.2.10,Black,secondary,\n"
        "AT-000101,,2001:0db8::0010,,loopback,false\n"
        ",site2-sw-stack1,192.0.2.1,Red,,yes\n"
    )

    assert counts(files.load("networks", networks)) == (3, 0, 0, 0)
    assert counts(files.load("addresses", addresses)) == (4, 0, 0, 0)

    assert [(one["label"], one["kind"]) for one in make.get("/networks")["items"]] == [
        ("Black", "vrf"),
        ("Lab", "network"),
        ("Red", "vrf"),
    ]
    held = make.get(f"/device-groups/{stack['hid']}")["addresses"]
    assert [(one["address"], one["role"], one["is_primary"]) for one in held] == [
        ("192.0.2.1", "management", True)
    ]
    assert make.get("/addresses", filter="address:eq:2001:db8::10")["total"] == 1
    # A row finds its address by whose it is, the address and the network.
    assert counts(files.preview("networks", networks)["job"]) == (0, 0, 3, 0)
    assert counts(files.preview("addresses", addresses)["job"]) == (0, 0, 4, 0)
    exported = files.export("addresses", own_values=True)
    assert counts(files.preview("addresses", exported)["job"]) == (0, 0, 4, 0)
    changed = addresses.replace("192.0.2.10,Black,secondary", "192.0.2.10,Black,virtual")
    preview = files.preview("addresses", changed)
    assert counts(preview["job"]) == (0, 1, 3, 0)
    assert changes(preview["rows"][1]) == {"role": ("secondary", "virtual")}


def test_what_a_row_of_addresses_must_say(make: Maker, files: Files) -> None:
    switch = _switch(make)
    make.group("site2-sw-stack1", "stack")
    make.address(switch, "198.51.100.1")
    make.address(switch, "198.51.100.1")
    head = "item,group,address,network,role,is_primary\n"
    for line, field, expected in (
        (",,192.0.2.10,,,", "item", "give an item or a group"),
        ("AT-000101,site2-sw-stack1,192.0.2.10,,,", "item", "and not both"),
        ("AT-000999,,192.0.2.10,,,", "item", "there is no item AT-000999"),
        (",no-such-group,192.0.2.10,,,", "group", "there is no device group"),
        ("AT-000101,,192.0.2.10,Blue,,", "network", "there is no network Blue"),
        ("AT-000101,,not-an-address,,,", "address", "such as 192.0.2.10"),
        ("AT-000101,,192.0.2.10,,loopback,true", "is_primary", "role management"),
        # The item has this address twice, so only the HID says which is meant.
        ("AT-000101,,198.51.100.1,,,", "address", "give the HID"),
    ):
        preview = files.preview("addresses", head + line + "\n")
        assert counts(preview["job"]) == (0, 0, 0, 1), line
        assert expected in reasons(preview["rows"][0])[field], line


# --- device groups and their members -------------------------------------------------

GROUPS = (
    "name,type,hostname,parent,owner,record_status,tags\n"
    "site2-wireless,controller_domain,,,,active,\n"
    "site2-wlc-ha,cluster,site2-wlc,site2-wireless,Network Engineering,active,critical\n"
    "site2-sw-stack1,stack,site2-sw-stack1,,,active,\n"
)
MEMBERS = (
    "group,item,role,position,joined_on,left_on\n"
    "site2-sw-stack1,AT-000101,master,1,2024-03-18,\n"
    "site2-sw-stack1,AT-000102,member,2,2024-03-18,\n"
    "site2-sw-stack1,AT-000103,member,3,2024-03-18,2026-06-30\n"
    "site2-wlc-ha,AT-000104,active,,2024-05-06,\n"
    "site2-wireless,AT-000105,,,2024-05-20,\n"
)


def _inventory(make: Maker) -> list[dict]:
    make.owner()
    make.tag("critical")
    return [
        _switch(make, serial_number=f"FCW0000X00{number}", asset_tag=f"AT-00010{number}")
        for number in range(1, 6)
    ]


def test_groups_and_their_members_load_in_order_and_again_unchanged(
    make: Maker, files: Files
) -> None:
    switches = _inventory(make)

    assert counts(files.load("device_groups", GROUPS)) == (3, 0, 0, 0)
    # The stack is there with no members yet, and is given them by the next file.
    assert counts(files.load("device_group_members", MEMBERS)) == (5, 0, 0, 0)

    stack = make.get("/device-groups", filter="name:eq:site2-sw-stack1")["items"][0]
    assert (stack["member_count"], stack["serial_number"]) == (2, "FCW0000X001")
    past = make.members(stack, include_past="true")
    assert [(one["item"]["asset_tag"], one["left_on"]) for one in past] == [
        ("AT-000101", None),
        ("AT-000102", None),
        ("AT-000103", "2026-06-30"),
    ]
    cluster = make.get("/device-groups", filter="name:eq:site2-wlc-ha")["items"][0]
    assert (cluster["parent"]["name"], cluster["owner"]["label"], cluster["tags"]) == (
        "site2-wireless",
        "Network Engineering",
        ["critical"],
    )
    point = make.get(f"/items/{switches[4]['hid']}")
    assert point["groups"][0]["role"] == "endpoint"
    assert [one["asset_tag"] for one in point["controllers"]] == ["AT-000104"]

    assert counts(files.preview("device_groups", GROUPS)["job"]) == (0, 0, 3, 0)
    assert counts(files.preview("device_group_members", MEMBERS)["job"]) == (0, 0, 5, 0)
    # What an export writes is a file that loads back unchanged.
    for entity, rows in (("device_groups", 3), ("device_group_members", 5)):
        text = files.export(entity, own_values=True)
        assert counts(files.preview(entity, text)["job"]) == (0, 0, rows, 0), entity
    exported = table(files.export("device_groups", columns=["name", "serial_number", "members"]))
    assert [(row["name"], row["serial_number"], row["members"]) for row in exported] == [
        ("site2-sw-stack1", "FCW0000X001", "2"),
        ("site2-wireless", "", "1"),
        ("site2-wlc-ha", "", "1"),
    ]


def test_a_stack_is_checked_when_the_whole_file_of_members_is_worked(
    make: Maker, files: Files
) -> None:
    _inventory(make)
    files.load("device_groups", GROUPS)
    text = (
        "group,item,role,position\n"
        "site2-sw-stack1,AT-000101,member,1\n"
        "site2-sw-stack1,AT-000102,member,2\n"
        "site2-wireless,AT-000105,endpoint,\n"
    )

    preview = files.preview("device_group_members", text)

    # The stack would have no master: its rows are rejected together, and the rest stands.
    assert counts(preview["job"]) == (1, 0, 0, 2)
    for row in preview["rows"][:2]:
        assert row["outcome"] == "rejected"
        assert reasons(row)[""] == (
            "the stack site2-sw-stack1 would have no master: a stack has exactly one "
            "master. The rows of this group are rejected together"
        )
    assert files.apply(preview, 422)["status"] == 422
    files.apply(preview, skip_rejected="true")
    stack = make.get("/device-groups", filter="name:eq:site2-sw-stack1")["items"][0]
    assert stack["member_count"] == 0
    domain = make.get("/device-groups", filter="name:eq:site2-wireless")["items"][0]
    assert domain["member_count"] == 1

    one = "group,item,role\nsite2-sw-stack1,AT-000101,master\n"
    preview = files.preview("device_group_members", one)
    assert "at least two members" in reasons(preview["rows"][0])[""]


def test_a_file_changes_the_master_and_ends_a_membership(make: Maker, files: Files) -> None:
    _inventory(make)
    files.load("device_groups", GROUPS)
    files.load("device_group_members", MEMBERS)
    text = (
        "group,item,role,left_on\n"
        "site2-sw-stack1,AT-000102,master,\n"
        "site2-sw-stack1,AT-000101,member,\n"
        "site2-wlc-ha,AT-000104,,2026-11-01\n"
    )

    preview = files.preview("device_group_members", text)

    assert counts(preview["job"]) == (0, 2, 1, 0)
    assert changes(preview["rows"][0]) == {"role": ("member", "master")}
    # Making the second the master made the first a member, so its row finds it so.
    assert preview["rows"][1]["outcome"] == "unchanged"
    assert changes(preview["rows"][2]) == {"left_on": (None, "2026-11-01")}
    files.apply(preview)
    stack = make.get("/device-groups", filter="name:eq:site2-sw-stack1")["items"][0]
    assert stack["serial_number"] == "FCW0000X002"
    cluster = make.get("/device-groups", filter="name:eq:site2-wlc-ha")["items"][0]
    assert cluster["member_count"] == 0


def test_what_a_row_of_groups_and_of_members_must_say(make: Maker, files: Files) -> None:
    _inventory(make)
    files.load("device_groups", GROUPS)
    for line, field, expected in (
        ("x,ring,,,,,", "type", "one of stack"),
        ("x,,,,,,", "type", "one of stack"),
        ("x,custom,,no-such-group,,,", "parent", "there is no device group"),
        ("x,custom,,,Nobody,,", "owner", "there is no owner"),
        ("x,custom,,,,retired,", "record_status", "does not retire"),
        ("site2-wireless,custom,,site2-wlc-ha,,,", "parent", "within it"),
    ):
        preview = files.preview("device_groups", GROUPS.splitlines()[0] + "\n" + line + "\n")
        assert counts(preview["job"])[3] == 1, line
        assert expected in reasons(preview["rows"][0])[field], line
    head = "group,item,role,position,joined_on,left_on\n"
    for line, field, expected in (
        ("no-such-group,AT-000101,,,,", "group", "there is no device group"),
        ("site2-wlc-ha,AT-000999,,,,", "item", "there is no item"),
        ("site2-wlc-ha,AT-000101,master,,,", "role", "in a cluster"),
        ("site2-wlc-ha,,,,,", "item", "must not be blank"),
        ("site2-wlc-ha,AT-000101,,,2026-02-01,2026-01-01", "left_on", "before the day it joined"),
    ):
        preview = files.preview("device_group_members", head + line + "\n")
        assert counts(preview["job"]) == (0, 0, 0, 1), line
        assert expected in reasons(preview["rows"][0])[field], line


def test_the_same_records_travel_as_json(make: Maker, files: Files) -> None:
    _inventory(make)
    files.load("device_groups", GROUPS)
    files.load("device_group_members", MEMBERS)
    envelope = {
        "schema": "hirdir/1",
        "entity": "items",
        "records": [
            {
                "name": "PS-A",
                "parent": "AT-000101",
                "position": "PS-A",
                "mgmt_address": "2001:db8::a",
            }
        ],
    }

    files.load("items", envelope)

    made = make.get("/items", filter="name:eq:PS-A")["items"][0]
    assert (made["parent"]["asset_tag"], made["addresses"][0]["address"]) == (
        "AT-000101",
        "2001:db8::a",
    )
    for entity in ("networks", "device_groups", "device_group_members", "addresses"):
        text = files.export(entity, format="json", own_values=True)
        assert f'"entity": "{entity}"' in text or f'"entity":"{entity}"' in text
