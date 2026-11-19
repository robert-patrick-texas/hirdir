"""What runs on a host in the items file and in a bulk edit (P-246, P-249)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files, counts, table
from tests.api.test_hosting import Lab


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


def test_a_file_names_hosts_that_its_own_later_rows_make(lab: Lab, files: Files) -> None:
    text = (
        "vendor,pid,name,host,host_group,observed_host,host_observed_at\n"
        "Example Virtual,CTR,site2-ctr-dns1,site2-vm-app01,,,\n"
        "Example Virtual,VM,site2-vm-app01,site2-esx-09,,site2-esx-01,2026-11-01T10:00:00Z\n"
        "Example Virtual,SRV-2U,site2-esx-09,,,,\n"
        "Example Virtual,VM,site2-vm-app02,,site2-esx-cluster,,\n"
        "Example Virtual,VDC,site2-n7k-01-vdc2,site2-n7k-01,,,\n"
    )
    job = files.load("items", text)
    assert counts(job) == (5, 0, 0, 0)
    make = lab.make
    server = _by_name(make, "site2-esx-09")
    vm = _by_name(make, "site2-vm-app01")
    assert (vm["host_item_hid"], vm["observed_host_hid"]) == (server["hid"], lab.esx["hid"])
    assert vm["host_observed_at"] == "2026-11-01T10:00:00Z"
    assert _by_name(make, "site2-ctr-dns1")["host_item_hid"] == vm["hid"]
    assert _by_name(make, "site2-vm-app02")["host_group_hid"] == lab.cluster["hid"]
    # A context's row is never matched by its switch's serial number: none is its own.
    vdc = _by_name(make, "site2-n7k-01-vdc2")
    assert vdc["effective"]["serial_number"]["value"] == "JAF0000X001"
    again = files.preview(
        "items", "vendor,pid,serial_number,name\nExample Virtual,VDC,JAF0000X001,site2-vdc-new\n"
    )
    assert again["rows"][0]["outcome"] == "create"


def test_a_row_that_names_a_host_that_may_not_host_is_rejected_on_its_column(
    lab: Lab, files: Files
) -> None:
    preview = files.preview(
        "items",
        "vendor,pid,name,host,host_group\n"
        "Example Virtual,SRV-2U,site2-esx-10,site2-esx-01,\n"
        "Example Virtual,VM,site2-vm-x,site2-esx-01,site2-esx-cluster\n"
        "Example Virtual,VM,site2-vm-y,site2-nowhere,\n",
    )
    assert preview["job"]["rejected"] == 3
    fields = [{reason["field"] for reason in row["reasons"]} for row in preview["rows"]]
    assert fields[0] == {"host"}
    assert fields[1] == {"host_group"}
    assert fields[2] == {"host"}


def test_an_export_writes_what_an_item_runs_on_and_loads_back_changing_nothing(
    lab: Lab, files: Files
) -> None:
    make = lab.make
    place = make.layout()["room"]
    owner = make.owner("Server Team")
    lab.patch(lab.esx, location_hid=place["hid"], owner_hid=owner["hid"])
    vm = lab.vm(host_item_hid=lab.esx["hid"], observed_host_hid=lab.esx2["hid"])
    lab.ctr(host_item_hid=vm["hid"])
    lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])
    lab.vm("site2-vm-lost")
    for own_values in (False, True):
        text = files.export(
            "items", filter="catalog.vendor:eq:Example Virtual", own_values=own_values
        )
        rows = {row["name"]: row for row in table(text)}
        row = rows["site2-vm-app01"]
        assert (row["host"], row["host_group"], row["observed_host"]) == (
            "SRV0000X001",
            "",
            "SRV0000X002",
        )
        assert row["host_observed_at"]
        assert rows["site2-vm-app02"]["host_group"] == "site2-esx-cluster"
        assert rows["site2-ctr-dns1"]["host"] == "site2-vm-app01"
        # In force, the machine is where its server is; as it is kept, it says nothing.
        assert row["location"] == (
            "" if own_values else "Americas > Central > Site-2 > Building 1 > Room 102"
        )
        job = files.load("items", text)
        assert counts(job)[:2] == (0, 0), job
    # The reasons it is to be looked at, and how many run on it, are written when asked.
    text = files.export(
        "items",
        filter="catalog.vendor:eq:Example Virtual",
        columns=["name", "review", "hosted_count"],
    )
    rows = {row["name"]: row for row in table(text)}
    assert rows["site2-vm-lost"]["review"] == "no_host"
    assert rows["site2-vm-app01"]["hosted_count"] == "1"
    assert rows["site2-esx-01"]["hosted_count"] == "1"


def test_a_bulk_edit_gives_the_rows_chosen_another_host_or_clears_it(lab: Lab) -> None:
    make = lab.make
    machines = [
        lab.vm(f"site2-vm-app{number:02d}", host_group_hid=lab.cluster["hid"])
        for number in (1, 2, 3)
    ]
    hids = [vm["hid"] for vm in machines]
    preview = make.post("/items/bulk-update", {"hids": hids, "set": {"host": "site2-esx-02"}})
    assert preview["job"]["rejected"] == 0, preview["rows"]
    job = make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    assert job["updated"] == 3
    for vm in machines:
        now = lab.get(vm)
        assert (now["host_item_hid"], now["host_group_hid"]) == (lab.esx2["hid"], None)
    assert make.get(f"/device-groups/{lab.cluster['hid']}")["hosted_count"] == 0

    preview = make.post(
        "/items/bulk-update", {"hids": hids, "set": {"host_group": "site2-esx-cluster"}}
    )
    make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    assert make.get(f"/device-groups/{lab.cluster['hid']}")["hosted_count"] == 3

    preview = make.post("/items/bulk-update", {"hids": hids[:1], "set": {"host_group": None}})
    make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    assert lab.get(machines[0])["review"] == [{"reason": "no_host", "about": None}]
    # A switch is given no host by a bulk edit either.
    refused = make.post(
        "/items/bulk-update", {"hids": [lab.n7k["hid"]], "set": {"host": "site2-esx-01"}}
    )
    assert refused["job"]["rejected"] == 1
