"""`hirdir admin` holds a code that is typed to the least length the setting says, and
makes its own codes whatever it says (P-295)."""

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from hirdir.auth import codes
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import User
from hirdir.domain import audit, settings

runner = CliRunner()


def _installed(tmp_path: Path, monkeypatch) -> Config:
    path = tmp_path / "config.toml"
    path.write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=tmp_path, listen="127.0.0.1:1")
    migrate.upgrade(config.database_url)
    return config


def _accepts(config: Config, username: str, code: str) -> bool:
    with make_sessions(make_engine(config.database_url))() as db:
        held = db.scalar(select(User.access_code_hash).where(User.username == username))
        return codes.verify(held, code)


def test_create_user_refuses_a_typed_code_that_is_too_short_and_says_the_length(
    tmp_path: Path, monkeypatch
) -> None:
    config = _installed(tmp_path, monkeypatch)
    short = runner.invoke(app, ["admin", "create-user", "--access-code", "eleven-char", "ada"])
    assert short.exit_code == 4, short.output
    assert "the access code is too short: at least 12 characters" in short.output
    with make_sessions(make_engine(config.database_url))() as db:
        assert db.scalar(select(User).where(User.username == "ada")) is None

    made = runner.invoke(app, ["admin", "create-user", "--access-code", "twelve-chars", "ada"])
    assert made.exit_code == 0, made.output
    # A code that was typed is not printed back.
    assert "twelve-chars" not in made.output
    assert _accepts(config, "ada", "twelve-chars")


def test_reset_access_code_refuses_a_typed_code_that_is_too_short_and_changes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    config = _installed(tmp_path, monkeypatch)
    runner.invoke(app, ["admin", "create-user", "--access-code", "twelve-chars", "ada"])
    short = runner.invoke(app, ["admin", "reset-access-code", "--access-code", "short", "ada"])
    assert short.exit_code == 4, short.output
    assert "the access code is too short: at least 12 characters" in short.output
    assert "every session" not in short.output
    assert _accepts(config, "ada", "twelve-chars")

    changed = runner.invoke(
        app, ["admin", "reset-access-code", "--access-code", "thirteen-char", "ada"]
    )
    assert changed.exit_code == 0, changed.output
    assert _accepts(config, "ada", "thirteen-char")
    assert not _accepts(config, "ada", "twelve-chars")


def test_the_setting_holds_for_hirdir_admin_and_a_made_code_is_not_held_to_it(
    tmp_path: Path, monkeypatch
) -> None:
    config = _installed(tmp_path, monkeypatch)
    with make_sessions(make_engine(config.database_url))() as db:
        settings.set_setting(db, audit.SYSTEM, settings.CODE_LENGTH_SETTING, 0, 20)
        db.commit()
    short = runner.invoke(app, ["admin", "create-user", "--access-code", "twelve-chars", "ada"])
    assert short.exit_code == 4, short.output
    assert "at least 20 characters" in short.output

    made = runner.invoke(app, ["admin", "create-user", "ada"])
    assert made.exit_code == 0, made.output
    code = made.output.split("access code: ")[1].strip()
    assert len(code) == 14
    assert _accepts(config, "ada", code)
    again = runner.invoke(app, ["admin", "reset-access-code", "ada"])
    assert again.exit_code == 0, again.output
    assert _accepts(config, "ada", again.output.split("access code: ")[1].strip())


def test_reset_access_code_gives_a_retired_account_none(tmp_path: Path, monkeypatch) -> None:
    """A retired account is given no code by `hirdir admin` either, which comes to
    `set_access_code` with no route (P-296)."""
    from hirdir.domain import accounts

    config = _installed(tmp_path, monkeypatch)
    # Two Admins, so that retiring one leaves an Admin.
    for name in ("ada", "bo"):
        made = runner.invoke(app, ["admin", "create-user", "--role", "admin", name])
        assert made.exit_code == 0, made.output
    with make_sessions(make_engine(config.database_url))() as db:
        user = db.scalar(select(User).where(User.username == "ada"))
        assert user is not None
        accounts.retire_user(db, audit.SYSTEM, user.hid, None)
        db.commit()

    for typed in ([], ["--access-code", "twelve-chars"]):
        refused = runner.invoke(app, ["admin", "reset-access-code", *typed, "ada"])
        assert refused.exit_code == 4, refused.output
        assert "the account ada is retired and is given no access code" in refused.output
    with make_sessions(make_engine(config.database_url))() as db:
        assert db.scalar(select(User.access_code_hash).where(User.username == "ada")) is None
