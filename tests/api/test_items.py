"""Items through the API: identity, inheritance, the lifecycle, history and stale edits."""

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors

BLANK_ON_A_NEW_ITEM = (
    "mac_address",
    "asset_tag",
    "name",
    "hostname",
    "fqdn",
    "description",
    "comments",
    "lifecycle_state",
    "disposition",
    "expected_online",
    "state_reason",
    "state_changed_at",
    "procured_on",
    "delivered_on",
    "in_service_on",
    "warranty_start",
    "warranty_end",
    "est_value",
    "support_weight",
    "annual_support_cost",
    "end_of_sale",
    "end_of_sw_support",
    "end_of_hw_support",
    "ldos",
)


@pytest.fixture
def entry(make: Maker) -> dict:
    return make.entry(make.vendor(), est_value="18000", support_weight="1", ldos="2034-04-30")


def test_item_needs_only_what_identifies_it(make: Maker, entry: dict) -> None:
    owner = make.owner()
    item = make.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW0000X001", owner_hid=owner["hid"]
    )
    assert all(item[field] is None for field in BLANK_ON_A_NEW_ITEM)
    assert (item["quantity"], item["record_status"], item["tags"]) == (1, "active", [])
    assert item["owner"] == {
        "hid": owner["hid"],
        "label": "Network Engineering",
        "is_external": False,
    }
    assert make.item(asset_tag="AT-000123")["catalog"] is None
    assert make.item(hostname="site2-tester-01")["name"] is None
    for body in ({}, {"serial_number": "FCW0000X009"}, {"catalog_entry_hid": entry["hid"]}):
        assert "serial_number" in errors(make.post("/items", body, 422))


def test_item_inherits_from_the_catalog_and_says_so(make: Maker, entry: dict) -> None:
    plain = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X001")
    assert plain["est_value"] is None
    assert plain["effective"]["est_value"] == {
        "value": "18000.00",
        "source": "catalog",
        "source_hid": entry["hid"],
    }
    assert plain["effective"]["end_of_sale"] == {
        "value": None,
        "source": "none",
        "source_hid": None,
    }

    own = make.patch(f"/items/{plain['hid']}", {"row_version": 1, "est_value": "21500.5"})
    assert own["est_value"] == "21500.50"
    assert own["effective"]["est_value"] == {
        "value": "21500.50",
        "source": "own",
        "source_hid": plain["hid"],
    }
    assert own["effective"]["ldos"]["source"] == "catalog"

    back = make.patch(f"/items/{plain['hid']}", {"row_version": 2, "est_value": None})
    assert back["effective"]["est_value"]["source"] == "catalog"


def test_changing_the_catalog_reaches_items_without_touching_them(make: Maker, entry: dict) -> None:
    items = [
        make.item(catalog_entry_hid=entry["hid"], serial_number=f"FCW0000X00{n}") for n in (1, 2)
    ]
    make.patch(f"/catalog-entries/{entry['hid']}", {"row_version": 1, "ldos": "2035-06-30"})
    for item in items:
        now = make.get(f"/items/{item['hid']}")
        assert now["effective"]["ldos"]["value"] == "2035-06-30"
        assert (now["row_version"], now["updated_at"]) == (item["row_version"], item["updated_at"])
    assert make.audit(record_type="item", action="update") == []


def test_serial_number_and_asset_tag_are_unique_and_mac_address_is_not(
    make: Maker, entry: dict
) -> None:
    other = make.entry(make.vendor("Juniper"), "EX4400-48P")
    first = make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW0000X001",
        asset_tag="AT-000123",
        mac_address="00:00:5E:00:53:01",
    )
    twin = make.post(
        "/items", {"catalog_entry_hid": entry["hid"], "serial_number": " fcw0000x001 "}, 409
    )
    assert first["hid"] in twin["detail"]
    # The same serial number on another model is another item.
    make.item(catalog_entry_hid=other["hid"], serial_number="FCW0000X001")
    assert make.post("/items", {"asset_tag": "at-000123"}, 409)["title"] == "Conflict"
    shared = make.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW0000X002", mac_address="0000.5e00.5301"
    )
    assert shared["mac_address"] == first["mac_address"] == "00005e005301"
    # Changing an item into a twin of another is refused as well.
    moved = make.patch(
        f"/items/{shared['hid']}", {"row_version": 1, "serial_number": "FCW0000X001"}, 409
    )
    assert first["hid"] in moved["detail"]
    for mac in ("00:00:5E:00:53", "zz:00:5e:00:53:01", "00005e0053010"):
        assert "mac_address" in errors(make.post("/items", {"name": "x", "mac_address": mac}, 422))


