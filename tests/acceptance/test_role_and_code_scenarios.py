"""Scenarios S59 and S60 of docs/build-plan.md, against a real server process: an account
that holds no role does not sign in, and an access code is not the one it replaces and
may be made by the server (R12.3, R12.9, P-299, P-300)."""

from typing import Any

import httpx2

from tests.acceptance.conftest import ADMIN, Server

CODE = "kim-lee-code-01"
NO_ROLE = "this account holds no role, and so cannot sign in: an Admin gives it one"


def _sign_in(server: Server, username: str, code: str) -> httpx2.Response:
    return httpx2.post(
        f"{server.url}/auth/sign-in", json={"username": username, "access_code": code}
    )


def _errors(response: httpx2.Response) -> dict[str, str]:
    return {entry["field"]: entry["message"] for entry in response.json()["errors"]}


def _put(admin: httpx2.Client, key: str, value: Any) -> None:
    listed = admin.get("/settings").json()
    version = next(one["row_version"] for one in listed if one["key"] == key)
    answer = admin.put(f"/settings/{key}", json={"row_version": version, "value": value})
    assert answer.status_code == 200, answer.text


def _total(admin: httpx2.Client, path: str, **params: str) -> int:
    return admin.get(path, params={"limit": 1, **params}).json()["total"]


def test_s59_an_account_with_no_role_does_not_sign_in(server: Server) -> None:
    """S59 (R12.3): the right code with no role is refused with whom to ask, and is in
    the audit trail; a role lost through a group ends the session at the next request,
    and signing in works again once one is given; a person is not made, nor brought
    back, with no role (P-299)."""
    admin = server.sign_in(*ADMIN)
    _put(admin, "help_organization", "Example Network Tools")
    _put(admin, "help_email", "tools@example.net")

    # Made with no role by `hirdir admin`, with --no-role (P-313): refused, and told.
    server.admin("create-user", "nrole", "--no-role", "--access-code", "no-role-code-01")
    refused = _sign_in(server, "nrole", "no-role-code-01")
    assert refused.status_code == 403, refused.text
    problem = refused.json()
    assert (problem["title"], problem["detail"]) == ("No role", NO_ROLE)
    assert problem["help"] == {
        "organization": "Example Network Tools",
        "email": "tools@example.net",
        "phone": None,
        "url": None,
    }
    assert "token" not in problem
    events = admin.get("/audit-events", params={"action": "sign_in_no_role"}).json()["items"]
    assert len(events) == 1
    nrole = next(one for one in admin.get("/users").json()["items"] if one["username"] == "nrole")
    assert (events[0]["record_hid"], events[0]["actor_hid"]) == (nrole["hid"], nrole["hid"])
    # A wrong code is refused as ever, and says nothing of the role.
    wrong = _sign_in(server, "nrole", "not-the-code-01")
    assert wrong.status_code == 401
    assert "help" not in wrong.json()

    # An Inventory user whose role is its group's: revoked, it is signed out at once.
    group = admin.post("/user-groups", json={"name": "Example Stores"}).json()
    grant = admin.post("/role-grants", json={"role": "inventory", "group_hid": group["hid"]})
    assert grant.status_code == 201, grant.text
    made = admin.post(
        "/users", json={"username": "klee", "access_code": CODE, "group_hids": [group["hid"]]}
    )
    assert made.status_code == 201, made.text
    kim = server.sign_in("klee", CODE)
    assert kim.get("/auth/me").json()["role"] == "inventory"
    assert admin.delete(f"/role-grants/{grant.json()['hid']}").status_code == 204
    ended = kim.get("/auth/me")
    assert ended.status_code == 401
    # Ended by the revocation, it says no more than that (P-299).
    assert ended.json()["detail"] == "the session has been ended"
    assert _sign_in(server, "klee", CODE).status_code == 403
    # Given a role again, the person signs in; the old session stays ended.
    again = admin.post("/role-grants", json={"role": "inventory", "group_hid": group["hid"]})
    assert again.status_code == 201, again.text
    assert kim.get("/auth/me").status_code == 401
    assert server.sign_in("klee", CODE).get("/auth/me").json()["role"] == "inventory"

    # New user: a person with no role, and no group that grants one, is not made.
    users = _total(admin, "/users")
    bare = admin.post("/users", json={"username": "sokafor", "access_code": "sam-okafor-01"})
    assert bare.status_code == 422, bare.text
    assert _errors(bare) == {"role": "give a role, or a group that grants one"}
    assert _total(admin, "/users") == users

    # Bring back: without a role refused, nothing changed; with one, it signs in holding it.
    user = made.json()["user"]
    retired = admin.post(f"/users/{user['hid']}/retire", json={"row_version": user["row_version"]})
    assert retired.status_code == 200, retired.text
    version = retired.json()["row_version"]
    no_role = admin.post(f"/users/{user['hid']}/bring-back", json={"row_version": version})
    assert no_role.status_code == 422, no_role.text
    assert set(_errors(no_role)) == {"role"}
    assert admin.get(f"/users/{user['hid']}").json()["record_status"] == "retired"
    back = admin.post(
        f"/users/{user['hid']}/bring-back", json={"row_version": version, "role": "viewer"}
    )
    assert back.status_code == 200, back.text
    assert back.json()["user"]["role"] == "viewer"
    signed = server.sign_in("klee", back.json()["access_code"])
    assert signed.get("/auth/me").json()["role"] == "viewer"


