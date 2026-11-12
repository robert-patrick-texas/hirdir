"""Scenarios S03 to S05 of docs/build-plan.md, against a real server process.

The server is started from an empty database on a free port, and the first Admin is
made with `hirdir admin`, exactly as on a new installation. S01 and S02 need the
installed package and a browser: `make package-test` and `make e2e` run them.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

HIRDIR = [sys.executable, "-m", "hirdir.cli.main"]
ADMIN = ("ada", "acceptance-admin")


@dataclass
class Server:
    """A running server, and how to run `hirdir admin` against the same state."""

    url: str
    env: dict[str, str]

    def admin(self, *arguments: str) -> str:
        """Run `hirdir admin` with arguments and return what it printed."""
        result = subprocess.run(  # noqa: S603 - our own command with fixed arguments
            [*HIRDIR, "admin", *arguments], env=self.env, capture_output=True, text=True, check=True
        )
        return result.stdout

    def sign_in(self, username: str, code: str) -> httpx.Client:
        """Sign in and return a client that carries the session."""
        response = httpx.post(
            f"{self.url}/auth/sign-in", json={"username": username, "access_code": code}
        )
        assert response.status_code == 200, response.text
        token = response.json()["token"]
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token}"})


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    """Start a server on an empty database and create its first Admin."""
    port = _free_port()
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\nlisten = "127.0.0.1:{port}"\nstate_dir = "."\n')
    env = {**os.environ, "HIRDIR_CONFIG": str(config)}
    process = subprocess.Popen(  # noqa: S603 - our own command with fixed arguments
        [*HIRDIR, "admin", "serve", "--dev"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    running = Server(url=f"http://127.0.0.1:{port}/api/v1", env=env)
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(f"{running.url}/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert process.poll() is None, "the server stopped while starting"
            assert time.monotonic() < deadline, "the server did not become ready"
            time.sleep(0.1)
        running.admin("create-user", ADMIN[0], "--role", "admin", "--access-code", ADMIN[1])
        yield running
    finally:
        process.terminate()
        process.wait(timeout=10)


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
        httpx.post(
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
