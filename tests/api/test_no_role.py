"""An account that holds no role does not sign in (P-299): the right code is refused
with whom to ask, a session and a token of such an account are refused, the last role
taken away ends the sessions, and a person is made and brought back with a role."""

from typing import Any

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.conftest import sign_in

CODE = "kim-lee-code-01"
NO_ROLE = "this account holds no role, and so cannot sign in: an Admin gives it one"


def _sign_in(client: TestClient, username: str, code: str) -> Any:
    return client.post(f"{API}/auth/sign-in", json={"username": username, "access_code": code})


def _grant(client: TestClient, admin: dict, **to: str) -> dict[str, Any]:
    return Maker(client, admin).post("/role-grants", {"role": "viewer", **to})


def _revoke(client: TestClient, admin: dict, grant: dict[str, Any]) -> None:
    assert client.delete(f"{API}/role-grants/{grant['hid']}", headers=admin).status_code == 204


def _roleless(client: TestClient, admin: dict, username: str = "klee") -> dict[str, Any]:
    """Make a person with a role, and take it away: an account that holds none."""
    desk = Maker(client, admin)
    user = desk.post("/users", {"username": username, "access_code": CODE, "role": "viewer"})
    grant = next(one for one in desk.get("/role-grants") if one["user_hid"] == user["user"]["hid"])
    _revoke(client, admin, grant)
    return user["user"]


def _events(client: TestClient, admin: dict, **params: str) -> list[dict[str, Any]]:
    return client.get(f"{API}/audit-events", params=params, headers=admin).json()["items"]


def _setting(client: TestClient, admin: dict, key: str, value: Any) -> None:
    listed = client.get(f"{API}/settings", headers=admin).json()
    version = next(one["row_version"] for one in listed if one["key"] == key)
    answer = client.put(
        f"{API}/settings/{key}", json={"row_version": version, "value": value}, headers=admin
    )
    assert answer.status_code == 200, answer.text


# --- signing in ----------------------------------------------------------------------


def test_the_right_code_with_no_role_is_a_403_with_whom_to_ask(
    client: TestClient, admin: dict
) -> None:
    user = _roleless(client, admin)
    refused = _sign_in(client, "klee", CODE)
    assert refused.status_code == 403, refused.text
    problem = refused.json()
    assert (problem["title"], problem["detail"], problem["errors"]) == ("No role", NO_ROLE, [])
    # Nobody named: each of the four is null, and the answer still says them.
    assert problem["help"] == {"organization": None, "email": None, "phone": None, "url": None}
    assert "token" not in problem

    # Whom to ask is given whatever `help_on_sign_in` says: the person gave the right code.
    _setting(client, admin, "help_phone", "+1 555 0100")
    _setting(client, admin, "help_on_sign_in", False)
    again = _sign_in(client, "KLEE", CODE).json()
    assert again["help"] == {
        "organization": None,
        "email": None,
        "phone": "+1 555 0100",
        "url": None,
    }

    events = _events(client, admin, action="sign_in_no_role")
    assert [(one["record_type"], one["record_hid"], one["actor_hid"]) for one in events] == [
        ("user", user["hid"], user["hid"])
    ] * 2
    assert [one["changes"] for one in events][-1] == [
        {"field": "username", "old": None, "new": "klee"}
    ]
    # It signed in nowhere: no session, and no time of a sign-in kept.
    assert Maker(client, admin).get(f"/users/{user['hid']}")["last_sign_in_at"] is None
    assert _events(client, admin, action="sign_in", record_hid=user["hid"]) == []


def test_every_other_refusal_is_as_it_was(client: TestClient, admin: dict) -> None:
    user = _roleless(client, admin)
    wrong = _sign_in(client, "klee", "not-the-code-01")
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "the username or access code was not accepted"
    assert "help" not in wrong.json()
    # Disabled, with no role and the right code, it is refused as disabled is.
    desk = Maker(client, admin)
    desk.patch(f"/users/{user['hid']}", {"row_version": user["row_version"], "disabled": True})
    disabled = _sign_in(client, "klee", CODE)
    assert (disabled.status_code, disabled.json()["title"]) == (401, "Sign-in refused")


