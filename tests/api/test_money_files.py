"""The records of 0.6.0 in files: each is exported, loaded into an empty inventory and
loaded again without a change."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker
from tests.api.test_files import Files, changes, counts, table


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


@pytest.fixture
def base(make: Maker) -> dict[str, Any]:
    cisco = make.vendor("Cisco")
    make.vendor("Example Reseller")
    entry = make.entry(cisco, "C9300-48P")
    switches = make.switches(entry, "sw", 3, lifecycle_state="Prod")
    return {"cisco": cisco, "entry": entry, "switches": switches}


def test_agreements_contracts_and_coverage_load_from_files(
    files: Files, make: Maker, base: dict
) -> None:
    agreements = (
        "name,number,vendor,reseller,starts_on,ends_on,support_level,account_manager,support_url\n"
        "Cisco Enterprise Agreement,EA-1,Cisco,Example Reseller,2025-01-01,2099-12-31,24x7,"
        '"Jordan Reyes, +1 555 0142",https://support.example.com/ea\n'
    )
    assert counts(files.load("agreements", agreements)) == (1, 0, 0, 0)
    contracts = (
        "number,vendor,agreement,support_level,purchase_reference,starts_on,ends_on,annual_cost\n"
        "CON-1,Cisco,Cisco Enterprise Agreement,,RITM0001,,,61000\n"
        "CON-2,Cisco,Cisco Enterprise Agreement,8x5,RITM0002,,,\n"
        "CON-3,Cisco,,8x5,RITM0003,2026-01-01,2099-12-31,2400.00\n"
    )
    assert counts(files.load("contracts", contracts)) == (3, 0, 0, 0)
    assert counts(files.load("contracts", contracts)) == (0, 0, 3, 0)
    listed = {one["number"]: one for one in make.get("/contracts")["items"]}
    assert listed["CON-1"]["effective"]["support_level"] == {
        "value": "24x7",
        "source": "agreement",
        "source_hid": listed["CON-1"]["agreement_hid"],
    }
    assert listed["CON-2"]["effective"]["support_level"]["source"] == "own"
    assert (listed["CON-3"]["agreement"], listed["CON-1"]["annual_cost"]) == (None, "61000.00")

    # An export of the values in force, loaded back, makes no override of what a
    # contract has from its agreement.
    in_force = files.export("contracts", include_sources=True)
    rows = {row["number"]: row for row in table(in_force)}
    assert (rows["CON-1"]["support_level"], rows["CON-1"]["support_level_source"]) == (
        "24x7",
        "agreement",
    )
    assert (rows["CON-1"]["ends_on"], rows["CON-1"]["reseller"]) == (
        "2099-12-31",
        "Example Reseller",
    )
    assert counts(files.load("contracts", in_force)) == (0, 0, 3, 0)
    assert make.get("/contracts", filter="number:eq:CON-1")["items"][0]["support_level"] is None
    own = {row["number"]: row for row in table(files.export("contracts", own_values=True))}
    assert (own["CON-1"]["support_level"], own["CON-1"]["ends_on"]) == ("", "")
    # A row rolls a contract into an agreement, and `!clear` takes it out of one.
    moved = files.preview(
        "contracts", "number,agreement\nCON-3,Cisco Enterprise Agreement\nCON-2,!clear\n"
    )
    assert [changes(row).get("agreement") for row in moved["rows"]] == [
        (None, "Cisco Enterprise Agreement"),
        ("Cisco Enterprise Agreement", None),
    ]
    assert "agreement" in errors_of(
        files.preview("contracts", "number,vendor,agreement\nX-1,Cisco,No such\n")
    )

    coverage = (
        "contract,vendor,item,starts_on,ends_on\n"
        "CON-1,Cisco,SW-001,,\n"
        "CON-1,Cisco,SW-002,2025-01-01,2099-12-31\n"
        "CON-3,,sw-03,2026-06-01,\n"
    )
    assert counts(files.load("contract_coverage", coverage)) == (3, 0, 0, 0)
    assert counts(files.load("contract_coverage", coverage)) == (0, 0, 3, 0)
    exported = table(files.export("contract_coverage", sort=["item.name"]))
    # A date that is the contract's own is kept blank: the coverage follows the contract.
    assert [
        (row["contract"], row["item"], row["starts_on"], row["ends_on"]) for row in exported
    ] == [
        ("CON-1", "SW-001", "", ""),
        ("CON-1", "SW-002", "", ""),
        ("CON-3", "SW-003", "2026-06-01", ""),
    ]
    assert counts(files.load("contract_coverage", files.export("contract_coverage"))) == (
        0,
        0,
        3,
        0,
    )
    # A coverage is ended by a row, and an item's file says what covers it.
    ended = files.load("contract_coverage", "contract,item,ends_on\nCON-3,SW-003,2026-07-31\n")
    assert counts(ended) == (0, 1, 0, 0)
    items = {
        row["serial_number"]: row
        for row in table(
            files.export(
                "items", columns=["serial_number", "covered", "covered_until", "contracts"]
            )
        )
    }
    assert (items["SW-001"]["covered"], items["SW-001"]["contracts"]) == ("true", "CON-1")
    assert (items["SW-003"]["covered"], items["SW-003"]["covered_until"]) == ("false", "")
    refused = files.preview("contract_coverage", "contract,item\nCON-9,SW-001\nCON-1,nothing\n")
    assert counts(refused["job"]) == (0, 0, 0, 2)


def errors_of(preview: dict[str, Any]) -> set[str]:
    return {reason["field"] for row in preview["rows"] for reason in row["reasons"]}


def test_purchases_and_the_items_that_arrived_load_from_files(
    files: Files, make: Maker, base: dict
) -> None:
    make.site("Site-3", make.region("Americas"))
    requests = "reference,requested_on,status,notes\nRITM0012345,2026-08-17,ordered,Switches\n"
    assert counts(files.load("purchase_requests", requests)) == (1, 0, 0, 0)
    lines = (
        "request,line,vendor,pid,quantity,destination_site,expected_on\n"
        "RITM0012345,1,Cisco,C9300-48P,2,Americas > Site-3,2026-12-01\n"
        "RITM0012345,,Cisco,C9300-NM-8X,1,,\n"
    )
    preview = files.preview("purchase_lines", lines)
    assert (
        "creates the catalog entry Cisco C9300-NM-8X, to be reviewed" in preview["rows"][1]["notes"]
    )
    files.apply(preview)
    assert [line["name"] for line in make.get("/purchase-lines")["items"]] == [
        "RITM0012345/1",
        "RITM0012345/2",
    ]
    # The serial numbers of a delivery, as a file of items that name their line.
    arrived = (
        "vendor,pid,serial_number,lifecycle_state,purchase_line\n"
        "Cisco,C9300-48P,FCW-101,Delivered,RITM0012345/1\n"
        "Cisco,C9300-48P,FCW-102,Delivered,RITM0012345/1\n"
        "Cisco,C9300-48P,FCW-103,Delivered,RITM0012345/1\n"
    )
    preview = files.preview("items", arrived)
    assert counts(preview["job"]) == (2, 0, 0, 1)
    assert "purchase_line" in errors_of(preview)
    files.apply(preview, skip_rejected="true")
    first = make.get("/purchase-lines", filter="line:eq:1")["items"][0]
    assert (first["received_quantity"], first["pending_quantity"]) == (2, 0)
    exported = table(files.export("purchase_lines"))
    assert [(row["request"], row["line"], row["pid"]) for row in exported] == [
        ("RITM0012345", "1", "C9300-48P"),
        ("RITM0012345", "2", "C9300-NM-8X"),
    ]
    assert counts(files.load("purchase_lines", files.export("purchase_lines"))) == (
        0,
        0,
        2,
        0,
    )
    assert counts(files.load("purchase_requests", files.export("purchase_requests"))) == (
        0,
        0,
        1,
        0,
    )
    items = table(
        files.export("items", filter="purchase_line_hid:empty:false", sort=["serial_number"])
    )
    assert [row["purchase_line"] for row in items] == ["RITM0012345/1", "RITM0012345/1"]
    assert counts(files.load("items", files.export("items", own_values=True)))[3] == 0
    assert "purchase_line" in errors_of(
        files.preview("items", "name,purchase_line\nx,RITM0099999/1\n")
    )


def test_systems_registrations_capacity_and_replacements_load_from_files(
    files: Files, make: Maker, base: dict
) -> None:
    stack = make.stack("site2-sw-stack1", base["switches"][:2])
    systems = (
        "name,kind,url\n"
        "NetWatch,monitoring,https://netwatch.example.net\n"
        "Config Vault,config_backup,\n"
    )
    assert counts(files.load("external_systems", systems)) == (2, 0, 0, 0)
    registrations = (
        "system,item,group,external_id,status,confirmed_at\n"
        "NetWatch,,site2-sw-stack1,node-1,registered,2026-11-02T10:00:00\n"
        "Config Vault,SW-003,,,pending,\n"
    )
    assert counts(files.load("registrations", registrations)) == (2, 0, 0, 0)
    assert counts(files.load("registrations", registrations)) == (0, 0, 2, 0)
    assert make.get(f"/device-groups/{stack['hid']}")["registrations"][0]["confirmed_at"] == (
        "2026-11-02T15:00:00Z"
    )
    removed = files.load("registrations", "system,item,status\nConfig Vault,SW-003,removed\n")
    assert counts(removed) == (0, 1, 0, 0)
    assert counts(files.load("registrations", files.export("registrations"))) == (0, 0, 2, 0)
    both = files.preview("registrations", "system,item,group\nNetWatch,SW-003,site2-sw-stack1\n")
    assert counts(both["job"]) == (0, 0, 0, 1)

    capacity = (
        "side,category,name,quantity,units_each,annual_cost,vendor,record_status\n"
        "supply,staff,Network engineer,3,1.0,,,active\n"
        "supply,services,AI assistant,1,1,24000,Cisco,draft\n"
        "demand,,Site consolidation project,1,1.5,,,\n"
    )
    assert counts(files.load("capacity_lines", capacity)) == (3, 0, 0, 0)
    assert counts(files.load("capacity_lines", capacity)) == (0, 0, 3, 0)
    report = make.get("/reports/capacity")
    assert (report["active"]["supply"], report["with_drafts"]["supply"]) == ("3", "4")
    exported = files.export("capacity_lines", include_drafts=True)
    assert counts(files.load("capacity_lines", exported)) == (0, 0, 3, 0)
    assert {row["name"]: row["category"] for row in table(exported)}[
        "Site consolidation project"
    ] == "other_work"

    spare = make.item(catalog_entry_hid=base["entry"]["hid"], serial_number="SW-900")
    replaced = "old_item,new_item,reason,reference\nSW-001,SW-900,rma,RMA-1\n"
    assert counts(files.load("item_replacements", replaced)) == (1, 0, 0, 0)
    assert counts(files.load("item_replacements", replaced)) == (0, 0, 1, 0)
    # The new item took over the place of the old one in its stack.
    members = {
        one["item"]["serial_number"]: one for one in make.members(stack, include_past="true")
    }
    assert members["SW-001"]["left_on"] == members["SW-900"]["joined_on"]
    assert members["SW-001"]["left_on"] is not None
    assert make.get(f"/items/{spare['hid']}")["replaces"]["serial_number"] == "SW-001"
    assert counts(files.load("item_replacements", files.export("item_replacements"))) == (
        0,
        0,
        1,
        0,
    )
    renamed = files.load("item_replacements", "old_item,reason,reference\nSW-001,refresh,CHG-2\n")
    assert counts(renamed) == (0, 1, 0, 0)
    # An item is replaced once: a row that names another new item is rejected.
    other = files.preview("item_replacements", "old_item,new_item,reason\nSW-001,SW-003,rma\n")
    assert counts(other["job"]) == (0, 0, 0, 1)
    assert "new_item" in errors_of(other)
