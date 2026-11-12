"""Vendors, catalog entries and owners, through the API."""

from typing import Any

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

INVENTORY_ROUTES = tuple(
    f"{API}/{name}"
    for name in (
        "vendors",
        "catalog-entries",
        "owners",
        "items",
        "tags",
        "choices",
        "settings",
        "lifecycle-rules",
    )
)


def test_vendor_names_and_aliases_are_unique_without_regard_to_case(make: Maker) -> None:
    cisco = make.vendor("Cisco", aliases=["Cisco Systems", " cisco "])
    assert cisco["aliases"] == ["Cisco Systems"]
    assert make.post("/vendors", {"name": "CISCO"}, 409)["title"] == "Conflict"
    assert "Cisco" in make.post("/vendors", {"name": "cisco systems"}, 409)["detail"]
    make.vendor("Juniper")
    taken = make.post("/vendors", {"name": "Arista", "aliases": ["juniper"]}, 409)
    assert "Juniper" in taken["detail"]
    assert errors(make.post("/vendors", {"name": "   "}, 422)) == {"name": "must not be blank"}


def test_vendor_changes_are_versioned_and_audited(make: Maker) -> None:
    vendor = make.vendor("Cisco")
    changed = make.patch(f"/vendors/{vendor['hid']}", {"row_version": 1, "notes": "renewal in May"})
    assert (changed["notes"], changed["row_version"]) == ("renewal in May", 2)
    stale = make.patch(f"/vendors/{vendor['hid']}", {"row_version": 1, "notes": "x"}, 409)
    assert stale["title"] == "Stale version"
    # A change that changes nothing leaves the version alone.
    same = make.patch(f"/vendors/{vendor['hid']}", {"row_version": 2, "notes": "renewal in May"})
    assert same["row_version"] == 2
    events = make.audit(record_type="vendor", record_hid=vendor["hid"])
    assert [event["action"] for event in events] == ["update", "create"]
    assert events[0]["changes"] == [{"field": "notes", "old": None, "new": "renewal in May"}]


def test_catalog_entry_holds_what_is_true_of_a_model(make: Maker) -> None:
    cisco = make.vendor()
    entry = make.entry(
        cisco,
        model_name="Catalyst 9300 48-port PoE+",
        type="Switch",
        function="access",
        end_of_sale="2029-04-30",
        ldos="2034-04-30",
        est_value="18000",
        support_weight=1,
        annual_support_cost="1250.5",
    )
    assert entry["vendor"] == {"hid": cisco["hid"], "name": "Cisco"}
    assert (entry["kind"], entry["type"], entry["review_status"]) == (
        "hardware",
        "switch",
        "reviewed",
    )
    assert (entry["est_value"], entry["support_weight"]) == ("18000.00", "1")
    assert entry["annual_support_cost"] == "1250.50"
    assert entry["effective"]["stack_discount_pct"] == {
        "value": "50",
        "source": "setting",
        "source_hid": None,
    }
    own = make.patch(
        f"/catalog-entries/{entry['hid']}", {"row_version": 1, "stack_discount_pct": "30"}
    )
    assert own["effective"]["stack_discount_pct"] == {
        "value": "30",
        "source": "own",
        "source_hid": entry["hid"],
    }


def test_catalog_entry_is_unique_on_vendor_and_pid(make: Maker) -> None:
    cisco, juniper = make.vendor("Cisco"), make.vendor("Juniper")
    make.entry(cisco, "C9300-48P")
    make.entry(juniper, "C9300-48P")
    again = make.post("/catalog-entries", {"vendor_hid": cisco["hid"], "pid": "c9300-48p"}, 409)
    assert "C9300-48P" in again["detail"]


def test_catalog_entry_refuses_what_it_cannot_hold(make: Maker) -> None:
    cisco = make.vendor()
    base = {"vendor_hid": cisco["hid"], "pid": "X"}
    for field, value in (
        ("kind", "appliance"),
        ("type", "toaster"),
        ("function", "decoration"),
        ("est_value", "-1"),
        ("est_value", "1.234"),
        ("stack_discount_pct", "101"),
        ("ldos", "next year"),
        ("review_status", "maybe"),
        ("successor_hid", "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"),
        ("tags", ["no-such-tag"]),
    ):
        problem = make.post("/catalog-entries", {**base, field: value}, 422)
        assert field in errors(problem), (field, problem)
    assert errors(make.post("/catalog-entries", {**base, "vendor_hid": "nobody"}, 422)) == {
        "vendor_hid": "there is no such vendor"
    }
    assert make.get("/catalog-entries")["total"] == 0


