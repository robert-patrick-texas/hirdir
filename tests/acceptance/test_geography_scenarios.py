"""Scenarios S24 to S28 of docs/build-plan.md, against a real server process."""

from typing import Any

import pytest

from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_item_scenarios import IVY, Inventory

ROOM = "Americas > Central > Site-2 > Building 1 > Room 102"


class Geography(Inventory):
    """A signed-in Inventory user who lays out regions, sites, locations and contacts."""

    def region(self, name: str, parent: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {"name": name, "parent_region_hid": parent["hid"] if parent else None}
        return self.post("/regions", body)

    def site(self, name: str, region: dict[str, Any], **more: Any) -> dict[str, Any]:
        return self.post("/sites", {"name": name, "region_hid": region["hid"], **more})

    def location(
        self, name: str, site: dict[str, Any], parent: dict[str, Any] | None = None, **more: Any
    ) -> dict[str, Any]:
        body = {"name": name, "site_hid": site["hid"], **more}
        if parent is not None:
            body["parent_location_hid"] = parent["hid"]
        return self.post("/locations", body)

    def layout(self) -> dict[str, dict[str, Any]]:
        """Make `Americas > Central`, Site-2, Building 1 and Room 102 within it."""
        americas = self.region("Americas")
        central = self.region("Central", americas)
        site = self.site("Site-2", central)
        building = self.location("Building 1", site, kind="building")
        room = self.location("Room 102", site, building, kind="room")
        return {
            "americas": americas,
            "central": central,
            "site": site,
            "building": building,
            "room": room,
        }

    def contact(self, name: str) -> dict[str, Any]:
        email = f"{name.lower().replace(' ', '.')}@example.net"
        return self.post("/contacts", {"name": name, "email": email})

    def assign(self, contact: dict[str, Any], role: str, **place: str) -> dict[str, Any]:
        return self.post(
            "/contact-assignments", {"contact_hid": contact["hid"], "role": role, **place}
        )

    def in_force(self, location: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return what a location has in force for each role."""
        found = self.get(f"/locations/{location['hid']}/effective")
        return {one["role"]: one for one in found["contacts"]}

    def switch(self, serial: str, location: dict[str, Any] | None, **more: Any) -> dict[str, Any]:
        entries = self.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
        entry = entries[0] if entries else self.entry()
        body = {"catalog_entry_hid": entry["hid"], "serial_number": serial, **more}
        if location is not None:
            body["location_hid"] = location["hid"]
        return self.post("/items", body)

    def counts(self, **params: Any) -> dict[str, tuple[int, int]]:
        """Return the items and the components at or beneath each place of the tree, by path."""
        tree = self.get("/geography/tree", **params)
        found: dict[str, tuple[int, int]] = {
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


@pytest.fixture
def geography(server: Server) -> Geography:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Geography(server.sign_in(*IVY))


def test_s24_paths_and_roll_up_counts_are_right_at_every_level(geography: Geography) -> None:
    places = geography.layout()
    assert places["americas"]["path"] == "Americas"
    assert places["central"]["path"] == "Americas > Central"
    assert places["site"]["path"] == "Americas > Central > Site-2"
    assert places["building"]["path"] == "Americas > Central > Site-2 > Building 1"
    assert places["room"]["path"] == ROOM

    # Two switches in the room, one in the building, one that is nowhere, and a power
    # supply in one of the switches of the room, which is where its switch is.
    in_room = geography.switch("FCW0000X001", places["room"])
    geography.switch("FCW0000X002", places["room"])
    geography.switch("FCW0000X003", places["building"])
    geography.switch("FCW0000X004", None)
    supply = geography.entry("PWR-C1-715WAC-P", type="power-supply")
    geography.post(
        "/items",
        {
            "catalog_entry_hid": supply["hid"],
            "serial_number": "LIT0000X001",
            "parent_item_hid": in_room["hid"],
            "position": "PS-A",
        },
    )

    counts = geography.counts()
    assert counts[ROOM] == (3, 2)
    assert counts["Americas > Central > Site-2 > Building 1"] == (4, 3)
    assert counts["Americas > Central > Site-2"] == (4, 3)
    assert counts["Americas > Central"] == (4, 3)
    assert counts["Americas"] == (4, 3)
    assert counts["unplaced"] == (1, 1)
    assert counts["hidden"] == (0, 0)
    assert counts["totals"] == (5, 4)

    # The item list finds what is within a place by the same paths.
    assert geography.get("/items", filter=f"location:within:{ROOM}")["total"] == 3
    assert geography.get("/items", filter="location:within:Americas")["total"] == 4
    assert geography.get("/items", filter="location:empty:true")["total"] == 1
    item = geography.get(f"/items/{in_room['hid']}")
    assert item["location"]["path"] == ROOM
    assert item["effective"]["location_hid"]["source"] == "own"
    assert item["effective"]["location_hid"]["site"] == "Site-2"


def test_s25_a_room_shows_contacts_from_the_levels_they_came_from(geography: Geography) -> None:
    places = geography.layout()
    technical = geography.contact("Dana Whitfield")
    shipping = geography.contact("Sam Okafor")
    geography.assign(technical, "technical", region_hid=places["americas"]["hid"])
    geography.assign(shipping, "shipping", site_hid=places["site"]["hid"])

    found = geography.in_force(places["room"])
    assert [one["name"] for one in found["technical"]["contacts"]] == ["Dana Whitfield"]
    assert (found["technical"]["source"], found["technical"]["source_path"]) == (
        "region",
        "Americas",
    )
    assert found["technical"]["source_hid"] == places["americas"]["hid"]
    assert [one["name"] for one in found["shipping"]["contacts"]] == ["Sam Okafor"]
    assert (found["shipping"]["source"], found["shipping"]["source_path"]) == (
        "site",
        "Americas > Central > Site-2",
    )
    # A role nobody is assigned to at any level is there, and empty.
    assert (found["escalation"]["source"], found["escalation"]["contacts"]) == ("none", [])


def test_s26_an_override_on_a_building_holds_when_the_region_changes(geography: Geography) -> None:
    places = geography.layout()
    other = geography.location("Building 2", places["site"], kind="building")
    elsewhere = geography.location("Room 201", places["site"], other, kind="room")
    regional = geography.contact("Dana Whitfield")
    local = geography.contact("Lee Marchetti")
    successor = geography.contact("Robin Achterberg")
    on_region = geography.assign(regional, "technical", region_hid=places["americas"]["hid"])
    geography.assign(local, "technical", location_hid=places["building"]["hid"])

    # The technical contact of the region is changed to another person.
    geography.patch(
        f"/contact-assignments/{on_region['hid']}",
        {"row_version": on_region["row_version"], "contact_hid": successor["hid"]},
    )

    room = geography.in_force(places["room"])["technical"]
    assert [one["name"] for one in room["contacts"]] == ["Lee Marchetti"]
    assert (room["source"], room["source_path"]) == (
        "location",
        "Americas > Central > Site-2 > Building 1",
    )
    there = geography.in_force(elsewhere)["technical"]
    assert [one["name"] for one in there["contacts"]] == ["Robin Achterberg"]
    assert (there["source"], there["source_path"]) == ("region", "Americas")


def test_s27_moving_a_site_changes_paths_contacts_and_roll_ups_and_no_item(
    geography: Geography,
) -> None:
    places = geography.layout()
    east = geography.region("East", places["americas"])
    central_contact = geography.contact("Dana Whitfield")
    east_contact = geography.contact("Robin Achterberg")
    geography.assign(central_contact, "technical", region_hid=places["central"]["hid"])
    geography.assign(east_contact, "technical", region_hid=east["hid"])
    switches = [geography.switch(f"FCW0000X00{number}", places["room"]) for number in (1, 2)]
    before = geography.counts()
    assert before["Americas > Central"] == (2, 2)
    assert before["Americas > East"] == (0, 0)
    events = geography.get("/audit-events", limit=1)["total"]

    site = places["site"]
    moved = geography.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "region_hid": east["hid"]}
    )

    assert moved["path"] == "Americas > East > Site-2"
    room = geography.get(f"/locations/{places['room']['hid']}")
    assert room["path"] == "Americas > East > Site-2 > Building 1 > Room 102"
    assert room["row_version"] == places["room"]["row_version"]
    technical = geography.in_force(places["room"])["technical"]
    assert [one["name"] for one in technical["contacts"]] == ["Robin Achterberg"]
    assert technical["source_path"] == "Americas > East"
    after = geography.counts()
    assert after["Americas > Central"] == (0, 0)
    assert after["Americas > East"] == (2, 2)
    assert after["Americas"] == (2, 2)
    # No item was written to: each is the record it was, at the version it had.
    for switch in switches:
        now = geography.get(f"/items/{switch['hid']}")
        assert (now["hid"], now["row_version"]) == (switch["hid"], switch["row_version"])
        assert now["effective"]["location_hid"]["label"] == room["path"]
    assert geography.get("/items", filter="location:within:Americas > East")["total"] == 2
    # The move is one audit event, on the site.
    assert geography.get("/audit-events", limit=1)["total"] == events + 1
    last = geography.get("/audit-events", limit=1)["items"][0]
    assert (last["record_type"], last["record_hid"], last["action"]) == (
        "site",
        site["hid"],
        "update",
    )
    assert last["changes"] == [
        {"field": "region_hid", "old": places["central"]["hid"], "new": east["hid"]}
    ]


def test_s28_an_external_owner_needs_a_reason_and_marks_the_item(geography: Geography) -> None:
    team = geography.post("/owners", {"label": "Network Engineering"})
    outside = geography.post(
        "/owners",
        {
            "label": "Facilities",
            "organization": "Building Services",
            "is_external": True,
            "exception_reason": "Looks after the door controllers",
        },
    )
    item = geography.switch("FCW0000X001", None, owner_hid=team["hid"])
    assert item["owner_exception"] is False

    refused = geography.patch(
        f"/items/{item['hid']}",
        {"row_version": item["row_version"], "owner_hid": outside["hid"]},
        expect=422,
    )
    assert [error["field"] for error in refused["errors"]] == ["owner_exception_reason"]
    assert geography.get(f"/items/{item['hid']}")["owner_hid"] == team["hid"]

    given = geography.patch(
        f"/items/{item['hid']}",
        {
            "row_version": item["row_version"],
            "owner_hid": outside["hid"],
            "owner_exception_reason": "Mounted in the lobby, behind their badge readers",
        },
    )
    assert given["owner_hid"] == outside["hid"]
    assert given["owner_exception"] is True
    assert given["owner_exception_reason"] == "Mounted in the lobby, behind their badge readers"
    marked = geography.get("/items", filter="owner_exception:eq:true")["items"]
    assert [one["hid"] for one in marked] == [item["hid"]]
