"""The files that are exported write a time as the API does, in UTC with `Z` (P-311).

Every column of a time of every table, in both formats, one table at a time and in the
zip of Export everything: each time that is written ends with `Z`, and is the time the
API answers for the same record.
"""

import csv
import io
import json
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.io import examples
from hirdir.io.entities import LOAD_ORDER, entity
from tests.api.inventory import API
from tests.api.test_export_loads_back import (
    FORMATS,
    config,  # noqa: F401 - the fixture of a database that holds the examples
    examples_db,  # noqa: F401 - the fixture that config is given
    export,
)


def _rows(text: str, format_: str) -> list[dict[str, Any]]:
    if format_ == "csv":
        return list(csv.DictReader(io.StringIO(text)))
    return json.loads(text)["records"]


def _times(name: str) -> list[str]:
    """The columns of a time of a table's file."""
    return [column.name for column in entity(name).columns if column.kind == "timestamp"]


def _written(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    return [row[name] for row in rows for name in columns if row.get(name)]


@pytest.mark.parametrize("format_", FORMATS)
def test_every_time_of_every_table_is_written_in_utc_with_z(
    client: TestClient, inventory: dict[str, str], format_: str
) -> None:
    written: list[str] = []
    for name in LOAD_ORDER:
        columns = _times(name)
        if not columns:
            continue
        rows = _rows(export(client, inventory, name, format_), format_)
        times = _written(rows, columns)
        assert all(time.endswith("Z") and "+" not in time for time in times), (name, times[:3])
        written += times
    # The examples hold times to write: an empty column would prove nothing.
    assert written

    # The zip of every table writes them so too.
    response = client.post(f"{API}/exports/all", json={"format": format_}, headers=inventory)
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    zipped: list[str] = []
    for name in LOAD_ORDER:
        rows = _rows(archive.read(examples.file_name(name, format_)).decode("utf-8"), format_)
        zipped += _written(rows, _times(name))
    assert sorted(zipped) == sorted(written)


def test_a_time_is_the_one_the_api_answers(client: TestClient, inventory: dict[str, str]) -> None:
    rows = _rows(export(client, inventory, "items", "csv"), "csv")
    seen = [row for row in rows if row.get("observed_at")]
    assert seen, "the examples hold an item that was seen"
    for row in seen[:5]:
        item = client.get(f"{API}/items/{row['hid']}", headers=inventory).json()
        assert row["observed_at"] == item["observed_at"]
