"""What the acceptance scenarios share: a real server process on an empty database.

The server is started on a free port, and the first Admin is made with `hirdir admin`,
exactly as on a new installation.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
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

    def sign_in(self, username: str, code: str) -> httpx2.Client:
        """Sign in and return a client that carries the session."""
        response = httpx2.post(
            f"{self.url}/auth/sign-in", json={"username": username, "access_code": code}
        )
        assert response.status_code == 200, response.text
        token = response.json()["token"]
        return httpx2.Client(base_url=self.url, headers={"Authorization": f"Bearer {token}"})


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
                if httpx2.get(f"{running.url}/health/ready").status_code == 200:
                    break
            except httpx2.HTTPError:
                pass
            assert process.poll() is None, "the server stopped while starting"
            assert time.monotonic() < deadline, "the server did not become ready"
            time.sleep(0.1)
        running.admin("create-user", ADMIN[0], "--role", "admin", "--access-code", ADMIN[1])
        yield running
    finally:
        process.terminate()
        process.wait(timeout=10)
