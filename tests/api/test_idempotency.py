"""Idempotency keys, and lists that return only the fields asked for."""

from datetime import timedelta

from fastapi.testclient import TestClient

from hirdir import clock
from hirdir.domain import idempotency
from tests.api.inventory import API, Maker, errors

KEY = "Idempotency-Key"


def test_the_same_request_with_the_same_key_is_carried_out_once(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    headers = {**inventory, KEY: "create-fluke-1"}
    first = client.post(f"{API}/items", json={"name": "Fluke-1"}, headers=headers)
    again = client.post(f"{API}/items", json={"name": "Fluke-1"}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert "idempotency-replayed" not in first.headers
    assert again.headers["idempotency-replayed"] == "true"
    assert again.headers["x-request-id"] != first.headers["x-request-id"]
    assert make.get("/items")["total"] == 1
    assert len(make.audit(record_type="item")) == 1
    # Without a key the same request is a second item.
    client.post(f"{API}/items", json={"name": "Fluke-1"}, headers=inventory)
    assert make.get("/items")["total"] == 2


def test_the_same_key_on_a_different_request_is_refused(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    headers = {**inventory, KEY: "k-1"}
    assert client.post(f"{API}/items", json={"name": "one"}, headers=headers).status_code == 201
    other = client.post(f"{API}/items", json={"name": "two"}, headers=headers)
    assert other.status_code == 422
    assert "different request" in errors(other.json())[KEY]
    elsewhere = client.post(f"{API}/vendors", json={"name": "one"}, headers=headers)
    assert elsewhere.status_code == 422
    assert make.get("/items")["total"] == 1


def test_a_key_belongs_to_its_caller_and_a_failure_is_not_kept(
    client: TestClient, make: Maker, inventory: dict[str, str], admin: dict[str, str]
) -> None:
    body = {"name": "shared"}
    mine = client.post(f"{API}/items", json=body, headers={**inventory, KEY: "k-1"})
    theirs = client.post(f"{API}/items", json=body, headers={**admin, KEY: "k-1"})
    assert mine.json()["hid"] != theirs.json()["hid"]

    # A request that fails gives its key back, so the corrected one may use it.
    bad = {**inventory, KEY: "k-2"}
    assert client.post(f"{API}/items", json={}, headers=bad).status_code == 422
    assert client.post(f"{API}/items", json={}, headers=bad).status_code == 422
    assert "idempotency-replayed" not in client.post(f"{API}/items", json={}, headers=bad).headers
    assert client.post(f"{API}/items", json={"name": "x"}, headers={KEY: "k-3"}).status_code == 401
    for wrong in ("", "x" * 201):
        refused = client.post(f"{API}/items", json=body, headers={**inventory, KEY: wrong})
        assert refused.status_code == 422, wrong


def test_a_key_is_kept_for_a_day(
    client: TestClient, make: Maker, inventory: dict[str, str], monkeypatch
) -> None:
    headers = {**inventory, KEY: "k-1"}
    client.post(f"{API}/items", json={"name": "one"}, headers=headers)
    later = clock.now() + idempotency.KEPT_FOR + timedelta(minutes=1)
    monkeypatch.setattr(clock, "now", lambda: later)
    again = client.post(f"{API}/items", json={"name": "one"}, headers=headers)
    assert "idempotency-replayed" not in again.headers
    assert make.get("/items")["total"] == 2


def test_a_request_still_being_worked_on_is_not_started_twice(
    client: TestClient, db, inventory: dict[str, str]
) -> None:
    me = client.get(f"{API}/auth/me", headers=inventory).json()
    body = b'{"name":"one"}'
    assert (
        idempotency.begin(
            db, me["hid"], "k-1", idempotency.fingerprint("POST", f"{API}/items", body)
        )
        is None
    )
    db.commit()
    waiting = client.post(
        f"{API}/items",
        content=body,
        headers={**inventory, KEY: "k-1", "Content-Type": "application/json"},
    )
    assert waiting.status_code == 409
    assert "being worked on" in waiting.json()["detail"]


def test_an_import_and_a_bulk_edit_take_a_key(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    headers = {**inventory, KEY: "load-1", "Content-Type": "text/csv"}
    path = f"{API}/imports/preview?entity=vendors"
    first = client.post(path, content="name\nCisco\n", headers=headers)
    again = client.post(path, content="name\nCisco\n", headers=headers)
    assert first.json()["job"]["hid"] == again.json()["job"]["hid"]
    assert make.get("/imports")["total"] == 1
    apply = f"{API}/imports/{first.json()['job']['hid']}/apply"
    keyed = {**inventory, KEY: "apply-1"}
    assert client.post(apply, headers=keyed).json()["status"] == "applied"
    # Sent again, it is answered as it was, and not refused as applied already.
    assert client.post(apply, headers=keyed).status_code == 200
    assert make.get("/vendors")["total"] == 1


def test_the_routes_of_accounts_refuse_a_key(client: TestClient, admin: dict[str, str]) -> None:
    refused = client.post(f"{API}/users", json={"username": "uma"}, headers={**admin, KEY: "k-1"})
    assert refused.status_code == 422
    assert KEY in errors(refused.json())
    assert client.get(f"{API}/users", headers=admin).json()["total"] == 3
    signing_in = client.post(
        f"{API}/auth/sign-in", json={"username": "ada", "access_code": "x"}, headers={KEY: "k"}
    )
    assert signing_in.status_code == 422


# --- fields --------------------------------------------------------------------------


def test_a_list_returns_only_the_fields_asked_for(make: Maker) -> None:
    entry = make.entry(make.vendor(), ldos="2034-04-30")
    make.item(catalog_entry_hid=entry["hid"], serial_number="S1", name="one")
    page = make.get("/items", fields="name,catalog.pid,effective.ldos")
    assert page["total"] == 1
    row = page["items"][0]
    assert set(row) == {"hid", "row_version", "name", "catalog", "effective"}
    assert row["catalog"] == {"pid": "C9300-48P"}
    assert row["effective"] == {
        "ldos": {"value": "2034-04-30", "source": "catalog", "source_hid": entry["hid"]}
    }
    whole = make.get("/items", fields="catalog,catalog.pid")["items"][0]["catalog"]
    assert whole["vendor"] == "Cisco"
    body = make.post("/items/query", {"fields": ["serial_number"]}, expect=200)
    assert set(body["items"][0]) == {"hid", "row_version", "serial_number"}
    assert set(make.get("/vendors", fields="name")["items"][0]) == {"hid", "row_version", "name"}
    assert set(make.get("/catalog-entries", fields="vendor.name")["items"][0]) == {
        "hid",
        "row_version",
        "vendor",
    }
    for wrong in ("nonsense", "catalog.nonsense", "name.first", "tags.label"):
        assert "fields" in errors(make.get("/items", expect=422, fields=wrong)), wrong
