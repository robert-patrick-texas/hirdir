"""The late review of P-251 and P-252: what a context holds, a row with no model, an item
brought back, and a member named again."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files, counts
from tests.api.test_hosting import Lab

CHASSIS = "EXN7K0001"


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _by_name(make: Maker, name: str) -> dict[str, Any]:
    found = make.get("/items", filter=f"name:eq:{name}")["items"]
    assert len(found) == 1, found
    return found[0]


def _rows(*names: str) -> str:
    lines = "".join(f"Example Virtual,VDC,{name},{CHASSIS}\n" for name in names)
    return "vendor,pid,name,serial_number\n" + lines


def test_contexts_of_one_chassis_reported_before_it_are_each_held(lab: Lab, files: Files) -> None:
    make = lab.make
    names = ("n7k-02-vdc2", "n7k-02-vdc3", "n7k-02-vdc4")
    job = files.load("items", _rows(*names))
    assert counts(job)[0] == 3
    for name in names:
        held = _by_name(make, name)
        assert (held["serial_number"], held["review"][0]["reason"]) == (CHASSIS, "no_host")
    # One waiting, and a second the next night, and the same by the API.
    files.load("items", _rows("n7k-02-vdc5"))
    for name in ("n7k-02-vdc6", "n7k-02-vdc7"):
        assert lab.vdc(name, serial_number=CHASSIS)["serial_number"] == CHASSIS
    # The switch is entered, still unique by its model and serial number, and found.
    switch = make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number=CHASSIS, name="n7k-02"
    )
    twin = make.post(
        "/items",
        {"catalog_entry_hid": lab.switch_model["hid"], "serial_number": CHASSIS, "name": "x"},
        409,
    )
    assert "serial_number" in errors(twin)
    found = files.preview("items", f"vendor,pid,serial_number\nCisco,N7K-C7010,{CHASSIS}\n")
    assert found["rows"][0]["record_hid"] == switch["hid"]
    # The file again: all three run on it and hold nothing.
    files.load("items", _rows(*names))
    for name in names:
        now = _by_name(make, name)
        assert (now["host_item_hid"], now["serial_number"]) == (switch["hid"], None)
