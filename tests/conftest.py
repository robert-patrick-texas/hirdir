"""Fixtures shared by the tests: a fresh database, an application and signed-in callers."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit

ADMIN_CODE = "admin-code"
VIEWER_CODE = "viewer-code"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A configuration whose state lives in a temporary directory."""
    config = Config(state_dir=tmp_path, trusted_proxies=("testclient",))
    migrate.upgrade(config.database_url)
    return config


@pytest.fixture
def db(config: Config) -> Iterator:
    """A session on the test database."""
    with make_sessions(make_engine(config.database_url))() as session:
        yield session


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    """A client of the application, with one Admin and one View-only user in place."""
    with make_sessions(make_engine(config.database_url))() as session:
        for name, code, role in (("ada", ADMIN_CODE, "admin"), ("vic", VIEWER_CODE, "viewer")):
            user, _ = accounts.create_user(session, audit.SYSTEM, username=name, access_code=code)
            accounts.grant_role(session, audit.SYSTEM, role=role, user_hid=user.hid)
        session.commit()
    with TestClient(create_app(config)) as test_client:
        yield test_client


def sign_in(client: TestClient, username: str, code: str) -> dict[str, str]:
    """Sign in and return the headers that carry the session."""
    response = client.post("/api/v1/auth/sign-in", json={"username": username, "access_code": code})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    """Headers of a signed-in Admin."""
    return sign_in(client, "ada", ADMIN_CODE)


@pytest.fixture
def viewer(client: TestClient) -> dict[str, str]:
    """Headers of a signed-in View-only user."""
    return sign_in(client, "vic", VIEWER_CODE)
