"""Scenarios S57 and S58 of docs/build-plan.md, against a real server process: a retired
account, and a person retired together (R12.10, R12.11)."""

import csv
import io

import httpx2

from tests.acceptance.conftest import ADMIN, Server

CODE = "kim-lee-code-01"


def _events(admin: httpx2.Client, request_id: str) -> list[tuple[str, str]]:
    """The events of one request, oldest first: the action and the kind of record."""
    found = admin.get("/audit-events", params={"request_id": request_id, "limit": 200}).json()
    return [(one["action"], one["record_type"]) for one in reversed(found["items"])]


def _usernames(admin: httpx2.Client, **params: str) -> list[str]:
    return [one["username"] for one in admin.get("/users", params=params).json()["items"]]


def _file(admin: httpx2.Client, **params: str) -> list[dict[str, str]]:
    answer = admin.post("/users/export", params=params)
    assert answer.status_code == 200, answer.text
    return list(csv.DictReader(io.StringIO(answer.text)))


def test_s57_an_account_is_retired_left_out_and_brought_back_with_nothing(server: Server) -> None:
    """S57 (R12.10): the account signs in no longer, is in no group and holds no role,
    each audited; the list and the users' file leave it out until the retired are asked
    for; a new account of its username is refused with it named; and brought back with a
    role, which a person is given, it has a new access code, that role and no group
    (P-292, P-296, P-299)."""
    admin = server.sign_in(*ADMIN)
    groups = [
        admin.post("/user-groups", json={"name": name}).json()
        for name in ("Example East", "Example West")
    ]
    kim = admin.post(
        "/users",
        json={
            "username": "klee",
            "access_code": CODE,
            "role": "inventory",
            "group_hids": [group["hid"] for group in groups],
        },
    ).json()["user"]
    session = server.sign_in("klee", CODE)
    assert session.get("/auth/me").json()["role"] == "inventory"

    retired = admin.post(f"/users/{kim['hid']}/retire", json={"row_version": kim["row_version"]})
    assert retired.status_code == 200, retired.text
    assert retired.json()["record_status"] == "retired"
    assert (retired.json()["role"], retired.json()["groups"]) == (None, [])
    assert session.get("/auth/me").status_code == 401
    refused = httpx2.post(
        f"{server.url}/auth/sign-in", json={"username": "klee", "access_code": CODE}
    )
    assert refused.status_code == 401
    assert _events(admin, retired.headers["x-request-id"]) == [
        ("remove_member", "user_group"),
        ("remove_member", "user_group"),
        ("revoke_role", "user"),
        ("retire", "user"),
    ]

    # Left out of the list and of the file until the retired are asked for.
    assert _usernames(admin) == ["ada"]
    assert _usernames(admin, retired="yes") == ["ada", "klee"]
    assert _usernames(admin, retired="only") == ["klee"]
    assert [row["username"] for row in _file(admin)] == ["ada"]
    rows = _file(admin, retired="yes")
    assert [(row["username"], row["record_status"]) for row in rows] == [
        ("ada", "active"),
        ("klee", "retired"),
    ]

    # The username stays the retired account's.
    again = admin.post("/users", json={"username": "klee"})
    assert again.status_code == 409
    problem = again.json()
    assert "retired" in problem["detail"]
    assert problem["existing"] == {"hid": kim["hid"], "record_type": "user", "label": "klee"}

    # Brought back: a new code, the role given and no group.
    back = admin.post(
        f"/users/{kim['hid']}/bring-back",
        json={"row_version": retired.json()["row_version"], "role": "viewer"},
    )
    assert back.status_code == 200, back.text
    code = back.json()["access_code"]
    assert code
    assert code != CODE
    assert (back.json()["user"]["role"], back.json()["user"]["groups"]) == ("viewer", [])
    assert _events(admin, back.headers["x-request-id"]) == [
        ("bring_back", "user"),
        ("grant_role", "user"),
    ]
    assert (
        httpx2.post(
            f"{server.url}/auth/sign-in", json={"username": "klee", "access_code": CODE}
        ).status_code
        == 401
    )
    assert server.sign_in("klee", code).get("/auth/me").json()["role"] == "viewer"
    assert _usernames(admin) == ["ada", "klee"]


