"""What the review of 0.5.0 found, each held by a test: changes at the same moment,
records brought back, the depth of regions, a reason that outlives its owner's flag,
files whose rows stand in any order, and who may change what."""

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.domain import items
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files
from tests.api.test_hardening import _together


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _retire(make: Maker, level: str, place: dict[str, Any], expect: int = 200) -> dict[str, Any]:
    now = make.get(f"/{level}/{place['hid']}")
    return make.post(f"/{level}/{place['hid']}/retire", {"row_version": now["row_version"]}, expect)


# --- two requests at the same moment ---------------------------------------------------


def test_a_location_is_not_retired_while_an_item_is_being_put_into_it(
    make: Maker, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = make.layout()["room"]
    switch = make.item(hostname="site2-sw-access-01")
    looked = threading.Event()
    real = items._reference

    def reference(db: Any, model: Any, field: str, value: Any, item: Any, what: str) -> Any:
        found = real(db, model, field, value, item, what)
        if field == "location_hid":
            # The item's request has seen the room in order. The other request is let
            # go now, and has a moment to retire the room before the item is written.
            looked.set()
            threading.Event().wait(0.5)
        return found

    monkeypatch.setattr(items, "_reference", reference)

    def place(caller: TestClient) -> Any:
        return caller.patch(
            f"{API}/items/{switch['hid']}",
            json={"row_version": switch["row_version"], "location_hid": room["hid"]},
            headers=make.headers,
        )

    def retire(caller: TestClient) -> Any:
        looked.wait(5)
        return caller.post(
            f"{API}/locations/{room['hid']}/retire",
            json={"row_version": room["row_version"]},
            headers=make.headers,
        )

    # The item took its turn before it looked, so the retiring waits, and then finds it.
    assert _together(client, [place, retire]) == [200, 409]
    assert make.get(f"/items/{switch['hid']}")["location_hid"] == room["hid"]
    assert make.get(f"/locations/{room['hid']}")["record_status"] == "active"


def test_of_two_places_of_one_name_made_at_once_one_is_a_conflict(
    make: Maker, client: TestClient
) -> None:
    places = make.layout()
    gate = threading.Barrier(2, timeout=5)

    def create(path: str, body: dict[str, Any]) -> Any:
        def call(caller: TestClient) -> Any:
            gate.wait()
            return caller.post(API + path, json=body, headers=make.headers)

        return call

    for path, body in (
        ("/regions", {"name": "East", "parent_region_hid": places["americas"]["hid"]}),
        ("/sites", {"name": "Site-9", "region_hid": places["central"]["hid"]}),
        ("/locations", {"name": "Annex", "site_hid": places["site"]["hid"]}),
    ):
        assert _together(client, [create(path, body), create(path, body)]) == [201, 409]
        gate.reset()


def test_two_members_made_primary_at_once_leave_one_primary(
    make: Maker, client: TestClient
) -> None:
    owner = make.owner()
    first, second, third = (make.contact(name) for name in ("Dana W", "Robin A", "Lee M"))
    path = f"/owners/{owner['hid']}/members"
    make.post(path, {"contact_hid": first["hid"]})
    gate = threading.Barrier(2, timeout=5)

    def add(contact: dict[str, Any]) -> Any:
        def call(caller: TestClient) -> Any:
            gate.wait()
            body = {"contact_hid": contact["hid"], "role": "primary"}
            return caller.post(API + path, json=body, headers=make.headers)

        return call

    assert _together(client, [add(second), add(third)]) == [201, 201]
    roles = [member["role"] for member in make.get(path)["items"]]
    assert sorted(roles) == ["alternate", "alternate", "primary"]


def test_two_moves_at_once_make_no_region_a_part_of_itself(make: Maker, client: TestClient) -> None:
    one, other = make.region("North"), make.region("South")
    gate = threading.Barrier(2, timeout=5)

    def move(region: dict[str, Any], into: dict[str, Any]) -> Any:
        def call(caller: TestClient) -> Any:
            gate.wait()
            body = {"row_version": region["row_version"], "parent_region_hid": into["hid"]}
            return caller.patch(f"{API}/regions/{region['hid']}", json=body, headers=make.headers)

        return call

    assert _together(client, [move(one, other), move(other, one)]) == [200, 422]


# --- brought back ----------------------------------------------------------------------


def test_nothing_is_brought_back_into_a_place_that_is_retired(make: Maker) -> None:
    places = make.layout()
    room, building, site = places["room"], places["building"], places["site"]
    switch = make.item(hostname="site2-sw-access-01", location_hid=room["hid"])
    stack = make.group("site2-sw-stack1", location_hid=room["hid"])
    switch = make.post(
        f"/items/{switch['hid']}/retire", {"row_version": switch["row_version"]}, 200
    )
    stack = make.post(
        f"/device-groups/{stack['hid']}/retire", {"row_version": stack["row_version"]}, 200
    )
    for level, place in (("locations", room), ("locations", building), ("sites", site)):
        _retire(make, level, place)

    def back(path: str, record: dict[str, Any], expect: int = 200, **more: Any) -> dict[str, Any]:
        now = make.get(path)
        body = {"row_version": now["row_version"], "record_status": "active", **more}
        return make.patch(path, body, expect)

    # The room is in a building that is retired, in a site that is retired.
    refused = back(f"/locations/{room['hid']}", room, 422)
    assert "Building 1" in errors(refused)["record_status"]
    assert "Site-2" in errors(back(f"/locations/{building['hid']}", building, 422))["record_status"]
    # Nor is an item or a group brought back to where it was, while that is retired.
    assert "record_status" in errors(back(f"/items/{switch['hid']}", switch, 422))
    assert "record_status" in errors(back(f"/device-groups/{stack['hid']}", stack, 422))
    # Given another place, or none, with the change, it is.
    assert back(f"/items/{switch['hid']}", switch, location_hid=None)["record_status"] == "active"
    # From the top down, each place comes back, and then what was in it.
    for path in (f"/sites/{site['hid']}", f"/locations/{building['hid']}"):
        assert back(path, {})["record_status"] == "active"
    assert back(f"/locations/{room['hid']}", room)["record_status"] == "active"
    assert back(f"/device-groups/{stack['hid']}", stack)["location"]["name"] == "Room 102"
    # A file is held to the same.
    _retire(make, "locations", building, 409)


def test_regions_nest_sixteen_deep_and_no_deeper(make: Maker) -> None:
    line = [make.region("Level 1")]
    for depth in range(2, 17):
        line.append(make.region(f"Level {depth}", line[-1]))
    too_deep = {"name": "Level 17", "parent_region_hid": line[-1]["hid"]}
    assert "at most 16 deep" in errors(make.post("/regions", too_deep, 422))["parent_region_hid"]
    # Nor is a region with regions in it moved to where they would be too deep.
    other = make.region("Other")
    make.region("Inner", other)
    moved = make.patch(
        f"/regions/{other['hid']}",
        {"row_version": other["row_version"], "parent_region_hid": line[-2]["hid"]},
        422,
    )
    assert "parent_region_hid" in errors(moved)
    # The whole line is shown, and answered, as one tree.
    tree = make.get("/geography/tree")
    node, depth = tree["roots"][0], 1
    while node["children"]:
        node, depth = node["children"][0], depth + 1
    assert (depth, node["path"].count(" > ")) == (16, 15)


# --- the tree --------------------------------------------------------------------------


def test_the_counts_beside_the_tree_do_not_change_with_where_it_starts(make: Maker) -> None:
    places = make.layout()
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan)
    make.item(hostname="a", location_hid=places["room"]["hid"])
    make.item(hostname="b", location_hid=suite["hid"])
    make.item(hostname="c")

    whole = make.get("/geography/tree")
    for root in (plan["hid"], suite["hid"], places["room"]["hid"], "Americas"):
        rooted = make.get("/geography/tree", root=root)
        assert [rooted[name] for name in ("totals", "unplaced", "hidden")] == [
            whole[name] for name in ("totals", "unplaced", "hidden")
        ], root
    assert whole["hidden"]["items"] == 1
    # The place that was asked for is shown with what is in it all the same.
    assert make.get("/geography/tree", root=plan["hid"])["roots"][0]["items"] == 1


