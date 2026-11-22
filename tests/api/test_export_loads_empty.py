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
import shutil
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import Location, Vendor
from hirdir.domain import (
    addresses,
    audit,
    catalog,
    circuit_records,
    contacts,
    geography,
    groups,
    items,
    operators,
    owners,
    people,
    reset,
)
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
from tests.api.test_export_loads_back import _whole as whole
from tests.api.test_files import Files

# --- inventories of the shapes the app makes (the review of P-311) --------------------


def _built(
    factory: pytest.TempPathFactory, examples: Path, name: str, build: Callable[[Session], None]
) -> Path:
    """The examples, and what `build` adds to them by the rules: made once."""
    folder = factory.mktemp(name)
    made = Config(state_dir=folder)
    assert made.database_path is not None
    shutil.copyfile(examples, made.database_path)
    engine = make_engine(made.database_url)
    with make_sessions(engine)() as db:
        build(db)
        db.commit()
    engine.dispose()
    return whole(folder, made)


def _models(db: Session) -> tuple[str, str]:
    """A model of hardware, and one of a virtual machine, of the first vendor."""
    vendor = db.scalars(select(Vendor).order_by(Vendor.name_key)).first()
    assert vendor is not None
    context = audit.SYSTEM
    box = catalog.create_entry(
        db, context, {"vendor_hid": vendor.hid, "pid": "EX-BOX9", "kind": "hardware"}
    )
    vm = catalog.create_entry(
        db, context, {"vendor_hid": vendor.hid, "pid": "EX-VM9", "kind": "virtual_machine"}
    )
    return box.hid, vm.hid


def _hosted(db: Session) -> None:
    """A cluster and a stack that are not retired, each with a virtual machine on it."""
    context = audit.SYSTEM
    _, vm = _models(db)
    cluster = groups.create_group(db, context, {"type": "cluster", "name": "ex-cl9"})
    stack = groups.create_group(db, context, {"type": "stack", "name": "ex-st9"})
    for name, group in (("ex-vm9", cluster), ("ex-vm10", stack)):
        items.create_item(
            db, context, {"catalog_entry_hid": vm, "name": name, "host_group_hid": group.hid}
        )


def _retired_shapes(db: Session) -> None:
    """Retired as the app retires them: a host with a virtual machine, retired together,
    and a minor item in it; a stack in a closet with an owner, an operator, a host name,
    an address and members, retired; a cluster with a virtual machine, retired; a
    circuit; the rack and the closet; a person with their labels; and the owner."""
    context = audit.SYSTEM
    box, vm = _models(db)
    site = db.scalars(select(Location.site_hid).where(Location.site_hid.is_not(None))).first()
    closet = geography.create_place(
        db, context, geography.LOCATION, {"name": "Closet-R", "site_hid": site}
    )
    rack = geography.create_place(
        db,
        context,
        geography.LOCATION,
        {"name": "Rack-R", "site_hid": site, "parent_location_hid": closet.hid},
    )
    team = owners.create_owner(db, context, {"label": "Ex Old Team"})
    person = contacts.create_contact(
        db, context, {"name": "Rex Example", "email": "rex@example.net"}
    )
    label = operators.create_operator(db, context, {"label": "rex", "contact_hid": person.hid})
    second = operators.create_operator(db, context, {"label": "rex2", "contact_hid": person.hid})
    host = items.create_item(
        db,
        context,
        {
            "catalog_entry_hid": box,
            "name": "ex-host1",
            "hostname": "host1",
            "serial_number": "EX-SN-H1",
            "location_hid": rack.hid,
            "owner_hid": team.hid,
            "operator_hid": label.hid,
        },
    )
    guest = items.create_item(
        db, context, {"catalog_entry_hid": vm, "name": "ex-vm1", "host_item_hid": host.hid}
    )
    addresses.create_address(db, context, {"item_hid": host.hid, "address": "192.0.2.201"})
    addresses.create_address(db, context, {"item_hid": guest.hid, "address": "192.0.2.202"})
    part = items.create_item(db, context, {"name": "ex-psu", "parent_item_hid": host.hid})
    stack = groups.create_group(
        db,
        context,
        {
            "type": "stack",
            "name": "ex-stack",
            "hostname": "stack1",
            "location_hid": closet.hid,
            "owner_hid": team.hid,
            "operator_hid": second.hid,
        },
    )
    members = [
        items.create_item(
            db, context, {"catalog_entry_hid": box, "name": name, "serial_number": serial}
        )
        for name, serial in (("ex-sw1m", "EX-SN-S1"), ("ex-sw2m", "EX-SN-S2"))
    ]
    groups.add_members(db, context, stack.hid, [{"item_hid": one.hid} for one in members])
    addresses.create_address(db, context, {"group_hid": stack.hid, "address": "192.0.2.203"})
    cluster = groups.create_group(
        db, context, {"type": "cluster", "name": "ex-cluster", "location_hid": closet.hid}
    )
    on_cluster = items.create_item(
        db, context, {"catalog_entry_hid": vm, "name": "ex-vm2", "host_group_hid": cluster.hid}
    )
    circuit = circuit_records.create_circuit(
        db,
        context,
        {
            "name": "ex-circ",
            "a_location_hid": closet.hid,
            "z_location_hid": rack.hid,
            "owner_hid": team.hid,
        },
    )
    db.flush()

    def now(record: Any) -> int:
        db.refresh(record)
        return record.row_version

    items.retire_item(db, context, host.hid, now(host))
    items.retire_item(db, context, part.hid, now(part))
    items.retire_item(db, context, on_cluster.hid, now(on_cluster))
    items.retire_item(db, context, members[0].hid, now(members[0]))
    groups.retire_group(db, context, stack.hid, now(stack))
    groups.retire_group(db, context, cluster.hid, now(cluster))
    circuit_records.retire_circuit(db, context, circuit.hid, now(circuit))
    geography.retire_place(db, context, geography.LOCATION, rack.hid, now(rack))
    geography.retire_place(db, context, geography.LOCATION, closet.hid, now(closet))
    people.retire(
        db,
        context,
        Role.ADMIN,
        "contact",
        person.hid,
        now(person),
        {
            "operators": [
                {"hid": label.hid, "action": "retire"},
                {"hid": second.hid, "action": "retire"},
            ]
        },
    )
    owners.retire_owner(db, context, team.hid, now(team))


