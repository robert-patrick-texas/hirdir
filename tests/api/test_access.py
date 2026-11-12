"""Signing in, sessions, roles and the throttle, through the API."""

from fastapi.testclient import TestClient

from tests.conftest import ADMIN_CODE, VIEWER_CODE, sign_in

API = "/api/v1"


def test_health_needs_no_sign_in(client: TestClient) -> None:
    assert client.get(f"{API}/health/live").json() == {"status": "ok", "detail": ""}
    assert client.get(f"{API}/health/ready").status_code == 200


def test_everything_else_needs_a_sign_in(client: TestClient) -> None:
    for path in ("/auth/me", "/users", "/user-groups", "/role-grants", "/audit-events", "/about"):
        response = client.get(API + path)
        assert response.status_code == 401, path
        assert response.headers["content-type"] == "application/problem+json"
    assert client.get(f"{API}/openapi.json").status_code == 401


def test_sign_in_returns_a_session_and_the_role(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/sign-in", json={"username": "ADA", "access_code": ADMIN_CODE}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["user"]["username"] == "ada"
    assert body["user"]["role"] == "admin"
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json()["hid"] == body["user"]["hid"]


def test_wrong_code_and_unknown_user_get_the_same_answer(client: TestClient) -> None:
    wrong = client.post(f"{API}/auth/sign-in", json={"username": "ada", "access_code": "nope"})
    unknown = client.post(f"{API}/auth/sign-in", json={"username": "nobody", "access_code": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_garbage_and_missing_tokens_are_refused(client: TestClient) -> None:
    for header in ("Bearer nonsense", "Bearer ", "Basic abc", "hsv_whatever"):
        assert client.get(f"{API}/auth/me", headers={"Authorization": header}).status_code == 401


def test_viewer_cannot_manage_accounts(client: TestClient, viewer: dict) -> None:
    assert client.get(f"{API}/users", headers=viewer).status_code == 403
    created = client.post(f"{API}/users", headers=viewer, json={"username": "eve"})
    assert created.status_code == 403
    assert client.get(f"{API}/audit-events", headers=viewer).status_code == 200


def test_user_with_no_grant_signs_in_and_sees_nothing(client: TestClient, admin: dict) -> None:
    client.post(f"{API}/users", headers=admin, json={"username": "nia", "access_code": "nia-code"})
    nia = sign_in(client, "nia", "nia-code")
    assert client.get(f"{API}/auth/me", headers=nia).json()["role"] is None
    assert client.get(f"{API}/audit-events", headers=nia).status_code == 403


def test_s03_highest_role_wins_and_a_removed_grant_bites_at_once(
    client: TestClient, admin: dict
) -> None:
    """S03: a user in a View-only group who is also granted Admin directly."""
    user = client.post(
        f"{API}/users", headers=admin, json={"username": "uma", "access_code": "uma-code"}
    ).json()["user"]
    group = client.post(f"{API}/user-groups", headers=admin, json={"name": "Readers"}).json()
    client.post(
        f"{API}/role-grants", headers=admin, json={"role": "viewer", "group_hid": group["hid"]}
    )
    assert (
        client.put(
            f"{API}/user-groups/{group['hid']}/members/{user['hid']}", headers=admin
        ).status_code
        == 204
    )
    direct = client.post(
        f"{API}/role-grants", headers=admin, json={"role": "admin", "user_hid": user["hid"]}
    ).json()

    uma = sign_in(client, "uma", "uma-code")
    assert client.get(f"{API}/auth/me", headers=uma).json()["role"] == "admin"
    assert (
        client.post(f"{API}/users", headers=uma, json={"username": "made-by-uma"}).status_code
        == 201
    )

    assert client.delete(f"{API}/role-grants/{direct['hid']}", headers=admin).status_code == 204
    # The same token, with no new sign-in: the role is read on every request.
    assert client.get(f"{API}/auth/me", headers=uma).json()["role"] == "viewer"
    assert (
        client.post(f"{API}/users", headers=uma, json={"username": "not-made"}).status_code == 403
    )


def test_s04_resetting_a_code_ends_the_users_sessions(client: TestClient, admin: dict) -> None:
    """S04: an Admin resets a user's access code while that user is signed in."""
    vic = sign_in(client, "vic", VIEWER_CODE)
    assert client.get(f"{API}/auth/me", headers=vic).status_code == 200
    hid = client.get(f"{API}/auth/me", headers=vic).json()["hid"]

    reset = client.post(f"{API}/users/{hid}/access-code", headers=admin, json={})
    new_code = reset.json()["access_code"]
    assert client.get(f"{API}/auth/me", headers=vic).status_code == 401

    old = client.post(f"{API}/auth/sign-in", json={"username": "vic", "access_code": VIEWER_CODE})
    assert old.status_code == 401
    assert client.get(f"{API}/auth/me", headers=sign_in(client, "vic", new_code)).status_code == 200
    assert client.get(f"{API}/auth/me", headers=admin).status_code == 200


def test_sign_out_everywhere_and_disabling_end_sessions(client: TestClient, admin: dict) -> None:
    vic = sign_in(client, "vic", VIEWER_CODE)
    assert client.post(f"{API}/auth/sign-out-everywhere", headers=vic).status_code == 204
    assert client.get(f"{API}/auth/me", headers=vic).status_code == 401

    vic = sign_in(client, "vic", VIEWER_CODE)
    me = client.get(f"{API}/auth/me", headers=vic).json()
    disabled = client.patch(
        f"{API}/users/{me['hid']}",
        headers=admin,
        json={"row_version": me["row_version"], "disabled": True},
    )
    assert disabled.status_code == 200
    assert client.get(f"{API}/auth/me", headers=vic).status_code == 401
    refused = client.post(
        f"{API}/auth/sign-in", json={"username": "vic", "access_code": VIEWER_CODE}
    )
    assert refused.status_code == 401


def test_s05_the_sixth_wrong_code_is_delayed_and_each_failure_is_audited(
    client: TestClient, admin: dict
) -> None:
    """S05: six wrong access codes in a row."""
    statuses = [
        client.post(f"{API}/auth/sign-in", json={"username": "vic", "access_code": f"wrong-{n}"})
        for n in range(6)
    ]
    assert [r.status_code for r in statuses] == [401, 401, 401, 401, 401, 429]
    assert int(statuses[5].headers["retry-after"]) >= 1
    # The right code is delayed too, while the wait lasts.
    right = client.post(f"{API}/auth/sign-in", json={"username": "vic", "access_code": VIEWER_CODE})
    assert right.status_code == 429

    failed = client.get(f"{API}/audit-events?action=sign_in_failed", headers=admin).json()
    delayed = client.get(f"{API}/audit-events?action=sign_in_delayed", headers=admin).json()
    assert failed["total"] == 5
    assert delayed["total"] == 2
    assert {event["changes"][0]["new"] for event in failed["items"]} == {"vic"}


def test_stale_edit_is_refused(client: TestClient, admin: dict) -> None:
    me = client.get(f"{API}/auth/me", headers=admin).json()
    first = client.patch(
        f"{API}/users/{me['hid']}",
        headers=admin,
        json={"row_version": me["row_version"], "display_name": "Ada One"},
    )
    assert first.json()["row_version"] == me["row_version"] + 1
    second = client.patch(
        f"{API}/users/{me['hid']}",
        headers=admin,
        json={"row_version": me["row_version"], "display_name": "Ada Two"},
    )
    assert second.status_code == 409
    assert second.json()["title"] == "Stale version"


def test_the_last_admin_cannot_be_removed(client: TestClient, admin: dict) -> None:
    me = client.get(f"{API}/auth/me", headers=admin).json()
    grant = next(
        g
        for g in client.get(f"{API}/role-grants", headers=admin).json()
        if g["user_hid"] == me["hid"]
    )
    assert client.delete(f"{API}/role-grants/{grant['hid']}", headers=admin).status_code == 409
    disabled = client.patch(
        f"{API}/users/{me['hid']}",
        headers=admin,
        json={"row_version": me["row_version"], "disabled": True},
    )
    assert disabled.status_code == 409
    assert client.get(f"{API}/auth/me", headers=admin).json()["role"] == "admin"


def test_service_account_uses_tokens_not_codes(client: TestClient, admin: dict) -> None:
    created = client.post(
        f"{API}/users",
        headers=admin,
        json={"username": "svc-monitor", "is_service_account": True, "role": "viewer"},
    ).json()
    assert created["access_code"] is None
    hid = created["user"]["hid"]

    made = client.post(f"{API}/users/{hid}/service-tokens", headers=admin, json={"name": "probe"})
    secret, token = made.json()["secret"], made.json()["token"]
    service = {"Authorization": f"Bearer {secret}"}
    assert client.get(f"{API}/auth/me", headers=service).json()["username"] == "svc-monitor"
    assert client.get(f"{API}/audit-events", headers=service).status_code == 200
    assert client.get(f"{API}/users", headers=service).status_code == 403

    listed = client.get(f"{API}/users/{hid}/service-tokens", headers=admin).json()
    assert secret not in str(listed)
    assert (
        client.post(f"{API}/service-tokens/{token['hid']}/revoke", headers=admin).status_code == 200
    )
    assert client.get(f"{API}/auth/me", headers=service).status_code == 401

    person = client.get(f"{API}/auth/me", headers=admin).json()
    refused = client.post(
        f"{API}/users/{person['hid']}/service-tokens", headers=admin, json={"name": "x"}
    )
    assert refused.status_code == 409


def test_invalid_input_names_the_field(client: TestClient, admin: dict) -> None:
    bad_name = client.post(f"{API}/users", headers=admin, json={"username": "has space"})
    assert bad_name.status_code == 422
    assert bad_name.json()["errors"][0]["field"] == "username"
    unknown_field = client.post(f"{API}/users", headers=admin, json={"username": "ok", "x": 1})
    assert unknown_field.status_code == 422
    duplicate = client.post(f"{API}/users", headers=admin, json={"username": "Ada"})
    assert duplicate.status_code == 409


def test_every_change_is_audited_with_the_request_id(client: TestClient, admin: dict) -> None:
    created = client.post(
        f"{API}/users",
        headers={**admin, "X-Request-Id": "test-request-0001", "X-Hirdir-Client": "web"},
        json={"username": "tom", "role": "inventory"},
    )
    assert created.headers["x-request-id"] == "test-request-0001"
    events = client.get(f"{API}/audit-events?request_id=test-request-0001", headers=admin).json()
    assert {event["action"] for event in events["items"]} == {"create", "grant_role"}
    assert {event["via"] for event in events["items"]} == {"web"}
    assert {event["actor_name"] for event in events["items"]} == {"ada"}
