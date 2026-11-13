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


def apply(make: Maker, preview: dict[str, Any], expect: int = 200, **params: str) -> dict[str, Any]:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    path = f"/items/bulk-update/{preview['job']['hid']}/apply" + (f"?{query}" if query else "")
    return make.post(path, {}, expect)


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


def test_the_second_of_two_overlapping_bulk_edits_is_refused_whole(
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

    refused = apply(other, theirs, expect=409)
    assert refused["title"] == "Preview out of date"
    in_the_way = errors(refused)
    assert list(in_the_way) == ["rows.1", "rows.2"]
    assert "site2-sw-2" in in_the_way["rows.1"]
    comments = [item["comments"] for item in make.get("/items", sort="hostname")["items"]]
    assert comments == ["mine", "mine", "mine", None]
    assert make.get(f"/imports/{theirs['job']['hid']}")["status"] == "failed"
    # Nobody applies another's preview.
    again = other.post(
        "/items/bulk-update", {"hids": [switches[3]["hid"]], "set": {"comments": "theirs"}}
    )
    assert apply(make, again, expect=403)["title"] == "Not allowed"


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
    assert preview["rows"][0]["reasons"][0]["field"] == "expected_online"
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
        ({"all_rows": True, "set": {"location": "x"}}, "set.location"),
        ({"all_rows": True, "set": {"model_name": "x"}}, "set.model_name"),
        ({"all_rows": True, "set": {"quantity": "many"}}, "set.quantity"),
        ({"all_rows": True, "set": {"comments": ""}}, "set.comments"),
        ({"all_rows": True, "add_tags": ["no-such-tag"]}, "add_tags"),
        ({"all_rows": True, "add_tags": ["critical"], "remove_tags": ["Critical"]}, "remove_tags"),
        ({"filter": "nonsense:eq:1", "set": {"comments": "x"}}, "filter"),
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