# --- files -----------------------------------------------------------------------------


def test_the_people_of_an_owner_load_wherever_their_rows_stand(make: Maker, files: Files) -> None:
    make.owner()
    for name in ("Dana Whitfield", "Robin Achterberg"):
        make.contact(name)
    dana, robin = "dana.whitfield@example.net", "robin.achterberg@example.net"
    header = "owner,contact,role\n"

    # The alternate's row stands before the primary's.
    files.load(
        "owner_members",
        f"{header}Network Engineering,{robin},alternate\nNetwork Engineering,{dana},primary\n",
    )
    owner = make.get("/owners")["items"][0]
    assert [(one["contact"]["email"], one["role"]) for one in owner["members"]] == [
        (dana, "primary"),
        (robin, "alternate"),
    ]
    # The two change places, and the row of the one that steps down stands first.
    swapped = files.load(
        "owner_members",
        f"{header}Network Engineering,{dana},alternate\nNetwork Engineering,{robin},primary\n",
    )
    assert (swapped["status"], swapped["rejected"]) == ("applied", 0)
    owner = make.get("/owners")["items"][0]
    assert [(one["contact"]["email"], one["role"]) for one in owner["members"]] == [
        (robin, "primary"),
        (dana, "alternate"),
    ]
    page = make.get(f"/owners/{owner['hid']}/members", limit=1)
    assert (page["total"], page["limit"], len(page["items"])) == (2, 1, 1)


