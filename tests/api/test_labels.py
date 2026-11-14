"""Tags, choices, settings and the lifecycle rules, through the API."""

from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors


def test_tags_are_made_renamed_and_removed_only_when_unused(make: Maker) -> None:
    tag = make.tag("refresh-2030", colour="#1F6FEB", description="replace by 2030")
    assert (tag["colour"], tag["uses"]) == ("#1f6feb", 0)
    assert make.post("/tags", {"label": "Refresh-2030"}, 409)["title"] == "Conflict"
    assert "colour" in errors(make.post("/tags", {"label": "x", "colour": "blue"}, 422))
    assert "label" in errors(make.post("/tags", {"label": "a;b"}, 422))

    item = make.item(name="site2-sw-core-01", tags=["refresh-2030"])
    assert [(t["label"], t["uses"]) for t in make.get("/tags")] == [("refresh-2030", 1)]
    renamed = make.patch(f"/tags/{tag['hid']}", {"row_version": 1, "label": "refresh-2031"})
    assert (renamed["label"], renamed["uses"]) == ("refresh-2031", 1)
    assert make.get(f"/items/{item['hid']}")["tags"] == ["refresh-2031"]

    in_use = make.client.delete(f"/api/v1/tags/{tag['hid']}", headers=make.headers)
    assert in_use.status_code == 409
    make.patch(f"/items/{item['hid']}", {"row_version": 1, "tags": []})
    assert make.client.delete(f"/api/v1/tags/{tag['hid']}", headers=make.headers).status_code == 204
    assert make.get("/tags") == []
    assert [e["action"] for e in make.audit(record_type="tag")] == ["delete", "update", "create"]


def test_choices_come_with_defaults_and_can_be_added_to(make: Maker) -> None:
    types = make.get("/choices", list="catalog_type")
    assert {"switch", "router", "firewall", "access-point", "phone"} <= {c["value"] for c in types}
    assert [c["sort"] for c in types] == sorted(c["sort"] for c in types)
    assert {c["list"] for c in make.get("/choices")} == {
        "catalog_type",
        "catalog_function",
        "state_reason",
        "replacement_reason",
    }
    assert "list" in errors(make.get("/choices", 422, list="colours"))

    added = make.post("/choices", {"list": "catalog_type", "value": "Load-Balancer"})
    assert (added["value"], added["label"]) == ("load-balancer", "load-balancer")
    assert make.post("/choices", {"list": "catalog_type", "value": "load-balancer"}, 409)
    assert "value" in errors(make.post("/choices", {"list": "catalog_type", "value": "a b"}, 422))
    assert "list" in errors(make.post("/choices", {"list": "colours", "value": "red"}, 422))
    entry = make.entry(make.vendor("F5"), "BIG-IP-i4800", type="load-balancer")
    assert entry["type"] == "load-balancer"


def test_choice_in_use_cannot_be_removed_only_made_inactive(make: Maker) -> None:
    added = make.post("/choices", {"list": "catalog_type", "value": "load-balancer"})
    cisco = make.vendor()
    entry = make.entry(cisco, "X1", type="load-balancer")
    path = f"/api/v1/choices/{added['hid']}"
    refused = make.client.delete(path, headers=make.headers)
    assert refused.status_code == 409
    assert "inactive" in refused.json()["detail"]

    off = make.patch(f"/choices/{added['hid']}", {"row_version": 1, "active": False, "label": "LB"})
    assert (off["active"], off["label"]) == (False, "LB")
    # It is no longer offered, and the record that holds it keeps it.
    assert "type" in errors(
        make.post(
            "/catalog-entries",
            {"vendor_hid": cisco["hid"], "pid": "X2", "type": "load-balancer"},
            422,
        )
    )
    kept = make.patch(
        f"/catalog-entries/{entry['hid']}",
        {"row_version": 1, "type": "load-balancer", "model_name": "kept"},
    )
    assert (kept["type"], kept["model_name"]) == ("load-balancer", "kept")

    make.patch(f"/catalog-entries/{entry['hid']}", {"row_version": 2, "type": None})
    assert make.client.delete(path, headers=make.headers).status_code == 204
    assert [e["action"] for e in make.audit(record_type="choice")] == ["delete", "update", "create"]


def test_settings_have_defaults_and_only_an_admin_changes_them(
    client: TestClient, make: Maker, admin: dict
) -> None:
    listed = {s["key"]: s for s in make.get("/settings")}
    assert listed["stack_discount_pct"]["value"] == 50
    assert listed["count_states"]["value"] == [
        "Assigned",
        "Test",
        "Prod",
        "Down",
        "Pending-Removal",
    ]
    assert listed["weight_per_resource_unit"]["value"] == 300
    assert listed["time_zone"]["value"] == "America/New_York"
    assert all(s["is_default"] and s["row_version"] == 0 for s in listed.values())
    assert "session_hours" not in listed

    url = "/api/v1/settings/stack_discount_pct"
    assert (
        client.put(url, json={"row_version": 0, "value": 30}, headers=make.headers).status_code
        == 403
    )
    changed = client.put(url, json={"row_version": 0, "value": "30"}, headers=admin).json()
    assert (changed["value"], changed["is_default"], changed["row_version"]) == (30, False, 1)
    stale = client.put(url, json={"row_version": 0, "value": 40}, headers=admin)
    assert stale.status_code == 409
    back = client.put(url, json={"row_version": 1, "value": None}, headers=admin).json()
    assert (back["value"], back["is_default"], back["row_version"]) == (50, True, 2)
    events = make.audit(record_type="setting")
    assert [e["changes"][0]["new"] for e in events] == [None, 30]


