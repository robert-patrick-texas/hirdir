"""Scenarios S03 to S05 of docs/build-plan.md, against a real server process.

S01 and S02 need the installed package and a browser: `make package-test` and
`make e2e` run them.
"""

import time

import httpx2

from tests.acceptance.conftest import ADMIN, Server


def test_s03_highest_role_wins_and_removal_takes_effect_at_once(server: Server) -> None:
    admin = server.sign_in(*ADMIN)
    user = admin.post("/users", json={"username": "uma", "access_code": "uma-code"}).json()["user"]
    group = admin.post("/user-groups", json={"name": "Readers"}).json()
    admin.post("/role-grants", json={"role": "viewer", "group_hid": group["hid"]})
    admin.put(f"/user-groups/{group['hid']}/members/{user['hid']}")
    direct = admin.post("/role-grants", json={"role": "admin", "user_hid": user["hid"]}).json()

    uma = server.sign_in("uma", "uma-code")
    assert uma.get("/auth/me").json()["role"] == "admin"
    assert uma.post("/users", json={"username": "made-by-uma"}).status_code == 201

    assert admin.delete(f"/role-grants/{direct['hid']}").status_code == 204
    assert uma.post("/users", json={"username": "not-made"}).status_code == 403
    assert uma.get("/auth/me").json()["role"] == "viewer"


def test_s04_resetting_an_access_code_ends_the_users_sessions(server: Server) -> None:
    admin = server.sign_in(*ADMIN)
    admin.post("/users", json={"username": "vic", "access_code": "first-code", "role": "viewer"})
    vic = server.sign_in("vic", "first-code")
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


def test_prefix_reaches_the_server_for_a_client_behind_the_proxy(server: Server) -> None:
    """The proxy on this host forwards a request from a client somewhere else."""
    admin = server.sign_in(*ADMIN)
    forwarded = {"X-Forwarded-Prefix": "/hirdir", "X-Forwarded-For": "192.0.2.50"}
    document = admin.get("/openapi.json", headers=forwarded).json()
    assert document["servers"] == [{"url": "/hirdir"}]
