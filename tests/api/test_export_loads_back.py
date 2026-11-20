"""What is exported loads back (P-286).

The file of any table, as `POST /exports` gives it with its stored values and its
retired and drafts among them, previewed as an import into the inventory it came from,
changes nothing: every row is `unchanged`, none rejected, in both formats. On an empty
inventory the CSV of a table is its template, its header row alone, and previewing it is
accepted with nothing to do.
"""

import io
import shutil
import sqlite3
import zipfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hirdir.auth.roles import Role
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import CatalogEntry
from hirdir.domain import audit, contacts, items, operators
from hirdir.ids import new_hid
from hirdir.io import examples, imports
from hirdir.io.entities import LOAD_ORDER
from tests.api.inventory import API

FORMATS = ("csv", "json")
CONTENT_TYPES = {"csv": "text/csv", "json": "application/json"}


def _whole(folder: Path, config: Config) -> Path:
    """Write a database out whole, with nothing of it left in a write-ahead log."""
    whole = folder / "whole.db"
    with closing(sqlite3.connect(str(config.database_path))) as connection:
        connection.execute("VACUUM INTO ?", (str(whole),))
    return whole


@pytest.fixture(scope="module")
def examples_db(tmp_path_factory: pytest.TempPathFactory, migrated: Path) -> Path:
    """A database with the examples loaded, as `hirdir admin load-examples` loads them:
    made once, and copied for each test."""
    folder = tmp_path_factory.mktemp("examples")
    made = Config(state_dir=folder)
    assert made.database_path is not None
    shutil.copyfile(migrated, made.database_path)
    engine = make_engine(made.database_url)
    with make_sessions(engine)() as db:
        examples.load(db, examples.folder())
    engine.dispose()
    return _whole(folder, made)


# What the examples lack and a file must carry all the same: values with a comma, a
# quote, a leading character that a spreadsheet takes for a formula, several values in a
# cell, a part number that ends as a spare's does; drafts; and places of one name in two
# places. Each is loaded as a file is, in the order of loading.
RICHER = {
    "tags": 'label,colour,description\nexample-odd,#123456,"=1+1, said ""one"""\n',
    "vendors": (
        "name,aliases,notes\n"
        '"Example, Comma ""Quoted""",Example Alias One;Example Alias Two,=SUM(A1)\n'
    ),
    "catalog_entries": (
        "vendor,pid,model_name,kind,description,est_value,tags\n"
        '"Example, Comma ""Quoted""",EX-PSU=,-48V supply,hardware,"@spare; one, of two",'
        "12.50,example-odd;lab\n"
    ),
    "contacts": "name,email,notes,record_status\nExample Draft,,@starts with an at,draft\n",
    "operators": "label,description,colour,record_status\nex-draft,+plus,#00aa00,draft\n",
    "regions": (
        "name,parent,notes\n"
        "Example North,Americas,=one of two\n"
        "Example Region,,\n"
        "Example North,Example Region,+the other\n"
    ),
    "sites": (
        "name,region,notes,record_status\n"
        "Site-1,Americas > Example North,the second of the name,draft\n"
        "Site-1,Example Region > Example North,the third of the name,active\n"
    ),
    "locations": (
        "name,site,kind\n"
        "Comms Room,Americas > Example North > Site-1,room\n"
        "Comms Room,Example Region > Example North > Site-1,room\n"
    ),
    "owners": 'label,organization\n"Example, Owner","=Example ""Org"""\n',
    "items": (
        "vendor,pid,serial_number,name,description,location,record_status,tags\n"
        '"Example, Comma ""Quoted""",EX-PSU=,EXSN0001,ex-psu-1,"-one, ""two""",'
        "Americas > Example North > Site-1 > Comms Room,draft,example-odd;critical\n"
        '"Example, Comma ""Quoted""",EX-PSU=,EXSN0002,ex-psu-2,,'
        "Example Region > Example North > Site-1 > Comms Room,active,\n"
    ),
}


def _load(db: Any, entity: str, text: str) -> None:
    """Preview and apply one file, as the examples are loaded."""
    context = replace(audit.SYSTEM, request_id=new_hid())
    job = imports.preview(
        db, context, Role.INVENTORY, data=text.encode(), format_="csv", entity_name=entity
    )
    db.commit()
    assert job.rejected == 0, (entity, examples._rejected(db, job.hid))
    imports.begin_apply(db, context, job.hid, source="file")
    db.commit()
    assert imports.work_job(db, job.hid, as_role=Role.INVENTORY) == "applied"


