"""Scenario S56 of docs/build-plan.md, against a real server process: a person changes
what is their own on their profile, and nothing of another (P-289, P-294, P-295)."""

import subprocess
from typing import Any

import httpx2

from tests.acceptance.conftest import ADMIN, HIRDIR, Server

CODE = "kim-lee-code-01"
NEW_CODE = "kim-lee-code-02"
KIM = {"name": "Kim Lee", "email": "kim.lee@example.com", "phone": "+1 555 0100"}
SAM = {"name": "Sam Okafor", "email": "sam.okafor@example.com"}


def _person(
    admin: httpx2.Client, username: str, contact: dict[str, Any], code: str
) -> dict[str, Any]:
    made = admin.post(
        "/users",
        json={
            "username": username,
            "access_code": code,
            "role": "viewer",
            "contact": contact,
            "operator": {},
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def _events(admin: httpx2.Client, **params: Any) -> list[dict[str, Any]]:
    return admin.get("/audit-events", params={"limit": 100, **params}).json()["items"]


def _errors(response: httpx2.Response) -> dict[str, str]:
    return {entry["field"]: entry["message"] for entry in response.json()["errors"]}


def _hirdir(server: Server, token: str, *arguments: str) -> str:
    """Run a client command of `hirdir` as whoever holds the token."""
    env = {**server.env, "HIRDIR_URL": server.url.removesuffix("/api/v1"), "HIRDIR_TOKEN": token}
    result = subprocess.run(  # noqa: S603 - our own command with fixed arguments
        [*HIRDIR, *arguments], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr.strip() or result.stdout.strip()
    return result.stdout


def test_s56_a_view_only_user_changes_what_is_their_own_and_nothing_of_another(
    server: Server,
) -> None:
    admin = server.sign_in(*ADMIN)
    made = _person(admin, "klee", KIM, CODE)
    other = _person(admin, "sokafor", SAM, "sam-okafor-code-01")
    hid, contact_hid, operator = made["user"]["hid"], made["user"]["contact_hid"], made["operator"]
    kim = server.sign_in("klee", CODE)
    elsewhere = server.sign_in("klee", CODE)
    me = kim.get("/auth/me").json()
    assert (me["role"], me["contact"]["name"], me["operators"][0]["label"]) == (
        "viewer",
        "Kim Lee",
        "klee",
    )

    # Their name, email, numbers and organization, which are their contact's.
    own = {
        "name": "Kim A. Lee",
        "email": "kim.a.lee@example.com",
        "phone": "+1 555 0110",
        "phone2": "+1 555 0111",
        "organization": "Example Networks",
    }
    changed = kim.patch(
        "/auth/me/contact", json={"row_version": me["contact"]["row_version"], **own}
    )
    assert changed.status_code == 200, changed.text
    read = admin.get(f"/contacts/{contact_hid}").json()
    assert {field: read[field] for field in own} == own

    # Their label and colour.
    marked = kim.patch(
        f"/auth/me/operators/{operator['hid']}",
        json={"row_version": operator["row_version"], "label": "KAL", "colour": "#1f6feb"},
    )
    assert marked.status_code == 200, marked.text
    read = admin.get(f"/operators/{operator['hid']}").json()
    assert (read["label"], read["colour"]) == ("KAL", "#1f6feb")

    # Their access code: first with a wrong current code, and with one that is too short.
    wrong = kim.post(
        "/auth/me/access-code",
        json={"current_access_code": "not-the-code-i-have", "access_code": NEW_CODE},
    )
    assert wrong.status_code == 422
    assert _errors(wrong) == {"current_access_code": "this is not the access code you have"}
    short = kim.post(
        "/auth/me/access-code", json={"current_access_code": CODE, "access_code": "eleven-char"}
    )
    assert short.status_code == 422
    assert _errors(short) == {"access_code": "at least 12 characters"}
    # Both refusals changed nothing: both sessions stand, and the code is what it was.
    assert kim.get("/auth/me").status_code == 200
    assert elsewhere.get("/auth/me").status_code == 200
    server.sign_in("klee", CODE)
    assert _events(admin, action="set_access_code", record_hid=hid) == []

    accepted = kim.post(
        "/auth/me/access-code", json={"current_access_code": CODE, "access_code": NEW_CODE}
    )
    assert accepted.status_code == 200, accepted.text
    session = accepted.json()
    # The session in hand stays signed in, by the token of the answer; another is ended.
    in_hand = httpx2.Client(
        base_url=server.url, headers={"Authorization": f"Bearer {session['token']}"}
    )
    assert in_hand.get("/auth/me").json()["contact"]["name"] == "Kim A. Lee"
    assert elsewhere.get("/auth/me").status_code == 401
    # The old code signs in no longer, and the new one does.
    old = httpx2.post(f"{server.url}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    assert old.status_code == 401
    assert server.sign_in("klee", NEW_CODE).get("/auth/me").status_code == 200

    # Each change is in the audit trail, by that user.
    (contact_event,) = _events(
        admin, record_type="contact", record_hid=contact_hid, action="update", actor_hid=hid
    )
    assert {entry["field"]: entry["new"] for entry in contact_event["changes"]} == own
    (operator_event,) = _events(
        admin, record_type="operator", record_hid=operator["hid"], action="update"
    )
    assert operator_event["actor_hid"] == hid
    assert {entry["field"]: entry["new"] for entry in operator_event["changes"]} == {
        "label": "KAL",
        "colour": "#1f6feb",
    }
    (code_event,) = _events(admin, action="set_access_code", record_hid=hid)
    assert code_event["actor_hid"] == hid
    (refusal,) = _events(admin, action="access_code_refused")
    assert (refusal["actor_hid"], refusal["record_hid"]) == (hid, hid)

    # And the user changes nothing of another person: not by the routes of their own,
    # which take no HID of a contact and find no operator of another, nor by the routes
    # of the inventory, which their role does not open.
    theirs = other["operator"]
    assert (
        in_hand.patch(
            f"/auth/me/operators/{theirs['hid']}",
            json={"row_version": theirs["row_version"], "label": "taken"},
        ).status_code
        == 404
    )
    sams = admin.get(f"/contacts/{other['user']['contact_hid']}").json()
    assert (
        in_hand.patch(
            f"/contacts/{sams['hid']}", json={"row_version": sams["row_version"], "name": "Taken"}
        ).status_code
        == 403
    )
    assert (
        in_hand.patch(
            f"/operators/{theirs['hid']}",
            json={"row_version": theirs["row_version"], "label": "taken"},
        ).status_code
        == 403
    )
    assert in_hand.post(f"/users/{other['user']['hid']}/access-code", json={}).status_code == 403
    taken = in_hand.patch(
        "/auth/me/contact",
        json={
            "row_version": in_hand.get("/auth/me").json()["contact"]["row_version"],
            "email": SAM["email"],
        },
    )
    assert taken.status_code == 409
    assert taken.json()["existing"]["label"] == "Sam Okafor"
    assert admin.get(f"/contacts/{sams['hid']}").json() == sams
    assert admin.get(f"/operators/{theirs['hid']}").json()["label"] == "sokafor"
    server.sign_in("sokafor", "sam-okafor-code-01")

    # The command line shows the same profile, and changes it by the same routes.
    shown = _hirdir(server, session["token"], "profile", "show")
    assert "Kim A. Lee" in shown
    assert "KAL  #1f6feb" in shown
    _hirdir(server, session["token"], "profile", "set", "--phone2", "", "--label", "KL")
    me = in_hand.get("/auth/me").json()
    assert (me["contact"]["phone2"], me["operators"][0]["label"]) == (None, "KL")
    assert "KL" in _hirdir(server, session["token"], "whoami")
