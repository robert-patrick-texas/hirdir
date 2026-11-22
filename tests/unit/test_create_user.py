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


def test_a_person_with_no_role_is_refused_unless_no_role_is_given(
    tmp_path: Path, monkeypatch
) -> None:
    """P-313: as New user does, a person with no --role and no --group that grants one is
    refused, exit 4, and nothing is made; --no-role makes it, with the warning; --role
    with --no-role is a mistake of usage, exit 2."""
    config = _installed(tmp_path, monkeypatch)
    refused = runner.invoke(app, ["admin", "create-user", "--name", "Kim Lee", "klee"])
    assert refused.exit_code == 4, refused.output
    assert refused.output.strip() == (
        "hirdir: a person is made with a role, since an account with no role does not sign "
        "in: give --role, a --group that grants one, or --no-role to make it with none"
    )
    both = runner.invoke(app, ["admin", "create-user", "--role", "viewer", "--no-role", "klee"])
    assert both.exit_code == 2, both.output
    assert "--role and --no-role are not given together" in both.output
    with make_sessions(make_engine(config.database_url))() as db:
        assert accounts.find_user(db, "klee") is None
        assert db.scalar(select(Contact).where(Contact.name == "Kim Lee")) is None
        assert db.scalars(select(AuditEvent)).all() == []
    made = runner.invoke(app, ["admin", "create-user", "--no-role", "klee"])
    assert made.exit_code == 0, made.output
    assert "klee holds no role, and cannot sign in until an Admin gives it one" in made.output


def test_an_agent_is_made_for_a_person_and_never_admin(tmp_path: Path, monkeypatch) -> None:
    """P-316: --kind agent with --for USERNAME; --for is needed by an agent alone, and the
    rules of an agent are the server's, exit 4."""
    config = _installed(tmp_path, monkeypatch)
    assert runner.invoke(app, ["admin", "create-user", "--role", "inventory", "sam"]).exit_code == 0
    for args, words in (
        (["--kind", "agent", "agent-reconcile"], "name them with --for USERNAME"),
        (["--for", "sam", "--role", "viewer", "lee"], "give it with --kind agent"),
        (["--kind", "robot", "lee"], "the kind must be person, service or agent"),
        (["--kind", "service", "--for", "sam", "svc"], "give it with --kind agent"),
    ):
        refused = runner.invoke(app, ["admin", "create-user", *args])
        assert refused.exit_code == 2, (args, refused.output)
        assert words in refused.output
    for args, words in (
        (["--for", "nobody"], "there is no user named nobody"),
        (["--for", "sam", "--role", "admin"], "an agent is never Admin"),
    ):
        refused = runner.invoke(
            app, ["admin", "create-user", "--kind", "agent", *args, "agent-reconcile"]
        )
        assert refused.exit_code == 4, (args, refused.output)
        assert words in refused.output
    made = runner.invoke(
        app,
        [
            "admin",
            "create-user",
            "--kind",
            "agent",
            "--for",
            "SAM",
            "--role",
            "inventory",
            "agent-reconcile",
        ],
    )
    assert made.exit_code == 0, made.output
    assert "created agent-reconcile, an agent answerable to sam, with the inventory role" in (
        made.output
    )
    assert "access code" not in made.output
    bare = runner.invoke(
        app, ["admin", "create-user", "--kind", "agent", "--for", "sam", "agent-two"]
    )
    assert bare.exit_code == 0, bare.output
    assert "agent-two holds no role, and its tokens are refused until an Admin gives it one" in (
        bare.output
    )
    with make_sessions(make_engine(config.database_url))() as db:
        agent = accounts.find_user(db, "agent-reconcile")
        sam = accounts.find_user(db, "sam")
        assert agent is not None
        assert sam is not None
        assert (agent.kind, agent.answerable_hid, agent.access_code_hash) == (
            "agent",
            sam.hid,
            None,
        )