def test_s60_a_new_code_is_not_the_current_one_and_may_be_made(server: Server) -> None:
    """S60 (R12.9): the code in hand as the new one is refused and changes nothing; a
    code made by the server meets a raised least length and is taken; an Admin changes
    their own code with the current one; and an Admin sets somebody's code to the one
    they had (P-300)."""
    admin = server.sign_in(*ADMIN)
    made = admin.post("/users", json={"username": "klee", "access_code": CODE, "role": "viewer"})
    assert made.status_code == 201, made.text
    hid = made.json()["user"]["hid"]
    kim = server.sign_in("klee", CODE)

    same = kim.post("/auth/me/access-code", json={"current_access_code": CODE, "access_code": CODE})
    assert same.status_code == 422, same.text
    assert _errors(same) == {"access_code": "this is the access code you have now"}
    assert kim.get("/auth/me").status_code == 200
    assert _sign_in(server, "klee", CODE).status_code == 200

    # A made code, with the least length raised to 20: stored nowhere, written nowhere.
    _put(admin, "access_code_min_length", 20)
    events = _total(admin, "/audit-events")
    asked = kim.get("/auth/new-access-code")
    assert asked.status_code == 200, asked.text
    assert asked.headers["cache-control"] == "no-store"
    code = asked.json()["access_code"]
    assert len(code) >= 20
    assert _total(admin, "/audit-events") == events
    taken = kim.post(
        "/auth/me/access-code", json={"current_access_code": CODE, "access_code": code}
    )
    assert taken.status_code == 200, taken.text
    assert _sign_in(server, "klee", code).status_code == 200
    assert _sign_in(server, "klee", CODE).status_code == 401

    # An Admin changes their own code on the profile as anybody does, with the current one.
    mine = "acceptance-admin-two"
    wrong = admin.post(
        "/auth/me/access-code", json={"current_access_code": "not-the-code-01", "access_code": mine}
    )
    assert wrong.status_code == 422
    assert set(_errors(wrong)) == {"current_access_code"}
    changed = admin.post(
        "/auth/me/access-code", json={"current_access_code": ADMIN[1], "access_code": mine}
    )
    assert changed.status_code == 200, changed.text
    admin = server.sign_in(ADMIN[0], mine)

    # An Admin sets the code of somebody else to the one they had: it is taken.
    again = admin.post(f"/users/{hid}/access-code", json={"access_code": code})
    assert again.status_code == 200, again.text
    assert again.json()["access_code"] == code
    assert _sign_in(server, "klee", code).status_code == 200
