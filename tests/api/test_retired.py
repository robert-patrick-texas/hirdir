"""A retired account (P-292, P-296): what retiring takes away, what is refused of a
retired account, where it is left out, and how it is brought back. Through the API."""

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth import codes
from hirdir.db.models import User
from tests.api.inventory import API, Maker, errors
from tests.conftest import INVENTORY_CODE, sign_in

CODE = "kim-lee-code-01"


def person(desk: Maker, username: str = "klee", name: str = "Kim Lee", **more: Any) -> dict:
    """Make a user who is a contact, with a code to sign in with."""
    email = f"{name.lower().replace(' ', '.')}@example.com"
    body = {
        "username": username,
        "contact": {"name": name, "email": email},
        "access_code": CODE,
        "role": "viewer",
        **more,
    }
    return desk.post("/users", body)["user"]


def retire(desk: Maker, user: dict, expect: int = 200, **linked: Any) -> dict:
    now = desk.get(f"/users/{user['hid']}")
    body: dict[str, Any] = {"row_version": now["row_version"]}
    if linked:
        body["linked"] = linked
    return desk.post(f"/users/{user['hid']}/retire", body, expect)


def bring_back(desk: Maker, user: dict, expect: int = 200, **linked: Any) -> dict:
    """Bring a user back with what is linked, as View-only: a person is brought back with
    a role (P-299)."""
    now = desk.get(f"/users/{user['hid']}")
    body: dict[str, Any] = {"row_version": now["row_version"], "role": "viewer"}
    if linked:
        body["linked"] = linked
    return desk.post(f"/users/{user['hid']}/bring-back", body, expect)


def events(desk: Maker, **params: Any) -> list[tuple[str, str, str | None]]:
    """The events that match, oldest first: the action, the kind and the record."""
    found = desk.audit(limit=200, **params)
    return [(one["action"], one["record_type"], one["record_hid"]) for one in reversed(found)]


# --- retiring an account ---------------------------------------------------------------


