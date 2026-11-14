"""A planned location: what is meant for a place that is not in use yet moves in when
the place is made active, and nobody moves it device by device."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _patch(make: Maker, path: str, expect: int = 200, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields}, expect)


def _planned(make: Maker, **params: Any) -> dict[str, int]:
    """Return what is planned for each place of the tree, by path."""
    found: dict[str, int] = {}

    def walk(node: dict[str, Any]) -> None:
        found[node["path"]] = node["planned"]
        for child in node["children"]:
            walk(child)

    for root in make.get("/geography/tree", **params)["roots"]:
        walk(root)
    return found


def test_spares_planned_for_a_draft_site_move_in_when_it_is_made_active(make: Maker) -> None:
    places = make.layout()
    store = make.location("Store Room", places["site"], kind="warehouse")
    # The team plans a new site: a draft, with its building and its room.
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan, kind="room")
    closet = make.location("Closet", parent=suite)
    spares = make.switches(make.entry(make.vendor()), "spare", 3, lifecycle_state="Prod")
    for spare in spares:
        _patch(make, f"/items/{spare['hid']}", location_hid=store["hid"])
    supply = make.item(name="PS-A", parent_item_hid=spares[0]["hid"])

    # Two spares are meant for the new site. They stay in the store room, and are
    # counted and found there; the draft site shows what is planned for it.
    first = _patch(make, f"/items/{spares[0]['hid']}", planned_location_hid=suite["hid"])
    _patch(make, f"/items/{spares[1]['hid']}", planned_location_hid=closet["hid"])
    assert first["location"]["name"] == "Store Room"
    assert first["planned_location"]["path"] == "Americas > Central > Site-3 > Suite 300"
    assert make.get("/items", filter="location:within:Americas > Central > Site-2")["total"] == 4
    # The power supply is planned for where its switch is planned for, and says so.
    assert make.found(filter="planned_location:within:Americas > Central > Site-3") == [
        "PS-A",
        "spare-01",
        "spare-02",
    ]
    assert make.found(filter="planned_location_hid:empty:false location.name:eq:Store Room") == [
        "spare-01",
        "spare-02",
    ]
    going = make.get(f"/items/{supply['hid']}")
    assert going["planned_location_hid"] is None
    plan_in_force = going["effective"]["planned_location_hid"]
    assert (plan_in_force["label"], plan_in_force["source"], plan_in_force["source_label"]) == (
        "Americas > Central > Site-3 > Suite 300",
        "parent_item",
        "spare-01",
    )
    assert make.get(f"/locations/{suite['hid']}")["planned_items"] == 1
    planned = _planned(make, include_drafts="true")
    # The count is of items as a list counts them, the power supply among them.
    assert planned["Americas > Central > Site-3"] == 3
    assert planned["Americas > Central > Site-3 > Suite 300"] == 3
    assert planned["Americas > Central > Site-3 > Suite 300 > Closet"] == 1
    assert (planned["Americas > Central"], planned["Americas > Central > Site-2"]) == (3, 0)
    tree = make.get("/geography/tree")
    assert (tree["hidden"]["items"], tree["unplaced"]["items"]) == (0, 0)
    versions = {spare["hid"]: make.get(f"/items/{spare['hid']}")["row_version"] for spare in spares}
    events = make.get("/audit-events", limit=1)["total"]

    # The site opens: one change, of the site. What was planned for it is there.
    opened = _patch(make, f"/sites/{plan['hid']}", record_status="active")
    assert opened["record_status"] == "active"
    moved = make.get(f"/items/{spares[0]['hid']}")
    assert moved["location"]["path"] == "Americas > Central > Site-3 > Suite 300"
    assert (moved["planned_location_hid"], moved["planned_location"]) == (None, None)
    assert make.get(f"/items/{spares[1]['hid']}")["location"]["name"] == "Closet"
    # The power supply is where its switch is, and the third spare is where it was.
    in_force = make.get(f"/items/{supply['hid']}")["effective"]["location_hid"]
    assert (in_force["label"], in_force["source"]) == (
        "Americas > Central > Site-3 > Suite 300",
        "parent_item",
    )
    assert make.get(f"/items/{spares[2]['hid']}")["location"]["name"] == "Store Room"
    assert make.get("/items", filter="location:within:Americas > Central > Site-3")["total"] == 3
    assert make.get("/items", filter="planned_location:empty:false")["total"] == 0
    assert _planned(make)["Americas > Central > Site-3"] == 0
    # Each item has an entry of its own for the move, with the request that opened
    # the site; the third spare was not written to.
    assert make.get("/audit-events", limit=1)["total"] == events + 3
    history = make.get(f"/items/{spares[0]['hid']}/history")["items"][0]
    assert history["changes"] == [
        {"field": "location_hid", "old": store["hid"], "new": suite["hid"]},
        {"field": "planned_location_hid", "old": suite["hid"], "new": None},
    ]
    site_event = make.audit(record_type="site", record_hid=plan["hid"])[0]
    assert history["request_id"] == site_event["request_id"]
    assert make.get(f"/items/{spares[0]['hid']}")["row_version"] == versions[spares[0]["hid"]] + 1
    assert make.get(f"/items/{spares[2]['hid']}")["row_version"] == versions[spares[2]["hid"]]


def test_a_plan_waits_until_everything_the_location_is_in_is_active(make: Maker) -> None:
    americas = make.region("Americas")
    west = make.region("West", americas, record_status="draft")
    site = make.site("Site-7", west, record_status="draft")
    room = make.location("Room 1", site, record_status="draft")
    here = make.location("Staging", make.site("Site-2", americas))
    spare = make.item(
        hostname="spare-01", location_hid=here["hid"], planned_location_hid=room["hid"]
    )

    def where() -> tuple[str, str | None]:
        now = make.get(f"/items/{spare['hid']}")
        return now["location"]["name"], now["planned_location_hid"]

    # The room and the site are made active, and the region is still a draft.
    _patch(make, f"/locations/{room['hid']}", record_status="active")
    _patch(make, f"/sites/{site['hid']}", record_status="active")
    assert where() == ("Staging", room["hid"])
    # With the region, the room is in use, and the spare is there.
    _patch(make, f"/regions/{west['hid']}", record_status="active")
    assert where() == ("Room 1", None)


def test_only_a_place_that_is_not_in_use_is_planned_for(make: Maker, files: Files) -> None:
    places = make.layout()
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan)
    # The list of locations says which are in use, as the rule that refuses does: a
    # draft, what is in a draft, and what is in a site of a draft region are not.
    west = make.region("West", places["americas"], record_status="draft")
    make.location("Room 9", make.site("Site-9", west))
    make.location("Annex", places["site"], record_status="draft")
    closet = make.location("Closet", parent=suite)
    idle = make.get("/locations", filter="in_use:eq:false", include_drafts="true")["items"]
    assert sorted(one["name"] for one in idle) == ["Annex", "Closet", "Room 9", "Suite 300"]
    busy = make.get("/locations", filter="in_use:eq:true", include_drafts="true")["items"]
    assert sorted(one["name"] for one in busy) == ["Building 1", "Room 102"]
    make.post(f"/locations/{closet['hid']}/retire", {"row_version": closet["row_version"]}, 200)
    spare = make.item(hostname="spare-01", location_hid=places["room"]["hid"])
    path = f"/items/{spare['hid']}"

    # A location in use is where an item is moved to, not planned for.
    refused = _patch(make, path, 422, planned_location_hid=places["building"]["hid"])
    assert "in use" in refused["detail"]
    assert "planned_location_hid" in errors(refused)
    nobody = "01900000-0000-7000-8000-000000000000"
    assert "planned_location_hid" in errors(_patch(make, path, 422, planned_location_hid=nobody))
    planned = _patch(make, path, planned_location_hid=suite["hid"])
    assert planned["planned_location"]["name"] == "Suite 300"
    # Another shelf in staging in the meantime leaves the plan standing.
    moved = _patch(make, path, location_hid=places["building"]["hid"])
    assert moved["planned_location_hid"] == suite["hid"]
    # A location is not retired while something is planned for it.
    kept = make.post(
        f"/locations/{suite['hid']}/retire", {"row_version": suite["row_version"]}, 409
    )
    assert "1 item planned for it" in kept["detail"]
    # Carried there by hand, it is there, and nothing is planned any more.
    there = _patch(make, path, location_hid=suite["hid"])
    assert (there["location"]["name"], there["planned_location_hid"]) == ("Suite 300", None)
    # A plan is given up by clearing it, and a retired item is not moved.
    other = make.item(hostname="spare-02", planned_location_hid=suite["hid"])
    gone = make.item(hostname="spare-03", planned_location_hid=suite["hid"])
    cleared = _patch(make, f"/items/{other['hid']}", planned_location_hid=None)
    assert cleared["planned_location"] is None
    make.post(f"/items/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)
    _patch(make, f"/sites/{plan['hid']}", record_status="active")
    assert make.get(f"/items/{other['hid']}")["location"] is None
    retired = make.get(f"/items/{gone['hid']}")
    assert (retired["location"], retired["planned_location_hid"]) == (None, suite["hid"])


def test_a_plan_travels_in_files_is_set_on_many_and_a_file_opens_a_site(
    make: Maker, files: Files
) -> None:
    places = make.layout()
    make.tag("for-site-3")
    plan = make.site("Site-3", places["central"], record_status="draft")
    make.location("Suite 300", plan)
    suite = "Americas > Central > Site-3 > Suite 300"
    spares = make.switches(make.entry(make.vendor()), "spare", 3, tags=["for-site-3"])

    # A bulk edit plans many at once, and a file one more.
    edit = make.post(
        "/items/bulk-update",
        {
            "filter": "tags:has:for-site-3 hostname:in:spare-01,spare-02",
            "set": {"planned_location": suite},
        },
        201,
    )
    assert edit["job"]["updated"] == 2
    make.post(f"/items/bulk-update/{edit['job']['hid']}/apply", {}, 200)
    files.load("items", f"hid,planned_location\n{spares[2]['hid']},{suite}\n")
    assert make.get("/items", filter=f"planned_location:within:{suite}")["total"] == 3
    exported = files.export("items", own_values=True)
    assert exported.count(suite) == 3
    back = files.preview("items", exported)
    assert back["job"]["unchanged"] == back["job"]["row_count"] == 3
    wrong = files.preview(
        "items",
        f"hid,planned_location\n{spares[0]['hid']},Americas > Central > Site-2 > Building 1\n",
    )
    assert wrong["rows"][0]["reasons"][0]["field"] == "planned_location"
    # The site is made active by a file: the preview changes nothing, and the apply
    # moves the three in, each with its own entry.
    opening = files.preview(
        "sites", "name,region,record_status\nSite-3,Americas > Central,active\n"
    )
    assert opening["rows"][0]["outcome"] == "update"
    assert make.get("/items", filter=f"location:within:{suite}")["total"] == 0
    files.apply(opening)
    assert make.found(filter=f"location:within:{suite}") == ["spare-01", "spare-02", "spare-03"]
    assert make.get("/items", filter="planned_location:empty:false")["total"] == 0
    moves = make.audit(record_type="item", action="update", limit=3)
    assert {event["request_id"] for event in moves} == {moves[0]["request_id"]}


def test_a_device_group_is_planned_for_and_its_members_go_with_it(
    make: Maker, files: Files
) -> None:
    places = make.layout()
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan)
    switches = make.switches(make.entry(make.vendor()), "spare", 3)
    # Two members are in the room by a location of their own; the third has none.
    for switch in switches[:2]:
        _patch(make, f"/items/{switch['hid']}", location_hid=places["room"]["hid"])
    supply = make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    stack = make.stack("site3-sw-stack1", switches, location_hid=places["room"]["hid"])
    path = f"/device-groups/{stack['hid']}"

    # The third member is where its group is, and says so.
    third = make.get(f"/items/{switches[2]['hid']}")
    assert third["location_hid"] is None
    where = third["effective"]["location_hid"]
    assert (where["label"], where["source"], where["source_hid"], where["source_label"]) == (
        "Americas > Central > Site-2 > Building 1 > Room 102",
        "device_group",
        stack["hid"],
        "site3-sw-stack1",
    )
    assert make.get("/items", filter="location:within:Americas > Central > Site-2")["total"] == 4

    # The group is planned for the room of the draft site: one change, of the group.
    refused = _patch(make, path, 422, planned_location_hid=places["building"]["hid"])
    assert "planned_location_hid" in errors(refused)
    planned = _patch(make, path, planned_location_hid=suite["hid"])
    assert (planned["location"]["name"], planned["planned_location"]["name"]) == (
        "Room 102",
        "Suite 300",
    )
    names = make.get("/device-groups", filter="planned_location:within:Americas > Central > Site-3")
    assert [group["name"] for group in names["items"]] == ["site3-sw-stack1"]
    # The column of the grid is sorted and found by the name of the place.
    by_plan = make.get("/items", sort="-planned_location.name,name", limit=2)["items"]
    assert [item["hostname"] or item["name"] for item in by_plan] == ["PS-A", "spare-01"]
    named = make.get("/device-groups", filter="planned_location.name:contains:suite")
    assert named["total"] == 1
    # Its members are planned for with it, and nothing was written to them.
    assert make.found(filter="planned_location:within:Americas > Central > Site-3") == [
        "PS-A",
        "spare-01",
        "spare-02",
        "spare-03",
    ]
    member = make.get(f"/items/{switches[0]['hid']}")
    assert (member["planned_location_hid"], member["row_version"]) == (
        None,
        switches[0]["row_version"] + 1,
    )
    going = member["effective"]["planned_location_hid"]
    assert (going["label"], going["source"], going["source_label"]) == (
        "Americas > Central > Site-3 > Suite 300",
        "device_group",
        "site3-sw-stack1",
    )
    node = make.get("/geography/tree", root=plan["hid"], include_drafts="true")["roots"][0]
    assert (node["planned"], node["planned_groups"]) == (4, 1)
    assert make.get(f"/locations/{suite['hid']}")["planned_groups"] == 1
    kept = make.post(
        f"/locations/{suite['hid']}/retire", {"row_version": suite["row_version"]}, 409
    )
    assert "1 device group planned for it" in kept["detail"]
    # What a file says of a member is what the member has in force, and loading it back
    # gives the member nothing of its own.
    exported = files.export("items", columns=["hid", "location", "planned_location"])
    assert exported.count("Suite 300") == 4
    back = files.preview("items", exported)
    assert back["job"]["unchanged"] == back["job"]["row_count"] == 4
    back = files.preview("device_groups", files.export("device_groups", own_values=True))
    assert back["job"]["unchanged"] == back["job"]["row_count"] == 1
    # A member with a plan of its own keeps it: an override of the group's.
    closet = make.location("Closet", parent=suite)
    _patch(make, f"/items/{switches[1]['hid']}", planned_location_hid=closet["hid"])

    # The site opens. The group is there, and its members with it: the one with a plan
    # of its own is where that said, and the others are where the group is, with no
    # place of their own any more.
    _patch(make, f"/sites/{plan['hid']}", record_status="active")
    moved = make.get(path)
    assert (moved["location"]["name"], moved["planned_location_hid"]) == ("Suite 300", None)

    def now(hid: str) -> tuple[str | None, str, str, str | None]:
        item = make.get(f"/items/{hid}")
        in_force = item["effective"]["location_hid"]
        return (
            item["location_hid"],
            in_force["label"].rsplit(" > ", 1)[-1],
            in_force["source"],
            item["effective"]["planned_location_hid"]["value"],
        )

    assert now(switches[0]["hid"]) == (None, "Suite 300", "device_group", None)
    assert now(switches[1]["hid"]) == (closet["hid"], "Closet", "own", None)
    assert now(switches[2]["hid"]) == (None, "Suite 300", "device_group", None)
    # The power supply has it from the stack its switch is in, the switch having none.
    assert now(supply["hid"]) == (None, "Suite 300", "device_group", None)
    assert make.get("/items", filter="location:within:Americas > Central > Site-3")["total"] == 4
    assert make.get("/items", filter="location:within:Americas > Central > Site-2")["total"] == 0
    event = make.audit(record_type="device_group", record_hid=stack["hid"])[0]
    assert [change["field"] for change in event["changes"]] == [
        "location_hid",
        "planned_location_hid",
    ]
    site_event = make.audit(record_type="site", record_hid=plan["hid"])[0]
    assert event["request_id"] == site_event["request_id"]
    # The member that gave its own place up has an entry for it, under the same request;
    # the one that had none was not written to.
    went = make.get(f"/items/{switches[0]['hid']}/history")["items"][0]
    assert went["changes"] == [{"field": "location_hid", "old": places["room"]["hid"], "new": None}]
    assert went["request_id"] == site_event["request_id"]
    assert make.get(f"/items/{switches[2]['hid']}")["row_version"] == switches[2]["row_version"]


def test_a_group_is_moved_and_the_members_that_say_nothing_are_where_it_is(make: Maker) -> None:
    places = make.layout()
    room, building = places["room"], places["building"]
    switches = make.switches(make.entry(make.vendor()), "sw", 3)
    stack = make.stack("site2-sw-stack1", switches, location_hid=room["hid"])
    inner = make.post(
        "/device-groups",
        {"name": "inner", "type": "custom", "parent_group_hid": stack["hid"]},
        201,
    )
    # A group nested in another is where that group is.
    in_force = make.get(f"/device-groups/{inner['hid']}")["effective"]["location_hid"]
    assert (in_force["value"], in_force["source"], in_force["source_label"]) == (
        room["hid"],
        "device_group",
        "site2-sw-stack1",
    )
    found = make.get("/device-groups", filter="location:within:Americas > Central > Site-2")
    assert found["total"] == 2
    # One member is somewhere else by a location of its own: an override.
    _patch(make, f"/items/{switches[2]['hid']}", location_hid=building["hid"])
    assert make.found(filter=f"effective.location_hid:eq:{room['hid']}") == ["sw-01", "sw-02"]
    # The group is moved: one change, and its members are there.
    _patch(make, f"/device-groups/{stack['hid']}", location_hid=building["hid"])
    assert make.found(filter=f"effective.location_hid:eq:{building['hid']}") == [
        "sw-01",
        "sw-02",
        "sw-03",
    ]
    sources = {
        make.get(f"/items/{switch['hid']}")["effective"]["location_hid"]["source"]
        for switch in switches[:2]
    }
    assert sources == {"device_group"}
    rows = {row["key"]: row["items"] for row in make.get("/reports/summary", by="site")["rows"]}
    assert rows == {places["site"]["hid"]: 3}
    # Out of the group, a member with no place of its own is nowhere.
    first = make.members(stack)[0]
    make.patch(
        f"/device-groups/{stack['hid']}/members/{first['hid']}",
        {"row_version": first["row_version"], "role": "member"},
    )
    first = make.members(stack)[0]
    make.patch(
        f"/device-groups/{stack['hid']}/members/{first['hid']}",
        {"row_version": first["row_version"], "left_on": "2099-01-01"},
    )
    assert make.get(f"/items/{switches[0]['hid']}")["effective"]["location_hid"]["value"] is None


def test_the_list_and_the_record_agree_on_where_every_item_is_and_is_going(make: Maker) -> None:
    """Where an item is, and where it is going, is worked out twice: for a record and
    for the database to filter by. Whatever the inventory holds, the two agree."""
    places = make.layout()
    room, building = places["room"], places["building"]
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan)
    closet = make.location("Closet", parent=suite)
    switches = make.switches(make.entry(make.vendor()), "sw", 8)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"], location_hid=building["hid"])
    module = make.item(name="MOD-1", parent_item_hid=switches[1]["hid"])
    make.item(name="SFP-1", parent_item_hid=module["hid"], planned_location_hid=closet["hid"])
    ours, theirs = make.owner(), make.owner("Voice Services")
    make.stack(
        "stack-b",
        switches[:2],
        location_hid=room["hid"],
        planned_location_hid=suite["hid"],
        owner_hid=ours["hid"],
    )
    outer = make.group(
        "domain",
        "controller_domain",
        location_hid=building["hid"],
        planned_location_hid=closet["hid"],
        owner_hid=theirs["hid"],
    )
    make.group(
        "cluster-a",
        "cluster",
        [(switches[1], "active"), (switches[2], "standby")],
        parent_group_hid=outer["hid"],
    )
    # Of two groups of one type, the first by name decides; a group with nothing passes.
    make.group("custom-a", "custom", [(switches[3], "member")], location_hid=room["hid"])
    make.group("custom-b", "custom", [(switches[3], "member")], location_hid=building["hid"])
    make.group("empty-handed", "custom", [(switches[4], "member")])
    _patch(make, f"/items/{switches[5]['hid']}", location_hid=building["hid"])
    _patch(make, f"/items/{switches[6]['hid']}", planned_location_hid=suite["hid"])
    retired = make.group("old", "custom", [(switches[7], "member")], location_hid=room["hid"])
    make.post(f"/device-groups/{retired['hid']}/retire", {"row_version": 1}, 200)

    everything = make.get("/items", limit=1000)["items"]
    for name in ("location_hid", "planned_location_hid", "owner_hid"):
        by_record: dict[str | None, set[str]] = {}
        for item in everything:
            by_record.setdefault(item["effective"][name]["value"], set()).add(item["hid"])
        assert len(by_record) == 3, name
        for place, hids in by_record.items():
            condition = (
                f"effective.{name}:empty:true" if place is None else f"effective.{name}:eq:{place}"
            )
            listed = {
                row["hid"] for row in make.get("/items", filter=condition, limit=1000)["items"]
            }
            assert listed == hids, (name, place)
    by_name = {item["hostname"] or item["name"]: item["effective"] for item in everything}
    assert by_name["sw-02"]["location_hid"]["source_label"] == "stack-b"
    assert by_name["sw-03"]["location_hid"]["source_label"] == "domain"
    assert by_name["sw-04"]["location_hid"]["value"] == room["hid"]
    assert by_name["sw-08"]["location_hid"]["value"] is None
    assert by_name["MOD-1"]["planned_location_hid"]["source"] == "device_group"
    assert by_name["SFP-1"]["planned_location_hid"]["source"] == "own"
    assert (by_name["sw-03"]["owner_hid"]["label"], by_name["sw-03"]["owner_hid"]["source"]) == (
        "Voice Services",
        "device_group",
    )
    assert by_name["sw-06"]["owner_hid"]["value"] is None


def test_an_item_with_no_owner_of_its_own_has_the_owner_of_its_group(
    make: Maker, files: Files
) -> None:
    ours = make.owner()
    outside = make.owner("Voice Services", is_external=True, exception_reason="Run by the vendor")
    switches = make.switches(make.entry(make.vendor()), "sw", 3)
    supply = make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    stack = make.stack("site2-sw-stack1", switches, owner_hid=ours["hid"])
    inner = make.group("inner", "custom", parent_group_hid=stack["hid"])

    # One change of the group, and its members are that owner's; none is written to.
    for hid in (switches[0]["hid"], supply["hid"]):
        owner = make.get(f"/items/{hid}")["effective"]["owner_hid"]
        assert (owner["label"], owner["source"], owner["source_hid"]) == (
            "Network Engineering",
            "device_group",
            stack["hid"],
        )
    assert make.get(f"/items/{switches[0]['hid']}")["owner_hid"] is None
    assert make.get("/items", filter=f"effective.owner_hid:eq:{ours['hid']}")["total"] == 4
    rows = {row["label"]: row["items"] for row in make.get("/reports/summary", by="owner")["rows"]}
    assert rows == {"Network Engineering": 4}
    nested = make.get(f"/device-groups/{inner['hid']}")["effective"]["owner_hid"]
    assert (nested["label"], nested["source"]) == ("Network Engineering", "device_group")
    found = make.get("/device-groups", filter=f"effective.owner_hid:eq:{ours['hid']}")
    assert found["total"] == 2
    # A member with an owner of its own keeps it, and the group says that it differs.
    _patch(make, f"/items/{switches[2]['hid']}", owner_hid=outside["hid"])
    third = make.get(f"/items/{switches[2]['hid']}")
    assert (third["effective"]["owner_hid"]["source"], third["owner_exception"]) == ("own", True)
    assert make.get(f"/device-groups/{stack['hid']}")["members_disagree"] == ["owner_hid"]
    # A file says the owner in force, and loaded back gives the members none of their own.
    exported = files.export("items", columns=["hid", "owner"])
    assert exported.count("Network Engineering") == 3
    back = files.preview("items", exported)
    assert back["job"]["unchanged"] == back["job"]["row_count"] == 4
    # Given to an owner outside the team, the group and its members are an exception.
    _patch(make, f"/device-groups/{stack['hid']}", owner_hid=outside["hid"])
    first = make.get(f"/items/{switches[0]['hid']}")
    assert (first["owner_exception"], first["owner_exception_reason"]) == (
        True,
        "Run by the vendor",
    )
    assert make.get(f"/device-groups/{inner['hid']}")["owner_exception"] is True
    assert make.get("/items", filter="owner_exception:eq:true")["total"] == 4


def test_a_group_list_finds_groups_by_the_operator_in_force(make: Maker) -> None:
    mark = make.post("/operators", {"label": "LM"})
    outer = make.group("domain", "controller_domain", operator_hid=mark["hid"])
    make.group("cluster-a", "cluster", parent_group_hid=outer["hid"])
    make.group("alone", "custom")
    found = make.get("/device-groups", filter=f"effective.operator_hid:eq:{mark['hid']}")
    assert [group["name"] for group in found["items"]] == ["cluster-a", "domain"]
    nobody = make.get("/device-groups", filter="effective.operator_hid:empty:true")
    assert [group["name"] for group in nobody["items"]] == ["alone"]
