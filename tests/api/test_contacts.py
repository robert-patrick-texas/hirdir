"""Contacts, their assignments to places, what a place has in force, the people of an
owner, and the item that is with an owner outside the team."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _names(found: dict[str, Any], role: str) -> list[str]:
    return [one["name"] for one in found["by_role"][role]["contacts"]]


def test_a_contact_is_one_record_with_an_email_address_of_its_own(make: Maker) -> None:
    make.tag("on-call")
    dana = make.contact("Dana Whitfield", phone="+1 555 0100", tags=["on-call"])

    assert (dana["email"], dana["uses"], dana["tags"]) == (
        "dana.whitfield@example.net",
        0,
        ["on-call"],
    )
    taken = {"name": "Another Dana", "email": "DANA.Whitfield@example.net"}
    assert "email" in errors(make.post("/contacts", taken, 409))
    assert "email" in errors(make.post("/contacts", {"name": "X", "email": "not an address"}, 422))
    assert "name" in errors(make.post("/contacts", {"name": " "}, 422))
    # Two people may share a name, and a shared mailbox has no person at all.
    make.post("/contacts", {"name": "Dana Whitfield"})
    desk = make.post("/contacts", {"name": "Network Operations Desk", "email": "noc@example.net"})
    assert make.get("/contacts", filter="name:eq:dana whitfield")["total"] == 2
    assert make.get("/contacts", filter="tags:has:on-call")["total"] == 1
    changed = make.patch(
        f"/contacts/{desk['hid']}", {"row_version": desk["row_version"], "email": None}
    )
    assert changed["email"] is None
    retired = make.post(
        f"/contacts/{desk['hid']}/retire", {"row_version": changed["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    assert make.get("/contacts")["total"] == 2


def test_a_contact_is_assigned_to_one_place_in_a_role(make: Maker) -> None:
    places = make.layout()
    dana, robin = make.contact("Dana Whitfield"), make.contact("Robin Achterberg")
    region = {"region_hid": places["americas"]["hid"]}

    first = make.assign(dana, "technical", **region)
    second = make.assign(robin, "Technical", **region)
    assert (first["priority"], second["priority"], second["role"]) == (1, 2, "technical")
    assert first["place"] == {
        "hid": places["americas"]["hid"],
        "name": "Americas",
        "path": "Americas",
        "level": "region",
    }
    assert first["contact"]["name"] == "Dana Whitfield"
    assert "contact_hid" in errors(make.assign(dana, "technical", 409, **region))
    assert "role" in errors(make.assign(dana, "gardening", 422, **region))
    both = {**region, "site_hid": places["site"]["hid"]}
    assert set(errors(make.assign(dana, "shipping", 422, **both))) == {"region_hid", "site_hid"}
    assert len(errors(make.assign(dana, "shipping", 422))) == 3
    assert "contact_hid" in errors(make.assign(None, "shipping", 422, **region))
    # It stays with its place, and its role, priority and contact may change.
    refused = make.patch(
        f"/contact-assignments/{first['hid']}",
        {"row_version": first["row_version"], "contact_hid": robin["hid"]},
        409,
    )
    assert "contact_hid" in errors(refused)
    moved = make.patch(
        f"/contact-assignments/{second['hid']}",
        {"row_version": second["row_version"], "role": "escalation", "priority": 1},
    )
    assert (moved["role"], moved["priority"]) == ("escalation", 1)
    listed = make.get("/contact-assignments", filter=f"region_hid:eq:{places['americas']['hid']}")
    assert [(one["role"], one["contact"]["name"]) for one in listed["items"]] == [
        ("escalation", "Robin Achterberg"),
        ("technical", "Dana Whitfield"),
    ]
    assert make.get(f"/contacts/{dana['hid']}")["uses"] == 1
    # Removed outright, and the audit event of the removal holds what it was.
    make.delete(f"/contact-assignments/{first['hid']}")
    assert make.get(f"/contact-assignments/{first['hid']}", 404)["status"] == 404
    (event,) = make.audit(record_type="contact_assignment", action="delete")
    assert {change["field"]: change["old"] for change in event["changes"]} == {
        "contact_hid": dana["hid"],
        "region_hid": places["americas"]["hid"],
        "role": "technical",
        "priority": 1,
    }
    # A retired contact is given no further assignment.
    make.post(f"/contacts/{dana['hid']}/retire", {"row_version": dana["row_version"]}, 200)
    assert "contact_hid" in errors(make.assign(dana, "technical", 422, **region))


def test_the_first_level_that_has_any_supplies_all_of_them(make: Maker) -> None:
    places = make.layout()
    dana, robin, lee, sam = (
        make.contact(name)
        for name in ("Dana Whitfield", "Robin Achterberg", "Lee Marchetti", "Sam Okafor")
    )
    make.assign(robin, "technical", region_hid=places["americas"]["hid"], priority=2)
    make.assign(dana, "technical", region_hid=places["americas"]["hid"], priority=1)
    make.assign(sam, "shipping", site_hid=places["site"]["hid"])

    room = make.in_force(places["room"])
    assert (room["level"], room["path"]) == (
        "location",
        "Americas > Central > Site-2 > Building 1 > Room 102",
    )
    assert _names(room, "technical") == ["Dana Whitfield", "Robin Achterberg"]
    assert room["by_role"]["technical"]["source"] == "region"
    assert room["by_role"]["shipping"]["source_path"] == "Americas > Central > Site-2"
    assert [one["role"] for one in room["contacts"]] == [
        "shipping",
        "technical",
        "federal",
        "operational",
        "escalation",
    ]
    # The building's own technician is the one for the building and what is in it, alone.
    make.assign(lee, "technical", location_hid=places["building"]["hid"])
    room = make.in_force(places["room"])
    assert _names(room, "technical") == ["Lee Marchetti"]
    assert (room["by_role"]["technical"]["source"], room["by_role"]["technical"]["stopped"]) == (
        "location",
        False,
    )
    building = make.in_force(places["building"])
    assert building["by_role"]["technical"]["source"] == "own"
    # The site and the region answer in the same way.
    site = make.in_force(places["site"], "sites")
    assert (site["level"], _names(site, "technical"), site["by_role"]["shipping"]["source"]) == (
        "site",
        ["Dana Whitfield", "Robin Achterberg"],
        "own",
    )
    central = make.in_force(places["central"], "regions")
    assert (
        central["by_role"]["technical"]["source"],
        central["by_role"]["shipping"]["source"],
    ) == (
        "region",
        "none",
    )


def test_a_place_may_say_that_it_has_nobody_and_stop_the_search(make: Maker) -> None:
    places = make.layout()
    sam = make.contact("Sam Okafor")
    make.assign(sam, "shipping", region_hid=places["americas"]["hid"])
    site = {"site_hid": places["site"]["hid"]}

    stop = make.assign(None, "shipping", stop_inheritance=True, **site)
    assert (stop["contact"], stop["stop_inheritance"]) == (None, True)
    room = make.in_force(places["room"])["by_role"]["shipping"]
    assert (room["contacts"], room["source"], room["stopped"]) == ([], "site", True)
    assert make.in_force(places["central"], "regions")["by_role"]["shipping"]["stopped"] is False
    # It stands alone for its place and role.
    assert "contact_hid" in errors(make.assign(sam, "shipping", 409, **site))
    assert "stop_inheritance" in errors(
        make.assign(None, "shipping", 409, stop_inheritance=True, **site)
    )
    assert "stop_inheritance" in errors(
        make.assign(sam, "technical", 422, stop_inheritance=True, **site)
    )
    region = {"region_hid": places["americas"]["hid"]}
    assert "stop_inheritance" in errors(
        make.assign(None, "shipping", 409, stop_inheritance=True, **region)
    )
    make.delete(f"/contact-assignments/{stop['hid']}")
    assert [
        one["name"] for one in make.in_force(places["room"])["by_role"]["shipping"]["contacts"]
    ] == ["Sam Okafor"]


def test_a_shipping_address_is_taken_whole_and_instructions_by_themselves(make: Maker) -> None:
    americas = make.region("Americas", ship_instructions="Call the desk a day ahead")
    central = make.region("Central", americas, ship_address1="1 Depot Road", ship_city="Riverton")
    site = make.site("Site-2", central, address1="100 Example Way", city="Springfield")
    building = make.location("Building 1", site)
    room = make.location("Room 102", parent=building)

    found = make.in_force(room)
    # The street address of the site is not a shipping address: the depot of the region is.
    assert found["ship_address"] == {
        "value": {
            "address1": "1 Depot Road",
            "address2": None,
            "city": "Riverton",
            "state": None,
            "postal_code": None,
            "country": None,
        },
        "source": "region",
        "source_hid": central["hid"],
        "source_path": "Americas > Central",
    }
    assert found["ship_instructions"] == {
        "value": "Call the desk a day ahead",
        "source": "region",
        "source_hid": americas["hid"],
        "source_path": "Americas",
    }
    # One line of an address on the building makes the building's address the whole of it.
    make.patch(
        f"/locations/{building['hid']}",
        {
            "row_version": building["row_version"],
            "ship_address2": "Dock B",
            "ship_instructions": "Ring twice",
        },
    )
    found = make.in_force(room)
    assert (
        found["ship_address"]["value"]["address1"],
        found["ship_address"]["value"]["address2"],
    ) == (
        None,
        "Dock B",
    )
    assert (found["ship_address"]["source"], found["ship_instructions"]["value"]) == (
        "location",
        "Ring twice",
    )
    nothing = make.in_force(make.region("EMEA"), "regions")
    assert nothing["ship_address"] == {
        "value": None,
        "source": "none",
        "source_hid": None,
        "source_path": None,
    }


def test_an_owner_has_one_primary_among_its_people(make: Maker) -> None:
    make.tag("vendor-managed")
    owner = make.owner(tags=["vendor-managed"])
    dana, robin, lee = (
        make.contact(name) for name in ("Dana Whitfield", "Robin Achterberg", "Lee Marchetti")
    )
    path = f"/owners/{owner['hid']}/members"
    assert (owner["members"], owner["tags"]) == ([], ["vendor-managed"])

    assert "role" in errors(make.post(path, {"contact_hid": dana["hid"], "role": "alternate"}, 422))
    first = make.post(path, {"contact_hid": dana["hid"]})
    second = make.post(path, {"contact_hid": robin["hid"]})
    third = make.post(path, {"contact_hid": lee["hid"]})
    assert [(one["role"], one["priority"]) for one in (first, second, third)] == [
        ("primary", 1),
        ("alternate", 1),
        ("alternate", 2),
    ]
    assert "contact_hid" in errors(make.post(path, {"contact_hid": dana["hid"]}, 409))
    # Marking another makes the one that had it an alternate, in the same change.
    promoted = make.patch(
        f"{path}/{third['hid']}", {"row_version": third["row_version"], "role": "primary"}
    )
    assert promoted["role"] == "primary"
    people = make.get(f"/owners/{owner['hid']}")["members"]
    assert [(one["contact"]["name"], one["role"]) for one in people] == [
        ("Lee Marchetti", "primary"),
        ("Dana Whitfield", "alternate"),
        ("Robin Achterberg", "alternate"),
    ]
    assert make.get(path) == people
    # There is exactly one: it is not made an alternate, nor removed while others remain.
    refused = make.patch(
        f"{path}/{third['hid']}", {"row_version": promoted["row_version"], "role": "alternate"}, 422
    )
    assert "role" in errors(refused)
    assert (
        make.client.delete(f"/api/v1{path}/{third['hid']}", headers=make.headers).status_code == 409
    )
    make.delete(f"{path}/{second['hid']}")
    make.delete(f"{path}/{first['hid']}")
    make.delete(f"{path}/{third['hid']}")
    assert make.get(path) == []
    removed = make.audit(record_type="owner_member", action="delete")
    assert len(removed) == 3
    assert removed[0]["changes"][2] == {
        "field": "role",
        "old": "primary",
        "new": None,
    }
    assert make.get("/owners", filter="tags:has:vendor-managed")["total"] == 1


def test_an_item_with_an_owner_outside_the_team_says_why(make: Maker) -> None:
    team = make.owner()
    outside = make.owner("Facilities", is_external=True, exception_reason="Runs the plant rooms")
    other = make.owner("Landlord", is_external=True, exception_reason="Owns the risers")
    reason = "Mounted in the plant room"

    refused = make.post("/items", {"hostname": "bms-sw-01", "owner_hid": outside["hid"]}, 422)
    assert "Facilities is outside the team" in errors(refused)["owner_exception_reason"]
    alone = {"hostname": "bms-sw-01", "owner_hid": team["hid"], "owner_exception_reason": reason}
    assert "owner_exception_reason" in errors(make.post("/items", alone, 422))
    item = make.item(hostname="bms-sw-01", owner_hid=outside["hid"], owner_exception_reason=reason)
    assert (item["owner_exception"], item["owner_exception_reason"]) == (True, reason)
    # A minor item of it is marked too, and has no reason of its own.
    supply = make.item(name="PS-A", parent_item_hid=item["hid"])
    assert (supply["owner_exception"], supply["owner_exception_reason"]) == (True, None)
    assert make.get("/items", filter="owner_exception:eq:true")["total"] == 2
    assert make.get("/items", filter="owner_exception_reason:contains:plant")["total"] == 1
    # Given to another owner outside the team, it keeps the reason it has.
    item = make.patch(
        f"/items/{item['hid']}", {"row_version": item["row_version"], "owner_hid": other["hid"]}
    )
    assert item["owner_exception_reason"] == reason
    # A reason is not cleared while the owner is outside the team.
    cleared = make.patch(
        f"/items/{item['hid']}",
        {"row_version": item["row_version"], "owner_exception_reason": None},
        422,
    )
    assert "owner_exception_reason" in errors(cleared)
    # Given back to the team, the item is no exception and the reason is gone.
    back = make.patch(
        f"/items/{item['hid']}", {"row_version": item["row_version"], "owner_hid": team["hid"]}
    )
    assert (back["owner_exception"], back["owner_exception_reason"]) == (False, None)
    history = make.get(f"/items/{item['hid']}/history")["items"][0]["changes"]
    assert {"field": "owner_exception_reason", "old": reason, "new": None} in history
    assert make.get("/items", filter="owner_exception:eq:true")["total"] == 0


def test_people_travel_in_files(make: Maker, files: Files) -> None:
    places = make.layout()
    make.owner()
    outside = make.owner("Facilities", is_external=True, exception_reason="Runs the plant rooms")
    files.load(
        "contacts",
        "name,email,phone\nDana Whitfield,dana.whitfield@example.net,+1 555 0100\n"
        "Sam Okafor,,\nNetwork Operations Desk,noc@example.net,\n",
    )
    files.load(
        "contact_assignments",
        "region,site,location,role,contact,stop_inheritance\n"
        "Americas,,,technical,dana.whitfield@example.net,\n"
        ",Americas > Central > Site-2,,shipping,Sam Okafor,\n"
        ",,Americas > Central > Site-2 > Building 1,federal,,true\n",
    )
    files.load(
        "owner_members",
        "owner,contact,role\nNetwork Engineering,dana.whitfield@example.net,primary\n"
        "Network Engineering,noc@example.net,alternate\n",
    )
    room = make.in_force(places["room"])
    assert (_names(room, "technical"), _names(room, "shipping")) == (
        ["Dana Whitfield"],
        ["Sam Okafor"],
    )
    assert room["by_role"]["federal"]["stopped"] is True
    owner = make.get("/owners", filter="label:eq:Network Engineering")["items"][0]
    assert [one["contact"]["email"] for one in owner["members"]] == [
        "dana.whitfield@example.net",
        "noc@example.net",
    ]
    # Loaded again, every row finds its record as it is.
    for entity in ("contacts", "contact_assignments", "owners", "owner_members"):
        again = files.preview(entity, files.export(entity, own_values=True))
        assert again["job"]["unchanged"] == again["job"]["row_count"], (entity, again["rows"])
    # A row is matched by its email address: one that nobody has yet is a new contact,
    # also where somebody of that name is there. A row with none is matched by a name
    # that one contact alone has, and two of a name are no answer.
    renamed = files.preview("contacts", "name,email\nD. Whitfield,dana.whitfield@example.net\n")
    assert renamed["rows"][0]["outcome"] == "update"
    by_name = files.preview("contacts", "name,phone\nSam Okafor,+1 555 0110\n")
    assert by_name["rows"][0]["outcome"] == "update"
    files.load("contacts", "name,email\nSam Okafor,sam.okafor@example.net\n")
    assert make.get("/contacts", filter="name:eq:Sam Okafor")["total"] == 2
    twins = files.preview("contacts", "name,phone\nSam Okafor,+1 555 0199\n")
    assert twins["rows"][0]["reasons"][0]["field"] == "name"
    # An item that a file gives to an owner outside the team carries the reason.
    rows = files.preview(
        "items",
        "hostname,owner,owner_exception_reason\n"
        "bms-sw-01,Facilities,\nbms-sw-02,Facilities,In the plant room\n"
        "bms-sw-03,Network Engineering,In the plant room\n",
    )["rows"]
    assert [row["outcome"] for row in rows] == ["rejected", "create", "rejected"]
    assert (
        rows[0]["reasons"][0]["field"] == rows[2]["reasons"][0]["field"] == "owner_exception_reason"
    )
    assert outside["is_external"] is True
