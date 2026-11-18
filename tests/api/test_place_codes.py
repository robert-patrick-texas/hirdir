"""A place found by its code wherever its path is taken, and an export that writes places
by code and loads back to the same places (P-235)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit
from hirdir.io import examples
from hirdir.io.entities import LOAD_ORDER
from tests.api import test_cli
from tests.api.inventory import Maker
from tests.api.test_files import Files, table
from tests.conftest import INVENTORY_CODE, sign_in

ROOM = "Americas > Central > Site-2 > Building 1 > Room 102"
# The fixture that runs `hirdir` against the test client.
run = test_cli.run


@pytest.fixture
def coded(make: Maker) -> dict[str, dict[str, Any]]:
    """The layout of `Maker.layout`, each place with a code."""
    americas = make.region("Americas", code="AMER")
    central = make.region("Central", americas, code="CEN")
    site = make.site("Site-2", central, code="S2")
    building = make.location("Building 1", site, kind="building", code="B1")
    floor = make.location("Floor 1", parent=building, kind="floor")
    room = make.location("Room 102", parent=floor, kind="room", code="R102")
    return {
        "americas": americas,
        "central": central,
        "site": site,
        "building": building,
        "floor": floor,
        "room": room,
    }


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _root(make: Maker, text: str, expect: int = 200) -> Any:
    found = make.get("/geography/tree", expect, root=text)
    return found["roots"][0]["hid"] if expect == 200 else found


def test_a_step_of_a_path_is_a_name_or_else_a_code(
    make: Maker, coded: dict[str, dict[str, Any]]
) -> None:
    room, building, site = coded["room"], coded["building"], coded["site"]
    for text in (
        "Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102",
        # A path need not begin at the top: at the code of a site, or of any region.
        "S2 > Building 1 > Floor 1 > Room 102",
        "CEN > Site-2 > Building 1 > Floor 1 > Room 102",
        "AMER > CEN > S2 > B1 > Floor 1 > R102",
        # After a site or a location, the code of a location beneath it, at any depth.
        "S2 > R102",
        "s2 > b1 > r102",
        "Americas > Central > Site-2 > R102",
    ):
        assert _root(make, text) == room["hid"], text
    assert _root(make, "S2") == site["hid"]
    assert _root(make, "S2 > B1") == building["hid"]
    assert _root(make, "AMER") == coded["americas"]["hid"]
    # A code is of its own step: a site's code does not follow a region it is not in.
    make.region("East", coded["americas"], code="EAST")
    _root(make, "EAST > S2", 422)
    # Only a site's or a region's code begins a path: a location's is not unique.
    _root(make, "R102", 422)


def test_a_name_wins_over_a_code_and_a_shared_first_code_finds_neither(
    make: Maker, coded: dict[str, dict[str, Any]]
) -> None:
    # A region at the top named as the site's code is what the first step finds.
    named = make.region("S2")
    assert _root(make, "S2") == named["hid"]
    _root(make, "S2 > R102", 422)
    # Within the site, a location named as another's code is the one found.
    beside = make.location("R102", coded["site"])
    assert _root(make, "Americas > Central > Site-2 > R102") == beside["hid"]
    # A code that a region and a site both have begins no path.
    make.region("Other", code="SHARED")
    make.site("Site-9", coded["central"], code="SHARED")
    _root(make, "SHARED", 422)


def test_a_file_a_filter_and_a_command_take_a_place_by_one_rule(
    make: Maker, files: Files, coded: dict[str, dict[str, Any]], run
) -> None:
    room, building = coded["room"], coded["building"]
    job = files.load("items", "hostname,location\nsite2-sw-01,S2 > R102\nsite2-sw-02,S2 > B1\n")
    assert job["created"] == 2
    placed = {
        row["hostname"]: row["location_hid"] for row in make.get("/items", sort="hostname")["items"]
    }
    assert placed == {"site2-sw-01": room["hid"], "site2-sw-02": building["hid"]}
    assert make.found(filter="location:within:S2 > B1", sort="hostname") == [
        "site2-sw-01",
        "site2-sw-02",
    ]
    assert make.found(filter="location:within:S2 > R102") == ["site2-sw-01"]
    shown = json.loads(run("locations", "show", "S2 > R102", "--format", "json").stdout)
    assert shown["path"] == "Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102"
    # A location's parent in a file of locations is a path too.
    files.load("locations", "name,parent,kind\nRack A1,S2 > R102,rack\n")
    rack = make.get("/locations", filter="name:eq:Rack A1")["items"][0]
    assert rack["parent_location_hid"] == room["hid"]
    # The name a row gives a place of its own is matched by its name alone: a new
    # location named as another's code is a new location.
    preview = files.preview("locations", "name,site\nB1,S2\n")
    assert preview["rows"][0]["outcome"] == "create"


def test_an_export_by_codes_writes_each_place_the_short_way(
    make: Maker, files: Files, coded: dict[str, dict[str, Any]]
) -> None:
    room, building, floor = coded["room"], coded["building"], coded["floor"]
    for name, place in (("sw-room", room), ("sw-building", building), ("sw-floor", floor)):
        make.item(hostname=name, location_hid=place["hid"])
    plain = {row["hostname"]: row["location"] for row in table(files.export("items"))}
    short = {
        row["hostname"]: row["location"]
        for row in table(files.export("items", place_codes=True, own_values=True))
    }
    assert plain["sw-room"] == "Americas > Central > Site-2 > Building 1 > Floor 1 > Room 102"
    assert short == {
        "sw-room": "S2 > R102",
        "sw-building": "S2 > B1",
        # A place with no code of its own is named from its site down.
        "sw-floor": "S2 > Building 1 > Floor 1",
    }
    wanted = ["name", "site", "parent", "path"]
    places = {
        row["name"]: row
        for row in table(files.export("locations", place_codes=True, columns=wanted))
    }
    assert (places["Room 102"]["site"], places["Room 102"]["parent"]) == (
        "S2",
        "S2 > Building 1 > Floor 1",
    )
    assert places["Room 102"]["path"] == "S2 > R102"
    sites = table(files.export("sites", place_codes=True, columns=["name", "region", "path"]))
    assert [(row["name"], row["region"], row["path"]) for row in sites] == [("Site-2", "CEN", "S2")]
    # Where a name would win over the code on the way back, the names are written.
    make.region("S2")
    again = {
        row["hostname"]: row["location"] for row in table(files.export("items", place_codes=True))
    }
    assert again["sw-room"] == plain["sw-room"]


@pytest.fixture(scope="module")
def stocked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Files]:
    """The fictional examples, loaded once for this module, worked by an Inventory user."""
    config = Config(state_dir=tmp_path_factory.mktemp("codes"), trusted_proxies=("testclient",))
    migrate.upgrade(config.database_url)
    with make_sessions(make_engine(config.database_url))() as session:
        examples.load(session, examples.folder())
        user, _ = accounts.create_user(
            session, audit.SYSTEM, username="ivy", access_code=INVENTORY_CODE
        )
        accounts.grant_role(session, audit.SYSTEM, role="inventory", user_hid=user.hid)
        session.commit()
    with TestClient(create_app(config)) as client:
        yield Files(client, sign_in(client, "ivy", INVENTORY_CODE))


@pytest.mark.parametrize("format_", ["csv", "json"])
def test_every_file_exported_by_codes_loads_back_to_the_same_places(
    stocked: Files, format_: str
) -> None:
    written = {}
    for entity in LOAD_ORDER:
        text = stocked.export(entity, place_codes=True, own_values=True, format=format_)
        written[entity] = text
        preview = stocked.preview(entity, json.loads(text) if format_ == "json" else text)
        job = preview["job"]
        assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0), (entity, preview)
        assert job["unchanged"] == job["row_count"], entity
    # The codes the examples have are what the files hold.
    if format_ == "csv":
        assert ",S2 > Building 1 > Floor 1 > Room 102," in written["items"]
        assert ",S2,S2 > B1," in written["locations"]
        assert ",CEN," in written["sites"]
