"""What the review of 0.9.8 mended in how what runs on a host is held (P-246)."""

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files, counts
from tests.api.test_hosting import Lab


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def test_a_machine_entered_as_installed_in_its_server_is_put_right_in_one_change(
    lab: Lab,
) -> None:
    # The way before 0.9.8: a machine installed in its server.
    vm = lab.vm(parent_item_hid=lab.esx["hid"])
    assert vm["review"] == [{"reason": "no_host", "about": None}]
    problem = lab.patch(vm, 422, host_item_hid=lab.esx["hid"])
    assert "send parent_item_hid as null with host_item_hid" in errors(problem)["host_item_hid"]
    fixed = lab.patch(vm, host_item_hid=lab.esx["hid"], parent_item_hid=None)
    assert (fixed["parent_item_hid"], fixed["host_item_hid"]) == (None, lab.esx["hid"])
    assert fixed["review"] == []


def test_a_file_puts_right_a_machine_installed_in_its_server_and_names_its_columns(
    lab: Lab, files: Files
) -> None:
    make = lab.make
    vm = lab.vm(parent_item_hid=lab.esx["hid"])
    other = lab.vm("site2-vm-app02", parent_item_hid=lab.esx["hid"])
    # A bulk edit to a host of rows that have a parent says how, in its own words.
    refused = make.post(
        "/items/bulk-update", {"hids": [vm["hid"]], "set": {"host": "site2-esx-01"}}
    )
    reasons = {one["field"]: one["message"] for one in refused["rows"][0]["reasons"]}
    assert "send parent as !clear with host" in reasons["host"]
    # A file that clears the parent with the host puts it right.
    job = files.load("items", f"hid,host,parent\n{vm['hid']},site2-esx-01,!clear\n")
    assert counts(job)[1] == 1
    now = lab.get(vm)
    assert (now["host_item_hid"], now["parent_item_hid"]) == (lab.esx["hid"], None)
    # A moment of what was seen, cleared by itself, names the file's column.
    lab.patch(other, parent_item_hid=None, observed_host_hid=lab.esx2["hid"])
    preview = files.preview("items", f"hid,host_observed_at\n{other['hid']},!clear\n")
    message = {one["field"]: one["message"] for one in preview["rows"][0]["reasons"]}
    assert message["host_observed_at"] == "clear observed_host, which clears its moment"


def test_what_was_seen_is_for_the_kinds_that_run_on_a_host(lab: Lab) -> None:
    blade = lab.make.item(catalog_entry_hid=lab.server_model["hid"], name="site2-blade-01")
    problem = lab.patch(blade, 422, observed_host_hid=lab.esx["hid"])
    assert "seen on nothing" in errors(problem)["observed_host_hid"]
    # A machine whose model is made hardware clears all three in the same request.
    vm = lab.vm(host_item_hid=lab.esx["hid"], observed_host_hid=lab.esx2["hid"])
    made = lab.patch(
        vm,
        catalog_entry_hid=lab.server_model["hid"],
        host_item_hid=None,
        host_group_hid=None,
        observed_host_hid=None,
    )
    assert (made["catalog"]["kind"], made["host"], made["observed_host"]) == (
        "hardware",
        None,
        None,
    )


def test_a_retired_item_with_a_host_does_not_hold_its_models_kind(lab: Lab) -> None:
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    lab.make.post(f"/items/{vm['hid']}/retire", {"row_version": vm["row_version"]}, 200)
    model = lab.make.get(f"/catalog-entries/{lab.vm_model['hid']}")
    body = {"row_version": model["row_version"], "kind": "hardware"}
    assert lab.make.patch(f"/catalog-entries/{model['hid']}", body)["kind"] == "hardware"
