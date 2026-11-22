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
        "contacts", "name,email,record_status\nExample Left,left@example.net,retired\n", mode=mode
    )
    files.load(
        "operators",
        "label,contact,record_status\nex-left,left@example.net,retired\n",
        mode=mode,
    )
    contact = make.get("/contacts", filter="name:eq:Example Left", include_archived=True)["items"][
        0
    ]
    label = make.get("/operators", filter="label:eq:ex-left", include_archived=True)["items"][0]
    assert (contact["record_status"], label["record_status"]) == ("retired", "retired")
    assert label["contact_hid"] == contact["hid"]
    # One event, the creation, which says it was made retired.
    events = make.audit(record_hid=contact["hid"])
    assert [event["action"] for event in events] == ["create"]
    assert {"field": "record_status", "old": None, "new": "retired"} in events[0]["changes"]


def test_a_row_does_not_retire_a_record_that_is_there(files: Files, make: Maker) -> None:
    make.owner("Voice Services")
    said = _reasons(files, "owners", "label,record_status\nVoice Services,retired\n")
    assert said[0]["field"] == "record_status"


def test_what_stands_on_a_retired_record_is_taken_as_the_app_keeps_it(
    files: Files, make: Maker
) -> None:
    files.load("regions", "name,record_status\nExample Old,retired\n")
    files.load("sites", "name,region,record_status\nSite-8,Example Old,retired\n")
    files.load("locations", "name,site,record_status\nCloset,Example Old > Site-8,retired\n")
    files.load(
        "items",
        "name,location,record_status\nex-retired,Example Old > Site-8 > Closet,retired\n",
    )
    files.load("device_groups", "name,type,record_status\nex-old-kit,custom,retired\n")
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
    files.load("contacts", "name,email,record_status\nExample Left,left@example.net,retired\n")
    files.load("regions", "name,record_status\nExample Old,retired\n")
    files.load("sites", "name,region,record_status\nSite-8,Example Old,retired\n")
    files.load("locations", "name,site,record_status\nCloset,Example Old > Site-8,retired\n")
    files.load("items", "name,record_status\nex-retired,retired\n")
    files.load("device_groups", "name,type,record_status\nex-old-kit,custom,retired\n")
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
    # An assignment of a retired contact to a place.
    files.load("regions", "name\nExample Open\n")
    said = _reasons(
        files,
        "contact_assignments",
        "region,role,contact\nExample Open,technical,left@example.net\n",
    )
    assert said[0]["field"] == "contact"
    # And the API gives a retired item no new address, as before: a file is the one door.
    item = make.get("/items", filter="name:eq:ex-retired", include_archived=True)["items"][0]
    make.post("/addresses", {"item_hid": item["hid"], "address": "198.51.100.11"}, 422)