def test_stale_edit_is_refused_and_nothing_is_applied(make: Maker) -> None:
    item = make.item(name="site2-sw-access-01")
    make.patch(f"/items/{item['hid']}", {"row_version": 1, "comments": "first"})
    stale = make.patch(f"/items/{item['hid']}", {"row_version": 1, "comments": "second"}, 409)
    assert stale["title"] == "Stale version"
    assert "version 2" in stale["detail"]
    assert make.get(f"/items/{item['hid']}")["comments"] == "first"
    assert errors(make.patch(f"/items/{item['hid']}", {"comments": "third"}, 422)) == {
        "row_version": "Field required"
    }


def test_item_refuses_what_it_cannot_hold(make: Maker, entry: dict) -> None:
    for field, value in (
        ("quantity", 0),
        ("owner_hid", "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"),
        ("catalog_entry_hid", "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"),
        ("lifecycle_state", "Lost"),
        ("disposition", "Spare"),
        ("expected_online", True),
        ("support_weight", "-0.5"),
        ("warranty_end", "soon"),
        ("tags", ["no-such-tag"]),
        ("record_status", "retired"),
    ):
        problem = make.post("/items", {"name": "site2-sw-access-01", field: value}, 422)
        assert field in errors(problem), (field, problem)
    dates = {"name": "x", "warranty_start": "2027-01-01", "warranty_end": "2026-01-01"}
    assert "warranty_end" in errors(make.post("/items", dates, 422))
    assert make.get("/items")["total"] == 0


def test_tags_on_an_item_are_set_as_a_whole_and_audited(make: Maker) -> None:
    make.tag("refresh-2030")
    make.tag("Core")
    item = make.item(name="site2-sw-core-01", tags=["refresh-2030"])
    assert item["tags"] == ["refresh-2030"]
    both = make.patch(f"/items/{item['hid']}", {"row_version": 1, "tags": ["CORE", "refresh-2030"]})
    assert (both["tags"], both["row_version"]) == (["Core", "refresh-2030"], 2)
    event = make.audit(record_type="item", action="update")[0]
    assert event["changes"] == [
        {"field": "tags", "old": ["refresh-2030"], "new": ["Core", "refresh-2030"]}
    ]
    none = make.patch(f"/items/{item['hid']}", {"row_version": 2, "tags": []})
    assert none["tags"] == []


def test_new_item_takes_the_standing_its_state_has_on_entry(make: Maker) -> None:
    def standing(**fields: object) -> tuple:
        item = make.item(name=f"item-{len(fields)}-{sorted(fields.items())}", **fields)
        return item["lifecycle_state"], item["disposition"], item["expected_online"]

    assert standing(lifecycle_state="purchased") == ("Purchased", None, False)
    assert standing(lifecycle_state="Assigned") == ("Assigned", "Staging", False)
    assert standing(lifecycle_state="PROD") == ("Prod", "Production", True)
    assert standing(lifecycle_state="Prod", disposition="spare", expected_online=False) == (
        "Prod",
        "Spare",
        False,
    )
    refused = make.post(
        "/items", {"name": "x", "lifecycle_state": "Prod", "disposition": "Excess"}, 422
    )
    assert errors(refused) == {
        "disposition": "an item in Prod is one of Production, Spare, not Excess"
    }
    offline = {"name": "x", "lifecycle_state": "Prod", "expected_online": False}
    assert errors(make.post("/items", offline, 422)) == {
        "expected_online": "a Production item in Prod is expected online"
    }


