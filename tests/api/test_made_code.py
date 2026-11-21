"""A new access code is not the one it replaces, and the server makes one as long as the
setting asks (P-300): `GET /auth/new-access-code`, an Admin's empty box, bring back."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.conftest import ADMIN_CODE, VIEWER_CODE, sign_in

KEY = "access_code_min_length"


def _least(client: TestClient, admin: dict, value: int) -> None:
    listed = client.get(f"{API}/settings", headers=admin).json()
    version = next(one["row_version"] for one in listed if one["key"] == KEY)
    answer = client.put(
        f"{API}/settings/{KEY}", json={"row_version": version, "value": value}, headers=admin
    )
    assert answer.status_code == 200, answer.text


def _total(client: TestClient, admin: dict) -> int:
    return client.get(f"{API}/audit-events", params={"limit": 1}, headers=admin).json()["total"]


def _own(client: TestClient, headers: dict, current: str, new: str) -> Any:
    return client.post(
        f"{API}/auth/me/access-code",
        json={"current_access_code": current, "access_code": new},
        headers=headers,
    )


def test_the_code_in_hand_is_not_taken_as_the_new_one(client: TestClient, viewer: dict) -> None:
    other = sign_in(client, "vic", VIEWER_CODE)
    same = _own(client, viewer, VIEWER_CODE, VIEWER_CODE)
    assert same.status_code == 422, same.text
    problem = same.json()
    assert errors(problem) == {"access_code": "this is the access code you have now"}
    assert problem["detail"] == "the new access code is the one you have now: choose another"
    # Nothing changed and no session ended.
    for headers in (viewer, other):
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 200
    sign_in(client, "vic", VIEWER_CODE)


def test_the_same_code_is_looked_at_after_the_current_one(client: TestClient, viewer: dict) -> None:
    wrong = _own(client, viewer, "not-the-code-01", VIEWER_CODE)
    assert set(errors(wrong.json())) == {"current_access_code"}


def test_an_admin_gives_the_current_code_and_sets_another_s_to_the_one_they_had(
    client: TestClient, admin: dict
) -> None:
    """On the profile an Admin is as anybody; for somebody else, the same code is taken."""
    assert set(errors(_own(client, admin, "not-the-code-01", "a-new-admin-code").json())) == {
        "current_access_code"
    }
    assert set(errors(_own(client, admin, ADMIN_CODE, ADMIN_CODE).json())) == {"access_code"}
    desk = Maker(client, admin)
    vic = next(one for one in desk.get("/users")["items"] if one["username"] == "vic")
    again = desk.post(f"/users/{vic['hid']}/access-code", {"access_code": VIEWER_CODE}, 200)
    assert again["access_code"] == VIEWER_CODE
    sign_in(client, "vic", VIEWER_CODE)


@pytest.mark.parametrize(("least", "length"), [(12, 14), (20, 24), (64, 64)])
def test_a_made_code_is_as_long_as_the_setting_asks(
    client: TestClient, admin: dict, viewer: dict, least: int, length: int
) -> None:
    _least(client, admin, least)
    before = _total(client, admin)
    asked = client.get(f"{API}/auth/new-access-code", headers=viewer)
    assert asked.status_code == 200, asked.text
    assert asked.headers["cache-control"] == "no-store"
    code = asked.json()["access_code"]
    assert len(code) == length
    assert {len(part) for part in code.split("-")} == {4}
    # It is stored nowhere and written nowhere: the trail is as it was.
    assert _total(client, admin) == before
    assert client.get(f"{API}/auth/new-access-code", headers=viewer).json()["access_code"] != code
    # Sent as a typed code is, it is taken.
    assert _own(client, viewer, VIEWER_CODE, code).status_code == 200
    sign_in(client, "vic", code)

    # An Admin's empty box, and bring back, make one as long.
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "klee", "role": "viewer"})
    assert len(made["access_code"]) == length
    sign_in(client, "klee", made["access_code"])
    hid = made["user"]["hid"]
    again = desk.post(f"/users/{hid}/access-code", {}, 200)
    assert len(again["access_code"]) == length
    version = desk.get(f"/users/{hid}")["row_version"]
    retired = desk.post(f"/users/{hid}/retire", {"row_version": version}, 200)
    back = desk.post(
        f"/users/{hid}/bring-back", {"row_version": retired["row_version"], "role": "viewer"}, 200
    )
    assert len(back["access_code"]) == length


def test_a_made_code_is_asked_for_with_a_role(client: TestClient, admin: dict) -> None:
    assert client.get(f"{API}/auth/new-access-code").status_code == 401
    desk = Maker(client, admin)
    robot = desk.post("/users", {"username": "robot", "is_service_account": True})["user"]
    secret = desk.post(f"/users/{robot['hid']}/service-tokens", {"name": "nightly"})["secret"]
    token = {"Authorization": f"Bearer {secret}"}
    assert client.get(f"{API}/auth/new-access-code", headers=token).status_code == 401
    desk.post("/role-grants", {"role": "viewer", "user_hid": robot["hid"]})
    assert client.get(f"{API}/auth/new-access-code", headers=token).status_code == 200
