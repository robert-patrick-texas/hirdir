"""Settings rather than constants (D-177, D-187): the five settings of 0.7.0 and what
each decides, and the values that are fixed, listed beside them."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.db import engine
from hirdir.domain import contracts, items, purchases
from hirdir.io import filters, imports, listing
from tests.api.inventory import API, Maker, errors

TODAY = date.today()
NEW = {
    "renewal_warning_days": 90,
    "renewal_pending_overdue_days": 60,
    "end_of_life_within_days": 730,
    "end_of_life_date": "ldos",
    "max_items_per_request": 1000,
}


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _put(client: TestClient, admin: dict, key: str, value: Any, expect: int = 200) -> Any:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=admin).json()}
    version = now[key]["row_version"] if key in now else 0
    answer = client.put(
        f"{API}/settings/{key}", json={"row_version": version, "value": value}, headers=admin
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


def test_the_settings_are_listed_with_their_defaults_and_then_what_is_fixed(
    client: TestClient, viewer: dict
) -> None:
    listed = client.get(f"{API}/settings", headers=viewer).json()
    keys = [one["key"] for one in listed]
    by_key = {one["key"]: one for one in listed}
    for key, default in NEW.items():
        assert (by_key[key]["value"], by_key[key]["default"]) == (default, default), key
        assert (by_key[key]["is_default"], by_key[key]["fixed"]) == (True, False), key
        assert by_key[key]["meaning"], key
        assert by_key[key]["accepts"], key
    assert by_key["renewal_warning_days"]["accepts"] == "a whole number of days from 1 to 36,500"
    assert by_key["end_of_life_date"]["options"] == [
        "end_of_sale",
        "end_of_sw_support",
        "end_of_hw_support",
        "ldos",
    ]
    assert "Pending-Removal" in by_key["count_states"]["options"]
    assert by_key["time_zone"]["options"] is None
    # Every setting comes first, and every fixed value after them.
    fixed = [one for one in listed if one["fixed"]]
    assert keys[: len(listed) - len(fixed)] == [one["key"] for one in listed if not one["fixed"]]
    for one in fixed:
        assert one["meaning"], one["key"]
        assert one["reason"], one["key"]
        assert (one["is_default"], one["row_version"], one["accepts"]) == (True, 0, None)
        assert one["value"] == one["default"]
    # Each is listed as the value the code uses.
    assert by_key["out_of_service_states"]["value"] == list(contracts.OUT_OF_SERVICE)
    assert by_key["out_of_service_states"]["decision"] == "D-142"
    assert by_key["out_of_hands_states"]["value"] == list(items.OUT_OF_HANDS)
    assert (by_key["received_state"]["value"], by_key["received_state"]["decision"]) == (
        purchases.RECEIVED_AS,
        "D-145",
    )
    assert by_key["condition_health"]["value"]["failed"] == ["failed", "dead"]
    assert by_key["condition_health"]["decision"] == "D-112"
    assert by_key["review_status_of_what_a_file_makes"]["value"] == "unreviewed"
    assert by_key["default_page_size"]["value"] == listing.DEFAULT_LIMIT
    assert by_key["max_page_size"]["value"] == listing.MAX_LIMIT
    assert by_key["max_offset"]["value"] == listing.MAX_OFFSET
    assert by_key["max_filter_length"]["value"] == filters.MAX_FILTER_LENGTH
    assert by_key["import_batch_rows"]["value"] == imports.BATCH_ROWS
    assert by_key["writer_wait_seconds"]["value"] == engine.WRITER_WAIT_SECONDS
    assert by_key["max_page_size"]["decision"] is None


def test_a_fixed_value_is_not_changed_and_a_setting_goes_back_to_its_default(
    client: TestClient, admin: dict, inventory: dict
) -> None:
    for key in ("max_page_size", "out_of_service_states", "writer_wait_seconds"):
        refused = client.put(
            f"{API}/settings/{key}", json={"row_version": 0, "value": 5}, headers=admin
        )
        assert refused.status_code == 422, key
        assert "is fixed" in errors(refused.json())["value"]
        back = client.put(
            f"{API}/settings/{key}", json={"row_version": 0, "value": None}, headers=admin
        )
        assert back.status_code == 422, key
    assert (
        client.put(
            f"{API}/settings/no_such_setting", json={"row_version": 0, "value": 1}, headers=admin
        ).status_code
        == 404
    )
    # Only an Admin changes a setting; one change returns it to its default.
    body = {"row_version": 0, "value": 30}
    url = f"{API}/settings/renewal_warning_days"
    assert client.put(url, json=body, headers=inventory).status_code == 403
    changed = _put(client, admin, "renewal_warning_days", 30)
    assert (changed["value"], changed["is_default"], changed["default"]) == (30, False, 90)
    back = _put(client, admin, "renewal_warning_days", None)
    assert (back["value"], back["is_default"]) == (90, True)
    events = client.get(
        f"{API}/audit-events", params={"record_type": "setting"}, headers=admin
    ).json()["items"]
    assert [event["changes"][0]["new"] for event in events] == [None, 30]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("renewal_warning_days", 0),
        ("renewal_warning_days", 36_501),
        ("renewal_warning_days", "90"),
        ("renewal_warning_days", True),
        ("renewal_warning_days", 1.5),
        ("renewal_pending_overdue_days", -1),
        ("end_of_life_within_days", 0),
        ("end_of_life_date", "birthday"),
        ("end_of_life_date", 3),
        ("max_items_per_request", 99),
        ("max_items_per_request", 5001),
        ("max_items_per_request", "1000"),
    ],
)
def test_a_setting_refuses_what_it_cannot_take(
    client: TestClient, admin: dict, key: str, value: Any
) -> None:
    refused = _put(client, admin, key, value, 422)
    assert "value" in errors(refused)


def test_a_setting_takes_what_it_can(client: TestClient, admin: dict) -> None:
    assert _put(client, admin, "end_of_life_date", " End_Of_Sale ")["value"] == "end_of_sale"
    assert _put(client, admin, "renewal_pending_overdue_days", 36_500)["value"] == 36_500
    assert _put(client, admin, "max_items_per_request", 100)["value"] == 100
    assert _put(client, admin, "max_items_per_request", 5000)["value"] == 5000


def test_the_coverage_report_looks_as_far_ahead_as_the_warning_period(
    make: Maker, client: TestClient, admin: dict
) -> None:
    cisco = make.vendor()
    entry = make.entry(cisco)
    switch = make.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW-1", lifecycle_state="Prod"
    )
    contract = make.post(
        "/contracts",
        {"number": "CON-1", "vendor_hid": cisco["hid"], "starts_on": day(-10), "ends_on": day(100)},
    )
    make.post(f"/contracts/{contract['hid']}/coverage", {"items": [{"item_hid": switch["hid"]}]})
    report = make.get("/reports/coverage")
    assert (report["within_days"], report["totals"]["expiring"]) == (90, 0)
    _put(client, admin, "renewal_warning_days", 120)
    report = make.get("/reports/coverage")
    assert (report["within_days"], report["totals"]["expiring"]) == (120, 1)
    # Asked, the report looks as far as it is asked.
    assert make.get("/reports/coverage", within_days=30)["totals"]["expiring"] == 0


def test_the_end_of_life_report_is_of_the_date_and_the_window_the_settings_say(
    make: Maker, client: TestClient, admin: dict
) -> None:
    cisco = make.vendor()
    entry = make.entry(cisco, "C9200L-48P", ldos=day(400), end_of_sale=day(50))
    make.item(catalog_entry_hid=entry["hid"], serial_number="JAE-1", lifecycle_state="Prod")
    report = make.get("/reports/end-of-life", section="approaching")
    assert (report["date"], report["within_days"], report["total"]) == ("ldos", 730, 1)
    _put(client, admin, "end_of_life_within_days", 300)
    _put(client, admin, "end_of_life_date", "end_of_sale")
    report = make.get("/reports/end-of-life", section="approaching")
    assert (report["date"], report["within_days"], report["total"]) == ("end_of_sale", 300, 1)
    assert report["dates"]["ldos"]["approaching"]["items"] == 0
    asked = make.get("/reports/end-of-life", date="ldos", within_days=500, section="approaching")
    assert (asked["date"], asked["within_days"], asked["total"]) == ("ldos", 500, 1)


def test_one_request_takes_as_many_items_as_the_setting_says(
    make: Maker, client: TestClient, admin: dict
) -> None:
    _put(client, admin, "max_items_per_request", 100)
    cisco = make.vendor()
    entry = make.entry(cisco)
    request = make.post(
        "/purchase-requests",
        {
            "reference": "RITM0012345",
            "lines": [{"catalog_entry_hid": entry["hid"], "quantity": 101}],
        },
    )
    (line,) = request["lines"]
    path = f"/purchase-lines/{line['hid']}/receive"
    refused = make.post(path, {"row_version": line["row_version"], "quantity": 101}, 422)
    assert "max_items_per_request" in errors(refused)["items"]
    first = make.post(path, {"row_version": line["row_version"], "quantity": 100})
    last = make.post(path, {"row_version": first["row_version"], "quantity": 1})
    arrived = [one["hid"] for one in first["items"] + last["items"]]
    assert len(arrived) == 101

    contract = make.post("/contracts", {"number": "CON-1", "vendor_hid": cisco["hid"]})
    cover = f"/contracts/{contract['hid']}/coverage"
    refused = make.post(cover, {"items": [{"item_hid": hid} for hid in arrived]}, 422)
    assert "max_items_per_request" in errors(refused)["items"]
    assert len(make.post(cover, {"items": [{"item_hid": hid} for hid in arrived[:100]]})) == 100

    group = make.post("/device-groups", {"name": "lab-domain", "type": "custom"})
    members = f"/device-groups/{group['hid']}/members"
    refused = make.post(members, {"members": [{"item_hid": hid} for hid in arrived]}, 422)
    assert "max_items_per_request" in errors(refused)["members"]
    many = {
        "name": "lab-domain-2",
        "type": "custom",
        "members": [{"item_hid": hid} for hid in arrived],
    }
    assert "max_items_per_request" in errors(make.post("/device-groups", many, 422))["members"]
    assert len(make.post(members, {"members": [{"item_hid": hid} for hid in arrived[:100]]})) == 100

    # Whatever the setting says, the API takes no more than 5,000 in one request.
    _put(client, admin, "max_items_per_request", 5000)
    too_many = {"items": [{"item_hid": arrived[0]}] * 5001}
    assert make.post(cover, too_many, 422)
