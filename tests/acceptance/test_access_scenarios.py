"""Scenarios S03 to S05 and S54 of docs/build-plan.md, against a real server process.

S01 and S02 need the installed package and a browser: `make package-test` and
`make e2e` run them.
"""

import time

import httpx2

from tests.acceptance.conftest import ADMIN, Server


def test_s03_highest_role_wins_and_removal_takes_effect_at_once(server: Server) -> None:
    admin = server.sign_in(*ADMIN)
    user = admin.post("/users", json={"username": "uma", "access_code": "uma-code-0001"}).json()[
        "user"
    ]
    group = admin.post("/user-groups", json={"name": "Readers"}).json()
    admin.post("/role-grants", json={"role": "viewer", "group_hid": group["hid"]})
    admin.put(f"/user-groups/{group['hid']}/members/{user['hid']}")
    direct = admin.post("/role-grants", json={"role": "admin", "user_hid": user["hid"]}).json()

    uma = server.sign_in("uma", "uma-code-0001")
    assert uma.get("/auth/me").json()["role"] == "admin"
    assert uma.post("/users", json={"username": "made-by-uma"}).status_code == 201

    assert admin.delete(f"/role-grants/{direct['hid']}").status_code == 204
    assert uma.post("/users", json={"username": "not-made"}).status_code == 403
    assert uma.get("/auth/me").json()["role"] == "viewer"


def test_s04_resetting_an_access_code_ends_the_users_sessions(server: Server) -> None:
    admin = server.sign_in(*ADMIN)
    admin.post("/users", json={"username": "vic", "access_code": "first-code-01", "role": "viewer"})
    vic = server.sign_in("vic", "first-code-01")
    assert vic.get("/auth/me").status_code == 200

    # Once through the API, and once from the server's own command line.
    hid = vic.get("/auth/me").json()["hid"]
    second = admin.post(f"/users/{hid}/access-code", json={}).json()["access_code"]
    assert vic.get("/auth/me").status_code == 401
    vic = server.sign_in("vic", second)

    output = server.admin("reset-access-code", "vic")
    third = output.split("access code:")[1].strip()
    assert vic.get("/auth/me").status_code == 401
    assert server.sign_in("vic", third).get("/auth/me").status_code == 200


def test_s05_the_sixth_wrong_code_is_delayed_and_every_failure_is_audited(server: Server) -> None:
    attempts = [
        httpx2.post(
            f"{server.url}/auth/sign-in", json={"username": "ada", "access_code": f"wrong-{n}"}
        )
        for n in range(6)
    ]
    assert [attempt.status_code for attempt in attempts] == [401, 401, 401, 401, 401, 429]
    wait = int(attempts[5].headers["retry-after"])
    assert wait >= 1

    time.sleep(wait + 0.2)
    admin = server.sign_in(*ADMIN)
    assert admin.get("/audit-events", params={"action": "sign_in_failed"}).json()["total"] == 5
    assert admin.get("/audit-events", params={"action": "sign_in_delayed"}).json()["total"] == 1
    assert all("set-cookie" not in attempt.headers for attempt in attempts)


def test_s54_a_person_is_onboarded_in_one_step_and_each_list_finds_the_gaps(
    server: Server,
) -> None:
    """S54 (R12.8): the user, its contact and its operator, with its role and its groups, in one
    request; a refusal of any part makes nothing; the lists say who is which (P-280 to
    P-283). The command line still makes a user with its contact."""
    admin = server.sign_in(*ADMIN)
    group = admin.post("/user-groups", json={"name": "Example Engineers"}).json()
    admin.post("/role-grants", json={"role": "inventory", "group_hid": group["hid"]})
    before = admin.get("/audit-events", params={"limit": 1}).json()["total"]
    refused = admin.post(
        "/users",
        json={
            "username": "ex-ops",
            "contact": {"name": "Example Person"},
            "group_hids": [group["hid"]],
            "operator": {"colour": "orange"},
        },
    )
    assert refused.status_code == 422
    assert [one["field"] for one in refused.json()["errors"]] == ["operator.colour"]
    assert admin.get("/audit-events", params={"limit": 1}).json()["total"] == before
    assert admin.get("/users", params={"q": "ex-ops"}).json()["total"] == 0
    assert admin.get("/contacts", params={"filter": "name:eq:Example Person"}).json()["total"] == 0

    made = admin.post(
        "/users",
        json={
            "username": "ex-ops",
            "contact": {"name": "Example Person", "email": "example.person@example.net"},
            "group_hids": [group["hid"]],
            "operator": {},
            "notes": "For the example team.",
            "access_code": "ex-ops-code-01",
        },
    ).json()
    assert made["operator"]["label"] == "ex-ops"
    assert made["user"]["operators"][0]["hid"] == made["operator"]["hid"]
    ops = server.sign_in("ex-ops", "ex-ops-code-01")
    assert ops.get("/auth/me").json()["role"] == "inventory"
    contact = ops.get(f"/contacts/{made['user']['contact_hid']}").json()
    assert (contact["is_user"], contact["is_operator"]) == (True, True)

    server.admin("create-user", "ex-desk", "--name", "Example Desk", "--role", "viewer")
    gaps = admin.get("/users", params={"operator": "none"}).json()["items"]
    assert sorted(one["username"] for one in gaps) == ["ada", "ex-desk"]
    nobody = admin.get("/contacts", params={"filter": "is_operator:eq:false"}).json()["items"]
    assert [one["name"] for one in nobody] == ["Example Desk"]


def test_prefix_reaches_the_server_for_a_client_behind_the_proxy(server: Server) -> None:
    """The proxy on this host forwards a request from a client somewhere else."""
    admin = server.sign_in(*ADMIN)
    forwarded = {"X-Forwarded-Prefix": "/hirdir", "X-Forwarded-For": "192.0.2.50"}
    document = admin.get("/openapi.json", headers=forwarded).json()
    assert document["servers"] == [{"url": "/hirdir"}]
