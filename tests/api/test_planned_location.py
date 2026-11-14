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
    assert make.found(filter="planned_location:within:Americas > Central > Site-3") == [
        "spare-01",
        "spare-02",
    ]
    assert make.found(filter="planned_location:empty:false location.name:eq:Store Room") == [
        "spare-01",
        "spare-02",
    ]
    assert make.get(f"/locations/{suite['hid']}")["planned_items"] == 1
    planned = _planned(make, include_drafts="true")
    assert planned["Americas > Central > Site-3"] == 2
    assert planned["Americas > Central > Site-3 > Suite 300"] == 2
    assert planned["Americas > Central > Site-3 > Suite 300 > Closet"] == 1
    assert (planned["Americas > Central"], planned["Americas > Central > Site-2"]) == (2, 0)
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
