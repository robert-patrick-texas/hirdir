"""What runs on a stack runs on the stack, and not on a member of it (P-252)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files
from tests.api.test_hosting import Lab


class Stacked:
    def __init__(self, make: Maker) -> None:
        self.make = make
        self.lab = Lab(make)
        model = make.entry(make.vendor("Example Switch"), "XS-48P")
        self.members = [
            make.item(
                catalog_entry_hid=model["hid"],
                serial_number=f"XS0000X00{n}",
                name=f"site2-sw-stack1-0{n}",
            )
            for n in (1, 2)
        ]
        self.stack = make.stack("site2-sw-stack1", self.members)


@pytest.fixture
def stacked(make: Maker) -> Stacked:
    return Stacked(make)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _on_stack(found: dict[str, Any], stacked: Stacked, member: int = 0) -> None:
    assert (found["host_item_hid"], found["host_group_hid"]) == (None, stacked.stack["hid"])
    assert (found["host"]["name"], found["host"]["type"]) == ("site2-sw-stack1", "stack")
    assert found["observed_host"]["hid"] == stacked.members[member]["hid"]
    assert found["host_observed_at"] is not None
    assert found["host_differs"] is False


def test_a_member_named_as_a_host_stands_for_its_stack(stacked: Stacked) -> None:
    lab = stacked.lab
    ctr = lab.ctr(host_item_hid=stacked.members[0]["hid"])
    _on_stack(ctr, stacked)
    assert stacked.make.get(f"/device-groups/{stacked.stack['hid']}")["hosted_count"] == 1
    # A request that says what it was seen on keeps its own.
    other = lab.ctr(
        "site2-ctr-dns2",
        host_item_hid=stacked.members[0]["hid"],
        observed_host_hid=stacked.members[1]["hid"],
    )
    assert other["host_group_hid"] == stacked.stack["hid"]
    assert other["observed_host"]["hid"] == stacked.members[1]["hid"]


def test_a_member_of_a_cluster_is_still_a_host(stacked: Stacked) -> None:
    lab = stacked.lab
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    assert (vm["host_item_hid"], vm["host_group_hid"], vm["observed_host"]) == (
        lab.esx["hid"],
        None,
        None,
    )


def test_a_contexts_serial_number_of_a_member_names_the_stack(stacked: Stacked) -> None:
    vdc = stacked.lab.vdc(serial_number="XS0000X002")
    _on_stack(vdc, stacked, member=1)
    assert vdc["serial_number"] is None


def test_a_file_that_names_a_member_says_its_stack_is_the_host(
    stacked: Stacked, files: Files
) -> None:
    text = "vendor,pid,name,host\nExample Virtual,CTR,site2-ctr-dns1,site2-sw-stack1-01\n"
    preview = files.preview("items", text)
    row = preview["rows"][0]
    assert row["outcome"] == "create", row
    changed = {change["field"]: change["new"] for change in row["changes"]}
    assert changed["host_group"] == "site2-sw-stack1"
    assert changed["observed_host"] == "XS0000X001"
    assert row["notes"] == [
        "site2-sw-stack1-01, the host named, is a member of the stack site2-sw-stack1, "
        "which is the host"
    ]
    files.apply(preview)
    found = stacked.make.get("/items", filter="name:eq:site2-ctr-dns1")["items"][0]
    _on_stack(found, stacked)
    # The same report loaded again changes nothing.
    again = files.preview("items", text)
    assert again["rows"][0]["outcome"] == "unchanged", again["rows"][0]


def test_a_bulk_edit_to_a_member_puts_the_rows_on_the_stack(stacked: Stacked) -> None:
    make, lab = stacked.make, stacked.lab
    machines = [lab.ctr(f"site2-ctr-app{n}") for n in (1, 2)]
    preview = make.post(
        "/items/bulk-update",
        {"hids": [one["hid"] for one in machines], "set": {"host": "site2-sw-stack1-02"}},
    )
    assert preview["job"]["rejected"] == 0, preview["rows"]
    make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    for one in machines:
        _on_stack(make.get(f"/items/{one['hid']}"), stacked, member=1)
