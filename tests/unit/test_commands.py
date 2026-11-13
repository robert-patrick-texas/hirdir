"""The commands that show or write a time: backups, and signing in at the command line."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text
from typer.testing import CliRunner

from hirdir import clock
from hirdir.cli import client
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import audit, settings

runner = CliRunner()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch) -> Config:
    """A configuration file and a migrated database, as `hirdir admin` finds them."""
    path = tmp_path / "config.toml"
    path.write_text('[server]\nstate_dir = "."\n[backup]\nkeep = 3\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=tmp_path)
    migrate.upgrade(config.database_url)
    return config


def _backup() -> Path:
    result = runner.invoke(app, ["admin", "backup"])
    assert result.exit_code == 0, result.output
    return Path(result.output.strip())


def test_backup_is_named_in_the_applications_time(installed: Config, monkeypatch) -> None:
    moment = datetime(2026, 11, 13, 2, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: moment)
    assert _backup().name == "hirdir-20261112T210000-0500.db"

    with make_sessions(make_engine(installed.database_url))() as db:
        settings.set_setting(db, audit.SYSTEM, "time_zone", 0, "America/Chicago")
        db.commit()
    monkeypatch.setattr(clock, "now", lambda: moment.replace(hour=3))
    assert _backup().name == "hirdir-20261112T210000-0600.db"


def test_backup_of_a_database_older_than_the_settings_uses_the_default_zone(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[server]\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    command.upgrade(migrate.alembic_config(Config(state_dir=tmp_path).database_url), "0001")
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 7, 1, 16, 0, 0, tzinfo=UTC))
    assert _backup().name == "hirdir-20260701T120000-0400.db"


def test_only_the_newest_backups_are_kept_whatever_zone_named_them(
    installed: Config, monkeypatch
) -> None:
    folder = installed.backup_dir
    folder.mkdir()
    # Written by 0.2.0, in UTC, and by hand, with no time in its name but an old file.
    old_names = ["hirdir-20261110T020000Z.db", "hirdir-20261111T020000Z.db", "hirdir-by-hand.db"]
    for name in old_names:
        (folder / name).write_bytes(b"")
    long_ago = time.time() - 30 * 86400
    os.utime(folder / "hirdir-by-hand.db", (long_ago, long_ago))
    # Named in a zone east of UTC: as text it would sort before the ones above.
    (folder / "hirdir-20261112T040000+0100.db").write_bytes(b"")
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 13, 2, 0, 0, tzinfo=UTC))
    newest = _backup()
    assert sorted(path.name for path in folder.glob("hirdir-*.db")) == sorted(
        ["hirdir-20261111T020000Z.db", "hirdir-20261112T040000+0100.db", newest.name]
    )


def test_migration_keeps_support_weight_to_two_places(tmp_path: Path) -> None:
    url = Config(state_dir=tmp_path).database_url
    command.upgrade(migrate.alembic_config(url), "0002")
    engine = make_engine(url)
    row = (
        "INSERT INTO vendors (hid, name, name_key, aliases, created_at, updated_at, row_version)"
        " VALUES ('v', 'Cisco', 'cisco', '[]', '2026-01-01', '2026-01-01', 1)"
    )
    entry = (
        "INSERT INTO catalog_entries (hid, vendor_hid, pid, pid_key, kind, review_status,"
        " record_status, support_weight, est_value, created_at, updated_at, row_version)"
        " VALUES (:hid, 'v', :hid, :hid, 'hardware', 'reviewed', 'active', :weight, 1800000,"
        " '2026-01-01', '2026-01-01', 1)"
    )
    item = (
        "INSERT INTO items (hid, name, quantity, record_status, support_weight, created_at,"
        " updated_at, row_version) VALUES (:hid, :hid, 1, 'active', :weight, '2026-01-01',"
        " '2026-01-01', 1)"
    )
    # As 0.2.0 stored them, in thousandths: 1.5, 0.125, 0.124 and none.
    weights = {"a": 1500, "b": 125, "c": 124, "d": None}
    with engine.begin() as connection:
        connection.execute(text(row))
        for hid, weight in weights.items():
            connection.execute(text(entry), {"hid": hid, "weight": weight})
            connection.execute(text(item), {"hid": hid, "weight": weight})
    engine.dispose()

    migrate.upgrade(url)

    engine = make_engine(url)
    with engine.connect() as connection:
        expected = {"a": 150, "b": 13, "c": 12, "d": None}
        entries = connection.execute(text("SELECT hid, support_weight FROM catalog_entries"))
        assert dict(entries.all()) == expected
        items = connection.execute(text("SELECT hid, support_weight FROM items"))
        assert dict(items.all()) == expected
        value = connection.execute(text("SELECT est_value FROM catalog_entries WHERE hid = 'a'"))
        assert value.scalar() == 1800000


def test_signing_in_says_when_the_session_ends_in_the_applications_time(
    tmp_path: Path, monkeypatch
) -> None:
    asked = []

    def call(target: client.Target, method: str, path: str, body: object = None) -> object:
        asked.append((method, path))
        if path == "/auth/sign-in":
            return {
                "token": "a-token",
                "expires_at": "2026-02-01T02:05:09Z",
                "user": {"username": "ada", "role": "admin"},
            }
        assert target.token == "a-token"
        return [
            {"key": "currency", "value": "USD"},
            {"key": "time_zone", "value": "America/Chicago"},
        ]

    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(client, "save_target", lambda target: tmp_path / "config.toml")
    result = runner.invoke(
        app, ["sign-in", "--url", "https://hirdir.example", "--username", "ada"], input="code\n"
    )
    assert result.exit_code == 0, result.output
    assert "signed in as ada (admin) until 2026-01-31 20:05:09 CST" in result.output
    assert asked == [("POST", "/auth/sign-in"), ("GET", "/settings")]