def test_retiring_an_account_takes_away_what_it_could_do_each_audited(
    client: TestClient, admin: dict, db: Session
) -> None:
    desk = Maker(client, admin)
    east = desk.post("/user-groups", {"name": "Example East"})
    west = desk.post("/user-groups", {"name": "Example West"})
    desk.post("/role-grants", {"role": "viewer", "group_hid": east["hid"]})
    kim = person(desk, role="inventory", group_hids=[east["hid"], west["hid"]])
    session = sign_in(client, "klee", CODE)
    assert client.get(f"{API}/auth/me", headers=session).json()["role"] == "inventory"

    response = client.post(
        f"{API}/users/{kim['hid']}/retire",
        json={"row_version": kim["row_version"], "linked": {"contact": "keep"}},
        headers=admin,
    )
    assert response.status_code == 200, response.text
    retired = response.json()
    assert retired["record_status"] == "retired"
    assert (retired["role"], retired["groups"], retired["disabled"]) == (None, [], False)
    # Its session is ended, and it signs in with nothing: as an unknown account is told.
    assert client.get(f"{API}/auth/me", headers=session).status_code == 401
    refused = client.post(f"{API}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    unknown = client.post(f"{API}/auth/sign-in", json={"username": "nobody", "access_code": CODE})
    assert refused.status_code == unknown.status_code == 401
    assert refused.json() == unknown.json()
    # The code is erased.
    db.expire_all()
    assert db.scalar(select(User.access_code_hash).where(User.hid == kim["hid"])) is None
    # Neither group has it, and the group's own role stays the group's.
    assert desk.get(f"/user-groups/{east['hid']}")["members"] == []
    assert desk.get(f"/user-groups/{east['hid']}")["roles"] == ["viewer"]
    assert [one for one in desk.get("/role-grants") if one["user_hid"] == kim["hid"]] == []
    # One request, an event to each thing done, as when it is done by itself.
    request = response.headers["x-request-id"]
    assert events(desk, request_id=request) == [
        ("remove_member", "user_group", east["hid"]),
        ("remove_member", "user_group", west["hid"]),
        ("revoke_role", "user", kim["hid"]),
        ("retire", "user", kim["hid"]),
        # Its contact is told that it is no user's now, as it was told that it was one.
        ("update", "contact", kim["contact_hid"]),
    ]
    told = desk.audit(request_id=request, record_type="contact")[0]["changes"]
    assert told == [{"field": "user_record_status", "old": "active", "new": "retired"}]
    last = desk.audit(request_id=request, action="retire")[0]
    assert last["changes"] == [{"field": "record_status", "old": "active", "new": "retired"}]
    left = desk.audit(request_id=request, action="remove_member")[0]["changes"]
    assert left == [{"field": "user_hid", "old": kim["hid"], "new": None}]


def test_retiring_a_service_account_revokes_its_tokens(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    tool = desk.post(
        "/users", {"username": "ex-tool", "is_service_account": True, "role": "viewer"}
    )
    made = desk.post(f"/users/{tool['user']['hid']}/service-tokens", {"name": "a tool"})
    old = desk.post(f"/users/{tool['user']['hid']}/service-tokens", {"name": "an old tool"})
    desk.post(f"/service-tokens/{old['token']['hid']}/revoke", {}, 200)
    bearer = {"Authorization": f"Bearer {made['secret']}"}
    assert client.get(f"{API}/auth/me", headers=bearer).status_code == 200

    response = client.post(
        f"{API}/users/{tool['user']['hid']}/retire",
        json={"row_version": tool["user"]["row_version"]},
        headers=admin,
    )
    assert response.status_code == 200, response.text
    assert client.get(f"{API}/auth/me", headers=bearer).status_code == 401
    tokens = desk.get(f"/users/{tool['user']['hid']}/service-tokens")
    assert all(one["revoked_at"] is not None for one in tokens)
    # The token that was revoked before is not revoked again.
    assert events(desk, request_id=response.headers["x-request-id"]) == [
        ("revoke_role", "user", tool["user"]["hid"]),
        ("revoke", "service_token", made["token"]["hid"]),
        ("retire", "user", tool["user"]["hid"]),
    ]
    # Brought back, it has no code, as no service account has, and no token that works.
    back = bring_back(desk, tool["user"])
    assert (back["access_code"], back["user"]["record_status"]) == (None, "active")
    assert client.get(f"{API}/auth/me", headers=bearer).status_code == 401


def test_the_last_admin_is_not_retired_and_nothing_of_it_is_changed(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    group = desk.post("/user-groups", {"name": "Example Admins"})
    ada = desk.get("/auth/me")
    desk.client.put(f"{API}/user-groups/{group['hid']}/members/{ada['hid']}", headers=admin)
    before = desk.get("/audit-events", limit=1)["total"]
    refused = retire(desk, ada, 409)
    assert "no Admin" in refused["detail"]
    now = desk.get(f"/users/{ada['hid']}")
    assert (now["record_status"], now["role"], now["row_version"]) == (
        "active",
        "admin",
        ada["row_version"],
    )
    # It is in its group still: what was done before the refusal is undone with it.
    assert [one["name"] for one in now["groups"]] == ["Example Admins"]
    assert desk.get("/audit-events", limit=1)["total"] == before
    # With another Admin there, it is retired, by itself too.
    person(desk, "sokafor", "Sam Okafor", role="admin")
    assert retire(desk, ada)["record_status"] == "retired"
    assert client.get(f"{API}/auth/me", headers=admin).status_code == 401


def test_who_retires_an_account_and_what_refuses_it(
    client: TestClient, admin: dict, inventory: dict, viewer: dict
) -> None:
    desk = Maker(client, admin)
    kim = desk.post("/users", {"role": "viewer", "username": "klee", "access_code": CODE})["user"]
    body = {"row_version": kim["row_version"]}
    for headers in (inventory, viewer):
        response = client.post(f"{API}/users/{kim['hid']}/retire", json=body, headers=headers)
        assert response.status_code == 403
        response = client.post(f"{API}/users/{kim['hid']}/bring-back", json=body, headers=headers)
        assert response.status_code == 403
    desk.post("/users/no-such-user/retire", body, 404)
    # A stale copy is refused, and nothing is changed.
    stale = desk.post(f"/users/{kim['hid']}/retire", {"row_version": kim["row_version"] + 1}, 409)
    assert stale["title"] == "Stale version"
    assert desk.get(f"/users/{kim['hid']}")["record_status"] == "active"
    retired = desk.post(f"/users/{kim['hid']}/retire", body, 200)
    # Retired already.
    again = desk.post(f"/users/{kim['hid']}/retire", {"row_version": retired["row_version"]}, 409)
    assert "retired already" in again["detail"]
    # One that is not retired is not brought back.
    ivy = next(one for one in desk.get("/users")["items"] if one["username"] == "ivy")
    refused = bring_back(desk, ivy, 409)
    assert "not retired" in refused["detail"]


def test_a_disabled_account_stays_disabled_when_retired_and_is_enabled_when_brought_back(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    kim = desk.post("/users", {"username": "klee", "access_code": CODE, "role": "viewer"})["user"]
    off = desk.patch(f"/users/{kim['hid']}", {"row_version": kim["row_version"], "disabled": True})
    retired = retire(desk, off)
    assert (retired["disabled"], retired["record_status"]) == (True, "retired")
    back = bring_back(desk, retired)
    assert (back["user"]["disabled"], back["user"]["record_status"]) == (False, "active")
    changes = desk.audit(record_hid=kim["hid"], action="bring_back")[0]["changes"]
    assert changes == [
        {"field": "record_status", "old": "retired", "new": "active"},
        {"field": "disabled", "old": True, "new": False},
    ]


# --- what a retired account is, and is not, given --------------------------------------


def test_a_retired_account_is_refused_as_an_unknown_one_in_the_same_way(
    client: TestClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = Maker(client, admin)
    kim = desk.post("/users", {"username": "klee", "access_code": CODE, "role": "viewer"})["user"]
    retire(desk, kim)
    checked: list[str | None] = []
    real = codes.verify

    def verify(stored: str | None, code: str) -> bool:
        checked.append(stored)
        return real(stored, code)

    monkeypatch.setattr(codes, "verify", verify)
    for name in ("klee", "nobody"):
        response = client.post(f"{API}/auth/sign-in", json={"username": name, "access_code": CODE})
        assert response.status_code == 401
    # Each is checked against the hash that no code has: the same work, the same time.
    assert checked == [None, None]
    failed = desk.audit(action="sign_in_failed")
    assert [one["record_hid"] for one in failed] == [None, kim["hid"]]


def test_what_is_changed_of_a_retired_account_and_what_it_is_not_given(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    group = desk.post("/user-groups", {"name": "Example East"})
    kim = person(desk, role="viewer")
    other = desk.contact("Sam Okafor")
    tool = desk.post("/users", {"username": "ex-tool", "is_service_account": True})["user"]
    retire(desk, tool)
    gone = retire(desk, kim, contact="keep")
    path = f"/users/{kim['hid']}"

    def refused(response: Any) -> str:
        assert response.status_code == 409, response.text
        return response.json()["detail"]

    patched = desk.patch(path, {"row_version": gone["row_version"], "disabled": True}, 409)
    assert "retired" in patched["detail"]
    assert "disabled" in errors(patched)
    patched = desk.patch(
        path, {"row_version": gone["row_version"], "contact_hid": other["hid"]}, 409
    )
    assert "retired" in patched["detail"]
    assert "contact_hid" in errors(patched)
    assert "retired" in refused(client.post(f"{API}{path}/access-code", json={}, headers=admin))
    assert "retired" in refused(
        client.post(
            f"{API}/users/{tool['hid']}/service-tokens", json={"name": "a tool"}, headers=admin
        )
    )
    assert "retired" in refused(
        client.put(f"{API}/user-groups/{group['hid']}/members/{kim['hid']}", headers=admin)
    )
    granted = desk.post("/role-grants", {"role": "viewer", "user_hid": kim["hid"]}, 409)
    assert "retired" in granted["detail"]
    assert "user_hid" in errors(granted)
    now = desk.get(path)
    assert (now["role"], now["groups"], now["row_version"]) == (None, [], gone["row_version"])

    # Its username, its notes and its contact taken off are what is changed of it.
    renamed = desk.patch(
        path, {"row_version": now["row_version"], "username": "klee-left", "notes": "Left in 2026."}
    )
    assert (renamed["username"], renamed["notes"]) == ("klee-left", "Left in 2026.")
    # The value it has already is no change, and is not refused.
    same = desk.patch(
        path,
        {
            "row_version": renamed["row_version"],
            "disabled": False,
            "contact_hid": kim["contact_hid"],
        },
    )
    assert same["row_version"] == renamed["row_version"]
    bare = desk.patch(path, {"row_version": same["row_version"], "contact_hid": None})
    assert (bare["contact"], bare["record_status"]) == (None, "retired")


def test_a_username_stays_the_retired_accounts_until_it_is_renamed(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    kim = desk.post("/users", {"role": "viewer", "username": "klee", "access_code": CODE})["user"]
    gone = retire(desk, kim)
    refused = desk.post("/users", {"role": "viewer", "username": "KLee"}, 409)
    assert "retired" in refused["detail"]
    assert "retired" in errors(refused)["username"]
    assert refused["existing"] == {"hid": kim["hid"], "record_type": "user", "label": "klee"}
    sam = desk.post("/users", {"role": "viewer", "username": "sokafor"})["user"]
    refused = desk.patch(
        f"/users/{sam['hid']}", {"row_version": sam["row_version"], "username": "klee"}, 409
    )
    assert refused["existing"]["hid"] == kim["hid"]
    assert "retired" in errors(refused)["username"]
    # An account that is not retired refuses the name in other words, as before.
    plain = desk.post("/users", {"role": "viewer", "username": "sokafor"}, 409)
    assert "retired" not in plain["detail"]
    # The Admin renames the retired one, and the name is free.
    desk.patch(
        f"/users/{kim['hid']}", {"row_version": gone["row_version"], "username": "klee-2026"}
    )
    assert desk.post("/users", {"role": "viewer", "username": "klee"})["user"]["username"] == "klee"


# --- where a retired account is left out ----------------------------------------------


def _names(page: dict) -> list[str]:
    return [one["username"] for one in page["items"]]


def test_the_list_of_users_leaves_the_retired_out_until_they_are_asked_for(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    kim = person(desk)
    desk.post("/users", {"role": "viewer", "username": "sokafor"})
    retire(desk, kim, contact="keep")
    assert _names(desk.get("/users")) == ["ada", "ivy", "sokafor", "vic"]
    assert _names(desk.get("/users", retired="no")) == ["ada", "ivy", "sokafor", "vic"]
    everyone = desk.get("/users", retired="yes")
    assert _names(everyone) == ["ada", "ivy", "klee", "sokafor", "vic"]
    assert everyone["total"] == 5
    statuses = {one["username"]: one["record_status"] for one in everyone["items"]}
    assert statuses["klee"] == "retired"
    assert statuses["ada"] == "active"
    alone = desk.get("/users", retired="only")
    assert (_names(alone), alone["total"]) == (["klee"], 1)
    assert desk.get("/users", retired="only", q="lee")["total"] == 1
    assert desk.get("/users", q="lee")["total"] == 0
    # A retired account is in no gap, whatever is asked of the retired.
    for retired in ("no", "yes", "only"):
        assert "klee" not in _names(desk.get("/users", retired=retired, contact="none"))
        assert "klee" not in _names(desk.get("/users", retired=retired, operator="none"))
    assert "sokafor" in _names(desk.get("/users", retired="yes", contact="none"))
    # `some` is by the contact, as before: the retired account still has its own.
    assert _names(desk.get("/users", retired="only", contact="some")) == ["klee"]
    assert _names(desk.get("/users", contact="some")) == []
    refused = desk.get("/users", 422, retired="maybe")
    assert "query.retired" in errors(refused)
    # One is read by its HID as before, retired or not.
    assert desk.get(f"/users/{kim['hid']}")["record_status"] == "retired"


def _file(client: TestClient, admin: dict, **params: str) -> list[dict[str, str]]:
    response = client.post(f"{API}/users/export", params=params, headers=admin)
    assert response.status_code == 200, response.text
    return list(csv.DictReader(io.StringIO(response.text)))


def test_the_users_file_leaves_the_retired_out_until_they_are_asked_for(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    kim = person(desk)
    retire(desk, kim, contact="keep")
    rows = _file(client, admin)
    assert [row["username"] for row in rows] == ["ada", "ivy", "vic"]
    assert {row["record_status"] for row in rows} == {"active"}
    rows = _file(client, admin, retired="yes")
    assert [(row["username"], row["record_status"]) for row in rows] == [
        ("ada", "active"),
        ("ivy", "active"),
        ("klee", "retired"),
        ("vic", "active"),
    ]
    assert [row["username"] for row in _file(client, admin, retired="only")] == ["klee"]
    # The audit event counts what the file holds.
    counted = [
        next(change["new"] for change in one["changes"] if change["field"] == "users")
        for one in reversed(desk.audit(action="export", record_type="user"))
    ]
    assert counted == [3, 4, 1]
    response = client.post(f"{API}/users/export", params={"retired": "maybe"}, headers=admin)
    assert response.status_code == 422


def test_a_retired_account_is_no_user_of_its_contact_and_is_shown_still(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    kim = person(desk)
    label = desk.post("/operators", {"label": "KL", "contact_hid": kim["contact_hid"]})
    contact = desk.get(f"/contacts/{kim['contact_hid']}")
    assert (contact["is_user"], desk.get(f"/operators/{label['hid']}")["scope"]) == (
        True,
        "internal",
    )
    retire(desk, kim, contact="keep", operators=[{"hid": label["hid"], "action": "keep"}])
    shown = {"hid": kim["hid"], "username": "klee", "record_status": "retired"}
    contact = desk.get(f"/contacts/{kim['contact_hid']}")
    assert (contact["is_user"], contact["user"]) == (False, shown)
    operator = desk.get(f"/operators/{label['hid']}")
    assert (operator["scope"], operator["user"], operator["is_open"]) == ("external", shown, False)
    # The lists filter by the same.
    assert desk.get("/contacts", filter="is_user:eq:true")["total"] == 0
    assert desk.get("/operators", filter="scope:eq:internal")["total"] == 0
    assert [
        one["label"] for one in desk.get("/operators", filter="scope:eq:external")["items"]
    ] == ["KL"]
    # The contact is still the retired account's: no other user is given it.
    refused = desk.post(
        "/users", {"role": "viewer", "username": "klee2", "contact_hid": kim["contact_hid"]}, 409
    )
    assert "retired account klee" in refused["detail"]
    assert refused["existing"] == {"hid": kim["hid"], "record_type": "user", "label": "klee"}
    # Taken off the retired account, it is another's to have.
    now = desk.get(f"/users/{kim['hid']}")
    desk.patch(f"/users/{kim['hid']}", {"row_version": now["row_version"], "contact_hid": None})
    made = desk.post(
        "/users", {"role": "viewer", "username": "klee2", "contact_hid": kim["contact_hid"]}
    )["user"]
    assert made["contact_hid"] == kim["contact_hid"]


# --- bringing an account back ----------------------------------------------------------


def test_an_account_brought_back_has_a_new_code_the_role_given_and_no_group(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    group = desk.post("/user-groups", {"name": "Example East"})
    kim = person(desk, role="inventory", group_hids=[group["hid"]])
    old = sign_in(client, "klee", CODE)
    retire(desk, kim, contact="keep")
    response = client.post(
        f"{API}/users/{kim['hid']}/bring-back",
        json={"row_version": desk.get(f"/users/{kim['hid']}")["row_version"], "role": "viewer"},
        headers=admin,
    )
    assert response.status_code == 200, response.text
    back = response.json()
    assert back["user"]["record_status"] == "active"
    # What it held was taken away; the role given comes with it, and no group (P-299).
    assert (back["user"]["role"], back["user"]["groups"]) == ("viewer", [])
    assert back["access_code"]
    assert back["access_code"] != CODE
    # The old code and the old session are gone; the new code signs in, with its role.
    refused = client.post(f"{API}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    assert refused.status_code == 401
    assert client.get(f"{API}/auth/me", headers=old).status_code == 401
    new = sign_in(client, "klee", back["access_code"])
    assert client.get(f"{API}/auth/me", headers=new).json()["role"] == "viewer"
    assert events(desk, request_id=response.headers["x-request-id"]) == [
        ("bring_back", "user", kim["hid"]),
        ("update", "contact", kim["contact_hid"]),
        ("grant_role", "user", kim["hid"]),
    ]
    # It is given a group again, as any account is.
    put = client.put(f"{API}/user-groups/{group['hid']}/members/{kim['hid']}", headers=admin)
    assert put.status_code == 204
    assert client.get(f"{API}/auth/me", headers=new).json()["role"] == "viewer"
    # And it is in the list and its gaps again.
    assert "klee" in _names(desk.get("/users"))
    assert "klee" in _names(desk.get("/users", operator="none"))
    # An Inventory user neither retires nor brings back.
    ivy = sign_in(client, "ivy", INVENTORY_CODE)
    response = client.post(
        f"{API}/users/{kim['hid']}/bring-back", json={"row_version": 1}, headers=ivy
    )
    assert response.status_code == 403


def test_a_kept_answer_is_worked_out_again_when_an_account_is_retired_and_brought_back(
    client: TestClient, admin: dict, make: Maker
) -> None:
    """What a kept answer shows of an operator, internal or external, follows the account
    of who is behind it: the contact is told, and so the answer is no longer good."""
    from hirdir.io import kept

    kept.drop()
    desk = Maker(client, admin)
    kim = person(desk)
    label = make.post("/operators", {"label": "KL", "contact_hid": kim["contact_hid"]})
    make.item(name="site2-sw-01", operator_hid=label["hid"], lifecycle_state="Prod")
    first = make.get("/reports/coverage", section="uncovered")
    assert first["items"][0]["operator"]["scope"] == "internal"
    retire(desk, kim, contact="keep", operators=[{"hid": label["hid"], "action": "keep"}])
    again = make.get("/reports/coverage", section="uncovered")
    assert again["items"][0]["operator"]["scope"] == "external"
    bring_back(desk, kim)
    back = make.get("/reports/coverage", section="uncovered")
    assert back["items"][0]["operator"]["scope"] == "internal"
    assert desk.post("/kept-answers/check", {}, 200)["differed"] == []