def test_the_throttle_counts_it_a_success(client: TestClient, admin: dict) -> None:
    """Four wrong codes, the right one with no role, four more wrong: the count began
    again at the right one, so the last is not delayed."""
    _roleless(client, admin)
    for n in range(4):
        assert _sign_in(client, "klee", f"wrong-{n}").status_code == 401
    assert _sign_in(client, "klee", CODE).status_code == 403
    for n in range(4):
        assert _sign_in(client, "klee", f"again-{n}").status_code == 401
    assert _sign_in(client, "klee", "the-last-one").status_code == 401


# --- a role lost while signed in ---------------------------------------------------------


def test_a_session_with_no_role_is_ended_and_a_role_given_again_does_not_bring_it_back(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    user = desk.post("/users", {"username": "klee", "access_code": CODE, "role": "viewer"})
    kim = sign_in(client, "klee", CODE)
    grant = next(one for one in desk.get("/role-grants") if one["user_hid"] == user["user"]["hid"])
    _revoke(client, admin, grant)
    ended = client.get(f"{API}/auth/me", headers=kim)
    assert ended.status_code == 401
    assert ended.json()["detail"] == "the session has been ended: this account holds no role"
    # The grant's own event is all that is written of it.
    newest = _events(client, admin, record_hid=user["user"]["hid"])[0]
    assert newest["action"] == "revoke_role"
    _grant(client, admin, user_hid=user["user"]["hid"])
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    assert client.get(f"{API}/auth/me", headers=sign_in(client, "klee", CODE)).status_code == 200


def _in_a_group(client: TestClient, admin: dict) -> tuple[dict, dict, dict, dict]:
    """A person whose one role is its group's, signed in: the user, the group, the grant
    of the group and the session."""
    desk = Maker(client, admin)
    group = desk.post("/user-groups", {"name": "Example Stores"})
    grant = _grant(client, admin, group_hid=group["hid"])
    made = desk.post(
        "/users", {"username": "klee", "access_code": CODE, "group_hids": [group["hid"]]}
    )
    return made["user"], group, grant, sign_in(client, "klee", CODE)


def test_the_grant_of_its_group_revoked_ends_the_sessions(client: TestClient, admin: dict) -> None:
    _, group, grant, kim = _in_a_group(client, admin)
    _revoke(client, admin, grant)
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    _grant(client, admin, group_hid=group["hid"])
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401


def test_taken_out_of_its_group_the_sessions_end(client: TestClient, admin: dict) -> None:
    user, group, _, kim = _in_a_group(client, admin)
    path = f"{API}/user-groups/{group['hid']}/members/{user['hid']}"
    assert client.delete(path, headers=admin).status_code == 204
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    assert client.put(path, headers=admin).status_code == 204
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    assert client.get(f"{API}/auth/me", headers=sign_in(client, "klee", CODE)).status_code == 200


def test_its_group_deleted_the_sessions_end(client: TestClient, admin: dict) -> None:
    user, group, _, kim = _in_a_group(client, admin)
    assert client.delete(f"{API}/user-groups/{group['hid']}", headers=admin).status_code == 204
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    _grant(client, admin, user_hid=user["hid"])
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401


def test_a_role_that_is_not_the_last_ends_nothing(client: TestClient, admin: dict) -> None:
    user, _, grant, kim = _in_a_group(client, admin)
    Maker(client, admin).post("/role-grants", {"role": "inventory", "user_hid": user["hid"]})
    _revoke(client, admin, grant)
    me = client.get(f"{API}/auth/me", headers=kim)
    assert (me.status_code, me.json()["role"]) == (200, "inventory")


def test_a_service_account_with_no_role_has_its_tokens_refused(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    robot = desk.post("/users", {"username": "robot", "is_service_account": True})["user"]
    # An Admin makes a token for it all the same: it works once a role is given.
    made = desk.post(f"/users/{robot['hid']}/service-tokens", {"name": "nightly"})
    token = {"Authorization": f"Bearer {made['secret']}"}
    refused = client.get(f"{API}/auth/me", headers=token)
    assert refused.status_code == 401
    assert (
        refused.json()["detail"] == "the token is not accepted: its service account holds no role"
    )
    grant = _grant(client, admin, user_hid=robot["hid"])
    assert client.get(f"{API}/auth/me", headers=token).status_code == 200
    _revoke(client, admin, grant)
    assert client.get(f"{API}/auth/me", headers=token).status_code == 401


# --- made and brought back with a role ---------------------------------------------------


def test_a_person_is_made_with_a_role_and_a_service_account_may_have_none(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    users = desk.get("/users", limit=1)["total"]
    contacts = desk.get("/contacts", limit=1)["total"]
    bare = client.post(
        f"{API}/users",
        headers=admin,
        json={"username": "klee", "contact": {"name": "Kim Lee"}, "operator": {}},
    )
    assert bare.status_code == 422, bare.text
    assert errors(bare.json()) == {"role": "give a role, or a group that grants one"}
    # A group that grants nothing is no role either.
    label = desk.post("/user-groups", {"name": "Example Label"})
    labelled = client.post(
        f"{API}/users", headers=admin, json={"username": "klee", "group_hids": [label["hid"]]}
    )
    assert labelled.status_code == 422
    assert desk.get("/users", limit=1)["total"] == users
    assert desk.get("/contacts", limit=1)["total"] == contacts
    _grant(client, admin, group_hid=label["hid"])
    desk.post("/users", {"username": "klee", "group_hids": [label["hid"]]})
    desk.post("/users", {"username": "robot", "is_service_account": True})


def _retired(client: TestClient, admin: dict, **more: Any) -> dict[str, Any]:
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "klee", "role": "inventory", **more})["user"]
    return desk.post(f"/users/{made['hid']}/retire", {"row_version": made["row_version"]}, 200)


def test_a_person_is_brought_back_with_a_role(client: TestClient, admin: dict) -> None:
    user = _retired(client, admin)
    path = f"{API}/users/{user['hid']}/bring-back"
    events = client.get(f"{API}/audit-events", params={"limit": 1}, headers=admin).json()["total"]
    for body in ({}, {"role": None}, {"role": ""}):
        refused = client.post(
            path, headers=admin, json={"row_version": user["row_version"], **body}
        )
        assert refused.status_code == 422, refused.text
        assert errors(refused.json()) == {"role": "give the role the account is to hold"}
    wrong = client.post(
        path, headers=admin, json={"row_version": user["row_version"], "role": "root"}
    )
    assert errors(wrong.json()) == {"role": "viewer, inventory or admin"}
    # Nothing changed, and nothing was written.
    desk = Maker(client, admin)
    assert desk.get(f"/users/{user['hid']}")["record_status"] == "retired"
    assert desk.get("/audit-events", limit=1)["total"] == events

    back = client.post(
        path, headers=admin, json={"row_version": user["row_version"], "role": "viewer"}
    )
    assert back.status_code == 200, back.text
    assert (back.json()["user"]["role"], back.json()["user"]["groups"]) == ("viewer", [])
    trail = _events(client, admin, request_id=back.headers["x-request-id"])
    assert [(one["action"], one["record_type"]) for one in reversed(trail)] == [
        ("bring_back", "user"),
        ("grant_role", "user"),
    ]
    kim = sign_in(client, "klee", back.json()["access_code"])
    assert client.get(f"{API}/auth/me", headers=kim).json()["role"] == "viewer"


def test_a_service_account_is_brought_back_with_or_without_a_role(
    client: TestClient, admin: dict
) -> None:
    user = _retired(client, admin, is_service_account=True)
    desk = Maker(client, admin)
    back = desk.post(f"/users/{user['hid']}/bring-back", {"row_version": user["row_version"]}, 200)
    assert (back["user"]["role"], back["access_code"]) == (None, None)
