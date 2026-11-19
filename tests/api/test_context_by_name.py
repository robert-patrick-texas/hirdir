"""A row with a name and a serial number and no model is the context of that name (P-251)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
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


def test_a_row_with_a_name_and_a_serial_number_and_no_model_is_the_context_of_that_name(
    lab: Lab, files: Files
) -> None:
    make = lab.make
    chassis = make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number=CHASSIS, name="n7k-02"
    )
    vdc = lab.vdc("n7k-02-vdc2", host_item_hid=chassis["hid"])
    preview = files.preview("items", f"name,serial_number\nn7k-02-vdc2,{CHASSIS}\n")
    assert preview["rows"][0]["record_hid"] == vdc["hid"], preview["rows"]
    assert preview["rows"][0]["outcome"] == "unchanged"
    # Two of the name are an error on the row.
    lab.vdc("n7k-02-vdc9")
    lab.vdc("n7k-02-vdc9")
    two = files.preview("items", f"name,serial_number\nn7k-02-vdc9,{CHASSIS}\n")
    assert two["rows"][0]["outcome"] == "rejected"
    # An item of that name that is no context is matched as before.
    make.item(name="lab-box-01")
    plain = files.preview("items", "name,serial_number\nlab-box-01,BOX0000X001\n")
    assert plain["rows"][0]["outcome"] == "create"


def test_two_items_of_one_name_that_are_no_contexts_leave_a_row_as_it_was(
    lab: Lab, files: Files
) -> None:
    """Two spares called alike, neither a context: a row that gives that name and a new
    serial number and no model is a new item, as before 0.9.8, and no error of names."""
    make = lab.make
    for serial in ("EXSP0001", "EXSP0002"):
        make.item(
            catalog_entry_hid=lab.switch_model["hid"], serial_number=serial, name="site2-spare"
        )

    preview = files.preview("items", "name,serial_number\nsite2-spare,EXSP0003\n")

    assert [row["outcome"] for row in preview["rows"]] == ["create"]
