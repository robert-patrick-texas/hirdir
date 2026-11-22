"""The file of every table, Export everything, loads into an empty inventory (P-311).

The zip of every table, as `POST /exports/all` gives it, with the HIDs in it, is loaded
file by file in the order of loading into the inventory once `hirdir admin reset` has
emptied it: every row is taken, none rejected, each record keeps its HID, and the zip of
the inventory then made is the zip that was loaded, but for what no file sets. A row
whose HID no record has makes the record with it; it is refused where that record was
deleted, where its key finds another, in a bulk edit and for text that is no HID.

The records of the richer inventory that are retired are loaded retired, with what a
retired record keeps: a row that makes a record may make it retired, and what stands on
it, loaded after it, is taken as the app keeps it on a retired record (P-311).
"""

import csv
import io
import json
import zipfile
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirdir.db.engine import make_sessions
from hirdir.domain import audit, reset
from hirdir.ids import new_hid
from hirdir.io import examples
from hirdir.io.entities import LOAD_ORDER, entity
from tests.api.inventory import API, Maker, wait_for_job
from tests.api.test_export_loads_back import (
    FORMATS,
    changed_rows,
    config,  # noqa: F401 - the fixture of a database that holds the examples
    counts,
    examples_db,  # noqa: F401 - the fixture that config is given
    preview,
    richer_db,  # noqa: F401 - the fixture that config is given
)
from tests.api.test_files import Files


def _zip(client: TestClient, headers: dict[str, str], format_: str) -> zipfile.ZipFile:
    response = client.post(f"{API}/exports/all", json={"format": format_}, headers=headers)
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def _emptied(client: TestClient) -> None:
    """Empty the inventory as `hirdir admin reset` does: the accounts stay."""
    with make_sessions(cast(FastAPI, client.app).state.engine)() as db:
        reset.clear_inventory(db, replace(audit.SYSTEM, request_id=new_hid()), "none")
        db.commit()


def _rows(archive: zipfile.ZipFile, name: str, format_: str) -> list[dict[str, Any]]:
    """The rows of one file of the zip, without what no file sets, by their HIDs."""
    text = archive.read(examples.file_name(name, format_)).decode("utf-8")
    if format_ == "csv":
        rows: list[dict[str, Any]] = list(csv.DictReader(io.StringIO(text)))
    else:
        rows = json.loads(text)["records"]
    which = entity(name)
    fixed = {column.name for column in which.columns if not column.settable}
    return sorted(
        ({key: value for key, value in row.items() if key not in fixed} for row in rows),
        key=lambda row: str(row.get("hid")),
    )


def _rejected(client: TestClient, headers: dict[str, str], job: dict[str, Any]) -> list[dict]:
    return [row for row in changed_rows(client, headers, job) if row["outcome"] == "rejected"]


@pytest.mark.parametrize("config", ["examples_db", "richer_db"], indirect=True)
@pytest.mark.parametrize("format_", FORMATS)
def test_the_zip_of_every_table_loads_into_an_empty_inventory_as_it_was(
    client: TestClient, inventory: dict[str, str], format_: str
) -> None:
    first = _zip(client, inventory, format_)
    held = counts(client, inventory)
    _emptied(client)
    assert set(counts(client, inventory).values()) == {0}

    for name in LOAD_ORDER:
        text = first.read(examples.file_name(name, format_)).decode("utf-8")
        job = preview(client, inventory, name, format_, text)["job"]
        assert job["rejected"] == 0, (
            name,
            [(row["key"], row["reasons"]) for row in _rejected(client, inventory, job)[:3]],
        )
        assert job["created"] == job["row_count"] == held[name], name
        applied = client.post(f"{API}/imports/{job['hid']}/apply", headers=inventory)
        assert applied.status_code == 202, applied.text
        done = wait_for_job(client, inventory, applied.json()["hid"])
        assert (done["status"], done["applied"], done["stale"]) == (
            "applied",
            held[name],
            0,
        ), name

    assert counts(client, inventory) == held
    again = _zip(client, inventory, format_)
    for name in LOAD_ORDER:
        assert _rows(again, name, format_) == _rows(first, name, format_), name
    # And loaded once more, every row is as it was.
    for name in LOAD_ORDER:
        text = again.read(examples.file_name(name, format_)).decode("utf-8")
        job = preview(client, inventory, name, format_, text)["job"]
        assert job["unchanged"] == job["row_count"], (
            name,
            list(changed_rows(client, inventory, job))[:3],
        )


