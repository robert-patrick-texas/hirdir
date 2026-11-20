"""Every table exported from one place, all of them at once, and the users (P-286, P-288)."""

import csv
import io
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent, ServiceToken, User
from hirdir.io.entities import LOAD_ORDER
from tests.api.inventory import API, Maker


def tables(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get(f"{API}/exports/tables", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_table_is_listed_in_the_order_of_loading_with_its_count_and_columns(
    client: TestClient, viewer: dict[str, str], make: Maker
) -> None:
    make.vendor("Juniper")
    make.vendor("Cisco")
    listed = tables(client, viewer)
    assert [table["entity"] for table in listed] == list(LOAD_ORDER)
    by_entity = {table["entity"]: table for table in listed}
    assert by_entity["vendors"] == {
        "entity": "vendors",
        "label": "Vendors",
        "file": "vendors",
        "count": 2,
        "columns": ["hid", "name", "aliases", "notes", "review_status"],
    }
    assert by_entity["catalog_entries"]["file"] == "catalog-entries"
    assert by_entity["items"]["count"] == 0
    assert all(table["columns"][0] == "hid" for table in listed)


def test_an_empty_table_exports_as_its_template(client: TestClient, viewer: dict[str, str]) -> None:
    for table in tables(client, viewer):
        response = client.post(
            f"{API}/exports",
            json={"entity": table["entity"], "own_values": True},
            headers=viewer,
        )
        assert response.status_code == 200, response.text
        assert list(csv.reader(io.StringIO(response.text))) == [table["columns"]]
        as_json = client.post(
            f"{API}/exports",
            json={"entity": table["entity"], "format": "json"},
            headers=viewer,
        ).json()
        assert as_json["records"] == []
        assert as_json["entity"] == table["entity"]


def test_every_table_is_one_zip_named_as_the_examples_are(
    client: TestClient, viewer: dict[str, str], make: Maker
) -> None:
    make.vendor("Juniper")
    for format_ in ("csv", "json"):
        response = client.post(f"{API}/exports/all", json={"format": format_}, headers=viewer)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        name = response.headers["content-disposition"]
        assert name.startswith(f'attachment; filename="hirdir-all-{format_}-')
        assert name.endswith('.zip"')
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert archive.namelist() == [
            f"{entity.replace('_', '-')}.{format_}" for entity in LOAD_ORDER
        ]
        alone = client.post(
            f"{API}/exports",
            json={
                "entity": "vendors",
                "format": format_,
                "own_values": True,
                "include_archived": True,
                "include_drafts": True,
            },
            headers=viewer,
        )
        assert archive.read(f"vendors.{format_}").decode() == alone.text


def test_the_zip_takes_a_format_it_knows(client: TestClient, viewer: dict[str, str]) -> None:
    response = client.post(f"{API}/exports/all", json={"format": "xlsx"}, headers=viewer)
    assert response.status_code == 422, response.text


# --- the users, for an Admin (P-288) ---------------------------------------------------

USER_COLUMNS = [
    "username",
    "name",
    "email",
    "phone",
    "phone2",
    "role",
    "groups",
    "operators",
    "kind",
    "state",
    "last_sign_in_at",
    "notes",
]


def export_users(client: TestClient, headers: dict[str, str], expect: int = 200) -> str:
    response = client.post(f"{API}/users/export", headers=headers)
    assert response.status_code == expect, response.text
    return response.text


def test_the_users_are_a_file_for_an_admin_alone(
    client: TestClient, admin: dict[str, str], inventory: dict[str, str], viewer: dict[str, str]
) -> None:
    export_users(client, inventory, expect=403)
    export_users(client, viewer, expect=403)
    response = client.post(f"{API}/users/export", headers=admin)
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    name = response.headers["content-disposition"]
    assert name.startswith('attachment; filename="hirdir-users-')
    assert name.endswith('.csv"')
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["username"] for row in rows] == ["ada", "ivy", "vic"]
    assert [row["role"] for row in rows] == ["admin", "inventory", "viewer"]


def test_a_row_tells_the_person_the_role_in_force_the_groups_and_the_operators(
    client: TestClient, admin: dict[str, str], make: Maker
) -> None:
    people = Maker(client, admin)
    made = people.post(
        "/users",
        {
            "username": "ex-ops",
            "contact": {
                "name": "Example Person",
                "email": "example.person@example.net",
                "phone": "+1 555 0100",
                "phone2": "@desk",
            },
        },
    )["user"]
    service = people.post("/users", {"username": "ex-service", "is_service_account": True})
    people.post(f"/users/{service['user']['hid']}/service-tokens", {"name": "monitoring"})
    for name, role in (("Example Team; East", "inventory"), ("Example Readers", "viewer")):
        group = people.post("/user-groups", {"name": name})
        people.post("/role-grants", {"role": role, "group_hid": group["hid"]})
        response = client.put(
            f"{API}/user-groups/{group['hid']}/members/{made['hid']}", headers=admin
        )
        assert response.status_code == 204, response.text
    contact = made["contact_hid"]
    make.post("/operators", {"label": "EP", "contact_hid": contact})
    make.post("/operators", {"label": "ex-ops", "contact_hid": contact})
    gone = make.post("/operators", {"label": "EP-old", "contact_hid": contact})
    make.post(f"/operators/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)
    people.patch(f"/users/{made['hid']}", {"row_version": made["row_version"], "disabled": True})
    rows = {
        row["username"]: row for row in csv.DictReader(io.StringIO(export_users(client, admin)))
    }
    assert list(rows["ex-ops"]) == USER_COLUMNS
    assert rows["ex-ops"] == {
        "username": "ex-ops",
        "name": "Example Person",
        "email": "example.person@example.net",
        # A cell that a spreadsheet would run as a formula is guarded, as in every file.
        "phone": "'+1 555 0100",
        "phone2": "'@desk",
        "role": "inventory",
        "groups": "Example Readers;Example Team; East",
        "operators": "EP;ex-ops",
        "kind": "person",
        "state": "disabled",
        "last_sign_in_at": "",
        "notes": "",
    }
    assert rows["ex-service"] == {
        **dict.fromkeys(USER_COLUMNS, ""),
        "username": "ex-service",
        "kind": "service",
        "state": "enabled",
    }
    assert rows["ada"]["last_sign_in_at"].endswith("+00:00")


def test_the_users_file_holds_no_access_code_token_or_hash_and_is_audited(
    client: TestClient, admin: dict[str, str], db: Session
) -> None:
    people = Maker(client, admin)
    made = people.post("/users", {"username": "ex-person", "access_code": "a-secret-code-1"})
    service = people.post("/users", {"username": "ex-service", "is_service_account": True})
    token = people.post(f"/users/{service['user']['hid']}/service-tokens", {"name": "a tool"})
    text = export_users(client, admin)
    db.expire_all()
    secrets = [made["access_code"], token["secret"], admin["Authorization"].split()[1]]
    secrets += [hashed for hashed in db.scalars(select(User.access_code_hash)) if hashed]
    secrets += list(db.scalars(select(ServiceToken.token_hash)))
    # The new person's code, the token's secret, the Admin's own session, and the hashes
    # of the codes of the four people and of the token.
    assert len(secrets) >= 3 + 4 + 1
    for secret in secrets:
        assert secret not in text
    header, *rows = list(csv.reader(io.StringIO(text)))
    assert header == USER_COLUMNS
    assert len(rows) == 5
    assert all(len(row) == len(USER_COLUMNS) for row in rows)
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "export")))
    assert len(events) == 1
    assert (events[0].record_type, events[0].record_hid) == ("user", None)
    assert events[0].actor_hid == db.scalar(select(User.hid).where(User.username == "ada"))
    told = {entry["field"]: entry["new"] for entry in events[0].changes}
    assert told["users"] == 5
    assert told["file_name"].startswith("hirdir-users-")