def test_settings_refuse_values_they_cannot_take(client: TestClient, admin: dict) -> None:
    def put(key: str, value: object) -> int:
        body = {"row_version": 0, "value": value}
        return client.put(f"/api/v1/settings/{key}", json=body, headers=admin).status_code

    for key, value in (
        ("stack_discount_pct", 101),
        ("stack_discount_pct", -1),
        ("stack_discount_pct", True),
        ("stack_discount_pct", "half"),
        ("currency", "dollars"),
        ("fiscal_year_start_month", 13),
        ("fiscal_year_start_month", "7"),
        ("count_states", ["Prod", "Lost"]),
        ("count_states", []),
        ("count_kinds", "hardware"),
        ("weight_per_resource_unit", 0),
    ):
        assert put(key, value) == 422, (key, value)
    assert put("no_such_setting", 1) == 404
    for zone in ("Mars/Olympus", "", "../etc/passwd", "/etc/localtime", 5):
        assert put("time_zone", zone) == 422, zone
    assert put("time_zone", "Europe/Berlin") == 200
    assert put("currency", "eur") == 200
    assert put("count_states", ["prod", "Test", "Prod"]) == 200
    listed = {s["key"]: s["value"] for s in client.get("/api/v1/settings", headers=admin).json()}
    assert (listed["currency"], listed["count_states"]) == ("EUR", ["Test", "Prod"])


def test_stack_discount_setting_reaches_catalog_entries_at_once(
    client: TestClient, make: Maker, admin: dict
) -> None:
    entry = make.entry(make.vendor())
    client.put(
        "/api/v1/settings/stack_discount_pct", json={"row_version": 0, "value": 35.5}, headers=admin
    )
    now = make.get(f"/catalog-entries/{entry['hid']}")
    assert now["effective"]["stack_discount_pct"]["value"] == "35.5"
    assert now["row_version"] == entry["row_version"]


def test_lifecycle_rules_are_data_with_the_documented_defaults(make: Maker) -> None:
    rules = make.get("/lifecycle-rules")
    assert [rule["state"] for rule in rules] == [
        "Purchased",
        "Delivered",
        "Assigned",
        "Test",
        "Prod",
        "Down",
        "Pending-Removal",
        "Released",
        "Archived",
    ]
    by_state = {rule["state"]: rule for rule in rules}
    assert by_state["Assigned"]["dispositions"] == ["Staging", "Spare", "Excess"]
    assert by_state["Prod"]["must_be_online"] == ["Production"]
    assert by_state["Down"]["keeps_disposition"] is True
    onward = {state: set(rule["next_states"]) for state, rule in by_state.items()}
    assert onward["Test"] == {"Prod", "Down", "Pending-Removal"}
    assert onward["Down"] == {"Test", "Prod", "Pending-Removal"}
    assert onward["Pending-Removal"] == {"Released", "Assigned"}
    assert onward["Archived"] == set()
    # Every state from Assigned to Down may go to Pending-Removal.
    assert all("Pending-Removal" in onward[state] for state in ("Assigned", "Test", "Prod", "Down"))


def test_admin_edits_a_rule_and_the_next_move_obeys_it(
    client: TestClient, make: Maker, admin: dict
) -> None:
    rules = {rule["state"]: rule for rule in make.get("/lifecycle-rules")}
    delivered = rules["Delivered"]
    item = make.item(name="site2-sw-access-01", lifecycle_state="Delivered")
    assert "to" in errors(make.move(item, "Test", expect=422))

    url = f"/api/v1/lifecycle-rules/{delivered['hid']}"
    body = {"row_version": delivered["row_version"], "next_states": ["assigned", "Test"]}
    assert client.patch(url, json=body, headers=make.headers).status_code == 403
    changed = client.patch(url, json=body, headers=admin).json()
    assert changed["next_states"] == ["Assigned", "Test"]
    assert make.move(item, "Test")["lifecycle_state"] == "Test"
    event = make.audit(record_type="lifecycle_rule")[0]
    assert event["changes"] == [
        {"field": "next_states", "old": ["Assigned"], "new": ["Assigned", "Test"]}
    ]


def test_a_rule_that_does_not_agree_with_itself_is_refused(
    client: TestClient, make: Maker, admin: dict
) -> None:
    prod = next(rule for rule in make.get("/lifecycle-rules") if rule["state"] == "Prod")
    url = f"/api/v1/lifecycle-rules/{prod['hid']}"

    def refused(**fields: object) -> dict:
        response = client.patch(
            url, json={"row_version": prod["row_version"], **fields}, headers=admin
        )
        assert response.status_code == 422, response.text
        return errors(response.json())

    assert "next_states" in refused(next_states=["Prod"])
    assert "next_states" in refused(next_states=["Nowhere"])
    assert "dispositions" in refused(dispositions=["Loaned"])
    assert "entry_disposition" in refused(dispositions=["Spare"])
    assert "must_be_online" in refused(may_be_online=["Spare"])
    assert (
        client.patch(
            url.replace(prod["hid"], "nope"), json={"row_version": 1}, headers=admin
        ).status_code
        == 404
    )
