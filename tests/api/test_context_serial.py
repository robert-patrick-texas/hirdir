"""The serial number given for a virtual context names its host (P-251)."""

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


def _chassis(lab: Lab) -> dict[str, Any]:
    return lab.make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number=CHASSIS, name="site2-n7k-02"
    )


def _by_name(make: Maker, name: str) -> dict[str, Any]:
    found = make.get("/items", filter=f"name:eq:{name}")["items"]
    assert len(found) == 1, found
    return found[0]


def test_a_serial_number_given_for_a_context_names_its_host_and_is_not_stored(
    lab: Lab,
) -> None:
    chassis = _chassis(lab)
    vdc = lab.vdc(serial_number=CHASSIS)
    assert (vdc["host_item_hid"], vdc["serial_number"]) == (chassis["hid"], None)
    assert vdc["effective"]["serial_number"]["value"] == CHASSIS
    assert vdc["review"] == []
    # Given again with its host, nothing changes.
    again = lab.patch(vdc, serial_number=CHASSIS)
    assert again["row_version"] == vdc["row_version"]
    # A machine keeps a serial number of its own.
    vm = lab.vm(serial_number=CHASSIS)
    assert (vm["serial_number"], vm["host_item_hid"]) == (CHASSIS, None)


def test_a_serial_number_that_names_another_host_than_the_one_named_is_refused(
    lab: Lab,
) -> None:
    chassis = _chassis(lab)
    problem = lab.vdc(expect=422, serial_number=CHASSIS, host_item_hid=lab.n7k["hid"])
    said = errors(problem)["serial_number"]
    assert "site2-n7k-02" in said
    assert "site2-n7k-01" in said
    # Naming the same one is no refusal.
    vdc = lab.vdc(serial_number=CHASSIS, host_item_hid=chassis["hid"])
    assert vdc["host_item_hid"] == chassis["hid"]


def test_a_serial_number_that_two_items_have_is_refused_and_one_none_has_is_held(
    lab: Lab,
) -> None:
    other = lab.make.entry(lab.make.vendor("Example Switch"), "XS-9000")
    _chassis(lab)
    lab.make.item(catalog_entry_hid=other["hid"], serial_number=CHASSIS, name="site2-xs-01")
    problem = lab.vdc(expect=422, serial_number=CHASSIS)
    said = errors(problem)["serial_number"]
    assert "site2-n7k-02" in said
    assert "site2-xs-01" in said

    held = lab.vdc("site2-n7k-09-vdc2", serial_number="EXN7K0009")
    assert (held["serial_number"], held["host_item_hid"]) == ("EXN7K0009", None)
    assert held["review"] == [{"reason": "no_host", "about": None}]
    # Once a switch of that serial number is entered, the reason names it; nothing joins
    # the two by itself.
    switch = lab.make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number="EXN7K0009", name="site2-n7k-09"
    )
    marks = lab.get(held)["review"]
    assert marks == [
        {
            "reason": "no_host",
            "about": {"hid": switch["hid"], "record_type": "item", "label": "site2-n7k-09"},
        }
    ]
    row = lab.make.get("/items", filter=f"hid:eq:{held['hid']}")["items"][0]
    assert row["review"] == marks
    assert lab.get(held)["host_item_hid"] is None
    # A context given a host by any way holds no serial number from then on.
    given = lab.patch(held, host_item_hid=switch["hid"])
    assert (given["serial_number"], given["host_item_hid"]) == (None, switch["hid"])
    event = lab.make.audit(record_hid=held["hid"])[0]
    assert {"field": "serial_number", "old": "EXN7K0009", "new": None} in event["changes"]


def test_a_file_of_contexts_of_one_chassis_finds_them_by_name_and_hosts_them(
    lab: Lab, files: Files
) -> None:
    make = lab.make
    chassis = _chassis(lab)
    existing = lab.vdc("site2-n7k-01-vdc2", host_item_hid=chassis["hid"])
    text = (
        "vendor,pid,name,serial_number\n"
        f"Example Virtual,VDC,site2-n7k-01-vdc2,{CHASSIS}\n"
        f"Example Virtual,VDC,site2-n7k-01-vdc3,{CHASSIS}\n"
        f"Example Virtual,VDC,site2-n7k-01-vdc4,{CHASSIS}\n"
        f"Cisco,N7K-C7010,site2-n7k-02,{CHASSIS}\n"
    )
    preview = files.preview("items", text)
    assert preview["job"]["rejected"] == 0, preview["rows"]
    outcomes = [row["outcome"] for row in preview["rows"]]
    assert outcomes == ["unchanged", "create", "create", "unchanged"]
    assert preview["rows"][0]["record_hid"] == existing["hid"]
    assert preview["rows"][3]["record_hid"] == chassis["hid"]
    files.apply(preview)
    for name in ("site2-n7k-01-vdc3", "site2-n7k-01-vdc4"):
        made = _by_name(make, name)
        assert (made["host_item_hid"], made["serial_number"]) == (chassis["hid"], None)
    assert make.get(f"/items/{existing['hid']}")["serial_number"] is None


def test_a_context_reported_before_its_switch_is_joined_by_the_next_report(
    lab: Lab, files: Files
) -> None:
    make = lab.make
    text = "vendor,pid,name,serial_number\nExample Virtual,VDC,site2-n7k-03-vdc2,EXN7K0003\n"
    job = files.load("items", text)
    assert counts(job)[0] == 1
    early = _by_name(make, "site2-n7k-03-vdc2")
    assert (early["serial_number"], early["review"][0]["reason"]) == ("EXN7K0003", "no_host")
    switch = make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number="EXN7K0003", name="site2-n7k-03"
    )
    preview = files.preview("items", text)
    row = preview["rows"][0]
    assert row["outcome"] == "update"
    changed = {change["field"]: (change["old"], change["new"]) for change in row["changes"]}
    assert changed["serial_number"] == ("EXN7K0003", None)
    assert changed["host"][1] is not None
    files.apply(preview)
    now = make.get(f"/items/{early['hid']}")
    assert (now["host_item_hid"], now["serial_number"], now["review"]) == (switch["hid"], None, [])
