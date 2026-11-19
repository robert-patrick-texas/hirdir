"""A member of a stack named again is no news (P-252)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files
from tests.api.test_hosting import Lab
from tests.api.test_stack_host import Stacked

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


def test_naming_a_member_again_is_no_news_and_another_member_is(make: Maker) -> None:
    stacked = Stacked(make)
    ctr = stacked.lab.ctr(host_item_hid=stacked.members[0]["hid"])
    again = stacked.lab.patch(ctr, host_item_hid=stacked.members[0]["hid"])
    assert again["row_version"] == ctr["row_version"]
    assert again["host_observed_at"] == ctr["host_observed_at"]
    moved = stacked.lab.patch(ctr, host_item_hid=stacked.members[1]["hid"])
    assert moved["observed_host"]["hid"] == stacked.members[1]["hid"]
    assert moved["row_version"] == ctr["row_version"] + 1
