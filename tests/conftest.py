"""Fixtures shared by the tests: a fresh database, an application and signed-in callers.

Three things here are for the time a run takes, and change nothing a test can see.

The database of a test is a copy of one that was migrated once, for each worker, and
not migrated again for each test. The migrations themselves are tested in
`tests/unit/test_database.py`, on databases of their own.

The routes of the application are built once, for each worker, and bound to the state
of each test in turn: its settings, its database, its key and its count of failed
sign-ins, which is all the application holds. A test whose settings differ in more than
where its state lives gets an application of its own, as do the tests that build one.

Access codes are hashed cheaply in the tests that run inside this process: Argon2 at
its full cost is meant to be slow, and nearly every test makes three users and signs
one in. `full_cost` gives a test the hashing that is released. The acceptance
scenarios and the package test start the server as a process of its own, and so
always run with it.
"""

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirdir.app import bind, create_app
from hirdir.auth import codes
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit

ADMIN_CODE = "admin-code"
INVENTORY_CODE = "inventory-code"
VIEWER_CODE = "viewer-code"
USERS = (
    ("ada", ADMIN_CODE, "admin"),
    ("ivy", INVENTORY_CODE, "inventory"),
    ("vic", VIEWER_CODE, "viewer"),
)


@pytest.fixture(scope="session", autouse=True)
def quick_codes() -> Iterator[None]:
    """Hash access codes at the least cost Argon2 has, in the tests inside this process."""
    quick = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(codes, "_HASHER", quick)
        patch.setattr(codes, "_DUMMY_HASH", quick.hash("no such user"))
        yield


@pytest.fixture
def full_cost(monkeypatch: pytest.MonkeyPatch) -> PasswordHasher:
    """Hash access codes as the release does, for the test that asks. Return that hasher."""
    released = PasswordHasher()
    monkeypatch.setattr(codes, "_HASHER", released)
    monkeypatch.setattr(codes, "_DUMMY_HASH", released.hash("no such user"))
    return released


@pytest.fixture(scope="session")
def migrated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database at the newest schema, in one file: made once, and copied for each test."""
    folder = tmp_path_factory.mktemp("migrated")
    made = Config(state_dir=folder)
    migrate.upgrade(made.database_url)
    # Written out whole, so that nothing of it is left in a write-ahead log beside it.
    whole = folder / "whole.db"
    with closing(sqlite3.connect(folder / "hirdir.db")) as connection:
        connection.execute("VACUUM INTO ?", (str(whole),))
    return whole


@pytest.fixture
def config(tmp_path: Path, migrated: Path) -> Config:
    """A configuration whose state lives in a temporary directory."""
    config = Config(state_dir=tmp_path, trusted_proxies=("testclient",))
    path = config.database_path
    assert path is not None, "the tests run on SQLite"
    shutil.copyfile(migrated, path)
    return config


@pytest.fixture
def db(config: Config) -> Iterator:
    """A session on the test database."""
    with make_sessions(make_engine(config.database_url))() as session:
        yield session


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[FastAPI, Config]:
    """The application with its routes, built once, and the settings it was built for."""
    settings = Config(state_dir=tmp_path_factory.mktemp("built"), trusted_proxies=("testclient",))
    return create_app(settings), settings


def application(config: Config, built: tuple[FastAPI, Config]) -> FastAPI:
    """Return the application for config: the one that is built, bound to this state."""
    app, settings = built
    if (
        replace(config, state_dir=settings.state_dir, database_url=settings.database_url)
        != settings
    ):
        # Some of the settings are built into the application, so it is built again.
        return create_app(config)
    app.state.engine.dispose()
    bind(app, config)
    return app


@pytest.fixture
def client(config: Config, built: tuple[FastAPI, Config]) -> Iterator[TestClient]:
    """A client of the application, with one user of each role in place."""
    engine = make_engine(config.database_url)
    with make_sessions(engine)() as session:
        for name, code, role in USERS:
            user, _ = accounts.create_user(session, audit.SYSTEM, username=name, access_code=code)
            accounts.grant_role(session, audit.SYSTEM, role=role, user_hid=user.hid)
        session.commit()
    engine.dispose()
    app = application(config, built)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


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
def inventory(client: TestClient) -> dict[str, str]:
    """Headers of a signed-in Inventory user."""
    return sign_in(client, "ivy", INVENTORY_CODE)


@pytest.fixture
def viewer(client: TestClient) -> dict[str, str]:
    """Headers of a signed-in View-only user."""
    return sign_in(client, "vic", VIEWER_CODE)


@pytest.fixture
def make(client: TestClient, inventory: dict[str, str]):
    """A maker of inventory records, signed in with the Inventory role."""
    from tests.api.inventory import Maker

    return Maker(client, inventory)