def test_locations_load_wherever_their_rows_stand_and_however_the_parent_is_named(
    make: Maker, files: Files
) -> None:
    places = make.layout()
    site = "Americas > Central > Site-2"
    # A region at the top has the name of the building: it is not what a location of
    # the site is in.
    make.region("Building 1")
    done = files.load(
        "locations",
        "name,site,parent\n"
        # In a floor that a later row makes, named from the site down.
        f"Room 201,{site},Building 1 > Floor 2\n"
        # The floor's own row names the building whole, with odd spacing and no site.
        "Floor 2,,americas>Central >  Site-2 > Building 1\n"
        f"Rack 7,{site},Building 1 > Floor 2 > Room 201\n",
    )
    assert (done["created"], done["rejected"]) == (3, 0)
    rack = make.get("/locations", filter="name:eq:Rack 7")["items"][0]
    assert rack["path"] == f"{site} > Building 1 > Floor 2 > Room 201 > Rack 7"
    assert rack["site_hid"] == places["site"]["hid"]
    again = files.preview("locations", files.export("locations", own_values=True))
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 5


def test_a_contact_is_found_by_name_retired_or_not_and_of_two_the_one_with_no_address(
    make: Maker, files: Files
) -> None:
    sam = make.post("/contacts", {"name": "Sam Okafor"})
    make.post(f"/contacts/{sam['hid']}/retire", {"row_version": sam["row_version"]}, 200)

    # A row may bring a retired record back: it finds it, and makes no second Sam.
    back = files.load("contacts", "name,record_status\nSam Okafor,active\n")
    assert (back["updated"], back["created"]) == (1, 0)
    # Two of one name, one of them with an email address: the file loads twice.
    both = "name,email,phone\nSam Okafor,,+1 555 0110\nSam Okafor,sam.okafor@example.net,\n"
    files.load("contacts", both)
    again = files.preview("contacts", both)
    assert (again["job"]["unchanged"], again["job"]["rejected"]) == (2, 0)
    assert make.get("/contacts", filter="name:eq:Sam Okafor")["total"] == 2
    # A third of the name, with no address either, and a row by name alone is no answer.
    make.post("/contacts", {"name": "Sam Okafor"})
    twins = files.preview("contacts", "name,phone\nSam Okafor,+1 555 0111\n")
    assert twins["rows"][0]["reasons"][0]["field"] == "name"


def test_a_name_that_could_be_taken_for_something_else_is_written_so_that_it_is_not(
    make: Maker, files: Files
) -> None:
    places = make.layout()
    # A region named with the HID of another place, and a region within it.
    odd = make.region(places["site"]["hid"])
    make.region("Inner", odd)
    again = files.preview("regions", files.export("regions", own_values=True))
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 4
    # A contact whose name is the email address of another.
    dana = make.contact("Dana Whitfield")
    alias = make.post("/contacts", {"name": "dana.whitfield@example.net"})
    make.assign(dana, "technical", region_hid=places["americas"]["hid"])
    make.assign(alias, "escalation", region_hid=places["americas"]["hid"])
    again = files.preview(
        "contact_assignments", files.export("contact_assignments", own_values=True)
    )
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 2


def test_a_row_does_not_make_an_override_of_where_a_minor_item_is_anyway(
    make: Maker, files: Files
) -> None:
    places = make.layout()
    room = "Americas > Central > Site-2 > Building 1 > Room 102"
    switch = make.item(hostname="site2-sw-access-01", location_hid=places["room"]["hid"])
    supply = make.item(name="PS-A", parent_item_hid=switch["hid"])

    # An export of the values in force holds the room for the power supply as well.
    exported = files.export("items", columns=["name", "hostname", "location"])
    assert exported.count(room) == 2
    again = files.preview("items", exported)
    assert again["job"]["unchanged"] == 2
    files.apply(again)
    assert make.get(f"/items/{supply['hid']}")["location_hid"] is None
    # The region of an item is written as a filter names it, and finds the item.
    row = files.export("items", columns=["hostname", "site", "region"]).splitlines()[-1]
    assert row.endswith("site2-sw-access-01,Site-2,Central")
    assert make.get("/items", filter="region:eq:Central site:eq:Site-2")["total"] == 2
    # An assignment stays with its place, in a file as on its page.
    dana = make.contact("Dana Whitfield")
    assigned = make.assign(dana, "technical", region_hid=places["americas"]["hid"])
    moved = files.preview(
        "contact_assignments",
        f"hid,site,role,contact\n{assigned['hid']},Americas > Central > Site-2,technical,"
        "dana.whitfield@example.net\n",
    )
    assert moved["rows"][0]["outcome"] == "rejected"


