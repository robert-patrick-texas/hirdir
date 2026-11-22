"""`hirdir admin create-user`, which makes the first Admin and the contact it is (P-172)."""

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from hirdir.auth.roles import Role
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import AuditEvent, Contact, User
from hirdir.domain import accounts, audit

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
    bare = runner.invoke(app, ["admin", "create-user", "--no-role", "lee"])
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
    tokens are refused until it is given a role (P-299). A person is made so with
    --no-role alone (P-313)."""
    _installed(tmp_path, monkeypatch)
    person = runner.invoke(app, ["admin", "create-user", "--no-role", "lee"])
    assert person.exit_code == 0, person.output
    assert "lee holds no role, and cannot sign in until an Admin gives it one" in person.output
    service = runner.invoke(app, ["admin", "create-user", "--kind", "service", "svc2"])
    assert service.exit_code == 0, service.output
    assert (
        "svc2 holds no role, and its tokens are refused until an Admin gives it one"
        in service.output
    )
    assert "sign in" not in service.output
    held = runner.invoke(app, ["admin", "create-user", "--role", "viewer", "vic"])
    assert "holds no role" not in held.output


def test_a_user_is_put_in_groups_by_name_and_has_a_groups_role(tmp_path: Path, monkeypatch) -> None:
    """P-304: `--group NAME`, again for another; a group that grants a role gives the
    user that role, and a name that no group has makes nothing."""
    config = _installed(tmp_path, monkeypatch)
    sessions = make_sessions(make_engine(config.database_url))
    with sessions() as db:
        noc = accounts.create_group(db, audit.SYSTEM, name="NOC")
        accounts.grant_role(db, audit.SYSTEM, role="inventory", group_hid=noc.hid)
        accounts.create_group(db, audit.SYSTEM, name="Field team")
        db.commit()
    made = runner.invoke(
        app, ["admin", "create-user", "--group", "noc", "--group", "Field team", "lee"]
    )
    assert made.exit_code == 0, made.output
    assert "in the groups NOC, Field team" in made.output
    assert "lee holds the inventory role through its groups" in made.output
    assert "holds no role" not in made.output
    # A group that grants no role gives a person none: it is refused, and made with
    # --no-role (P-313).
    plain = runner.invoke(app, ["admin", "create-user", "--group", "Field team", "kai"])
    assert plain.exit_code == 4, plain.output
    assert "--no-role" in plain.output
    plain = runner.invoke(
        app, ["admin", "create-user", "--group", "Field team", "--no-role", "kai"]
    )
    assert plain.exit_code == 0, plain.output
    assert "kai holds no role, and cannot sign in until an Admin gives it one" in plain.output
    refused = runner.invoke(app, ["admin", "create-user", "--group", "Nobody", "sam"])
    assert refused.exit_code == 4
    assert "there is no user group named Nobody" in refused.output
    with sessions() as db:
        lee = accounts.find_user(db, "lee")
        assert lee is not None
        assert accounts.effective_role(db, lee) is Role.INVENTORY
        assert accounts.find_user(db, "sam") is None
        joined = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "add_member", AuditEvent.record_hid == noc.hid
            )
        ).all()
        assert len(joined) == 1