def _richer(db: Any) -> None:
    """Add to the examples what they lack, by files and by the rules."""
    for entity, text in RICHER.items():
        _load(db, entity, text)
    context = audit.SYSTEM
    # Two people of one name, neither with an email, each behind an operator; one
    # contact retired, and one operator.
    first = contacts.create_contact(db, context, {"name": "Example Person"})
    second = contacts.create_contact(db, context, {"name": "Example Person", "notes": "-"})
    operators.create_operator(db, context, {"label": "ex-ops", "contact_hid": first.hid})
    gone = operators.create_operator(db, context, {"label": "ex-ops-2", "contact_hid": second.hid})
    third = contacts.create_contact(db, context, {"name": "Example Gone"})
    db.flush()
    operators.retire_operator(db, context, gone.hid, gone.row_version)
    contacts.retire_contact(db, context, third.hid, third.row_version)
    # Two items of one name with neither a serial number nor an asset tag, each with an
    # address, the second a draft.
    model = db.scalar(select(CatalogEntry.hid).where(CatalogEntry.pid == "EX-PSU="))
    twins = [
        items.create_item(db, context, {"catalog_entry_hid": model, "name": "ex-twin", **more})
        for more in ({}, {"record_status": "draft"})
    ]
    db.commit()
    _load(
        db,
        "contact_assignments",
        f"region,role,contact\nExample Region,escalation,{first.hid}\n",
    )
    _load(
        db,
        "addresses",
        f"item,address,network\n{twins[0].hid},198.51.100.7,Management\n"
        f"{twins[1].hid},198.51.100.8,Management\n",
    )
    db.commit()


@pytest.fixture(scope="module")
def richer_db(tmp_path_factory: pytest.TempPathFactory, examples_db: Path) -> Path:
    """The examples, and what they lack: made once, and copied for each test."""
    folder = tmp_path_factory.mktemp("richer")
    made = Config(state_dir=folder)
    assert made.database_path is not None
    shutil.copyfile(examples_db, made.database_path)
    engine = make_engine(made.database_url)
    with make_sessions(engine)() as db:
        _richer(db)
    engine.dispose()
    return _whole(folder, made)


@pytest.fixture
def config(request: pytest.FixtureRequest, tmp_path: Path, migrated: Path) -> Config:
    """The configuration of a test, whose database holds the examples, or nothing where
    the test is given `empty`."""
    config = Config(state_dir=tmp_path, trusted_proxies=("testclient",))
    which = getattr(request, "param", "examples_db")
    source = migrated if which == "empty" else request.getfixturevalue(which)
    assert config.database_path is not None
    shutil.copyfile(source, config.database_path)
    return config


