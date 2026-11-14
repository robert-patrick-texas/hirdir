"""Regions, sites and locations: paths, nesting, moving, retiring, and what is found
within a place."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files

ROOM = "Americas > Central > Site-2 > Building 1 > Room 102"


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _counts(make: Maker, **params: Any) -> dict[str, tuple[int, int]]:
    tree = make.get("/geography/tree", **params)
    found = {
        name: (tree[name]["items"], tree[name]["component_count"])
        for name in ("totals", "unplaced", "hidden")
    }

    def walk(node: dict[str, Any]) -> None:
        found[node["path"]] = (node["items"], node["component_count"])
        for child in node["children"]:
            walk(child)

    for root in tree["roots"]:
        walk(root)
    return found


def test_a_path_is_the_names_from_the_top_region_down(make: Maker) -> None:
    places = make.layout()

    assert places["room"]["path"] == ROOM
    assert places["room"]["site"] == {
        "hid": places["site"]["hid"],
        "name": "Site-2",
        "path": "Americas > Central > Site-2",
    }
    assert places["room"]["parent"]["path"] == "Americas > Central > Site-2 > Building 1"
    assert (places["room"]["depth"], places["building"]["depth"]) == (1, 0)
    # A location that names what it is in need not name its site.
    assert places["room"]["site_hid"] == places["site"]["hid"]
    assert places["central"]["parent"] == {
        "hid": places["americas"]["hid"],
        "name": "Americas",
        "path": "Americas",
    }
    americas = make.get(f"/regions/{places['americas']['hid']}")
    assert (americas["regions"], americas["sites"]) == (1, 0)
    assert make.get(f"/sites/{places['site']['hid']}")["locations"] == 2
    assert make.get(f"/locations/{places['building']['hid']}")["locations"] == 1


def test_a_name_is_unique_among_what_stands_beside_it(make: Maker) -> None:
    places = make.layout()
    americas, central, site = places["americas"], places["central"], places["site"]

    assert "name" in errors(make.post("/regions", {"name": "americas"}, 409))
    again = {"name": "CENTRAL", "parent_region_hid": americas["hid"]}
    assert "name" in errors(make.post("/regions", again, 409))
    # The same name under another region, and at the top, is another record.
    make.region("Central")
    emea = make.region("EMEA")
    make.region("Central", emea)
    assert "name" in errors(
        make.post("/sites", {"name": "site-2", "region_hid": central["hid"]}, 409)
    )
    make.site("Site-2", emea)
    # A path names one record: a site does not share its name with a region beside it.
    assert "name" in errors(
        make.post("/sites", {"name": "Central", "region_hid": americas["hid"]}, 409)
    )
    beside = {"name": "Site-2", "parent_region_hid": central["hid"]}
    assert "name" in errors(make.post("/regions", beside, 409))
    assert "name" in errors(make.location("building 1", site, expect=409))
    make.location("Room 102", site)
    assert "name" in errors(make.location("Room 102", parent=places["building"], expect=409))
    # A name holds no '>', which separates the names of a path.
    assert "name" in errors(make.post("/regions", {"name": "North > South"}, 422))
    assert "name" in errors(make.post("/regions", {"name": "  "}, 422))


def test_a_code_is_unique_when_present(make: Maker) -> None:
    americas = make.region("Americas", code="AMER")
    emea = make.region("EMEA")
    assert "code" in errors(make.post("/regions", {"name": "North America", "code": "amer"}, 409))
    first = make.site("Site-1", americas, code="S1")
    assert "code" in errors(
        make.post("/sites", {"name": "Site-9", "region_hid": emea["hid"], "code": "s1"}, 409)
    )
    second = make.site("Site-2", emea)
    make.location("Building 1", first, code="B1")
    assert "code" in errors(make.location("Annex", first, code="b1", expect=409))
    # A code is unique within its site, and another site may use it.
    make.location("Building 1", second, code="B1")
    # A region and a site may share a code: each is unique among its own kind.
    make.site("Site-3", emea, code="AMER")


def test_no_place_is_ever_within_itself_and_locations_nest_so_deep(make: Maker) -> None:
    places = make.layout()
    americas, central = places["americas"], places["central"]

    refused = make.patch(
        f"/regions/{americas['hid']}",
        {"row_version": americas["row_version"], "parent_region_hid": central["hid"]},
        422,
    )
    assert "within it" in errors(refused)["parent_region_hid"]
    itself = make.patch(
        f"/regions/{americas['hid']}",
        {"row_version": americas["row_version"], "parent_region_hid": americas["hid"]},
        422,
    )
    assert "parent_region_hid" in errors(itself)
    building, room = places["building"], places["room"]
    refused = make.patch(
        f"/locations/{building['hid']}",
        {"row_version": building["row_version"], "parent_location_hid": room["hid"]},
        422,
    )
    assert "within it" in errors(refused)["parent_location_hid"]

    # Eight deep within a site, and no deeper.
    deepest = building
    for level in range(2, 9):
        deepest = make.location(f"Level {level}", parent=deepest)
    assert deepest["depth"] == 7
    too_deep = make.location("Level 9", parent=deepest, expect=422)
    assert "at most 8 deep" in errors(too_deep)["parent_location_hid"]
    # Nor is a location with locations in it moved to where they would be too deep.
    refused = make.patch(
        f"/locations/{room['hid']}",
        {"row_version": room["row_version"], "parent_location_hid": deepest["hid"]},
        422,
    )
    assert "parent_location_hid" in errors(refused)


def test_a_location_stays_in_its_site_and_within_a_location_of_it(make: Maker) -> None:
    places = make.layout()
    other = make.site("Site-3", places["central"])
    elsewhere = make.location("Building 9", other)

    wrong = {
        "name": "Room 9",
        "site_hid": places["site"]["hid"],
        "parent_location_hid": elsewhere["hid"],
    }
    assert "another site" in errors(make.post("/locations", wrong, 422))["parent_location_hid"]
    room = places["room"]
    moved = make.patch(
        f"/locations/{room['hid']}",
        {"row_version": room["row_version"], "parent_location_hid": elsewhere["hid"]},
        422,
    )
    assert "parent_location_hid" in errors(moved)
    assert "site_hid" in errors(make.post("/locations", {"name": "Nowhere"}, 422))
    # Within its site it is moved by giving it another parent, or none.
    top = make.patch(
        f"/locations/{room['hid']}",
        {"row_version": room["row_version"], "parent_location_hid": None},
    )
    assert (top["path"], top["depth"]) == ("Americas > Central > Site-2 > Room 102", 0)


def test_what_a_place_refers_to_must_be_there_and_in_order(make: Maker) -> None:
    places = make.layout()
    nobody = "01900000-0000-7000-8000-000000000000"

    assert "region_hid" in errors(make.post("/sites", {"name": "S", "region_hid": nobody}, 422))
    assert "parent_region_hid" in errors(
        make.post("/regions", {"name": "R", "parent_region_hid": nobody}, 422)
    )
    assert "kind" in errors(make.location("Vault", places["site"], kind="bunker", expect=422))
    one_only = {"name": "Site-9", "region_hid": places["central"]["hid"], "latitude": "41.5"}
    assert "longitude" in errors(make.post("/sites", one_only, 422))
    placed = make.site("Site-9", places["central"], latitude="41.5", longitude="-87.25")
    assert (placed["latitude"], placed["longitude"]) == ("41.500000", "-87.250000")
    too_far = {
        "name": "Site-8",
        "region_hid": places["central"]["hid"],
        "latitude": 91,
        "longitude": 0,
    }
    assert make.post("/sites", too_far, 422)["status"] == 422
    assert make.get(f"/regions/{nobody}", 404)["status"] == 404
    assert make.get(f"/locations/{nobody}/effective", 404)["status"] == 404


def test_only_inventory_changes_the_geography_and_every_change_is_audited(
    make: Maker, client: TestClient, viewer: dict[str, str]
) -> None:
    places = make.layout()
    site = places["site"]

    for path, body in (
        ("/regions", {"name": "EMEA"}),
        ("/sites", {"name": "Site-9", "region_hid": places["central"]["hid"]}),
        ("/locations", {"name": "Annex", "site_hid": site["hid"]}),
        ("/contacts", {"name": "Dana Whitfield"}),
    ):
        assert client.post(API + path, json=body, headers=viewer).status_code == 403
        assert client.post(API + path, json=body).status_code == 401
        assert client.get(API + path, headers=viewer).status_code == 200
    assert client.get(f"{API}/geography/tree", headers=viewer).status_code == 200
    assert client.get(f"{API}/geography/tree").status_code == 401

    renamed = make.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "name": "Site-2A", "tags": []}
    )
    assert renamed["path"] == "Americas > Central > Site-2A"
    # A stale edit is refused, and a change that changes nothing leaves the version alone.
    stale = make.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "name": "X"}, 409
    )
    assert stale["status"] == 409
    same = make.patch(
        f"/sites/{site['hid']}", {"row_version": renamed["row_version"], "name": "Site-2A"}
    )
    assert same["row_version"] == renamed["row_version"]
    events = make.audit(record_type="site", record_hid=site["hid"])
    assert [(event["action"], event["changes"][0]["field"]) for event in events] == [
        ("update", "name"),
        ("create", "name"),
    ]
    assert events[0]["changes"] == [{"field": "name", "old": "Site-2", "new": "Site-2A"}]


def test_a_place_is_retired_only_when_nothing_that_is_not_retired_is_in_it(make: Maker) -> None:
    places = make.layout()
    room, building, site = places["room"], places["building"], places["site"]
    switch = make.item(hostname="site2-sw-access-01", location_hid=room["hid"])
    stack = make.group("site2-sw-stack1", location_hid=room["hid"])

    def retire(level: str, place: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        now = make.get(f"/{level}/{place['hid']}")
        body = {"row_version": now["row_version"]}
        return make.post(f"/{level}/{place['hid']}/retire", body, expect)

    assert "1 site not" in retire("regions", places["central"], 409)["detail"]
    assert "1 region not" in retire("regions", places["americas"], 409)["detail"]
    assert "2 locations not" in retire("sites", site, 409)["detail"]
    assert "1 location not" in retire("locations", building, 409)["detail"]
    refused = retire("locations", room, 409)["detail"]
    assert "1 item," in refused
    assert "1 device group not" in refused

    # The switch is moved out and the stack retired: the room can go, then what held it.
    make.patch(
        f"/items/{switch['hid']}", {"row_version": switch["row_version"], "location_hid": None}
    )
    make.post(f"/device-groups/{stack['hid']}/retire", {"row_version": stack["row_version"]}, 200)
    assert retire("locations", room)["record_status"] == "retired"
    assert retire("locations", building)["record_status"] == "retired"
    assert retire("sites", site)["record_status"] == "retired"
    assert retire("regions", places["central"])["record_status"] == "retired"
    # A retired place is given to no further record, and is left out of the lists.
    assert "location_hid" in errors(
        make.patch(
            f"/items/{switch['hid']}",
            {"row_version": switch["row_version"] + 1, "location_hid": room["hid"]},
            422,
        )
    )
    assert "site_hid" in errors(make.location("Annex", site, expect=422))
    assert make.get("/locations")["total"] == 0
    assert make.get("/locations", include_archived="true")["total"] == 2
    # An item that has left the team's hands does not hold a location open.
    other = make.location("Dock", make.site("Site-3", places["americas"]))
    gone = make.item(hostname="old-sw-01", location_hid=other["hid"], lifecycle_state="Prod")
    for to in ("Pending-Removal", "Released"):
        gone = make.move(gone, to)
    assert retire("locations", other)["record_status"] == "retired"


def test_a_minor_item_is_where_the_item_above_it_is(make: Maker) -> None:
    places = make.layout()
    room, building = places["room"], places["building"]
    switch = make.item(hostname="site2-sw-access-01", location_hid=room["hid"])
    supply = make.item(name="PS-A", parent_item_hid=switch["hid"])

    assert (supply["location_hid"], supply["location"]) == (None, None)
    assert supply["effective"]["location_hid"] == {
        "value": room["hid"],
        "label": ROOM,
        "source": "parent_item",
        "source_hid": switch["hid"],
        "site_hid": places["site"]["hid"],
        "site": "Site-2",
        "region_hid": places["central"]["hid"],
        "region": "Central",
    }
    assert switch["location"] == {
        "hid": room["hid"],
        "name": "Room 102",
        "path": ROOM,
        "kind": "room",
        "site_hid": places["site"]["hid"],
        "site": "Site-2",
        "region_hid": places["central"]["hid"],
        "region": "Central",
    }
    # Both are found within the room, by path, by HID, and by what the site is called.
    assert make.get("/items", filter=f"location:within:{ROOM}")["total"] == 2
    assert make.get("/items", filter=f"location:within:{room['hid']}")["total"] == 2
    assert make.get("/items", filter="location:within:americas >central")["total"] == 2
    assert make.get("/items", filter="site:eq:site-2 is_major:eq:false")["total"] == 1
    assert make.get("/items", filter="region:eq:Central")["total"] == 2
    assert make.get("/items", filter=f"effective.location_hid:eq:{room['hid']}")["total"] == 2
    assert make.get("/items", filter=f"location_hid:eq:{room['hid']}")["total"] == 1
    # Given a place of its own, the minor item is there, and cleared it follows again.
    own = make.patch(
        f"/items/{supply['hid']}",
        {"row_version": supply["row_version"], "location_hid": building["hid"]},
    )
    assert own["effective"]["location_hid"]["source"] == "own"
    assert make.get("/items", filter=f"location:within:{ROOM}")["total"] == 1
    back = make.patch(
        f"/items/{supply['hid']}", {"row_version": own["row_version"], "location_hid": None}
    )
    assert back["effective"]["location_hid"]["source"] == "parent_item"


def test_within_finds_what_is_at_or_beneath_a_place_on_every_list(make: Maker) -> None:
    places = make.layout()
    east = make.region("East", places["americas"])
    far = make.site("Site-9", east)
    dock = make.location("Dock", far)
    make.item(hostname="a", location_hid=places["room"]["hid"])
    make.item(hostname="b", location_hid=places["building"]["hid"])
    make.item(hostname="c", location_hid=dock["hid"])
    make.item(hostname="d")
    make.group("stack-1", location_hid=places["room"]["hid"])
    make.group("stack-2", location_hid=dock["hid"])
    make.group("stack-3")

    assert make.found(filter="location:within:Americas > Central") == ["a", "b"]
    assert make.found(filter="location:within:Americas") == ["a", "b", "c"]
    assert make.found(filter="location:within:Americas > East > Site-9") == ["c"]
    assert make.found(filter="location:within:Americas > Central > Site-2 > Building 1") == [
        "a",
        "b",
    ]
    assert make.found(filter="location:empty:true") == ["d"]
    assert make.found(filter="location:empty:false", sort="-site,name") == ["c", "a", "b"]
    either = {
        "or": [
            {"field": "location", "op": "within", "value": ROOM},
            {"field": "location", "op": "within", "value": "Americas > East"},
        ]
    }
    listed = make.post("/items/query", {"filter": either}, 200)["items"]
    assert [row["hostname"] for row in listed] == ["a", "c"]
    names = [
        row["name"]
        for row in make.get("/device-groups", filter="location:within:Americas > East")["items"]
    ]
    assert names == ["stack-2"]
    assert make.get("/device-groups", filter="location:empty:true")["total"] == 1
    sites = make.get("/sites", filter="region:within:Americas")["items"]
    assert [site["name"] for site in sites] == ["Site-2", "Site-9"]
    assert make.get("/sites", filter="region:within:Americas > East")["total"] == 1
    assert make.get("/sites", filter="region.name:eq:central")["total"] == 1
    assert make.get("/locations", filter="location:within:Americas > Central")["total"] == 2
    assert (
        make.get("/locations", filter=f"location:within:{places['building']['hid']}")["total"] == 2
    )
    assert make.get("/locations", filter="is_top:eq:true")["total"] == 2
    assert make.get("/locations", filter="region.name:eq:east")["total"] == 1
    assert make.get("/regions", filter="region:within:Americas")["total"] == 3

    # A place that is not there is said to be so, and a place cannot be sorted by.
    nowhere = make.get("/items", 422, filter="location:within:Americas > West")
    assert "there is no region, site or location" in errors(nowhere)["filter"]
    assert "filter" in errors(make.get("/items", 422, filter="location:eq:Americas"))
    assert "sort" in errors(make.get("/items", 422, sort="location"))


def test_the_tree_adds_up_and_says_what_it_leaves_out(make: Maker) -> None:
    places = make.layout()
    plan = make.site("Site-3", places["central"], record_status="draft")
    suite = make.location("Suite 300", plan)
    make.item(hostname="a", location_hid=places["room"]["hid"], lifecycle_state="Prod")
    make.item(hostname="b", location_hid=places["building"]["hid"], lifecycle_state="Delivered")
    make.item(hostname="c", location_hid=suite["hid"])
    make.item(hostname="d")

    counts = _counts(make)
    assert counts[ROOM] == (1, 1)
    # A switch that is only delivered is an item there, and not yet a component.
    assert counts["Americas > Central > Site-2 > Building 1"] == (2, 1)
    assert counts["Americas"] == (2, 1)
    assert "Americas > Central > Site-3" not in counts
    assert (counts["unplaced"], counts["hidden"], counts["totals"]) == ((1, 1), (1, 1), (4, 3))
    with_drafts = _counts(make, include_drafts="true")
    assert with_drafts["Americas > Central > Site-3 > Suite 300"] == (1, 1)
    assert (with_drafts["Americas"], with_drafts["hidden"]) == ((3, 2), (0, 0))

    # From one place down, and no further than the sites.
    tree = make.get("/geography/tree", root="Americas > Central > Site-2", locations="false")
    (site,) = tree["roots"]
    assert (site["level"], site["path"], site["items"], site["children"]) == (
        "site",
        "Americas > Central > Site-2",
        2,
        [],
    )
    assert tree["totals"]["items"] == 4
    by_hid = make.get("/geography/tree", root=places["building"]["hid"])["roots"][0]
    assert [child["path"] for child in by_hid["children"]] == [ROOM]
    assert (by_hid["kind"], by_hid["children"][0]["level"]) == ("building", "location")
    # A place that is asked for by name is shown, also when the view would leave it out.
    draft = make.get("/geography/tree", root=plan["hid"])["roots"][0]
    assert (draft["record_status"], draft["items"]) == ("draft", 1)
    # The view is that of the item list for the same filter.
    filtered = _counts(make, filter="lifecycle_state:eq:Prod")
    assert (filtered["totals"], filtered["Americas"]) == ((1, 1), (1, 1))
    assert "root" in errors(make.get("/geography/tree", 422, root="Atlantis"))


def test_the_reports_are_by_site_and_by_region(make: Maker) -> None:
    places = make.layout()
    east = make.region("East", places["americas"])
    dock = make.location("Dock", make.site("Site-9", east))
    vendor = make.vendor()
    entry = make.entry(
        vendor, est_value="1000.00", annual_support_cost="100.00", support_weight="1"
    )
    for serial, where in (
        ("A1", places["room"]),
        ("A2", places["building"]),
        ("A3", dock),
        ("A4", None),
    ):
        make.item(
            catalog_entry_hid=entry["hid"],
            serial_number=serial,
            lifecycle_state="Prod",
            location_hid=where["hid"] if where else None,
        )

    money = make.get("/reports/management")
    assert money["by"] == "site"
    assert [(row["label"], row["items"], row["est_value"]) for row in money["rows"]] == [
        ("Americas > Central > Site-2", 2, "2000.00"),
        ("Americas > East > Site-9", 1, "1000.00"),
        (None, 1, "1000.00"),
    ]
    assert money["rows"][0]["key"] == places["site"]["hid"]
    assert money["totals"]["est_value"] == "4000.00"
    # A region holds everything at or beneath it, so an item is in the row of each
    # region above it, and the totals count it once.
    by_region = make.get("/reports/summary", by="region")
    assert [
        (row["label"], row["component_count"], row["support_weight"]) for row in by_region["rows"]
    ] == [
        ("Americas", 3, "3"),
        ("Americas > Central", 2, "2"),
        ("Americas > East", 1, "1"),
        (None, 1, "1"),
    ]
    assert by_region["totals"]["component_count"] == 4
    cost = make.get("/reports/management", by="region", filter="location:within:Americas > East")
    assert [(row["label"], row["annual_support_cost"]) for row in cost["rows"]] == [
        ("Americas", "100.00"),
        ("Americas > East", "100.00"),
    ]
    by_site = make.get("/reports/summary", by="site")["rows"]
    assert [row["managed_node_count"] for row in by_site] == [2, 1, 1]


def test_places_and_where_things_are_travel_in_files(make: Maker, files: Files) -> None:
    make.tag("critical")
    # A region stands after one that is within it, and a room before its building.
    files.load("regions", "name,parent,code\nCentral,Americas,CEN\nAmericas,,AMER\n")
    files.load(
        "sites",
        "name,region,code,city,latitude,longitude,tags\n"
        "Site-2,Americas > Central,S2,Springfield,40.5,'-89.25,critical\n",
    )
    files.load(
        "locations",
        "name,site,parent,kind\n"
        "Room 102,Americas > Central > Site-2,Building 1 > Floor 1,room\n"
        "Floor 1,Americas > Central > Site-2,Americas > Central > Site-2 > Building 1,floor\n"
        "Building 1,Americas > Central > Site-2,,building\n"
        # A row that names what the location is in, whole, need not name the site.
        "Rack A1,,Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102,rack\n",
    )
    rack = "Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102 > Rack A1"
    paths = sorted(row["path"] for row in make.get("/locations")["items"])
    assert (paths[-1], len(paths)) == (rack, 4)
    site = make.get("/sites")["items"][0]
    assert (site["latitude"], site["longitude"], site["tags"]) == (
        "40.500000",
        "-89.250000",
        ["critical"],
    )

    files.load("items", f"hostname,location\nsite2-sw-core-01,{rack}\nsite2-sw-access-01,\n")
    files.load("device_groups", f"name,type,location\nsite2-sw-core,stack,{rack}\n")
    assert make.found(filter=f"location:within:{rack}") == ["site2-sw-core-01"]
    assert make.get("/device-groups")["items"][0]["location"]["path"] == rack

    # Every file comes back as it went: an export of stored values changes nothing.
    for entity in ("regions", "sites", "locations", "items", "device_groups"):
        again = files.preview(entity, files.export(entity, own_values=True))
        assert again["job"]["unchanged"] == again["job"]["row_count"], (entity, again["rows"])
    exported = files.export("items", columns=["hostname", "location", "site", "region"])
    assert [line.split(",", 1)[1] for line in exported.splitlines()[1:]] == [
        "site2-sw-access-01,,,",
        f"site2-sw-core-01,{rack},Site-2,Central",
    ]
    # A place that is not there, or of another level, rejects the row, and so does a
    # row that would move a location to another site.
    wrong = files.preview("items", "hostname,location\nx,Americas > Central > Site-2\ny,Mars\n")
    assert [row["reasons"][0]["field"] for row in wrong["rows"]] == ["location", "location"]
    files.load("sites", "name,region\nSite-3,Americas > Central\n")
    moved = files.preview(
        "locations",
        f"hid,site\n{make.get('/locations', filter='name:eq:Building 1')['items'][0]['hid']},"
        "Americas > Central > Site-3\n",
    )
    assert moved["rows"][0]["reasons"][0]["field"] == "site"
    # A row finds its place among what stands beside it: a region, or a location, of
    # the same name somewhere else is another record, and is left as it is.
    files.load("regions", "name\nCentral\nBuilding 1\n")
    again = files.preview("regions", "name,parent,notes\nCentral,Americas,The middle\n")
    assert again["rows"][0]["outcome"] == "update"
    assert again["rows"][0]["record_hid"] == make.get("/sites")["items"][0]["region_hid"]
    same = files.preview(
        "locations", "name,site,kind\nBuilding 1,Americas > Central > Site-2,building\n"
    )
    assert same["rows"][0]["outcome"] == "unchanged"
    # A bulk edit moves many items at once, and clears where they are.
    edit = make.post("/items/bulk-update", {"all_rows": True, "set": {"location": rack}}, 201)
    assert (edit["job"]["updated"], edit["job"]["unchanged"]) == (1, 1)
    make.post(f"/items/bulk-update/{edit['job']['hid']}/apply", {}, 200)
    assert make.get("/items", filter=f"location:within:{rack}")["total"] == 2
