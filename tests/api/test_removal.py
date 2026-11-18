"""Several items or device groups retired at once, and an Admin's deletion of those that
were a mistake (P-227, P-228, P-236)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.domain import errors as domain_errors
from hirdir.domain import items as item_rules
from tests.api.inventory import API, Maker, errors

NOBODY = "01900000-0000-7000-8000-000000000000"


def _switches(make: Maker, count: int, prefix: str = "site9-sw-wrong") -> list[dict[str, Any]]:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    entry = entries[0] if entries else make.entry(vendor)
    return make.switches(entry, prefix, count)


def _retire(
    client: TestClient, headers: dict[str, str], path: str, hids: list[str], expect: int = 200
) -> dict[str, Any]:
    response = client.post(f"{API}{path}/retire", json={"hids": hids}, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


# --- several retired at once (P-228) --------------------------------------------------


def test_the_items_ticked_are_retired_by_one_request_each_as_its_page_retires_it(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    one, two, three = _switches(make, 3)
    stack = make.stack("site9-sw-stack-wrong", [one, two])
    make.post(f"/items/{three['hid']}/retire", {"row_version": three["row_version"]}, 200)

    named = [one["hid"], two["hid"], three["hid"], NOBODY, one["hid"]]
    done = _retire(client, inventory, "/items", named)

    assert done == {
        "retired": [
            {"hid": one["hid"], "label": "site9-sw-wrong-01"},
            {"hid": two["hid"], "label": "site9-sw-wrong-02"},
        ],
        # Retired before: counted, and not refused.
        "already": [{"hid": three["hid"], "label": "site9-sw-wrong-03"}],
        "refused": [],
        "missing": [NOBODY],
    }
    for item in (one, two):
        assert make.get(f"/items/{item['hid']}")["record_status"] == "retired"
        events = make.audit(record_hid=item["hid"], action="retire")
        assert len(events) == 1
        assert events[0]["request_id"]
    # As on its page: a retired item is in no stack any more, and the list leaves it out.
    assert make.members(stack) == []
    assert one["hid"] not in [row["hid"] for row in make.get("/items")["items"]]
    shown = make.get("/items", include_archived="true")["items"]
    assert one["hid"] in [row["hid"] for row in shown]
    # Brought back as before.
    back = make.get(f"/items/{one['hid']}")
    make.patch(
        f"/items/{one['hid']}", {"row_version": back["row_version"], "record_status": "active"}
    )


def test_device_groups_are_retired_several_at_once_and_their_memberships_end(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    one, two = _switches(make, 2)
    first = make.stack("site9-stack-a", [one])
    second = make.stack("site9-stack-b", [two])

    done = _retire(client, inventory, "/device-groups", [first["hid"], second["hid"]])

    assert [entry["label"] for entry in done["retired"]] == ["site9-stack-a", "site9-stack-b"]
    assert make.members(first) == []
    assert make.members(second) == []
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"
    events = make.audit(record_type="device_group", action="retire")
    assert {event["record_hid"] for event in events} == {first["hid"], second["hid"]}


def test_retiring_several_is_for_the_inventory_role_and_takes_at_most_a_thousand(
    client: TestClient, make: Maker, viewer: dict[str, str], inventory: dict[str, str]
) -> None:
    (one,) = _switches(make, 1)

    assert _retire(client, viewer, "/items", [one["hid"]], 403)
    assert _retire(client, viewer, "/device-groups", [one["hid"]], 403)
    too_many = [NOBODY] * 1001
    assert "hids" in errors(_retire(client, inventory, "/items", too_many, 422))
    assert "hids" in errors(_retire(client, inventory, "/items", [], 422))
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"


def test_one_that_is_refused_leaves_the_others_as_they_went(
    client: TestClient,
    make: Maker,
    inventory: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one, two = _switches(make, 2)
    retire = item_rules.retire_item

    def refusing(db: Any, context: Any, hid: str, row_version: int) -> Any:
        retire(db, context, hid, row_version)
        if hid == one["hid"]:
            # Refused after it had written: what it wrote is undone.
            raise domain_errors.Invalid("not now", {"record_status": "a rule says no"})
        return None

    monkeypatch.setattr(item_rules, "retire_item", refusing)
    done = _retire(client, inventory, "/items", [one["hid"], two["hid"]])

    assert done["refused"] == [
        {
            "hid": one["hid"],
            "label": "site9-sw-wrong-01",
            "detail": "not now; record_status: a rule says no",
        }
    ]
    assert [entry["hid"] for entry in done["retired"]] == [two["hid"]]
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"
    assert make.audit(record_hid=one["hid"], action="retire") == []
