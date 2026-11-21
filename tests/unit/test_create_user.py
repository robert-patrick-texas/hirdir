"""`hirdir admin create-user`, which makes the first Admin and the contact it is (P-172)."""

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import Contact, User

runner = CliRunner()


def _installed(tmp_path: Path, monkeypatch) -> Config:
    path = tmp_path / "config.toml"
    path.write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=tmp_path, listen="127.0.0.1:1")
    migrate.upgrade(config.database_url)
    return config


def test_the_first_admin_is_made_with_the_contact_it_is(tmp_path: Path, monkeypatch) -> None:
    config = _installed(tmp_path, monkeypatch)
    made = runner.invoke(
        app,
        [
            "admin",
            "create-user",
            "--role",
            "admin",
            "--name",
            "Ada Example",
            "--email",
            "ada@example.org",
            "--phone2",
            "+1 202 555 0101",
            "ada",
        ],
    )
    assert made.exit_code == 0, made.output
    assert "access code: " in made.output
    bare = runner.invoke(app, ["admin", "create-user", "lee"])
    assert bare.exit_code == 0, bare.output
    with make_sessions(make_engine(config.database_url))() as db:
        ada = db.scalar(select(User).where(User.username == "ada"))
        assert ada is not None
        contact = db.get(Contact, ada.contact_hid)
        assert contact is not None
        assert (contact.name, contact.email, contact.phone2) == (
            "Ada Example",
            "ada@example.org",
            "+1 202 555 0101",
        )
        assert db.scalar(select(User.contact_hid).where(User.username == "lee")) is None


def test_an_email_without_a_name_is_refused(tmp_path: Path, monkeypatch) -> None:
    _installed(tmp_path, monkeypatch)
    refused = runner.invoke(app, ["admin", "create-user", "--email", "x@example.org", "kai"])
    assert refused.exit_code == 2
    assert "--name" in refused.output


def test_an_account_made_with_no_role_is_told_what_that_means_for_it(
    tmp_path: Path, monkeypatch
) -> None:
    """A person with no role cannot sign in; a service account never signs in, and its
    tokens are refused until it is given a role (P-299)."""
    _installed(tmp_path, monkeypatch)
    person = runner.invoke(app, ["admin", "create-user", "lee"])
    assert person.exit_code == 0, person.output
    assert "lee holds no role, and cannot sign in until an Admin gives it one" in person.output
    service = runner.invoke(app, ["admin", "create-user", "--service-account", "svc2"])
    assert service.exit_code == 0, service.output
    assert (
        "svc2 holds no role, and its tokens are refused until an Admin gives it one"
        in service.output
    )
    assert "sign in" not in service.output
    held = runner.invoke(app, ["admin", "create-user", "--role", "viewer", "vic"])
    assert "holds no role" not in held.output
