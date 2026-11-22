"""The lists of countries and states, and the addresses that take them (P-318, P-321).

Both lists are an Admin's to change and every role's to read; an address stores the
codes, takes a country and a state by code or by name, answers their names, keeps a
value held from before until its country or state is changed, and the places whose
addresses hold what no list holds are listed for a person to choose.
"""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from hirdir.db.engine import make_sessions
from hirdir.db.models import Location, Region, Site
from hirdir.ids import new_hid
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files


@pytest.fixture
def desk(client: TestClient, admin: dict[str, str]) -> Maker:
    """An Admin, who keeps the lists."""
    return Maker(client, admin)


@pytest.fixture
def ivy(make: Maker) -> Maker:
    """A user with the Inventory role, who gives places their addresses."""
    return make


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    """Files sent by a user with the Inventory role."""
    return Files(client, inventory)


def _held(client: TestClient, model: Any, hid: str, **values: Any) -> None:
    """Write values onto a place as a release before 0.9.18 may have left them, past the
    rules, as the upgrade keeps what it does not find in the lists."""
    with make_sessions(cast(FastAPI, client.app).state.engine)() as db:
        db.execute(update(model).where(model.hid == hid).values(**values))
        db.commit()


def _refused(desk: Maker, path: str) -> dict[str, Any]:
    """The problem of a removal that is refused because something holds what it removes."""
    response = desk.client.delete(API + path, headers=desk.headers)
    assert response.status_code == 409, response.text
    return response.json()


def _hid_of(desk: Maker, path: str, **wanted: str) -> str:
    """The HID of the one record of a list that has the fields wanted."""
    found = [one for one in desk.get(path) if all(one[k] == v for k, v in wanted.items())]
    assert len(found) == 1, found
    return found[0]["hid"]


def test_the_lists_start_with_the_americas_the_united_states_first(
    client: TestClient, viewer: dict[str, str]
) -> None:
    reader = Maker(client, viewer)
    countries = reader.get("/countries")
    assert len(countries) == 55
    assert countries[0]["code"] == "US"
    rest = [one["name"] for one in countries[1:]]
    assert rest == sorted(rest, key=str.casefold)
    assert {"CA", "MX", "BR", "BM", "GL"} <= {one["code"] for one in countries}
    # Puerto Rico and the four others are states of the United States, and no countries.
    assert not {"PR", "GU", "VI", "AS", "MP"} & {one["code"] for one in countries}
    states = reader.get("/states", country="US")
    assert len(states) == 56
    assert {"TX", "DC", "PR", "GU", "VI", "AS", "MP"} <= {one["code"] for one in states}
    assert [one["name"] for one in states] == sorted(
        (one["name"] for one in states), key=str.casefold
    )
    # A country by its name, any case, as well as by its code.
    assert reader.get("/states", country="mexico") == reader.get("/states", country="MX")
    every = reader.get("/states")
    assert len(every) == 633
    assert {one["country"] for one in every[:56]} == {"US"}
    refused = reader.get("/states", 422, country="Narnia")
    assert set(errors(refused)) == {"country"}


