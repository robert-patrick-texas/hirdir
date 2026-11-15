"""Bulk edit: one change to many items, previewed, then applied or refused whole."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors


@pytest.fixture
def switches(make: Maker) -> list[dict[str, Any]]:
    """Four switches in Prod, an owner to give them to, and two tags."""
    entry = make.entry(make.vendor(), est_value="18000.00")
    make.owner("Network Engineering")
    make.owner("Voice Services")
    make.tag("refresh-2030")
    make.tag("critical")
    return [
        make.item(
            catalog_entry_hid=entry["hid"],
            serial_number=f"FCW0000X00{number}",
            hostname=f"site2-sw-{number}",
            lifecycle_state="Prod",
            tags=["critical"] if number == 1 else [],
        )
        for number in range(1, 5)
    ]


def changes(row: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in row["changes"]}


def apply(make: Maker, preview: dict[str, Any], expect: int = 202, **params: str) -> dict[str, Any]:
    """Apply a bulk edit, and return its job once the worker has applied it."""
    return make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply", expect, **params)


def test_a_bulk_edit_shows_before_and_after_and_changes_nothing_until_applied(
    make: Maker, switches: list[dict]
) -> None:
    preview = make.post(
        "/items/bulk-update",
        {
            "filter": "hostname:prefix:site2-sw-",
            "set": {"owner": "Voice Services", "disposition": "Spare", "est_value": "19000"},
            "add_tags": ["refresh-2030"],
            "remove_tags": ["critical"],
        },
    )
    job = preview["job"]
    assert (job["source"], job["mode"], job["entity"], job["updated"]) == (
        "bulk",
        "update",
        "items",
        4,
    )
    first = preview["rows"][0]
    assert first["record_hid"] == switches[0]["hid"]
    assert changes(first) == {
        "owner": (None, "Voice Services"),
        "disposition": ("Production", "Spare"),
        "est_value": (None, "19000.00"),
        "tags": (["critical"], ["refresh-2030"]),
    }
    assert make.get(f"/items/{switches[0]['hid']}")["owner"] is None

    assert apply(make, preview)["status"] == "applied"
    after = make.get("/items", sort="hostname")["items"]
    assert {item["owner"]["label"] for item in after} == {"Voice Services"}
    assert [item["tags"] for item in after] == [["refresh-2030"]] * 4
    assert {item["effective"]["est_value"]["source"] for item in after} == {"own"}
    events = make.audit(record_type="item", action="update")
    assert len({event["request_id"] for event in events}) == 1
    assert {event["via"] for event in events} == {"api"}
    # Bulk edits are kept apart from the imports of files.
    assert make.get("/imports")["total"] == 0
    assert make.get("/imports", source="bulk")["total"] == 1


def test_the_second_of_two_overlapping_bulk_edits_leaves_the_rows_of_the_first_alone(
    client: TestClient, make: Maker, admin: dict[str, str], switches: list[dict]
) -> None:
    other = Maker(client, admin)
    mine = make.post(
        "/items/bulk-update",
        {"hids": [item["hid"] for item in switches[:3]], "set": {"comments": "mine"}},
    )
    theirs = other.post(
        "/items/bulk-update",
        {"hids": [item["hid"] for item in switches[1:]], "set": {"comments": "theirs"}},
    )
    assert apply(make, mine)["status"] == "applied"

    # The two items the first changed are left as the first made them, and are told as
    # stale; the third, which nobody changed, is changed.
    ended = apply(other, theirs)
    assert (ended["status"], ended["applied"], ended["stale"]) == ("applied", 1, 2)
    comments = [item["comments"] for item in make.get("/items", sort="hostname")["items"]]
    assert comments == ["mine", "mine", "mine", "theirs"]
    stale = make.get(f"/imports/{theirs['job']['hid']}/rows", applied_outcome="stale")["items"]
    assert [(row["row"], row["record_hid"]) for row in stale] == [
        (1, switches[1]["hid"]),
        (2, switches[2]["hid"]),
    ]
    assert all("changed since the preview" in row["applied_reasons"][0]["message"] for row in stale)
    # A preview may be applied by another than the one who made it.
    again = other.post(
        "/items/bulk-update", {"hids": [switches[3]["hid"]], "set": {"comments": "again"}}
    )
    applied = apply(make, again)
    assert (applied["created_by_name"], applied["applied_by_name"]) == ("ada", "ivy")


def test_a_bulk_edit_may_move_items_and_clear_a_field(make: Maker, switches: list[dict]) -> None:
    one = switches[0]
    make.patch(f"/items/{one['hid']}", {"row_version": 1, "est_value": "5.00"})
    preview = make.post(
        "/items/bulk-update",
        {
            "hids": [one["hid"], switches[1]["hid"]],
            "set": {"lifecycle_state": "Down", "state_reason": "maintenance", "est_value": None},
        },
    )
    assert changes(preview["rows"][0]) == {
        "lifecycle_state": ("Prod", "Down"),
        "expected_online": (True, False),
        "state_reason": (None, "maintenance"),
        "est_value": ("5.00", None),
    }
    apply(make, preview)
    moved = make.get(f"/items/{one['hid']}")
    assert (moved["lifecycle_state"], moved["effective"]["est_value"]["source"]) == (
        "Down",
        "catalog",
    )
    assert make.get(f"/items/{one['hid']}/history")["items"][0]["action"] == "transition"


def test_rows_the_rules_refuse_are_rejected_and_may_be_skipped(
    make: Maker, switches: list[dict]
) -> None:
    make.move(switches[0], "Down")
    preview = make.post(
        "/items/bulk-update",
        {"filter": "hostname:prefix:site2-sw-", "set": {"expected_online": True}},
    )
    assert (preview["job"]["rejected"], preview["job"]["unchanged"]) == (1, 3)
    refused = preview["rows"][0]
    assert refused["reasons"][0]["field"] == "expected_online"
    # A row that is refused still says which item it was about.
    assert (refused["record_hid"], refused["key"]) == (switches[0]["hid"], "site2-sw-1")
    assert "skip_rejected" in errors(apply(make, preview, expect=422))
    assert apply(make, preview, skip_rejected="true")["status"] == "applied"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"set": {"comments": "x"}}, "filter"),
        ({"all_rows": True}, "set"),
        ({"all_rows": True, "set": {"serial_number": "S"}}, "set.serial_number"),
        ({"all_rows": True, "set": {"hostname": "h"}}, "set.hostname"),
        ({"all_rows": True, "set": {"tags": ["critical"]}}, "set.tags"),
        ({"all_rows": True, "set": {"contract": "x"}}, "set.contract"),
        ({"all_rows": True, "set": {"model_name": "x"}}, "set.model_name"),
        ({"all_rows": True, "set": {"quantity": "many"}}, "set.quantity"),
        ({"all_rows": True, "set": {"comments": ""}}, "set.comments"),
        ({"all_rows": True, "add_tags": ["no-such-tag"]}, "add_tags"),
        ({"all_rows": True, "add_tags": ["critical"], "remove_tags": ["Critical"]}, "remove_tags"),
        ({"filter": "nonsense:eq:1", "set": {"comments": "x"}}, "filter"),
        ({"filter": "hostname:regex:(", "set": {"comments": "x"}}, "filter"),
        ({"hids": [], "set": {"comments": "x"}}, "hids"),
        (
            {"hids": ["01900000-0000-7000-8000-000000000000"], "set": {"comments": "x"}},
            "hids",
        ),
    ],
)
def test_a_bulk_edit_that_makes_no_sense_is_refused_before_any_preview(
    make: Maker, switches: list[dict], body: dict, field: str
) -> None:
    refused = make.post("/items/bulk-update", body, expect=422)
    assert field in errors(refused), refused
    assert make.get("/imports", source="bulk")["total"] == 0


def test_all_rows_changes_every_item_and_a_viewer_changes_none(
    client: TestClient, make: Maker, viewer: dict[str, str], switches: list[dict]
) -> None:
    body = {"all_rows": True, "set": {"comments": "audited 2026"}}
    assert client.post(f"{API}/items/bulk-update", json=body, headers=viewer).status_code == 403
    preview = make.post("/items/bulk-update", body)
    assert preview["job"]["updated"] == 4
    path = f"{API}/items/bulk-update/{preview['job']['hid']}/apply"
    assert client.post(path, headers=viewer).status_code == 403
    # An import's apply route does not apply a bulk edit, nor the other way about.
    make.post(f"/imports/{preview['job']['hid']}/apply", {}, expect=404)


def test_one_item_named_by_its_hid_may_be_given_what_tells_it_from_another(
    make: Maker, switches: list[dict]
) -> None:
    one, two = switches[0], switches[1]
    body = {"set": {"hostname": "site2-sw-core-09", "asset_tag": "AT-000901"}}
    refused = make.post("/items/bulk-update", {**body, "hids": [one["hid"], two["hid"]]}, 422)
    assert set(errors(refused)) == {"set.hostname", "set.asset_tag"}
    make.post("/items/bulk-update", {**body, "filter": f"hid:eq:{one['hid']}"}, expect=422)
    preview = make.post("/items/bulk-update", {**body, "hids": [one["hid"]]})
    assert changes(preview["rows"][0]) == {
        "hostname": ("site2-sw-1", "site2-sw-core-09"),
        "asset_tag": (None, "AT-000901"),
    }
    assert apply(make, preview)["status"] == "applied"
    assert make.get(f"/items/{one['hid']}")["asset_tag"] == "AT-000901"


def test_a_filter_that_runs_out_of_time_is_refused_as_on_a_list(
    make: Maker, switches: list[dict], monkeypatch
) -> None:
    from hirdir.db import dialect

    monkeypatch.setattr(dialect, "REGEX_REQUEST_SECONDS", 0.0)
    body = {"filter": "hostname:regex:^site2", "set": {"comments": "x"}}
    assert "filter" in errors(make.post("/items/bulk-update", body, expect=422))