# --- who may change what, and what is not given to a retired record ---------------------


def test_every_change_of_places_and_people_needs_the_inventory_role(
    make: Maker, client: TestClient, viewer: dict[str, str]
) -> None:
    places = make.layout()
    owner = make.owner()
    dana = make.contact("Dana Whitfield")
    assigned = make.assign(dana, "technical", region_hid=places["americas"]["hid"])
    member = make.post(f"/owners/{owner['hid']}/members", {"contact_hid": dana["hid"]})
    version = {"row_version": 1}
    writes = [
        ("POST", "/regions", {"name": "EMEA"}),
        ("PATCH", f"/regions/{places['americas']['hid']}", {**version, "notes": "x"}),
        ("POST", f"/regions/{places['americas']['hid']}/retire", version),
        ("POST", "/sites", {"name": "Site-9", "region_hid": places["central"]["hid"]}),
        ("PATCH", f"/sites/{places['site']['hid']}", {**version, "notes": "x"}),
        ("POST", f"/sites/{places['site']['hid']}/retire", version),
        ("POST", "/locations", {"name": "Annex", "site_hid": places["site"]["hid"]}),
        ("PATCH", f"/locations/{places['room']['hid']}", {**version, "notes": "x"}),
        ("POST", f"/locations/{places['room']['hid']}/retire", version),
        ("POST", "/contacts", {"name": "Robin Achterberg"}),
        ("PATCH", f"/contacts/{dana['hid']}", {**version, "notes": "x"}),
        ("POST", f"/contacts/{dana['hid']}/retire", version),
        ("POST", "/contact-assignments", {"role": "technical", "contact_hid": dana["hid"]}),
        ("PATCH", f"/contact-assignments/{assigned['hid']}", {**version, "priority": 2}),
        ("DELETE", f"/contact-assignments/{assigned['hid']}", None),
        ("POST", f"/owners/{owner['hid']}/members", {"contact_hid": dana["hid"]}),
        ("PATCH", f"/owners/{owner['hid']}/members/{member['hid']}", {**version, "priority": 2}),
        ("DELETE", f"/owners/{owner['hid']}/members/{member['hid']}", None),
    ]
    events = make.get("/audit-events", limit=1)["total"]
    for method, path, body in writes:
        refused = client.request(method, API + path, json=body, headers=viewer)
        assert refused.status_code == 403, (method, path, refused.text)
        assert client.request(method, API + path, json=body).status_code == 401, (method, path)
    # Nothing of it was done, and nothing was written down.
    assert make.get("/audit-events", limit=1)["total"] == events
    assert make.get(f"/owners/{owner['hid']}/members")["total"] == 1
    assert make.get("/contact-assignments")["total"] == 1


def test_a_retired_record_is_given_to_nothing_further(make: Maker) -> None:
    places = make.layout()
    room = places["room"]
    owner = make.owner()
    dana = make.contact("Dana Whitfield")
    make.post(f"/contacts/{dana['hid']}/retire", {"row_version": dana["row_version"]}, 200)
    _retire(make, "locations", room)

    member = make.post(f"/owners/{owner['hid']}/members", {"contact_hid": dana["hid"]}, 422)
    assert "retired" in errors(member)["contact_hid"]
    group = {"type": "stack", "name": "site2-sw-stack1", "location_hid": room["hid"]}
    assert "retired" in errors(make.post("/device-groups", group, 422))["location_hid"]
    stack = make.group("site2-sw-stack1")
    moved = make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "location_hid": room["hid"]},
        422,
    )
    assert "location_hid" in errors(moved)
    within = make.location("Shelf", parent=room, expect=422)
    assert "parent_location_hid" in errors(within)
    assert "location_hid" in errors(
        make.assign(None, "shipping", 422, stop_inheritance=True, location_hid=room["hid"])
    )