def test_moves_follow_the_rules_and_each_is_in_the_history(make: Maker) -> None:
    item = make.item(name="site2-sw-access-01", lifecycle_state="Delivered")
    item = make.move(item, "Assigned", reason="received")
    assert (item["disposition"], item["expected_online"]) == ("Staging", False)
    item = make.move(item, "Test", reason="staged")
    assert (item["disposition"], item["expected_online"]) == ("Staging", True)
    item = make.move(item, "Prod", reason="deployed")
    assert (item["disposition"], item["expected_online"]) == ("Production", True)
    assert item["state_reason"] == "deployed"
    assert item["state_changed_at"] is not None

    skipped = make.move(item, "Released", expect=422)
    assert "may move to Down, Pending-Removal" in errors(skipped)["to"]
    assert "to" in errors(make.move(item, "Prod", expect=422))
    assert "to" in errors(make.move(item, "Nowhere", expect=422))
    assert "reason" in errors(make.move(item, "Down", expect=422, reason="boredom"))
    assert make.move({**item, "row_version": 1}, "Down", expect=409)["title"] == "Stale version"

    history = make.get(f"/items/{item['hid']}/history")
    assert history["total"] == 4
    moves = [event for event in history["items"] if event["action"] == "transition"]
    assert [event["actor_name"] for event in moves] == ["ivy", "ivy", "ivy"]

    def of(event: dict, field: str) -> tuple:
        return next((c["old"], c["new"]) for c in event["changes"] if c["field"] == field)

    assert [of(event, "lifecycle_state") for event in moves] == [
        ("Test", "Prod"),
        ("Assigned", "Test"),
        ("Delivered", "Assigned"),
    ]
    assert [of(event, "state_reason")[1] for event in moves] == ["deployed", "staged", "received"]


def test_the_same_reason_twice_is_recorded_twice(make: Maker) -> None:
    item = make.item(name="site2-sw-access-01", lifecycle_state="Test")
    item = make.move(item, "Down", reason="maintenance")
    item = make.move(item, "Test", reason="maintenance")
    reasons = [
        change["new"]
        for event in make.get(f"/items/{item['hid']}/history")["items"]
        for change in event["changes"]
        if event["action"] == "transition" and change["field"] == "state_reason"
    ]
    assert reasons == ["maintenance", "maintenance"]


def test_disposition_is_kept_where_the_new_state_allows_it(make: Maker) -> None:
    item = make.item(name="site2-sw-spare-01", lifecycle_state="Prod", disposition="Spare")
    item = make.move(item, "Down")
    assert (item["disposition"], item["expected_online"]) == ("Spare", False)
    kept = make.patch(
        f"/items/{item['hid']}", {"row_version": item["row_version"], "disposition": None}, 422
    )
    assert "disposition" in errors(kept)
    item = make.move(item, "Pending-Removal", disposition="Excess")
    assert item["disposition"] == "Excess"
    item = make.move(item, "Assigned", reason="found")
    assert (item["disposition"], item["expected_online"]) == ("Excess", False)
    item = make.move(item, "Test")
    assert (item["disposition"], item["expected_online"]) == ("Staging", True)
    item = make.move(item, "Prod", disposition="Spare", expected_online=False)
    assert (item["disposition"], item["expected_online"]) == ("Spare", False)


def test_disposition_and_intent_are_checked_on_an_edit(make: Maker) -> None:
    item = make.item(name="site2-sw-access-01", lifecycle_state="Prod")
    path = f"/items/{item['hid']}"
    spare = make.patch(path, {"row_version": 1, "disposition": "Spare", "expected_online": False})
    assert (spare["disposition"], spare["expected_online"]) == ("Spare", False)
    excess = make.patch(
        path, {"row_version": 2, "disposition": "Excess", "expected_online": True}, 422
    )
    assert "disposition" in errors(excess)
    production = make.patch(path, {"row_version": 2, "disposition": "Production"}, 422)
    assert errors(production) == {"expected_online": "a Production item in Prod is expected online"}
    by_patch = make.patch(path, {"row_version": 2, "lifecycle_state": "Down"}, 422)
    assert "lifecycle_state" in errors(by_patch)
    stateless = make.item(name="site2-tester-01")
    refused = make.patch(
        f"/items/{stateless['hid']}", {"row_version": 1, "disposition": "Spare"}, 422
    )
    assert errors(refused) == {"disposition": "give the item a lifecycle state first"}