def export(client: TestClient, headers: dict[str, str], entity: str, format_: str) -> str:
    response = client.post(
        f"{API}/exports",
        json={
            "entity": entity,
            "format": format_,
            "own_values": True,
            "include_archived": True,
            "include_drafts": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.text


def preview(
    client: TestClient, headers: dict[str, str], entity: str, format_: str, text: str
) -> dict[str, Any]:
    response = client.post(
        f"{API}/imports/preview",
        params={"entity": entity, "file_name": examples.file_name(entity, format_)},
        content=text.encode("utf-8"),
        headers={**headers, "Content-Type": CONTENT_TYPES[format_]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def changed_rows(
    client: TestClient, headers: dict[str, str], job: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """Yield each row of a preview that is not `unchanged`, with what it said."""
    offset = 0
    while True:
        page = client.get(
            f"{API}/imports/{job['hid']}/rows",
            params={"limit": 500, "offset": offset},
            headers=headers,
        ).json()
        for row in page["items"]:
            if row["outcome"] != "unchanged":
                yield {
                    "row": row["row"],
                    "outcome": row["outcome"],
                    "key": row.get("key"),
                    "changes": row.get("changes"),
                    "reasons": row.get("reasons"),
                    "notes": row.get("notes"),
                }
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            return


def counts(client: TestClient, headers: dict[str, str]) -> dict[str, int]:
    listed = client.get(f"{API}/exports/tables", headers=headers).json()
    return {table["entity"]: table["count"] for table in listed}


def assert_loads_back(
    client: TestClient, headers: dict[str, str], entity: str, format_: str
) -> dict[str, Any]:
    """Export a table whole, preview it as an import of the same table, and hold that
    every row is `unchanged`. Return the job of the preview."""
    job = preview(client, headers, entity, format_, export(client, headers, entity, format_))["job"]
    different = list(changed_rows(client, headers, job))
    assert different == [], (
        f"{entity} as {format_}: {len(different)} of {job['row_count']} rows: {different[:3]}"
    )
    assert job["unchanged"] == job["row_count"]
    assert job["row_count"] == counts(client, headers)[entity]
    return job


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("entity", LOAD_ORDER)
def test_the_file_of_every_table_of_the_examples_loads_back_as_nothing_to_change(
    client: TestClient, inventory: dict[str, str], entity: str, format_: str
) -> None:
    job = assert_loads_back(client, inventory, entity, format_)
    # Every table of the examples holds something: an empty file would hold nothing.
    assert job["row_count"] > 0


@pytest.mark.parametrize("config", ["empty"], indirect=True)
@pytest.mark.parametrize("entity", LOAD_ORDER)
def test_the_template_of_every_table_is_its_header_and_is_read_with_nothing_to_do(
    client: TestClient, inventory: dict[str, str], entity: str
) -> None:
    columns = {
        table["entity"]: table["columns"]
        for table in client.get(f"{API}/exports/tables", headers=inventory).json()
    }[entity]
    text = export(client, inventory, entity, "csv")
    assert text == ",".join(columns) + "\n"
    job = preview(client, inventory, entity, "csv", text)["job"]
    assert (job["row_count"], job["rejected"], job["created"]) == (0, 0, 0)
    as_json = export(client, inventory, entity, "json")
    job = preview(client, inventory, entity, "json", as_json)["job"]
    assert (job["row_count"], job["rejected"], job["created"]) == (0, 0, 0)


@pytest.mark.parametrize("config", ["empty"], indirect=True)
@pytest.mark.parametrize(
    ("entity", "filled"),
    [
        ("tags", {"label": "example-new"}),
        ("vendors", {"name": "Example Vendor"}),
        ("contacts", {"name": "Example Person", "email": "example.person@example.net"}),
        ("regions", {"name": "Example Region", "notes": "=a note"}),
        ("networks", {"label": "Example Network", "kind": "vrf"}),
        ("items", {"vendor": "Example Vendor", "pid": "EX-1", "serial_number": "EXSN1"}),
    ],
)
def test_a_template_with_a_row_filled_in_is_read_as_a_new_record(
    client: TestClient, inventory: dict[str, str], entity: str, filled: dict[str, str]
) -> None:
    template = export(client, inventory, entity, "csv")
    columns = template.rstrip("\n").split(",")
    row = ",".join(filled.get(column, "") for column in columns)
    job = preview(client, inventory, entity, "csv", f"{template}{row}\n")["job"]
    assert (job["row_count"], job["created"], job["rejected"]) == (1, 1, 0)


@pytest.mark.parametrize("config", ["richer_db"], indirect=True)
@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("entity", LOAD_ORDER)
def test_names_shared_odd_values_drafts_and_the_retired_load_back_too(
    client: TestClient, inventory: dict[str, str], entity: str, format_: str
) -> None:
    assert_loads_back(client, inventory, entity, format_)


@pytest.mark.parametrize("format_", FORMATS)
def test_each_file_of_the_zip_of_every_table_loads_back_as_nothing_to_change(
    client: TestClient, inventory: dict[str, str], format_: str
) -> None:
    response = client.post(f"{API}/exports/all", json={"format": format_}, headers=inventory)
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    held = counts(client, inventory)
    for entity in LOAD_ORDER:
        text = archive.read(examples.file_name(entity, format_)).decode("utf-8")
        job = preview(client, inventory, entity, format_, text)["job"]
        different = list(changed_rows(client, inventory, job))
        assert different == [], f"{entity} as {format_} from the zip: {different[:3]}"
        assert job["unchanged"] == job["row_count"] == held[entity]