def test_an_admin_keeps_the_lists_each_change_audited(desk: Maker, ivy: Maker) -> None:
    made = desk.post("/countries", {"code": "xa", "name": "Example Land"})
    assert (made["code"], made["name"]) == ("XA", "Example Land")
    north = desk.post("/states", {"country": "Example Land", "code": "n1", "name": "North"})
    south = desk.post("/states", {"country": "XA", "code": "S", "name": "South"})
    assert (north["country"], north["code"], south["code"]) == ("XA", "N1", "S")
    # The Inventory role reads them and changes neither.
    assert ivy.get("/states", country="XA") == desk.get("/states", country="XA")
    ivy.post("/countries", {"code": "XB", "name": "Other Land"}, 403)
    ivy.post("/states", {"country": "XA", "code": "E", "name": "East"}, 403)
    ivy.patch(f"/countries/{made['hid']}", {"row_version": made["row_version"], "name": "X"}, 403)
    ivy.delete(f"/states/{north['hid']}", 403)
    # Unique: a code, a name without regard to case, a state's code and name in its country.
    taken = desk.post("/countries", {"code": "XA", "name": "Elsewhere"}, 409)
    assert taken["existing"]["hid"] == made["hid"]
    desk.post("/countries", {"code": "XC", "name": "example LAND"}, 409)
    desk.post("/states", {"country": "XA", "code": "n1", "name": "Nord"}, 409)
    desk.post("/states", {"country": "XA", "code": "N2", "name": "north"}, 409)
    # Codes are of their form, and a state is of a listed country.
    assert set(errors(desk.post("/countries", {"code": "X1", "name": "Y"}, 422))) == {"code"}
    assert set(
        errors(desk.post("/states", {"country": "XA", "code": "N-1", "name": "Y"}, 422))
    ) == {"code"}
    refused = desk.post("/states", {"country": "Narnia", "code": "N", "name": "Y"}, 422)
    assert "GET /countries" in errors(refused)["country"]
    # Another state of the same code in another country is no collision.
    desk.post("/states", {"country": "CA", "code": "S", "name": "South of Canada"})

    renamed = desk.patch(
        f"/countries/{made['hid']}", {"row_version": made["row_version"], "name": "Exampleland"}
    )
    assert renamed["name"] == "Exampleland"
    # A code no address holds is changed, and its states go with it.
    recoded = desk.patch(
        f"/countries/{made['hid']}", {"row_version": renamed["row_version"], "code": "xd"}
    )
    assert recoded["code"] == "XD"
    assert {one["code"] for one in desk.get("/states", country="XD")} == {"N1", "S"}
    events = desk.audit(record_hid=made["hid"])
    assert [event["action"] for event in events][:3] == ["update", "update", "create"]

    desk.delete(f"/countries/{made['hid']}")
    assert "XD" not in {one["code"] for one in desk.get("/countries")}
    assert desk.get("/states", 422, country="XD")
    gone = desk.audit(record_hid=made["hid"], action="delete")[0]
    assert {entry["field"]: entry["old"] for entry in gone["changes"]} == {
        "code": "XD",
        "name": "Exampleland",
        "states": ["N1 North", "S South"],
    }
    # Each state that went with it has its own removal in the trail.
    for state in (north, south):
        (event,) = desk.audit(record_hid=state["hid"], action="delete")
        assert event["record_type"] == "state"


def test_the_united_states_is_renamed_but_keeps_its_code_and_its_place(desk: Maker) -> None:
    us = desk.get("/countries")[0]
    assert us["code"] == "US"
    renamed = desk.patch(
        f"/countries/{us['hid']}", {"row_version": us["row_version"], "name": "Zed States"}
    )
    first = desk.get("/countries")[0]
    assert (first["hid"], first["name"]) == (us["hid"], "Zed States")
    refused = desk.patch(
        f"/countries/{us['hid']}", {"row_version": renamed["row_version"], "code": "UA"}, 422
    )
    assert set(errors(refused)) == {"code"}
    desk.delete(f"/countries/{us['hid']}", 409)
    # Its common spellings name it, and are no other country's name.
    desk.post("/countries", {"code": "XU", "name": "U.S.A."}, 422)


def test_a_code_that_an_address_holds_is_not_changed_and_its_country_is_not_removed(
    desk: Maker, ivy: Maker
) -> None:
    land = desk.post("/countries", {"code": "XA", "name": "Example Land"})
    north = desk.post("/states", {"country": "XA", "code": "N", "name": "North"})
    region = ivy.region("Elsewhere")
    site = ivy.site("Site-X", region, city="Exampleton", country="XA", state="North")
    assert (site["country"], site["state"], site["state_name"]) == ("XA", "N", "North")

    refused = desk.patch(f"/countries/{land['hid']}", {"row_version": 1, "code": "XB"}, 409)
    assert "the site Site-X" in errors(refused)["code"]
    refused = _refused(desk, f"/countries/{land['hid']}")
    assert "the site Site-X" in errors(refused)["code"]
    desk.delete(f"/states/{north['hid']}", 409)
    desk.patch(f"/states/{north['hid']}", {"row_version": 1, "code": "NN"}, 409)
    # A state's country is not given another.
    desk.patch(f"/states/{north['hid']}", {"row_version": 1, "country": "CA"}, 422)
    # A rename is no change of what an address holds.
    named = desk.patch(f"/states/{north['hid']}", {"row_version": 1, "name": "Northern"})
    assert ivy.get(f"/sites/{site['hid']}")["state_name"] == "Northern"

    # A state the address does not hold goes; one of a blank country is the United States'.
    ivy.patch(
        f"/sites/{site['hid']}",
        {"row_version": site["row_version"], "country": None, "state": "tx"},
    )
    desk.delete(f"/states/{north['hid']}")
    texas = _hid_of(desk, "/states?country=US", code="TX")
    refused = _refused(desk, f"/states/{texas}")
    assert "the site Site-X" in errors(refused)["code"]
    desk.delete(f"/countries/{land['hid']}")
    assert named["row_version"] == 2