def test_only_an_admin_may_force_a_move_and_must_say_why(make: Maker, client, admin: dict) -> None:
    item = make.item(name="site2-sw-access-01", lifecycle_state="Delivered")
    assert make.move(item, "Prod", expect=403, force=True, reason="correction")["status"] == 403
    as_admin = Maker(client, admin)
    assert "reason" in errors(as_admin.move(item, "Prod", expect=422, force=True))
    forced = as_admin.move(item, "Prod", force=True, reason="correction")
    assert (forced["lifecycle_state"], forced["disposition"]) == ("Prod", "Production")
    event = as_admin.get(f"/items/{item['hid']}/history")["items"][0]
    assert {"field": "forced", "old": None, "new": True} in event["changes"]
    # A move the rules allow is not marked as forced, even when force is asked for.
    allowed = as_admin.move(forced, "Down", force=True)
    event = as_admin.get(f"/items/{item['hid']}/history")["items"][0]
    assert allowed["lifecycle_state"] == "Down"
    assert all(change["field"] != "forced" for change in event["changes"])


def test_item_with_no_state_may_be_given_any(make: Maker) -> None:
    item = make.item(name="site2-tester-01")
    item = make.move(item, "Prod", reason="correction")
    assert (item["lifecycle_state"], item["disposition"]) == ("Prod", "Production")


def test_retired_draft_and_archived_items_are_left_out_unless_asked_for(make: Maker) -> None:
    make.item(name="active")
    draft = make.item(name="draft", record_status="draft")
    retired = make.item(name="retired")
    make.post(f"/items/{retired['hid']}/retire", {"row_version": 1}, 200)
    make.item(name="archived", lifecycle_state="Archived")

    assert make.found() == ["active"]
    assert make.found(include_drafts=True) == ["active", "draft"]
    assert make.found(include_archived=True) == ["active", "archived", "retired"]
    assert len(make.found(include_archived=True, include_drafts=True)) == 4
    # Each is still reachable by its HID, with its history.
    assert make.get(f"/items/{retired['hid']}")["record_status"] == "retired"
    actions = [e["action"] for e in make.get(f"/items/{retired['hid']}/history")["items"]]
    assert actions == ["retire", "create"]
    active = make.patch(f"/items/{draft['hid']}", {"row_version": 1, "record_status": "active"})
    assert active["record_status"] == "active"


def test_history_of_an_unknown_item_is_not_found(make: Maker) -> None:
    make.get("/items/0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22/history", 404)
    make.get("/items/0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22", 404)


def test_the_history_of_an_item_is_sorted_by_its_events(
    make: Maker, client: TestClient, admin: dict
) -> None:
    item = make.item(name="site2-sw-access-01", lifecycle_state="Delivered")
    item = make.move(item, "Assigned", reason="received")
    as_admin = Maker(client, admin)
    as_admin.patch(f"/items/{item['hid']}", {"row_version": item["row_version"], "comments": "x"})
    path = f"/items/{item['hid']}/history"

    def history(**params) -> list[tuple[str, str]]:
        return [
            (event["action"], event["actor_name"]) for event in make.get(path, **params)["items"]
        ]

    made, moved, changed = ("create", "ivy"), ("transition", "ivy"), ("update", "ada")
    assert history() == [changed, moved, made]
    assert history(sort="at") == [made, moved, changed]
    assert history(sort="action") == [made, moved, changed]
    assert history(sort="-action", limit=2) == [changed, moved]
    # Those of one person stay newest first.
    assert history(sort="actor_name") == [changed, moved, made]
    assert history(sort="-actor_name") == [moved, made, changed]
    # An event's changes stay together: the events are what is sorted.
    newest = make.get(path, sort="-action")["items"][0]
    assert [change["field"] for change in newest["changes"]] == ["comments"]
    assert "via is not a field" in errors(make.get(path, 422, sort="via"))["sort"]