def test_retired_catalog_entry_leaves_the_default_list_and_keeps_its_items(make: Maker) -> None:
    entry = make.entry(make.vendor())
    item = make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X001")
    retired = make.post(f"/catalog-entries/{entry['hid']}/retire", {"row_version": 1}, 200)
    assert retired["record_status"] == "retired"
    assert make.get("/catalog-entries")["total"] == 0
    assert make.get("/catalog-entries", include_archived=True)["total"] == 1
    assert make.get(f"/items/{item['hid']}")["catalog"]["pid"] == "C9300-48P"
    refused = make.post(
        "/items", {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X002"}, 422
    )
    assert errors(refused) == {"catalog_entry_hid": "this catalog entry is retired"}
    back = make.patch(
        f"/catalog-entries/{entry['hid']}", {"row_version": 2, "record_status": "active"}
    )
    assert back["record_status"] == "active"
    actions = [e["action"] for e in make.audit(record_type="catalog_entry")]
    assert actions == ["update", "retire", "create"]


def test_catalog_list_filters_sorts_and_pages(make: Maker) -> None:
    cisco, juniper = make.vendor("Cisco"), make.vendor("Juniper")
    make.tag("refresh-2030")
    make.entry(cisco, "C9300-48P", type="switch", ldos="2034-04-30", tags=["refresh-2030"])
    make.entry(cisco, "C9200L-24T", type="switch", ldos="2032-01-31")
    make.entry(juniper, "EX4400-48P", type="switch")
    make.entry(juniper, "SRX1500", type="firewall", kind="hardware")

    def pids(**params: Any) -> list[str]:
        return [row["pid"] for row in make.get("/catalog-entries", **params)["items"]]

    assert pids() == ["C9200L-24T", "C9300-48P", "EX4400-48P", "SRX1500"]
    assert pids(filter="vendor:eq:juniper") == ["EX4400-48P", "SRX1500"]
    assert pids(filter="pid:glob:c9?00*") == ["C9200L-24T", "C9300-48P"]
    assert pids(filter="tags:has:REFRESH-2030") == ["C9300-48P"]
    assert pids(filter="ldos:lt:2033-01-01") == ["C9200L-24T"]
    assert pids(filter="ldos:empty:true type:eq:switch") == ["EX4400-48P"]
    assert pids(sort="-ldos") == ["C9300-48P", "C9200L-24T", "EX4400-48P", "SRX1500"]
    assert pids(sort="-pid", limit=2, offset=1) == ["EX4400-48P", "C9300-48P"]
    body = {"filter": {"field": "type", "op": "ne", "value": "switch"}, "sort": ["pid"]}
    assert [row["pid"] for row in make.post("/catalog-entries/query", body, 200)["items"]] == [
        "SRX1500"
    ]


def test_owner_outside_the_team_needs_a_reason(make: Maker) -> None:
    make.owner("Network Engineering")
    refused = make.post("/owners", {"label": "Facilities", "is_external": True}, 422)
    assert "exception_reason" in errors(refused)
    facilities = make.owner("Facilities", is_external=True, exception_reason="runs the door locks")
    assert make.post("/owners", {"label": "facilities"}, 409)["title"] == "Conflict"
    cleared = make.patch(
        f"/owners/{facilities['hid']}", {"row_version": 1, "exception_reason": None}, 422
    )
    assert "exception_reason" in errors(cleared)
    assert [row["label"] for row in make.get("/owners", filter="is_external:eq:true")["items"]] == [
        "Facilities"
    ]
    retired = make.post(f"/owners/{facilities['hid']}/retire", {"row_version": 1}, 200)
    assert retired["record_status"] == "retired"
    assert make.get("/owners")["total"] == 1


def test_unknown_field_in_a_request_is_refused(make: Maker) -> None:
    assert "colour" in errors(make.post("/vendors", {"name": "Cisco", "colour": "blue"}, 422))


def test_every_inventory_write_needs_the_inventory_role(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    document = client.get(f"{API}/openapi.json", headers=admin).json()["paths"]
    hid = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"
    checked = 0
    for path, methods in document.items():
        if not path.startswith(INVENTORY_ROUTES):
            continue
        url = path.replace("{hid}", hid).replace("{key}", "currency")
        for method in methods:
            reading = method == "get" or path.endswith("/query")
            assert client.request(method, url, json={}).status_code == 401, (method, path)
            as_viewer = client.request(method, url, json={}, headers=viewer).status_code
            if reading:
                assert as_viewer != 403, (method, path)
            else:
                assert as_viewer == 403, (method, path)
                checked += 1
    assert checked >= 20
