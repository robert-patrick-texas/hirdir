"""The audit trail holds what a later sync to IPAM, DNS and monitoring will read (P-310).

After 1.0.0 the names and addresses that changes add, remove and alter are to be read
from the audit trail in batches (P-223). Each way a name, a host name, an FQDN or an
address of an item, a device group or a place can change is driven here, and its events
are held to say the value before and after and whose it is, from the event alone:

- an item's, a group's and a place's names are the record's own, `record_type` and
  `record_hid`, with `old` and `new` of each that changes;
- every event of an address holds the address and the item or the group it belongs to,
  as `address` and `item_hid` or `group_hid`, with `old` and `new` the same where it did
  not change, and the network it is under where it has one;
- a retirement and a bringing back hold what the record is known by on a network, its
  names and, for an item or a group, `addresses`, each with `old` and `new` the same.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files

# The kinds of record whose names and addresses a sync reads.
NAMED = ("item", "device_group", "region", "site", "location")
NAMES = ("name", "hostname", "fqdn")


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


class Trail:
    """The events made since it was last read, oldest first."""

    def __init__(self, make: Maker) -> None:
        self.make = make
        self.seen = {event["hid"] for event in self._newest()}

    def _newest(self) -> list[dict[str, Any]]:
        return self.make.get("/audit-events", limit=500)["items"]

    def new(self) -> list[dict[str, Any]]:
        events = [event for event in self._newest() if event["hid"] not in self.seen]
        self.seen |= {event["hid"] for event in events}
        for event in events:
            readable(event)
        return list(reversed(events))


def entries(event: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in event["changes"]}


def whose(event: dict[str, Any]) -> tuple[str, str]:
    """Return the item or the group an event of an address says the address is of."""
    changed = entries(event)
    for field in ("item_hid", "group_hid"):
        old, new = changed.get(field, (None, None))
        if new is not None or (old is not None and event["action"] == "delete"):
            return field, new if new is not None else old
    raise AssertionError(f"an event of an address names no item or group: {event}")


def readable(event: dict[str, Any]) -> None:
    """Hold an event to what a sync reads of it, whatever made it."""
    if event["record_type"] == "address":
        old, new = entries(event).get("address", (None, None))
        assert (old if event["action"] == "delete" else new) is not None, event
        whose(event)


def of(events: list[dict[str, Any]], record: dict[str, Any], action: str | None = None) -> list:
    return [
        event
        for event in events
        if event["record_hid"] == record["hid"] and (action is None or event["action"] == action)
    ]


def one(events: list[dict[str, Any]], record: dict[str, Any], action: str | None = None) -> dict:
    found = of(events, record, action)
    assert len(found) == 1, (record["hid"], action, events)
    return found[0]


def _model(make: Maker) -> dict[str, Any]:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries_ = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    return entries_[0] if entries_ else make.entry(vendor)


def _switch(make: Maker, number: int, **more: Any) -> dict[str, Any]:
    return make.item(
        catalog_entry_hid=_model(make)["hid"],
        serial_number=f"FCW8000{number:04d}",
        lifecycle_state="Prod",
        **more,
    )


def _named_switch(make: Maker, number: int, **more: Any) -> dict[str, Any]:
    return _switch(
        make,
        number,
        name=f"sw-{number:02d}",
        hostname=f"sw-{number:02d}",
        fqdn=f"sw-{number:02d}.example.net",
        **more,
    )


def _now(make: Maker, record: dict[str, Any], path: str = "/items") -> dict[str, Any]:
    return make.get(f"{path}/{record['hid']}")


def _held(address: dict[str, Any], holder: str) -> dict[str, Any]:
    """An address as the event of its holder lists it."""
    return {
        "hid": address["hid"],
        "item_hid": address["item_hid"] if holder == "item_hid" else None,
        "group_hid": address["group_hid"] if holder == "group_hid" else None,
        "address": address["address"],
        "network_hid": address["network_hid"],
        "role": address["role"],
        "is_primary": address["is_primary"],
    }


# --- the API: create, update, retire, bring back -----------------------------------------


def test_what_the_api_creates_and_changes_says_its_values_and_whose_they_are(
    make: Maker,
) -> None:
    trail = Trail(make)
    item = _named_switch(make, 1)
    group = make.group("core-1", "cluster", hostname="core-1", fqdn="core-1.example.net")
    oob = make.network("oob")
    address = make.address(item, "192.0.2.10", oob, is_primary=True)
    shared = make.address(group, "2001:db8::10")
    made = trail.new()
    assert {
        name: value for name, value in entries(one(made, item, "create")).items() if name in NAMES
    } == {
        "name": (None, "sw-01"),
        "hostname": (None, "sw-01"),
        "fqdn": (None, "sw-01.example.net"),
    }
    assert entries(one(made, group, "create"))["fqdn"] == (None, "core-1.example.net")
    given = entries(one(made, address, "create"))
    assert (given["address"], given["item_hid"], given["network_hid"]) == (
        (None, "192.0.2.10"),
        (None, item["hid"]),
        (None, oob["hid"]),
    )
    assert whose(one(made, shared, "create")) == ("group_hid", group["hid"])

    # The names change, each with what it was.
    make.patch(
        f"/items/{item['hid']}",
        {"row_version": item["row_version"], "hostname": "sw-01a", "fqdn": None},
    )
    group = make.patch(
        f"/device-groups/{group['hid']}",
        {"row_version": group["row_version"], "name": "core-1a", "hostname": "core-1a"},
    )
    changed = trail.new()
    assert entries(one(changed, item)) == {
        "hostname": ("sw-01", "sw-01a"),
        "fqdn": ("sw-01.example.net", None),
    }
    assert entries(one(changed, group)) == {
        "name": ("core-1", "core-1a"),
        "hostname": ("core-1", "core-1a"),
    }

    # An address that changes says which it is and whose, whatever of it changed: the
    # address itself, its network, or only its role.
    address = make.patch(
        f"/addresses/{address['hid']}",
        {"row_version": address["row_version"], "address": "192.0.2.11"},
    )
    address = make.patch(
        f"/addresses/{address['hid']}", {"row_version": address["row_version"], "network_hid": None}
    )
    shared = make.patch(
        f"/addresses/{shared['hid']}", {"row_version": shared["row_version"], "role": "virtual"}
    )
    first, second = of(trail.new(), address)
    assert entries(first) == {
        "address": ("192.0.2.10", "192.0.2.11"),
        "item_hid": (item["hid"], item["hid"]),
        "network_hid": (oob["hid"], oob["hid"]),
    }
    assert entries(second) == {
        "network_hid": (oob["hid"], None),
        "address": ("192.0.2.11", "192.0.2.11"),
        "item_hid": (item["hid"], item["hid"]),
    }
    [role] = of(make.audit(record_type="address", record_hid=shared["hid"], limit=1), shared)
    assert entries(role) == {
        "role": ("management", "virtual"),
        "address": ("2001:db8::10", "2001:db8::10"),
        "group_hid": (group["hid"], group["hid"]),
    }
    # A request that changes nothing writes nothing.
    make.patch(
        f"/addresses/{shared['hid']}", {"row_version": shared["row_version"], "role": "virtual"}
    )
    assert trail.new() == []


def test_a_retirement_and_a_bringing_back_say_what_goes_out_of_service_and_comes_back(
    make: Maker,
) -> None:
    item = _named_switch(make, 2)
    address = make.address(item, "192.0.2.20", is_primary=True)
    group = make.group("core-2", "cluster", hostname="core-2")
    vip = make.address(group, "198.51.100.20", role="virtual")
    places = make.layout()
    closet = make.location("Closet 9", places["site"], kind="room")
    trail = Trail(make)

    gone = make.post(f"/items/{item['hid']}/retire", {"row_version": item["row_version"]}, 200)
    retired = one(trail.new(), item, "retire")
    assert entries(retired) == {
        "record_status": ("active", "retired"),
        "name": ("sw-02", "sw-02"),
        "hostname": ("sw-02", "sw-02"),
        "fqdn": ("sw-02.example.net", "sw-02.example.net"),
        "addresses": ([_held(address, "item_hid")], [_held(address, "item_hid")]),
    }
    # Brought back with another host name in the same change: the change says it, once.
    make.patch(
        f"/items/{item['hid']}",
        {"row_version": gone["row_version"], "record_status": "active", "hostname": "sw-02b"},
    )
    back = entries(one(trail.new(), item))
    assert back == {
        "record_status": ("retired", "active"),
        "hostname": ("sw-02", "sw-02b"),
        "name": ("sw-02", "sw-02"),
        "fqdn": ("sw-02.example.net", "sw-02.example.net"),
        "addresses": ([_held(address, "item_hid")], [_held(address, "item_hid")]),
    }
    # A change that neither retires nor brings back says nothing more than it changes.
    now = _now(make, item)
    make.patch(f"/items/{item['hid']}", {"row_version": now["row_version"], "comments": "back"})
    assert entries(one(trail.new(), item)) == {"comments": (None, "back")}

    gone = make.post(
        f"/device-groups/{group['hid']}/retire", {"row_version": group["row_version"]}, 200
    )
    held = [_held(vip, "group_hid")]
    assert entries(one(trail.new(), group, "retire")) == {
        "record_status": ("active", "retired"),
        "name": ("core-2", "core-2"),
        "hostname": ("core-2", "core-2"),
        "addresses": (held, held),
    }
    make.patch(
        f"/device-groups/{group['hid']}",
        {"row_version": gone["row_version"], "record_status": "active"},
    )
    assert entries(one(trail.new(), group))["addresses"] == (held, held)

    gone = make.post(
        f"/locations/{closet['hid']}/retire", {"row_version": closet["row_version"]}, 200
    )
    assert entries(one(trail.new(), closet, "retire")) == {
        "record_status": ("active", "retired"),
        "name": ("Closet 9", "Closet 9"),
    }
    make.patch(
        f"/locations/{closet['hid']}",
        {"row_version": gone["row_version"], "record_status": "active"},
    )
    assert entries(one(trail.new(), closet))["name"] == ("Closet 9", "Closet 9")


def test_a_place_renamed_says_the_name_it_had(make: Maker) -> None:
    places = make.layout()
    trail = Trail(make)
    for level, record, new in (
        ("regions", places["central"], "Central US"),
        ("sites", places["site"], "Site-2 East"),
        ("locations", places["room"], "Room 102A"),
    ):
        make.patch(f"/{level}/{record['hid']}", {"row_version": record["row_version"], "name": new})
        assert entries(one(trail.new(), record)) == {"name": (record["name"], new)}


def test_a_deletion_holds_the_names_and_each_address_that_went_with_it(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    item = _named_switch(make, 3)
    address = make.address(item, "192.0.2.30", is_primary=True)
    trail = Trail(make)
    response = client.post(
        "/api/v1/items/delete",
        json={"hids": [item["hid"]], "reason": "entered twice"},
        headers=admin,
    )
    assert response.status_code == 200, response.text
    gone = trail.new()
    deleted = entries(one(gone, item, "delete"))
    assert (deleted["hostname"], deleted["fqdn"]) == (
        ("sw-03", None),
        ("sw-03.example.net", None),
    )
    assert deleted["addresses"] == ([_held(address, "item_hid")], None)
    went = entries(one(gone, address, "delete"))
    assert (went["address"], went["item_hid"], went["deleted_with"]) == (
        ("192.0.2.30", None),
        (item["hid"], None),
        (None, item["hid"]),
    )


# --- a bulk edit, an import ----------------------------------------------------------------


def test_a_bulk_edit_of_one_item_says_the_names_and_the_address_it_changed(make: Maker) -> None:
    item = _named_switch(make, 4)
    address = make.address(item, "192.0.2.40", is_primary=True)
    trail = Trail(make)
    preview = make.post(
        "/items/bulk-update",
        {"hids": [item["hid"]], "set": {"hostname": "sw-04b", "mgmt_address": "192.0.2.41"}},
    )
    job = make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    assert job["status"] == "applied"
    made = [event for event in trail.new() if event["record_type"] in ("item", "address")]
    assert len({event["request_id"] for event in made}) == 1
    assert entries(one(made, item))["hostname"] == ("sw-04", "sw-04b")
    assert entries(one(made, address)) == {
        "address": ("192.0.2.40", "192.0.2.41"),
        "item_hid": (item["hid"], item["hid"]),
    }


def test_an_import_says_the_names_and_the_addresses_it_changed(make: Maker, files: Files) -> None:
    item = _named_switch(make, 5)
    address = make.address(item, "192.0.2.50", role="loopback")
    group = make.group("core-5", "cluster", hostname="core-5")
    trail = Trail(make)
    files.load("items", f"hid,hostname,mgmt_address\n{item['hid']},sw-05b,192.0.2.51\n")
    files.load("addresses", f"hid,address\n{address['hid']},192.0.2.52\n")
    files.load("device_groups", f"hid,fqdn\n{group['hid']},core-5.example.net\n")
    made = [event for event in trail.new() if event["via"] == "import"]
    assert entries(one(made, item))["hostname"] == ("sw-05", "sw-05b")
    primary = next(
        event for event in made if event["record_type"] == "address" and event["action"] == "create"
    )
    assert (entries(primary)["address"], whose(primary)) == (
        (None, "192.0.2.51"),
        ("item_hid", item["hid"]),
    )
    assert entries(one(made, address)) == {
        "address": ("192.0.2.50", "192.0.2.52"),
        "item_hid": (item["hid"], item["hid"]),
    }
    assert entries(one(made, group))["fqdn"] == (None, "core-5.example.net")


# --- groups: joining, leaving, a stack made of a switch, a replacement ---------------------


def _stack(make: Maker, *members: dict[str, Any]) -> dict[str, Any]:
    return make.group(
        "idf9-acc1",
        "stack",
        [(member, "master" if place == 0 else "member") for place, member in enumerate(members)],
        hostname="idf9-acc1",
        fqdn="idf9-acc1.example.net",
    )


def _joining(event: dict[str, Any]) -> Any:
    return entries(event).get("joining_group", (None, None))[1]


def test_a_spare_that_joins_a_stack_says_what_it_gave_up_and_one_that_leaves_what_it_took(
    make: Maker,
) -> None:
    stack = _stack(make, _switch(make, 60))
    spare = _named_switch(make, 61, disposition="Spare", expected_online=False)
    address = make.address(spare, "192.0.2.61", is_primary=True)
    trail = Trail(make)
    make.add(
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
    joined = trail.new()
    gave_up = entries(one(joined, spare))
    assert (gave_up["hostname"], gave_up["fqdn"], _joining(one(joined, spare))) == (
        ("sw-61", None),
        ("sw-61.example.net", None),
        stack["hid"],
    )
    dropped = one(joined, address, "delete")
    assert (entries(dropped)["address"], whose(dropped), _joining(dropped)) == (
        ("192.0.2.61", None),
        ("item_hid", spare["hid"]),
        stack["hid"],
    )

    member = next(one_ for one_ in make.members(stack) if one_["item_hid"] == spare["hid"])
    make.patch(
        f"/device-groups/{stack['hid']}/members/{member['hid']}",
        {
            "row_version": member["row_version"],
            "left_on": member["joined_on"],
            "item": {"hostname": "spare-sw-61", "fqdn": "spare-sw-61.example.net"},
        },
    )
    left = entries(one(trail.new(), spare))
    assert (left["hostname"], left["fqdn"], left["leaving_group"]) == (
        (None, "spare-sw-61"),
        (None, "spare-sw-61.example.net"),
        (stack["hid"], None),
    )


def test_a_stack_made_of_a_switch_says_each_address_it_took_and_from_whom(make: Maker) -> None:
    switch = _switch(make, 70, name="sw-70", hostname="idf7-acc1")
    address = make.address(switch, "192.0.2.70", is_primary=True)
    trail = Trail(make)
    stack = make.post(f"/items/{switch['hid']}/make-stack", {"row_version": switch["row_version"]})
    made = trail.new()
    assert entries(one(made, stack, "create"))["hostname"] == (None, "idf7-acc1")
    assert entries(one(made, switch))["hostname"] == ("idf7-acc1", None)
    moved = one(made, address)
    assert entries(moved) == {
        "item_hid": (switch["hid"], None),
        "group_hid": (None, stack["hid"]),
        "address": ("192.0.2.70", "192.0.2.70"),
        "joining_group": (None, stack["hid"]),
    }
    assert whose(moved) == ("group_hid", stack["hid"])


def test_an_item_that_takes_a_members_place_says_what_it_gave_up(make: Maker) -> None:
    master = _switch(make, 80)
    _stack(make, master)
    spare = _named_switch(make, 81)
    address = make.address(spare, "192.0.2.81", is_primary=True)
    trail = Trail(make)
    made = make.post(
        f"/items/{master['hid']}/replace",
        {
            "row_version": _now(make, master)["row_version"],
            "reason": "rma",
            "new_item_hid": spare["hid"],
            "drop_identity": True,
        },
    )
    events = trail.new()
    came = [event for event in of(events, spare) if "hostname" in entries(event)]
    assert len(came) == 1
    assert (entries(came[0])["hostname"], entries(came[0])["replacing"]) == (
        ("sw-81", None),
        (None, made["hid"]),
    )
    dropped = one(events, address, "delete")
    assert (entries(dropped)["address"], whose(dropped), entries(dropped)["replacing"]) == (
        ("192.0.2.81", None),
        ("item_hid", spare["hid"]),
        (None, made["hid"]),
    )


# --- an address made primary ---------------------------------------------------------------


def test_an_address_made_primary_says_which_lost_the_mark_and_whose(make: Maker) -> None:
    item = _named_switch(make, 9)
    first = make.address(item, "192.0.2.90", is_primary=True)
    second = make.address(item, "192.0.2.91")
    trail = Trail(make)
    make.patch(
        f"/addresses/{second['hid']}", {"row_version": second["row_version"], "is_primary": True}
    )
    made = trail.new()
    assert entries(one(made, second)) == {
        "is_primary": (False, True),
        "address": ("192.0.2.91", "192.0.2.91"),
        "item_hid": (item["hid"], item["hid"]),
    }
    assert entries(one(made, first)) == {
        "is_primary": (True, False),
        "address": ("192.0.2.90", "192.0.2.90"),
        "item_hid": (item["hid"], item["hid"]),
    }
    # Removed, an address says what it was and whose.
    make.delete(f"/addresses/{first['hid']}")
    removed = entries(one(trail.new(), first, "delete"))
    assert (removed["address"], removed["item_hid"]) == (("192.0.2.90", None), (item["hid"], None))