# --- a row whose HID no record has ---------------------------------------------------


@pytest.mark.parametrize("config", ["empty"], indirect=True)
def test_a_row_makes_its_record_with_the_hid_it_gives_and_a_reference_finds_it(
    client: TestClient, inventory: dict[str, str]
) -> None:
    make = Maker(client, inventory)
    files = Files(client, inventory)
    vendor, entry, item = new_hid(), new_hid(), new_hid()
    files.load("vendors", f"hid,name\n{vendor},Example Vendor\n")
    files.load("catalog_entries", f"hid,vendor,pid\n{entry},{vendor},EX-1\n")
    # Two items of one name, told apart by their HIDs; a minor item names the first by it.
    twin = new_hid()
    files.load(
        "items",
        f"hid,vendor,pid,name,parent\n{item},Example Vendor,EX-1,ex-twin,\n"
        f"{twin},Example Vendor,EX-1,ex-twin,\n{new_hid()},Example Vendor,EX-1,ex-part,{item}\n",
    )
    assert make.get(f"/vendors/{vendor}")["name"] == "Example Vendor"
    assert make.get(f"/catalog-entries/{entry}")["vendor_hid"] == vendor
    made = make.get(f"/items/{item}")
    assert (made["name"], made["catalog_entry_hid"]) == ("ex-twin", entry)
    assert make.get(f"/items/{twin}")["name"] == "ex-twin"
    # The event of each creation is of that HID.
    assert [event["action"] for event in make.audit(record_hid=item)] == ["create"]


@pytest.mark.parametrize("config", ["empty"], indirect=True)
def test_a_row_whose_hid_no_record_has_is_refused_where_it_would_bring_back_or_double(
    client: TestClient, inventory: dict[str, str], admin: dict[str, str]
) -> None:
    make = Maker(client, inventory)
    files = Files(client, inventory)
    kept = make.post("/tags", {"label": "example-kept"})
    item = make.item(name="ex-gone")
    response = client.post(
        f"{API}/items/delete", json={"hids": [item["hid"]], "reason": "made twice"}, headers=admin
    )
    assert response.status_code == 200, response.text

    def refused(entity: str, text: str) -> str:
        preview = files.preview(entity, text)
        assert preview["job"]["rejected"] == 1, preview["rows"]
        [reason] = preview["rows"][0]["reasons"]
        assert reason["field"] == "hid"
        return reason["message"]

    # A record that was deleted is not brought back by a file.
    assert "deleted" in refused("items", f"hid,name\n{item['hid']},ex-gone\n")
    # A row whose key finds another record does not make a second of it: a tag by its
    # label, an item by its serial number with its model, or by its asset tag.
    said = refused("tags", f"hid,label\n{new_hid()},example-kept\n")
    assert kept["hid"] in said
    vendor = make.post("/vendors", {"name": "Example Vendor"})
    model = make.post("/catalog-entries", {"vendor_hid": vendor["hid"], "pid": "EX-1"})
    known = make.item(catalog_entry_hid=model["hid"], serial_number="EXSN1", asset_tag="EX-AT-1")
    said = refused(
        "items", f"hid,vendor,pid,serial_number\n{new_hid()},Example Vendor,EX-1,EXSN1\n"
    )
    assert known["hid"] in said
    said = refused("items", f"hid,asset_tag,name\n{new_hid()},EX-AT-1,ex-other\n")
    assert known["hid"] in said
    # Text that is no HID names nothing.
    assert "no HID" in refused("tags", "hid,label\nnot-an-hid,example-other\n")
    # A bulk edit changes records that exist, and names none that is not.
    make.post("/items/bulk-update", {"hids": [new_hid()], "set": {"comments": "x"}}, 422)
