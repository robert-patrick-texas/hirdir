"""The least length of an access code that is typed, which a setting says (P-295):
12 from the start, for the person on their profile and for an Admin on `POST /users`,
on `POST /users/{hid}/access-code` and in a new person made in one step. A code the
server makes is not held to it, and a code that is held already is not looked at."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.conftest import VIEWER_CODE, sign_in

KEY = "access_code_min_length"
TWELVE = "twelve-chars"
ELEVEN = "eleven-char"


def _setting(client: TestClient, headers: dict) -> dict[str, Any]:
    listed = client.get(f"{API}/settings", headers=headers).json()
    return next(one for one in listed if one["key"] == KEY)


def _put(client: TestClient, admin: dict, value: Any, expect: int = 200) -> dict[str, Any]:
    answer = client.put(
        f"{API}/settings/{KEY}",
        json={"row_version": _setting(client, admin)["row_version"], "value": value},
        headers=admin,
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


def _refused(response: Any, least: int) -> None:
    """Hold a refusal to say the length, on `access_code`, and to name the setting."""
    assert response.status_code == 422, response.text
    problem = response.json()
    unit = "character" if least == 1 else "characters"
    # The length, in words a person reads at the box: the setting is not named.
    assert errors(problem) == {"access_code": f"at least {least} {unit}"}
    assert f"at least {least} {unit}" in problem["detail"]


def test_the_setting_is_twelve_from_the_start_and_every_role_reads_it(
    client: TestClient, viewer: dict
) -> None:
    setting = _setting(client, viewer)
    assert (setting["value"], setting["default"], setting["is_default"]) == (12, 12, True)
    assert "1 to 64" in setting["accepts"]


def test_an_admin_types_no_code_shorter_than_twelve(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    users = desk.get("/users", limit=1)["total"]
    _refused(
        client.post(
            f"{API}/users", headers=admin, json={"username": "klee", "access_code": ELEVEN}
        ),
        12,
    )
    # A new person made in one step is held to it too, and nothing of them is made.
    contacts = desk.get("/contacts", limit=1)["total"]
    _refused(
        client.post(
            f"{API}/users",
            headers=admin,
            json={
                "username": "klee",
                "access_code": ELEVEN,
                "contact": {"name": "Kim Lee"},
                "operator": {},
                "role": "viewer",
            },
        ),
        12,
    )
    assert desk.get("/users", limit=1)["total"] == users
    assert desk.get("/contacts", limit=1)["total"] == contacts

    made = desk.post("/users", {"username": "klee", "access_code": TWELVE})
    assert made["access_code"] == TWELVE
    kim = sign_in(client, "klee", TWELVE)
    url = f"{API}/users/{made['user']['hid']}/access-code"
    _refused(client.post(url, headers=admin, json={"access_code": ELEVEN}), 12)
    # The refusal ended no session and changed no code.
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 200
    assert client.post(url, headers=admin, json={"access_code": "thirteen-char"}).status_code == 200
    sign_in(client, "klee", "thirteen-char")


def test_a_code_the_server_makes_is_not_held_to_the_setting(
    client: TestClient, admin: dict
) -> None:
    _put(client, admin, 64)
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "klee"})
    assert len(made["access_code"]) == 14
    sign_in(client, "klee", made["access_code"])
    again = desk.post(f"/users/{made['user']['hid']}/access-code", {}, expect=200)
    assert len(again["access_code"]) == 14
    sign_in(client, "klee", again["access_code"])
    # A typed one is: 63 characters are one too few, and 64 are enough.
    _refused(
        client.post(
            f"{API}/users", headers=admin, json={"username": "sokafor", "access_code": "x" * 63}
        ),
        64,
    )
    desk.post("/users", {"username": "sokafor", "access_code": "x" * 64})


def test_the_setting_is_changed_and_returned_to_its_default(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    changed = _put(client, admin, 4)
    assert (changed["value"], changed["is_default"]) == (4, False)
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "klee", "access_code": "four"})
    _refused(
        client.post(
            f"{API}/users/{made['user']['hid']}/access-code",
            headers=admin,
            json={"access_code": "one"},
        ),
        4,
    )
    # The person is held to what the setting says now, on their profile.
    own = f"{API}/auth/me/access-code"
    short = client.post(
        own, headers=viewer, json={"current_access_code": VIEWER_CODE, "access_code": "abc"}
    )
    _refused(short, 4)
    kept = client.post(
        own, headers=viewer, json={"current_access_code": VIEWER_CODE, "access_code": "abcd"}
    )
    assert kept.status_code == 200, kept.text

    back = _put(client, admin, None)
    assert (back["value"], back["is_default"]) == (12, True)
    _refused(
        client.post(
            f"{API}/users", headers=admin, json={"username": "sokafor", "access_code": ELEVEN}
        ),
        12,
    )
    # A code that is held already is not looked at: nobody is signed out by the setting.
    sign_in(client, "klee", "four")
    sign_in(client, "vic", "abcd")

    (first, second) = Maker(client, admin).audit(record_type="setting", action="update")
    assert [entry["new"] for entry in second["changes"]] == [4]
    assert [entry["new"] for entry in first["changes"]] == [None]


def test_at_one_a_code_of_one_character_is_taken_and_a_blank_one_never(
    client: TestClient, admin: dict
) -> None:
    _put(client, admin, 1)
    Maker(client, admin).post("/users", {"username": "klee", "access_code": "x"})
    for code in ("", " x", "x "):
        blank = client.post(
            f"{API}/users", headers=admin, json={"username": "sokafor", "access_code": code}
        )
        assert blank.status_code == 422, code
        assert "must not be empty" in errors(blank.json())["access_code"]


@pytest.mark.parametrize("value", [0, 65, -1, 12.5, "12", True, [12]])
def test_the_setting_takes_a_whole_number_from_1_to_64(
    client: TestClient, admin: dict, value: Any
) -> None:
    refused = _put(client, admin, value, expect=422)
    assert "from 1 to 64" in errors(refused)["value"]
    assert _setting(client, admin)["value"] == 12


def test_only_an_admin_changes_the_setting(client: TestClient, inventory: dict) -> None:
    refused = client.put(
        f"{API}/settings/{KEY}", json={"row_version": 0, "value": 1}, headers=inventory
    )
    assert refused.status_code == 403
