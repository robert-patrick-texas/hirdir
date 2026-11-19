"""What runs on a switch that joins a stack runs on the stack, and not on a member of it
(P-252)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files, counts
from tests.api.test_hosting import Lab


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


class Running:
    """A switch with a container and a virtual machine on it, a container in the machine,
    and a container that ran on it and was retired."""

    def __init__(self, lab: Lab, number: int = 1) -> None:
        self.lab = lab
        self.switch = lab.make.item(
            catalog_entry_hid=lab.switch_model["hid"],
            serial_number=f"JAF0000X1{number:02d}",
            name=f"site2-sw-acc{number:02d}",
        )
        on = {"host_item_hid": self.switch["hid"]}
        self.ctr = lab.ctr(f"site2-ctr-mon{number:02d}", **on)
        self.vm = lab.vm(f"site2-vm-gs{number:02d}", **on)
        self.inner = lab.ctr(f"site2-ctr-in{number:02d}", host_item_hid=self.vm["hid"])
        gone = lab.ctr(f"site2-ctr-old{number:02d}", **on)
        self.gone = lab.make.post(
            f"/items/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200
        )

    def host(self, item: dict[str, Any]) -> tuple[str | None, str | None]:
        now = self.lab.get(item)
        return now["host_item_hid"], now["host_group_hid"]

    def handed_to(self, stack: dict[str, Any], on_stack: int = 2) -> None:
        """Say that what ran on the switch runs on the stack, each by an event of its own
        that names the stack, and that the rest is as it was."""
        make = self.lab.make
        for item in (self.ctr, self.vm):
            assert self.host(item) == (None, stack["hid"]), item["name"]
            event = make.get(f"/items/{item['hid']}/history")["items"][0]
            changed = {one["field"]: (one["old"], one["new"]) for one in event["changes"]}
            assert changed["host_item_hid"] == (self.switch["hid"], None)
            assert changed["host_group_hid"] == (None, stack["hid"])
            assert changed["joining_group"] == (None, stack["hid"])
        # The container in the machine still runs on the machine, and the one retired is
        # left as it was.
        assert self.host(self.inner) == (self.vm["hid"], None)
        assert self.host(self.gone) == (self.switch["hid"], None)
        assert self.lab.get(self.switch)["hosted_count"] == 0
        assert make.get(f"/device-groups/{stack['hid']}")["hosted_count"] == on_stack


def test_a_switch_that_joins_a_stack_hands_what_runs_on_it_to_the_stack(lab: Lab) -> None:
    other = lab.make.item(catalog_entry_hid=lab.switch_model["hid"], serial_number="JAF0000X199")
    stack = lab.make.group("site2-sw-stack1", "stack", [(other, "master")])
    running = Running(lab)
    assert lab.get(running.switch)["hosted_count"] == 2

    lab.make.add(stack, [{"item_hid": running.switch["hid"]}])

    running.handed_to(stack)


def test_a_switch_made_a_stack_hands_what_runs_on_it_to_the_stack(lab: Lab) -> None:
    running = Running(lab)
    switch = lab.get(running.switch)
    body = {"row_version": switch["row_version"]}
    stack = lab.make.post(f"/items/{switch['hid']}/make-stack", body)
    running.handed_to(stack)


def test_a_new_stack_takes_what_runs_on_its_first_members(lab: Lab) -> None:
    first, second = Running(lab, 1), Running(lab, 2)
    stack = lab.make.group(
        "site2-sw-stack2", "stack", [(first.switch, "master"), (second.switch, "member")]
    )
    first.handed_to(stack, 4)
    for item in (second.ctr, second.vm):
        assert second.host(item) == (None, stack["hid"])
    assert lab.make.get(f"/device-groups/{stack['hid']}")["hosted_count"] == 4


def test_a_file_of_members_hands_what_runs_on_each_to_its_stack(lab: Lab, files: Files) -> None:
    other = lab.make.item(catalog_entry_hid=lab.switch_model["hid"], serial_number="JAF0000X198")
    stack = lab.make.group("site2-sw-stack3", "stack", [(other, "master")])
    running = Running(lab)
    loaded = files.load(
        "device_group_members", f"group,item\nsite2-sw-stack3,{running.switch['hid']}\n"
    )
    assert counts(loaded) == (1, 0, 0, 0)
    running.handed_to(stack)


def test_the_item_that_comes_in_a_replacement_hands_what_runs_on_it_to_the_stack(
    lab: Lab,
) -> None:
    failed = lab.make.item(catalog_entry_hid=lab.switch_model["hid"], serial_number="JAF0000X197")
    stack = lab.make.group("site2-sw-stack4", "stack", [(failed, "master")])
    running = Running(lab)
    failed = lab.get(failed)
    lab.make.post(
        f"/items/{failed['hid']}/replace",
        {
            "row_version": failed["row_version"],
            "reason": "rma",
            "new_item_hid": running.switch["hid"],
        },
    )
    running.handed_to(stack)


def test_a_member_retired_leaves_what_runs_on_the_stack_with_the_stack(lab: Lab) -> None:
    running = Running(lab)
    other = lab.make.item(catalog_entry_hid=lab.switch_model["hid"], serial_number="JAF0000X196")
    stack = lab.make.group(
        "site2-sw-stack5", "stack", [(running.switch, "master"), (other, "member")]
    )
    switch = lab.get(running.switch)
    lab.make.post(f"/items/{switch['hid']}/retire", {"row_version": switch["row_version"]}, 200)
    container = lab.get(running.ctr)
    assert (container["record_status"], container["host_group_hid"]) == ("active", stack["hid"])
    assert container["host_item_hid"] is None


def test_a_new_member_of_a_cluster_keeps_what_runs_on_it(lab: Lab) -> None:
    server = lab.make.item(
        catalog_entry_hid=lab.server_model["hid"], serial_number="SRV0000X003", name="esx-03"
    )
    vm = lab.vm("site2-vm-app03", host_item_hid=server["hid"])
    lab.make.add(lab.cluster, [{"item_hid": server["hid"]}])
    assert (lab.get(vm)["host_item_hid"], lab.get(vm)["host_group_hid"]) == (server["hid"], None)