def test_an_address_takes_a_country_and_a_state_by_code_or_name_and_keeps_the_codes(
    ivy: Maker,
) -> None:
    region = ivy.region("Americas", ship_country="u.s.a.", ship_state="Illinois")
    assert (region["ship_country"], region["ship_state"]) == ("US", "IL")
    assert (region["ship_country_name"], region["ship_state_name"]) == ("United States", "Illinois")
    for given, state in (("usa", "texas"), (" U.S. ", "TX"), ("United States of America", "tx")):
        site = ivy.site(f"Site {given.strip()}", region, country=given, state=state)
        assert (site["country"], site["state"], site["state_name"]) == ("US", "TX", "Texas")
    mexico = ivy.site("Site MX", region, country="mexico", state="coahuila de zaragoza")
    assert (mexico["country"], mexico["state"], mexico["country_name"]) == ("MX", "COA", "Mexico")
    assert mexico["state_name"] == "Coahuila de Zaragoza"
    # A country with no states listed takes its state as typed.
    bermuda = ivy.site("Site BM", region, country="Bermuda", state=" Pembroke Parish ")
    assert (bermuda["country"], bermuda["state"], bermuda["state_name"]) == (
        "BM",
        "Pembroke Parish",
        None,
    )
    # A blank country is read as the United States beside another field, and not written.
    blank = ivy.site("Site blank", region, city="Springfield", state="IL")
    assert (blank["country"], blank["country_name"], blank["state"]) == (
        None,
        "United States",
        "IL",
    )
    assert blank["state_name"] == "Illinois"
    # With no other field there is no address, and no country.
    bare = ivy.site("Site bare", region)
    assert (bare["country_name"], bare["state_name"], bare["ship_country_name"]) == (
        None,
        None,
        None,
    )
    room = ivy.location("Room 1", bare, country="CA", state="Ontario", ship_country="ca")
    assert (room["state"], room["ship_country"], room["ship_country_name"]) == (
        "ON",
        "CA",
        "Canada",
    )


def test_a_value_that_no_list_holds_is_refused_at_its_field(ivy: Maker) -> None:
    region = ivy.region("Americas")
    refused = ivy.post(
        "/sites", {"name": "S", "region_hid": region["hid"], "country": "Narnia"}, 422
    )
    assert set(errors(refused)) == {"country"}
    assert "GET /countries" in errors(refused)["country"]
    refused = ivy.post(
        "/sites", {"name": "S", "region_hid": region["hid"], "state": "Ontario"}, 422
    )
    assert "GET /states?country=US" in errors(refused)["state"]
    refused = ivy.post(
        "/sites",
        {"name": "S", "region_hid": region["hid"], "ship_country": "MX", "ship_state": "Texas"},
        422,
    )
    assert set(errors(refused)) == {"ship_state"}
    refused = ivy.patch(
        f"/regions/{region['hid']}", {"row_version": 1, "ship_country": "Atlantis"}, 422
    )
    assert set(errors(refused)) == {"ship_country"}
    site = ivy.site("Site-1", region, country="CA", state="QC")
    # A change of the country holds the state to the new country's list.
    refused = ivy.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "country": "MX"}, 422
    )
    assert set(errors(refused)) == {"state"}