@pytest.fixture(scope="module")
def hosted_db(tmp_path_factory: pytest.TempPathFactory, examples_db: Path) -> Path:  # noqa: F811
    return _built(tmp_path_factory, examples_db, "hosted", _hosted)


@pytest.fixture(scope="module")
def retired_db(tmp_path_factory: pytest.TempPathFactory, examples_db: Path) -> Path:  # noqa: F811
    return _built(tmp_path_factory, examples_db, "retired", _retired_shapes)


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


@pytest.mark.parametrize(
    "config", ["examples_db", "richer_db", "hosted_db", "retired_db"], indirect=True
)
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
    # A record an earlier row of the file changed is one this inventory had: a later row
    # with an HID no record has makes no second of it. One the file made, it may.
    there = make.item(name="ex-new-sw")
    rows = files.preview(
        "items", f"hid,name,comments\n,ex-new-sw,touched\n{new_hid()},ex-new-sw,a second\n"
    )["rows"]
    assert [row["outcome"] for row in rows] == ["update", "rejected"]
    assert there["hid"] in rows[1]["reasons"][0]["message"]
    rows = files.preview("items", f"hid,name\n{new_hid()},ex-twin-9\n{new_hid()},ex-twin-9\n")[
        "rows"
    ]
    assert [row["outcome"] for row in rows] == ["create", "create"]
    # Text that is no HID names nothing, nor does a UUID of another version than 7.
    assert "no HID" in refused("tags", "hid,label\nnot-an-hid,example-other\n")
    for other in (
        str(uuid.uuid4()),
        "00000000-0000-0000-0000-000000000000",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ):
        assert "no HID" in refused("tags", f"hid,label\n{other},example-other\n"), other
    # An HID that a record of another table has, or had, is that record's for good.
    contact = make.post("/contacts", {"name": "Kim Lee", "email": "kim.lee@example.com"})
    said = refused("items", f"hid,name\n{contact['hid']},ex-taken\n")
    assert "contact" in said
    said = refused("device_groups", f"hid,name,type\n{item['hid']},ex-gone-group,custom\n")
    assert "deleted" in said
    # A bulk edit changes records that exist, and names none that is not.
    make.post("/items/bulk-update", {"hids": [new_hid()], "set": {"comments": "x"}}, 422)
