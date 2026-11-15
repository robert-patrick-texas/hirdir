"""The records of 0.6.0 in files: each is exported, loaded into an empty inventory and
loaded again without a change."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Contract
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
        "from_agreement": "24x7",
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
    make.entry(base["cisco"], "C9300-NM-8X")
    requests = "reference,requested_on,status,notes\nRITM0012345,2026-08-17,ordered,Switches\n"
    assert counts(files.load("purchase_requests", requests)) == (1, 0, 0, 0)
    lines = (
        "request,line,vendor,pid,quantity,destination_site,expected_on\n"
        "RITM0012345,1,Cisco,C9300-48P,2,Americas > Site-3,2026-12-01\n"
        "RITM0012345,,Cisco,C9300-NM-8X,1,,\n"
    )
    preview = files.preview("purchase_lines", lines)
    assert [row["notes"] for row in preview["rows"]] == [[], []]
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
    # A row that names a line and no model is of the line's model; one of another model
    # is rejected, and says the line's.
    other = (
        "vendor,pid,serial_number,lifecycle_state,purchase_line\n"
        "Cisco,C9300-48P,FCW-201,Delivered,RITM0012345/2\n"
    )
    rejected = files.preview("items", other)
    assert counts(rejected["job"]) == (0, 0, 0, 1)
    (reason,) = rejected["rows"][0]["reasons"]
    assert "C9300-NM-8X" in reason["message"]
    bare = "serial_number,lifecycle_state,purchase_line\nNM-201,Delivered,RITM0012345/2\n"
    assert counts(files.load("items", bare)) == (1, 0, 0, 0)
    (module,) = make.get("/items", filter="serial_number:eq:NM-201")["items"]
    assert (module["catalog"]["pid"], module["purchase_line_mismatch"]) == ("C9300-NM-8X", False)
    assert counts(files.load("items", bare)) == (0, 0, 1, 0)
    exported = table(
        files.export(
            "items",
            filter="serial_number:eq:NM-201",
            columns=["serial_number", "purchase_line_mismatch"],
        )
    )
    assert exported[0]["purchase_line_mismatch"] == "false"
    lines_now = table(files.export("purchase_lines", columns=["line", "mismatched_items"]))
    assert [row["mismatched_items"] for row in lines_now] == ["0", "0"]


def test_a_file_of_lines_matches_each_part_number_and_makes_no_catalog_entry(
    files: Files, make: Maker, base: dict
) -> None:
    cisco = base["cisco"]
    make.entry(cisco, "PWR-C1-715WAC-P")
    make.entry(cisco, "SFP-10G-SR")
    make.entry(make.vendor("Example Optics"), "SFP-10G-SR=")
    entries = make.get("/catalog-entries")["total"]
    vendors = make.get("/vendors")["total"]
    assert counts(files.load("purchase_requests", "reference\nRITM0012345\n")) == (1, 0, 0, 0)
    lines = (
        "request,line,vendor,part_number,description,quantity\n"
        "RITM0012345,1,,PWR-C1-715WAC-P=,Spare power supply,2\n"
        "RITM0012345,2,, sfp-10g-sr ,10G optic,4\n"
        "RITM0012345,3,Cisco,SFP-10G-SR=,10G optic,4\n"
        'RITM0012345,4,,HLT-100,"Hook-and-loop tape, 100",20\n'
        "RITM0012345,5,Nobody Inc,PWR-X,Power supply,1\n"
        "RITM0012345,6,Cisco,C9300-24P,Switch,1\n"
    )
    preview = files.preview("purchase_lines", lines)
    assert counts(preview["job"]) == (6, 0, 0, 0)
    notes = [row["notes"] for row in preview["rows"]]
    assert notes[0] == notes[2] == []
    assert notes[1] == [
        "the part number sfp-10g-sr matches 2 models, Cisco SFP-10G-SR, Example Optics "
        "SFP-10G-SR=: the line is not tracked"
    ]
    assert notes[3] == ["the part number HLT-100 matches no model: the line is not tracked"]
    assert notes[4] == [
        "there is no vendor Nobody Inc, so the part number PWR-X matches no model: the line is "
        "not tracked"
    ]
    assert notes[5] == [
        "the part number C9300-24P matches no model of Cisco: the line is not tracked"
    ]
    files.apply(preview)
    listed = {line["line"]: line for line in make.get("/purchase-lines")["items"]}
    assert listed[1]["catalog"]["pid"] == "PWR-C1-715WAC-P"
    assert listed[1]["part_number"] == "PWR-C1-715WAC-P="
    assert (listed[2]["tracked"], listed[2]["part_number"]) == (False, "sfp-10g-sr")
    assert (listed[3]["catalog"]["vendor"], listed[3]["catalog"]["pid"]) == ("Cisco", "SFP-10G-SR")
    assert [listed[number]["tracked"] for number in (4, 5, 6)] == [False, False, False]
    assert listed[4]["description"] == "Hook-and-loop tape, 100"
    # Nothing was made of a line: no vendor, no catalog entry.
    assert make.get("/catalog-entries")["total"] == entries
    assert make.get("/vendors")["total"] == vendors
    # An export says what is tracked, and loads back as it is.
    columns = ["request", "line", "vendor", "pid", "part_number", "tracked"]
    exported = table(files.export("purchase_lines", sort=["line"], columns=columns))
    assert [row["tracked"] for row in exported] == [
        "true",
        "false",
        "true",
        "false",
        "false",
        "false",
    ]
    assert (exported[0]["pid"], exported[0]["part_number"]) == (
        "PWR-C1-715WAC-P",
        "PWR-C1-715WAC-P=",
    )
    assert counts(files.load("purchase_lines", files.export("purchase_lines"))) == (0, 0, 6, 0)
    assert counts(
        files.load("purchase_lines", files.export("purchase_lines", columns=columns))
    ) == (
        0,
        0,
        6,
        0,
    )

    # A line matched by hand keeps its model when the file is loaded again.
    tape = listed[4]
    tape_model = make.entry(make.vendor("Example Supplies"), "HLT-100-ROLL")
    make.patch(
        f"/purchase-lines/{tape['hid']}",
        {"row_version": tape["row_version"], "catalog_entry_hid": tape_model["hid"]},
    )
    again = files.preview("purchase_lines", lines)
    assert counts(again["job"])[3] == 0
    assert again["rows"][3]["outcome"] == "unchanged"
    assert again["rows"][3]["notes"] == [
        "the part number HLT-100 matches no model: the line keeps its model, "
        "Example Supplies HLT-100-ROLL"
    ]
    # A row that would give a line on which items have arrived another model is
    # rejected: that is corrected by hand, where what becomes of the items is said.
    power = make.get("/purchase-lines", filter="line:eq:1")["items"][0]
    make.post(
        f"/purchase-lines/{power['hid']}/receive",
        {"row_version": power["row_version"], "items": [{"serial_number": "LIT-1"}]},
    )
    other = make.entry(cisco, "PWR-C1-1100WAC-P")
    changed = files.preview(
        "purchase_lines",
        f"request,line,vendor,pid\nRITM0012345,1,Cisco,{other['pid']}\n",
    )
    assert counts(changed["job"]) == (0, 0, 0, 1)
    (reason,) = changed["rows"][0]["reasons"]
    assert reason["field"] == "pid"
    assert "correct it by hand" in reason["message"]


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


def test_what_a_file_holds_of_a_term_goes_back_as_it_came(
    files: Files, make: Maker, base: dict, db: Session
) -> None:
    # The status of a renewal that is late, on a contract and on an agreement.
    agreements = "name,vendor,status\nCisco Enterprise Agreement,Cisco,renewal_pending\n"
    assert counts(files.load("agreements", agreements)) == (1, 0, 0, 0)
    assert counts(files.load("agreements", files.export("agreements"))) == (0, 0, 1, 0)
    held = (
        "number,vendor,status,starts_on,ends_on,next_number,next_starts_on,next_ends_on\n"
        "CON-1,Cisco,renewal_pending,2025-01-01,2026-01-31,,,\n"
        "CON-2,Cisco,,2025-01-01,2098-12-31,CON-2-R,2099-01-01,2099-12-31\n"
    )
    assert counts(files.load("contracts", held)) == (2, 0, 0, 0)
    assert counts(files.load("contracts", files.export("contracts"))) == (0, 0, 2, 0)
    # A term that has begun and is not written down yet: the file holds the record as
    # it is stored, the old term in its own columns, and loading it back changes nothing.
    today = date.fromisoformat(make.get("/reports/coverage")["as_of"])
    stored = db.scalars(select(Contract).where(Contract.number == "CON-2")).one()
    stored.starts_on, stored.ends_on = today - timedelta(days=400), today - timedelta(days=3)
    stored.next_starts_on = today - timedelta(days=2)
    stored.next_ends_on = today + timedelta(days=362)
    db.commit()
    assert make.get("/contracts", filter="number:eq:CON-2-R")["total"] == 1
    for options in ({}, {"own_values": True}, {"include_sources": True}):
        exported = files.export("contracts", **options)
        row = {one["number"]: one for one in table(exported)}["CON-2"]
        assert (row["starts_on"], row["ends_on"], row["next_number"], row["next_starts_on"]) == (
            (today - timedelta(days=400)).isoformat(),
            (today - timedelta(days=3)).isoformat(),
            "CON-2-R",
            (today - timedelta(days=2)).isoformat(),
        )
        assert counts(files.load("contracts", exported)) == (0, 0, 2, 0)
    (term,) = make.get(f"/contracts/{stored.hid}/terms")
    assert (term["number"], term["ends_on"]) == ("CON-2", (today - timedelta(days=3)).isoformat())
    # A next number is held to what a number is.
    bad = "number,vendor,next_number,next_starts_on\nCON-3,Cisco,a;b,2099-01-01\n"
    assert "next_number" in errors_of(files.preview("contracts", bad))
    # A coverage under a retired contract goes back as it came, and is not changed.
    assert counts(files.load("contract_coverage", "contract,item\nCON-1,SW-001\n")) == (1, 0, 0, 0)
    first = make.get("/contracts", filter="number:eq:CON-1")["items"][0]
    make.post(f"/contracts/{first['hid']}/retire", {"row_version": first["row_version"]}, 200)
    exported = files.export("contract_coverage")
    assert [row["contract"] for row in table(exported)] == ["CON-1"]
    assert counts(files.load("contract_coverage", exported)) == (0, 0, 1, 0)
    ended = files.preview("contract_coverage", "contract,item,ends_on\nCON-1,SW-001,2026-01-01\n")
    assert "contract" in errors_of(ended)


def test_a_file_gives_what_arrived_as_a_count_its_serial_number(
    files: Files, make: Maker, base: dict
) -> None:
    request = make.post(
        "/purchase-requests",
        {
            "reference": "RITM0012345",
            "lines": [{"catalog_entry_hid": base["entry"]["hid"], "quantity": 4}],
        },
    )
    (line,) = request["lines"]
    now = make.get(f"/purchase-lines/{line['hid']}")
    make.post(
        f"/purchase-lines/{line['hid']}/receive", {"row_version": now["row_version"], "quantity": 4}
    )
    before = make.get("/items")["total"]
    # Each names the item as its line named it, and gives it what it is known by.
    for rows in (
        "name,serial_number\nRITM0012345/1-001,FCW-1\n",
        "vendor,pid,name,serial_number\nCisco,C9300-48P,RITM0012345/1-002,FCW-2\n",
        "name,asset_tag\nRITM0012345/1-003,TAG-3\n",
        "name,serial_number,purchase_line\nRITM0012345/1-004,FCW-4,RITM0012345/1\n",
    ):
        assert counts(files.load("items", rows)) == (0, 1, 0, 0), rows
        # And the same file, loaded again, finds the same item.
        assert counts(files.load("items", rows)) == (0, 0, 1, 0), rows
    assert make.get("/items")["total"] == before
    arrived = make.get("/items", filter="purchase_line_hid:empty:false", sort="name")["items"]
    assert [(item["serial_number"], item["asset_tag"]) for item in arrived] == [
        ("FCW-1", None),
        ("FCW-2", None),
        (None, "TAG-3"),
        ("FCW-4", None),
    ]
    assert make.get(f"/purchase-lines/{line['hid']}")["received_quantity"] == 4
    # A name that no waiting item has is a new item, as it always was.
    other = files.preview("items", "name,asset_tag\nNot on a line,TAG-9\n")
    assert counts(other["job"]) == (1, 0, 0, 0)
    # Two contracts of two vendors with one number are two contracts in a file too.
    make.vendor("Juniper")
    for vendor in ("Cisco", "Juniper"):
        files.load("contracts", f"number,vendor\nSAME-1,{vendor}\n")
        files.load("contract_coverage", f"contract,vendor,item\nSAME-1,{vendor},SW-001\n")
    counted = table(files.export("items", columns=["serial_number", "contracts", "contract_count"]))
    row = {one["serial_number"]: one for one in counted}["SW-001"]
    assert (row["contracts"], row["contract_count"]) == ("SAME-1", "2")
