"""A refusal says where to go (P-207): a duplicate names the record that has the value,
and a filter or a sort that names a field its list does not have names the nearest."""

from typing import Any

from tests.api.inventory import Maker, errors


def existing(problem: dict[str, Any]) -> dict[str, Any]:
    """Return the record a refusal of a duplicate names."""
    assert problem["status"] == 409, problem
    assert problem["title"] == "Conflict", problem
    return problem["existing"]


def test_a_duplicate_serial_number_or_asset_tag_names_the_item_that_has_it(make: Maker) -> None:
    entry = make.entry(make.vendor("Example Networks"), "EXN-48P")
    first = make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="EXSN0001",
        asset_tag="EX-AT-0001",
        hostname="ex-sw-01.example.net",
    )
    twin = make.post(
        "/items", {"catalog_entry_hid": entry["hid"], "serial_number": "exsn0001"}, 409
    )
    assert existing(twin) == {
        "hid": first["hid"],
        "record_type": "item",
        "label": "ex-sw-01.example.net",
    }
    # The sentence keeps the HID, for the command line and for files.
    assert first["hid"] in twin["detail"]
    tagged = make.post("/items", {"asset_tag": "ex-at-0001"}, 409)
    assert existing(tagged)["hid"] == first["hid"]
    # A change into a twin names it too.
    other = make.item(name="ex-spare")
    moved = make.patch(f"/items/{other['hid']}", {"row_version": 1, "asset_tag": "EX-AT-0001"}, 409)
    assert existing(moved)["hid"] == first["hid"]


def test_a_duplicate_pid_or_vendor_name_names_the_record_that_has_it(make: Maker) -> None:
    vendor = make.vendor("Example Optics", aliases=["ExOpt"])
    entry = make.entry(vendor, "EXO-SFP-10G")
    twin = make.post("/catalog-entries", {"vendor_hid": vendor["hid"], "pid": "exo-sfp-10g"}, 409)
    assert existing(twin) == {
        "hid": entry["hid"],
        "record_type": "catalog_entry",
        "label": "Example Optics EXO-SFP-10G",
    }
    assert entry["hid"] in twin["detail"]
    named = make.post("/vendors", {"name": "exopt"}, 409)
    assert existing(named) == {
        "hid": vendor["hid"],
        "record_type": "vendor",
        "label": "Example Optics",
    }


def test_each_name_another_record_has_names_that_record(make: Maker) -> None:
    region = make.region("Example Region", code="EXR")
    vendor = make.vendor("Example Support")
    made = {
        "owner": make.owner("Example Owners"),
        "device_group": make.group("ex-stack-1"),
        "contact": make.contact("Example Person"),
        "tag": make.tag("ex-tag"),
        "network": make.network("ex-net"),
        "region": region,
        "site": make.site("Example Site", region),
        "operator": make.post("/operators", {"label": "Example Operations"}),
        "agreement": make.post(
            "/agreements", {"name": "Example Agreement", "vendor_hid": vendor["hid"]}
        ),
    }
    refused = [
        ("/owners", {"label": "example owners"}, "owner", "Example Owners"),
        ("/device-groups", {"name": "EX-STACK-1", "type": "stack"}, "device_group", "ex-stack-1"),
        (
            "/contacts",
            {"name": "Another", "email": "Example.Person@example.net"},
            "contact",
            "Example Person",
        ),
        ("/tags", {"label": "EX-TAG"}, "tag", "ex-tag"),
        ("/networks", {"label": "EX-NET", "kind": "vrf"}, "network", "ex-net"),
        ("/regions", {"name": "Example Other", "code": "exr"}, "region", "Example Region"),
        ("/sites", {"name": "example site", "region_hid": region["hid"]}, "site", "Example Site"),
        ("/operators", {"label": "example operations"}, "operator", "Example Operations"),
        (
            "/agreements",
            {"name": "EXAMPLE AGREEMENT", "vendor_hid": vendor["hid"]},
            "agreement",
            "Example Agreement",
        ),
    ]
    for path, body, kind, label in refused:
        problem = make.post(path, body, 409)
        assert existing(problem) == {
            "hid": made[kind]["hid"],
            "record_type": kind,
            "label": label,
        }, path


def test_a_refusal_of_anything_else_names_no_record(make: Maker) -> None:
    item = make.item(name="ex-once")
    stale = make.patch(f"/items/{item['hid']}", {"row_version": 9, "name": "ex-twice"}, 409)
    assert stale["title"] == "Stale version"
    assert "existing" not in stale
    invalid = make.post("/items", {"name": "x", "mac_address": "zz"}, 422)
    assert "existing" not in invalid


def test_a_second_replacement_names_no_record_that_has_a_value(make: Maker) -> None:
    # Nothing is had that another record has: the field says which replacement stands.
    old, new, other = (make.item(name=name) for name in ("ex-old", "ex-new", "ex-other"))

    def replace(item: dict[str, Any], by: dict[str, Any], expect: int = 201) -> dict[str, Any]:
        now = make.get(f"/items/{item['hid']}")
        body = {"row_version": now["row_version"], "reason": "rma", "new_item_hid": by["hid"]}
        return make.post(f"/items/{item['hid']}/replace", body, expect)

    replace(old, new)
    again = replace(old, other, 409)
    assert (again["detail"], "existing" in again) == ("this item has been replaced already", False)
    assert new["hid"] in errors(again)["new_item_hid"]
    taken = replace(other, new, 409)
    assert (taken["detail"], "existing" in taken) == (
        "this item took the place of another already",
        False,
    )
    assert old["hid"] in errors(taken)["new_item_hid"]


def test_a_filter_of_a_field_the_list_has_not_names_the_nearest(make: Maker) -> None:
    said = errors(make.get("/items", 422, filter="type:eq:switch"))["filter"]
    assert said.startswith("type is not a field this list can be filtered by")
    assert "catalog.type" in said
    # A near spelling, and nothing at all where nothing is near.
    said = errors(make.get("/items", 422, filter="hostnme:eq:x"))["filter"]
    assert "hostname" in said.partition(";")[2]
    said = errors(make.get("/items", 422, filter="zzqqxx:eq:x"))["filter"]
    assert said == "zzqqxx is not a field this list can be filtered by"
    # A sort is answered the same way, from the fields it is sorted by.
    said = errors(make.get("/items", 422, sort="type"))["sort"]
    assert "catalog.type" in said
    said = errors(make.get("/items", 422, sort="location"))["sort"]
    assert "location.name" in said