def test_a_value_held_from_before_is_kept_until_its_country_or_state_is_changed(
    client: TestClient, ivy: Maker
) -> None:
    region = ivy.region("Americas")
    site = ivy.site("Site-2", region, city="Springfield")
    _held(client, Site, site["hid"], country="Untied States", state="texas")
    held = ivy.get(f"/sites/{site['hid']}")
    assert (held["country"], held["state"], held["country_name"], held["state_name"]) == (
        "Untied States",
        "texas",
        None,
        None,
    )
    # A change of anything else goes through, and so does the value sent back as it is.
    held = ivy.patch(
        f"/sites/{site['hid']}", {"row_version": held["row_version"], "city": "Dallas"}
    )
    held = ivy.patch(
        f"/sites/{site['hid']}",
        {"row_version": held["row_version"], "notes": "Dock B", "country": "Untied States"},
    )
    assert held["country"] == "Untied States"
    # A change of the state checks both.
    refused = ivy.patch(
        f"/sites/{site['hid']}", {"row_version": held["row_version"], "state": "TX"}, 422
    )
    assert set(errors(refused)) == {"country"}
    chosen = ivy.patch(
        f"/sites/{site['hid']}", {"row_version": held["row_version"], "country": "US"}
    )
    assert (chosen["country"], chosen["state"], chosen["state_name"]) == ("US", "TX", "Texas")
    (event,) = ivy.audit(record_hid=site["hid"], limit=1)
    assert {entry["field"]: (entry["old"], entry["new"]) for entry in event["changes"]} == {
        "country": ("Untied States", "US"),
        "state": ("texas", "TX"),
    }


def test_the_shipping_address_in_force_answers_the_names_with_its_source(ivy: Maker) -> None:
    region = ivy.region("Americas", ship_country="MX", ship_state="jalisco", ship_city="Zapopan")
    site = ivy.site("Site-3", region)
    found = ivy.get(f"/sites/{site['hid']}/effective")["ship_address"]
    assert found["source"] == "region"
    assert {
        name: found["value"][name] for name in ("country", "state", "country_name", "state_name")
    } == {
        "country": "MX",
        "state": "JAL",
        "country_name": "Mexico",
        "state_name": "Jalisco",
    }
    # The street address of a site that deliveries go to, a blank country read as the US.
    own = ivy.site(
        "Site-4", region, address1="100 Example Way", state="NY", ship_same_as_address=True
    )
    found = ivy.get(f"/sites/{own['hid']}/effective")["ship_address"]
    assert (found["source"], found["same_as_address"]) == ("own", True)
    assert (found["value"]["country"], found["value"]["country_name"]) == (None, "United States")
    assert found["value"]["state_name"] == "New York"


def test_the_unlisted_addresses_are_listed_for_a_person_to_choose(
    client: TestClient, ivy: Maker, viewer: dict[str, str]
) -> None:
    region = ivy.region("Americas", ship_country="US", ship_state="IL")
    site = ivy.site("Site-2", region, country="US", state="TX")
    room = ivy.location("Room 1", site)
    _held(client, Region, region["hid"], ship_state="Narnia")
    _held(client, Site, site["hid"], ship_country="Untied States", ship_state="Texas")
    _held(client, Location, room["hid"], city="Austin", state="Lone Star")
    listed = Maker(client, viewer).get("/places/unlisted-addresses")
    assert listed["total"] == 3
    assert [
        (one["level"], one["path"], one["set"], one["field"], one["value"])
        for one in listed["items"]
    ] == [
        ("region", "Americas", "shipping", "ship_state", "Narnia"),
        ("site", "Americas > Site-2", "shipping", "ship_country", "Untied States"),
        ("location", "Americas > Site-2 > Room 1", "street", "state", "Lone Star"),
    ]
    assert listed["items"][1]["hid"] == site["hid"]
    assert listed["items"][1]["record_status"] == "active"
    # Chosen, a value is no longer listed.
    ivy.patch(f"/sites/{site['hid']}", {"row_version": site["row_version"], "ship_country": "US"})
    page = ivy.get("/places/unlisted-addresses", limit=1, offset=1)
    assert (page["total"], [one["field"] for one in page["items"]]) == (2, ["state"])


