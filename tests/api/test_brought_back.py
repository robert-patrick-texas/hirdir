"""An item brought back is held to the rules of its host (P-246, P-252)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files
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


def test_an_item_brought_back_is_held_to_the_rules_of_its_host(lab: Lab) -> None:
    make = lab.make
    model = make.entry(make.vendor("Example Switch"), "XS-48P")
    switch = make.item(catalog_entry_hid=model["hid"], serial_number="XS0000X009", name="sw-9")
    other = make.item(catalog_entry_hid=model["hid"], serial_number="XS0000X010", name="sw-10")
    ctr = lab.ctr(host_item_hid=switch["hid"])
    make.post(f"/items/{ctr['hid']}/retire", {"row_version": ctr["row_version"]}, 200)
    stack = make.stack("site2-sw-stack9", [switch, other])
    back = lab.patch(ctr, record_status="active")
    assert (back["host_item_hid"], back["host_group_hid"]) == (None, stack["hid"])
    assert back["observed_host"]["hid"] == switch["hid"]

    # A model made hardware while a retired item of it names a host.
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    make.post(f"/items/{vm['hid']}/retire", {"row_version": vm["row_version"]}, 200)
    entry = make.get(f"/catalog-entries/{lab.vm_model['hid']}")
    make.patch(
        f"/catalog-entries/{entry['hid']}",
        {"row_version": entry["row_version"], "kind": "hardware"},
    )
    problem = lab.patch(vm, 422, record_status="active")
    assert "send host_item_hid as null" in errors(problem)["record_status"]
    cleared = lab.patch(vm, record_status="active", host_item_hid=None)
    assert (cleared["record_status"], cleared["host"]) == ("active", None)

    # A host that is retired stays, and the item is marked host_gone.
    ctr2 = lab.ctr("site2-ctr-dns2", host_item_hid=lab.esx2["hid"])
    make.post(f"/items/{ctr2['hid']}/retire", {"row_version": ctr2["row_version"]}, 200)
    esx2 = make.get(f"/items/{lab.esx2['hid']}")
    make.post(f"/items/{esx2['hid']}/retire", {"row_version": esx2["row_version"]}, 200)
    again = lab.patch(ctr2, record_status="active")
    assert again["host_item_hid"] == lab.esx2["hid"]
    assert again["review"][0]["reason"] == "host_gone"