def test_s58_a_person_is_retired_together_or_not_at_all(server: Server) -> None:
    """S58 (R12.11): a retirement that says nothing of the linked records is refused with
    them named and changes nothing; one that says what becomes of each is one change,
    each record audited; an Inventory user cannot bring the contact back; and an Admin
    brings back the user with its contact (P-291, P-297, P-298)."""
    admin = server.sign_in(*ADMIN)
    kim = admin.post(
        "/users",
        json={
            "username": "klee",
            "access_code": CODE,
            "role": "viewer",
            "contact": {"name": "Kim Lee", "email": "kim.lee@example.com"},
        },
    ).json()["user"]
    contact_hid = kim["contact_hid"]
    labels = {
        label: admin.post("/operators", json={"label": label, "contact_hid": contact_hid}).json()
        for label in ("KL", "LM")
    }
    sam = admin.post(
        "/contacts", json={"name": "Sam Okafor", "email": "sam.okafor@example.com"}
    ).json()
    admin.post(
        "/users",
        json={"username": "ex-inventory", "access_code": "ex-inventory-01", "role": "inventory"},
    )
    contact = admin.get(f"/contacts/{contact_hid}").json()
    total = admin.get("/audit-events", params={"limit": 1}).json()["total"]

    # Saying nothing of the rest: refused, with the user and both operators named.
    bare = admin.post(
        f"/contacts/{contact_hid}/retire", json={"row_version": contact["row_version"]}
    )
    assert bare.status_code == 409
    assert sorted(one["field"] for one in bare.json()["errors"]) == [
        "linked.operators",
        "linked.user",
    ]
    assert [(one["record_type"], one["label"]) for one in bare.json()["depends_on"]] == [
        ("operator", "KL"),
        ("operator", "LM"),
        ("user", "klee"),
    ]
    linked = admin.get(f"/contacts/{contact_hid}/linked").json()
    assert linked["user"]["record_status"] == linked["contact"]["record_status"] == "active"
    assert [one["record_status"] for one in linked["operators"]] == ["active", "active"]
    assert admin.get("/audit-events", params={"limit": 1}).json()["total"] == total

    # With the user, one operator handed over and one released: one change.
    done = admin.post(
        f"/contacts/{contact_hid}/retire",
        json={
            "row_version": contact["row_version"],
            "linked": {
                "user": "retire",
                "operators": [
                    {"hid": labels["KL"]["hid"], "action": "hand_over", "contact_hid": sam["hid"]},
                    {"hid": labels["LM"]["hid"], "action": "retire"},
                ],
            },
        },
    )
    assert done.status_code == 200, done.text
    linked = admin.get(f"/users/{kim['hid']}/linked").json()
    assert (linked["user"]["record_status"], linked["contact"]["record_status"]) == (
        "retired",
        "retired",
    )
    assert [(one["label"], one["record_status"]) for one in linked["operators"]] == [
        ("LM", "retired")
    ]
    handed = admin.get(f"/operators/{labels['KL']['hid']}").json()
    assert (handed["contact_hid"], handed["record_status"]) == (sam["hid"], "active")
    assert _events(admin, done.headers["x-request-id"]) == [
        ("update", "operator"),
        ("retire", "operator"),
        ("revoke_role", "user"),
        ("retire", "user"),
        # The contact is told that it is no user's now, and then retired.
        ("update", "contact"),
        ("retire", "contact"),
    ]

    # An Inventory user cannot bring the contact back.
    inventory = server.sign_in("ex-inventory", "ex-inventory-01")
    now = admin.get(f"/contacts/{contact_hid}").json()
    refused = inventory.patch(
        f"/contacts/{contact_hid}",
        json={"row_version": now["row_version"], "record_status": "active"},
    )
    assert refused.status_code == 403
    assert admin.get(f"/contacts/{contact_hid}").json()["record_status"] == "retired"

    # An Admin brings back the user with its contact: alone it is refused, the contact named.
    user = admin.get(f"/users/{kim['hid']}").json()
    alone = admin.post(
        f"/users/{kim['hid']}/bring-back",
        json={"row_version": user["row_version"], "role": "viewer"},
    )
    assert alone.status_code == 409
    assert alone.json()["existing"]["hid"] == contact_hid
    back = admin.post(
        f"/users/{kim['hid']}/bring-back",
        json={
            "row_version": user["row_version"],
            "linked": {"contact": "bring_back"},
            "role": "viewer",
        },
    )
    assert back.status_code == 200, back.text
    linked = admin.get(f"/users/{kim['hid']}/linked").json()
    assert (linked["user"]["record_status"], linked["contact"]["record_status"]) == (
        "active",
        "active",
    )
    signed = server.sign_in("klee", back.json()["access_code"])
    assert signed.get("/auth/me").json()["role"] == "viewer"
