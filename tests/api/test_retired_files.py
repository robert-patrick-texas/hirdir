"""A file may make a record retired, and does not retire one that is there (P-311).

A row that makes a record may give it `retired`, in `create` and in `upsert`: it is made
so, in its one create event, with the links a retired record keeps in the app, to
records that are retired too. What stands on a retired record, loaded after it, is taken
as the app keeps it on one: its addresses and memberships that have ended. What the app
refuses to give a retired record is refused in a file the same way: a label that is not
retired on a retired contact, an item that is not retired in a retired location, a
membership with no end of a retired item or in a retired group, and an assignment of a
retired contact to a place. A row that would change a record that is there to
`retired` is refused, as before.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.ids import new_hid
from tests.api.inventory import Maker
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _reasons(files: Files, entity: str, text: str, mode: str = "upsert") -> list[dict[str, Any]]:
    """The reasons of the one row of a file, which is to be rejected."""
    (row,) = files.preview(entity, text, mode=mode)["rows"]
    assert row["outcome"] == "rejected", row
    return row["reasons"]


@pytest.mark.parametrize("mode", ["create", "upsert"])
def test_a_row_that_makes_a_record_may_make_it_retired_in_one_event(
    files: Files, make: Maker, mode: str
) -> None:
    files.load(
        "contacts",
        f"hid,name,email,record_status\n{new_hid()},Example Left,left@example.net,retired\n",
        mode=mode,
    )
    files.load(
        "operators",
        f"hid,label,contact,record_status\n{new_hid()},ex-left,left@example.net,retired\n",
        mode=mode,
    )
    contact = make.get("/contacts", filter="name:eq:Example Left", include_archived=True)["items"][
        0
    ]
    label = make.get("/operators", filter="label:eq:ex-left", include_archived=True)["items"][0]
    assert (contact["record_status"], label["record_status"]) == ("retired", "retired")
    assert label["contact_hid"] == contact["hid"]
    # The preview says so of the row, plainly (review 7).
    (row,) = files.preview(
        "items", f"hid,name,record_status\n{new_hid()},ex-gone,retired\n", mode=mode
    )["rows"]
    assert (row["outcome"], row["notes"]) == ("create", ["makes the record retired"])
    # One event, the creation, which says it was made retired.
    events = make.audit(record_hid=contact["hid"])
    assert [event["action"] for event in events] == ["create"]
    assert {"field": "record_status", "old": None, "new": "retired"} in events[0]["changes"]


def test_a_row_does_not_retire_a_record_that_is_there(files: Files, make: Maker) -> None:
    make.owner("Voice Services")
    said = _reasons(files, "owners", "label,record_status\nVoice Services,retired\n")
    assert said[0]["field"] == "record_status"


@pytest.mark.parametrize("mode", ["create", "upsert"])
def test_a_row_makes_a_record_retired_only_with_its_hid(
    files: Files, make: Maker, mode: str
) -> None:
    """A retired record is passed over by the keys of a file, so a row with no HID would
    make a retired twin at each load: it is refused, as before 0.9.17 (review 5)."""
    for text in (
        "name,record_status\nex-gone,retired\n",
        "hid,name,record_status\n,ex-gone,retired\n",
    ):
        said = _reasons(files, "items", text, mode=mode)
        assert said[0]["field"] == "record_status"
        assert "HID" in said[0]["message"]


def test_what_stands_on_a_retired_record_is_taken_as_the_app_keeps_it(
    files: Files, make: Maker
) -> None:
    files.load("regions", f"hid,name,record_status\n{new_hid()},Example Old,retired\n")
    files.load("sites", f"hid,name,region,record_status\n{new_hid()},Site-8,Example Old,retired\n")
    files.load(
        "locations",
        f"hid,name,site,record_status\n{new_hid()},Closet,Example Old > Site-8,retired\n",
    )
    files.load(
        "items",
        "hid,name,location,record_status\n"
        f"{new_hid()},ex-retired,Example Old > Site-8 > Closet,retired\n",
    )
    files.load(
        "device_groups", f"hid,name,type,record_status\n{new_hid()},ex-old-kit,custom,retired\n"
    )
    files.load("addresses", "item,address\nex-retired,198.51.100.9\n")
    files.load("addresses", "group,address\nex-old-kit,198.51.100.10\n")
    files.load(
        "device_group_members",
        "group,item,joined_on,left_on\nex-old-kit,ex-retired,2026-01-05,2026-02-05\n",
    )
    item = make.get("/items", filter="name:eq:ex-retired", include_archived=True)["items"][0]
    assert item["record_status"] == "retired"
    assert [
        one["address"] for one in make.get("/addresses", filter="address:eq:198.51.100.9")["items"]
    ] == ["198.51.100.9"]


def test_what_the_app_refuses_a_retired_record_a_file_refuses(
    files: Files, make: Maker, client: TestClient, inventory: dict[str, str]
) -> None:
    files.load(
        "contacts",
        f"hid,name,email,record_status\n{new_hid()},Example Left,left@example.net,retired\n",
    )
    files.load("regions", f"hid,name,record_status\n{new_hid()},Example Old,retired\n")
    files.load("sites", f"hid,name,region,record_status\n{new_hid()},Site-8,Example Old,retired\n")
    files.load(
        "locations",
        f"hid,name,site,record_status\n{new_hid()},Closet,Example Old > Site-8,retired\n",
    )
    files.load("items", f"hid,name,record_status\n{new_hid()},ex-retired,retired\n")
    files.load(
        "device_groups", f"hid,name,type,record_status\n{new_hid()},ex-old-kit,custom,retired\n"
    )
    make.group("ex-kit", "custom")
    make.item(name="ex-kept")

    # A label that is not retired, on a retired contact.
    said = _reasons(files, "operators", "label,contact\nex-open,left@example.net\n")
    assert said[0]["field"] == "contact"
    # An item that is not retired, in a retired location.
    said = _reasons(files, "items", "name,location\nex-there,Example Old > Site-8 > Closet\n")
    assert said[0]["field"] == "location"
    # A place that is not retired, in a retired one.
    said = _reasons(files, "sites", "name,region\nSite-9,Example Old\n")
    assert said[0]["field"] == "region"
    # A membership with no end, of a retired item and in a retired group.
    said = _reasons(files, "device_group_members", "group,item\nex-kit,ex-retired\n")
    assert said[0]["field"] == "item"
    said = _reasons(files, "device_group_members", "group,item\nex-old-kit,ex-kept\n")
    assert said[0]["field"] in ("group", "members", "")
    # And the API gives a retired item no new address, as before: a file is the one door.
    item = make.get("/items", filter="name:eq:ex-retired", include_archived=True)["items"][0]
    make.post("/addresses", {"item_hid": item["hid"], "address": "198.51.100.11"}, 422)


def test_what_stands_on_a_retired_record_is_taken_from_a_file_only_where_a_file_made_it(
    files: Files, make: Maker
) -> None:
    """Review 6: a record retired in the app is given nothing new by a file; one a file
    made retired is given what it kept, and the event of its address says that its
    holder is retired, for a sync to read as nothing to add."""
    kit = make.group("ex-kit", "custom")
    old = make.item(name="ex-old")
    old = make.post(f"/items/{old['hid']}/retire", {"row_version": old["row_version"]}, 200)
    said = _reasons(files, "addresses", "item,address\nex-old,198.51.100.21\n")
    assert said[0]["field"] == "item"
    said = _reasons(
        files,
        "device_group_members",
        "group,item,joined_on,left_on\nex-kit,ex-old,2026-01-05,2026-02-05\n",
    )
    assert said[0]["field"] == "item"

    files.load("items", f"hid,name,record_status\n{new_hid()},ex-filed,retired\n")
    files.load("addresses", "item,address\nex-filed,198.51.100.22\n")
    files.load(
        "device_group_members",
        "group,item,joined_on,left_on\nex-kit,ex-filed,2026-01-05,2026-02-05\n",
    )
    (address,) = make.get("/addresses", filter="address:eq:198.51.100.22")["items"]
    (made,) = make.audit(record_hid=address["hid"])
    assert {"field": "holder_retired", "old": None, "new": True} in made["changes"]
    # By the API, as before, a retired item takes neither, a file's or not.
    filed = make.get("/items", filter="name:eq:ex-filed", include_archived=True)["items"][0]
    make.post("/addresses", {"item_hid": filed["hid"], "address": "198.51.100.23"}, 422)
    make.add(
        kit, [{"item_hid": filed["hid"], "joined_on": "2026-03-01", "left_on": "2026-03-02"}], 422
    )
    # Brought back and retired again in the app, it is the app's retired record.
    back = make.patch(
        f"/items/{filed['hid']}", {"row_version": filed["row_version"], "record_status": "active"}
    )
    make.post(f"/items/{filed['hid']}/retire", {"row_version": back["row_version"]}, 200)
    said = _reasons(files, "addresses", "item,address\nex-filed,198.51.100.24\n")
    assert said[0]["field"] == "item"


def test_a_living_record_is_linked_from_a_file_to_a_retired_one_where_the_app_keeps_it(
    files: Files, make: Maker
) -> None:
    """The owner's answer to review 1b: "Allow where the app keeps it". Each row says so
    in its notes; what the app does not keep stays refused, and so does the API."""
    files.load(
        "contacts",
        f"hid,name,email,record_status\n{new_hid()},Rex Example,rex@example.net,retired\n",
    )
    files.load("owners", f"hid,label,record_status\n{new_hid()},Ex Old Team,retired\n")
    files.load("regions", f"hid,name,record_status\n{new_hid()},Example Old,retired\n")
    vendor = make.vendor("Example Vendor")
    model = make.entry(vendor, "EX-OLD9")
    make.post(f"/catalog-entries/{model['hid']}/retire", {"row_version": 1}, 200)

    def taken(entity: str, text: str, note: str) -> None:
        (row,) = files.preview(entity, text)["rows"]
        assert row["outcome"] == "create", row
        assert any(note in said for said in row["notes"]), row["notes"]
        files.load(entity, text)

    taken(
        "items",
        "name,vendor,pid,owner\nex-living,Example Vendor,EX-OLD9,Ex Old Team\n",
        "links to the retired catalog entry EX-OLD9",
    )
    taken(
        "owner_members",
        "owner,contact,role\nEx Old Team,rex@example.net,primary\n",
        "links to the retired owner Ex Old Team",
    )
    taken(
        "contact_assignments",
        "region,role,contact\nExample Old,technical,rex@example.net\n",
        "links to the retired region Example Old",
    )
    # What the app does not keep: a living place in a retired one, and a living label
    # on a retired contact.
    assert _reasons(files, "sites", "name,region\nSite-9,Example Old\n")[0]["field"] == "region"
    said = _reasons(files, "operators", "label,contact\nrex-open,rex@example.net\n")
    assert said[0]["field"] == "contact"
    # By the API, a new link to a retired record is refused, as before.
    owner = make.get("/owners", filter="label:eq:Ex Old Team", include_archived=True)["items"][0]
    make.post("/items", {"name": "ex-api", "owner_hid": owner["hid"]}, 422)


def _retired_owner_and_operator(files: Files, make: Maker) -> tuple[dict, dict]:
    files.load("owners", f"hid,label,record_status\n{new_hid()},Ex Old Team,retired\n")
    files.load("operators", f"hid,label,record_status\n{new_hid()},old-op,retired\n")
    owner = make.get("/owners", filter="label:eq:Ex Old Team", include_archived=True)["items"][0]
    operator = make.get("/operators", filter="label:eq:old-op", include_archived=True)["items"][0]
    return owner, operator


def test_a_bulk_edit_links_no_living_item_to_a_retired_record(files: Files, make: Maker) -> None:
    """Second review, 1: a bulk edit is the API's, and is held to its rules: a new link
    to a retired record is refused, as PATCH refuses it."""
    _retired_owner_and_operator(files, make)
    item = make.item(name="ex-sw")
    for set_ in ({"owner": "Ex Old Team"}, {"operator": "old-op"}):
        preview = make.post("/items/bulk-update", {"hids": [item["hid"]], "set": set_})
        assert preview["job"]["rejected"] == 1, (set_, preview["rows"])
        assert not any("links to the retired" in note for note in preview["rows"][0]["notes"])
