"""Links (P-138): an address with its text, on regions, sites, locations and catalog
entries; an item answers those of its model; a file carries them out and back."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.io import columns
from hirdir.io.columns import Column, Unreadable
from tests.api.inventory import Maker, errors
from tests.api.test_files import Files, changes, counts, table

SHEET = {"url": "https://www.example.com/c9300/datasheet.pdf", "text": "Data sheet"}
PLAN = {"url": "https://intranet.example.net/site-2/room-102/plan.pdf", "text": "Floor plan; B1"}
RACKS = {"url": "http://intranet.example.net/site-2/room-102/racks", "text": ""}


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


@pytest.fixture
def places(make: Maker) -> dict[str, dict[str, Any]]:
    region = make.region("Americas", links=[{"url": "https://intranet.example.net/americas"}])
    site = make.site("Site-2", region, links=[{"url": "https://intranet.example.net/site-2"}])
    room = make.location("Room 102", site, links=[PLAN, RACKS])
    return {"region": region, "site": site, "room": room}


def test_each_place_and_model_has_its_own_links_and_an_item_those_of_its_model(
    make: Maker, places: dict
) -> None:
    assert places["room"]["links"] == [PLAN, RACKS]
    # A link with no text shows its address, and a place inherits none from above.
    assert places["region"]["links"] == [
        {"url": "https://intranet.example.net/americas", "text": ""}
    ]
    room = make.get(f"/locations/{places['room']['hid']}")
    assert room["links"] == [PLAN, RACKS]
    assert make.get(f"/sites/{places['site']['hid']}")["links"][0]["text"] == ""
    entry = make.entry(make.vendor(), links=[SHEET])
    assert entry["links"] == [SHEET]
    item = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X001")
    assert item["catalog"]["links"] == [SHEET]
    listed = make.get("/items", fields="hid,catalog.links")["items"]
    assert listed == [{"hid": item["hid"], "row_version": 1, "catalog": {"links": [SHEET]}}]
    bare = make.item(hostname="site2-sw-02")
    assert bare["catalog"] is None


def test_links_are_changed_whole_and_audited_as_one_change(make: Maker, places: dict) -> None:
    room = places["room"]
    changed = make.patch(
        f"/locations/{room['hid']}", {"row_version": room["row_version"], "links": [RACKS, PLAN]}
    )
    assert changed["links"] == [RACKS, PLAN]
    [event, *_] = make.audit(record_type="location", record_hid=room["hid"])
    assert event["changes"] == [{"field": "links", "old": [PLAN, RACKS], "new": [RACKS, PLAN]}]
    cleared = make.patch(
        f"/locations/{room['hid']}", {"row_version": changed["row_version"], "links": None}
    )
    assert cleared["links"] == []
    same = make.patch(
        f"/locations/{room['hid']}", {"row_version": cleared["row_version"], "links": []}
    )
    assert same["row_version"] == cleared["row_version"]


@pytest.mark.parametrize(
    ("link", "wrong"),
    [
        ({"url": "ftp://files.example.com/a"}, "an address that begins with https://"),
        ({"url": "https://www.example.com/a b"}, "with no space"),
        ({"url": "https://www.example.com/<a>"}, "< or >"),
        ({"url": "mailto:noc@example.com"}, "https://"),
        ({"url": ""}, "https://"),
        ({"url": "https://www.example.com/" + "a" * 1990}, "2,000"),
        ({"url": "https://www.example.com/", "text": "a <b>"}, "no < or >"),
    ],
)
def test_an_address_that_is_no_web_address_is_refused_naming_the_link(
    make: Maker, places: dict, link: dict, wrong: str
) -> None:
    site = places["site"]
    refused = make.patch(
        f"/sites/{site['hid']}", {"row_version": site["row_version"], "links": [SHEET, link]}, 422
    )
    message = errors(refused)["links"]
    assert message.startswith("link 2: ")
    assert wrong in message


def test_a_record_has_twenty_links_at_most(make: Maker) -> None:
    many = [{"url": f"https://www.example.com/{number}"} for number in range(21)]
    assert "links" in errors(make.post("/regions", {"name": "Europe", "links": many}, 422))
    made = make.post("/regions", {"name": "Europe", "links": many[:20]})
    assert len(made["links"]) == 20
    vendor = make.vendor()
    long_text = {"url": "https://www.example.com/", "text": "a" * 201}
    refused = make.post(
        "/catalog-entries", {"vendor_hid": vendor["hid"], "pid": "X", "links": [long_text]}, 422
    )
    assert "links" in errors(refused)


def test_links_go_out_to_a_file_and_back_unchanged(make: Maker, places: dict, files: Files) -> None:
    entry = make.entry(make.vendor(), links=[SHEET, RACKS])
    for entity in ("locations", "regions", "sites", "catalog_entries"):
        for form in ("csv", "json"):
            exported = files.export(entity, format=form, own_values=True)
            loaded = files.load(entity, exported if form == "csv" else _json(exported))
            assert counts(loaded) == (0, 0, 1, 0), (entity, form)
    rows = table(files.export("locations", own_values=True))
    assert rows[0]["links"] == (
        "Floor plan; B1 <https://intranet.example.net/site-2/room-102/plan.pdf>; "
        "<http://intranet.example.net/site-2/room-102/racks>"
    )
    sheet = table(files.export("catalog_entries"))[0]["links"]
    assert sheet == f"Data sheet <{SHEET['url']}>; <{RACKS['url']}>"
    # A row changes the links whole, and `!clear` leaves none.
    preview = files.preview("catalog_entries", f"hid,links\n{entry['hid']},<{SHEET['url']}>\n")
    assert changes(preview["rows"][0])["links"] == (sheet, f"<{SHEET['url']}>")
    files.load("locations", f"hid,links\n{places['room']['hid']},!clear\n")
    assert make.get(f"/locations/{places['room']['hid']}")["links"] == []
    # A link that is not written as `text <url>`, or whose address is no web address,
    # rejects the row and names the link.
    for cell, reason in (
        ("Data sheet https://www.example.com/a", "link 1 is not written as text <url>"),
        ("<https://www.example.com/a> and more", "link 1 is followed by something other than ;"),
        ("<https://www.example.com/a>; Map <ftp://x>", "link 2: an address that begins"),
    ):
        refused = files.preview("regions", f"hid,links\n{places['region']['hid']},{cell}\n")
        [why] = refused["rows"][0]["reasons"]
        assert (why["field"], why["message"].startswith(reason)) == ("links", True), why


def _json(exported: str) -> dict[str, Any]:
    return json.loads(exported)


def test_the_text_of_a_file_reads_as_links_and_writes_back_the_same() -> None:
    column = Column("links", "links")
    cell = "Floor plan; B1 <https://a.example.com/p> ;<https://b.example.com/r>;"
    plain = columns.read(column, cell)
    assert plain == "Floor plan; B1 <https://a.example.com/p>; <https://b.example.com/r>"
    assert columns.typed(column, plain) == [
        {"url": "https://a.example.com/p", "text": "Floor plan; B1"},
        {"url": "https://b.example.com/r", "text": ""},
    ]
    assert columns.plain(column, columns.typed(column, plain)) == plain
    assert columns.from_cell(column, "!clear") is None
    with pytest.raises(Unreadable, match="links as text"):
        columns.from_json(column, [SHEET])
    with pytest.raises(Unreadable, match="at most 20 links"):
        columns.read(column, "; ".join(f"<https://x.example.com/{n}>" for n in range(21)))
