"""A value of a list that names a record comes with the record's HID, so that the list
makes it a link (P-232): the model of an item that a coverage or a membership names, and
the vendor of the contract of a coverage."""

from typing import Any

from tests.api.inventory import Maker


def _covered(make: Maker) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    vendor = make.vendor("Cisco")
    entry = make.entry(vendor)
    item = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000N001")
    contract = make.post("/contracts", {"number": "CON-2026-0009", "vendor_hid": vendor["hid"]})
    make.post(f"/contracts/{contract['hid']}/coverage", {"items": [{"item_hid": item["hid"]}]})
    return entry, item, contract


def test_the_coverage_of_a_contract_names_the_model_of_each_item(make: Maker) -> None:
    entry, item, contract = _covered(make)
    (row,) = make.get(f"/contracts/{contract['hid']}/coverage")["items"]
    assert row["item"]["hid"] == item["hid"]
    assert (row["item"]["catalog_entry_hid"], row["item"]["pid"]) == (entry["hid"], "C9300-48P")


def test_the_members_of_a_group_name_the_model_of_each_item(make: Maker) -> None:
    entry = make.entry(make.vendor("Cisco"))
    switch, bare = (
        make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000N002"),
        make.item(hostname="site2-ap-01"),
    )
    group = make.group("site2-cluster", "cluster", [(switch, "member"), (bare, "member")])
    named = {one["item"]["hid"]: one["item"] for one in make.members(group)}
    assert named[switch["hid"]]["catalog_entry_hid"] == entry["hid"]
    assert (named[bare["hid"]]["catalog_entry_hid"], named[bare["hid"]]["pid"]) == (None, None)


def test_the_coverage_of_an_item_names_the_vendor_of_each_contract(make: Maker) -> None:
    entry, item, contract = _covered(make)
    (row,) = make.get("/contract-coverage", filter=f"item_hid:eq:{item['hid']}")["items"]
    assert row["contract"]["hid"] == contract["hid"]
    assert (row["contract"]["vendor_hid"], row["contract"]["vendor"]) == (
        entry["vendor"]["hid"],
        "Cisco",
    )