def test_a_file_of_the_lists_is_an_admins_to_apply(
    client: TestClient, admin: dict[str, str], files: Files, desk: Maker
) -> None:
    keeper = Files(client, admin)
    preview = files.preview("countries", "code,name\nxb,Other Land\n")
    (row,) = preview["rows"]
    assert row["outcome"] == "rejected"
    assert "admin role" in " ".join(one["message"] for one in row["reasons"])
    made = keeper.preview("countries", "code,name\nxb,Other Land\nus,United States\n")
    assert [one["outcome"] for one in made["rows"]] == ["create", "unchanged"]
    # Another role may not apply what an Admin previewed, that changes the list.
    files.apply(made, expect=403)
    keeper.apply(made)
    assert "XB" in {one["code"] for one in desk.get("/countries")}
    # A file whose every row changes nothing is anybody's who may change the inventory.
    again = files.preview("countries", "code,name\nXB,Other Land\n")
    assert again["job"]["unchanged"] == 1
    files.apply(again)
    # A state is found by its code within its country, named by its code or its name.
    states = keeper.preview("states", "country,code,name\nOther Land,o1,Orient\nus,tx,Texas\n")
    assert [one["outcome"] for one in states["rows"]] == ["create", "unchanged"]
    keeper.apply(states)
    assert [one["code"] for one in desk.get("/states", country="XB")] == ["O1"]
    # The export of the list is in the order it is shown, the United States first.
    exported = keeper.export("countries", format="csv")
    assert exported.splitlines()[1].split(",")[1:3] == ["US", "United States"]


def test_a_file_of_places_takes_names_and_keeps_codes(files: Files, ivy: Maker) -> None:
    region = ivy.region("Americas")
    text = (
        "name,region,city,state,country\n"
        "Site-5,Americas,Springfield,illinois,United States\n"
        "Site-6,Americas,Monterrey,Nuevo León,MX\n"
        "Site-7,Americas,Nowhere,,Narnia\n"
    )
    preview = files.preview("sites", text)
    first, second, third = preview["rows"]
    said = {one["field"]: one["new"] for one in first["changes"]}
    assert (said["state"], said["country"]) == ("IL", "US")
    assert {one["field"]: one["new"] for one in second["changes"]}["state"] == "NLE"
    assert third["outcome"] == "rejected"
    assert [one["field"] for one in third["reasons"]] == ["country"]
    files.apply(preview, skip_rejected=True)
    sites = {one["name"]: one for one in ivy.get("/sites")["items"]}
    assert (sites["Site-5"]["state"], sites["Site-5"]["country"]) == ("IL", "US")
    assert sites["Site-6"]["state_name"] == "Nuevo León"
    assert region["hid"] == sites["Site-5"]["region_hid"]
    # Loaded again, by the names, it changes nothing.
    again = files.preview("sites", "name,region,state,country\nSite-5,Americas,IL,usa\n")
    assert again["job"]["unchanged"] == 1


def test_a_file_of_the_lists_of_another_inventory_finds_them_by_their_codes(
    client: TestClient, admin: dict[str, str], desk: Maker
) -> None:
    """Every inventory starts with the lists, each with HIDs of its own: a row whose HID
    no country has is the country of its code, where the list has it (P-321), and makes
    a country with its HID where it has none."""
    keeper = Files(client, admin)
    us, mexico = (desk.get("/countries")[0], _hid_of(desk, "/countries", code="MX"))
    texas = _hid_of(desk, "/states?country=US", code="TX")
    elsewhere, other, also = new_hid(), new_hid(), new_hid()
    preview = keeper.preview(
        "countries",
        f"hid,code,name\n{elsewhere},US,United States\n{other},mx,Mexico\n{also},XE,Exampleia\n",
    )
    assert [(row["outcome"], row["record_hid"]) for row in preview["rows"]][:2] == [
        ("unchanged", us["hid"]),
        ("unchanged", mexico),
    ]
    assert preview["rows"][2]["outcome"] == "create"
    keeper.apply(preview)
    assert _hid_of(desk, "/countries", code="XE") == also
    states = keeper.preview("states", f"hid,country,code,name\n{new_hid()},US,TX,Texas\n")
    assert [(row["outcome"], row["record_hid"]) for row in states["rows"]] == [("unchanged", texas)]
