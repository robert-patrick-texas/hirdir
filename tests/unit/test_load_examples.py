"""`hirdir admin load-examples`: the examples loaded by one command, into an empty inventory."""

import shutil
import socket
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from typer.testing import CliRunner

from hirdir.app import create_app
from hirdir.cli import admin
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import AuditEvent, ImportJob, Item, Setting, Tag, User, Vendor
from hirdir.domain import accounts, audit, reset, settings, tags
from hirdir.io import examples, imports
from hirdir.io.entities import LOAD_ORDER

runner = CliRunner()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch) -> Config:
    """An installation that is not serving, with an account, a setting, a preview that
    was never applied, and no record of the inventory."""
    path = tmp_path / "config.toml"
    path.write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=tmp_path, listen="127.0.0.1:1")
    migrate.upgrade(config.database_url)
    with make_sessions(make_engine(config.database_url))() as db:
        ada, _ = accounts.create_user(db, audit.SYSTEM, username="ada", access_code="a-code")
        accounts.grant_role(db, audit.SYSTEM, role="admin", user_hid=ada.hid)
        context = audit.AuditContext(actor_hid=ada.hid, via="api", request_id="r-1")
        settings.set_setting(db, context, "stack_discount_pct", 0, 40)
        imports.preview(
            db, context, None, data=b"name\nJuniper\n", format_="csv", entity_name="vendors"
        )
        db.commit()
    return config


def held(config: Config, model) -> int:
    with make_sessions(make_engine(config.database_url))() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def inventory(config: Config) -> dict[str, int]:
    with make_sessions(make_engine(config.database_url))() as db:
        return reset.held(db)


def test_what_does_not_make_an_inventory_is_cleared_by_a_reset() -> None:
    assert set(reset.BOOKKEEPING) < set(reset.CLEARED)


def test_the_examples_load_as_stored_imports_audited_as_the_system(installed: Config) -> None:
    assert inventory(installed) == {}
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 0, result.output
    assert f"loading the examples from {examples.folder()}:" in result.output
    assert "tags.csv" in result.output
    assert "to clear them, with the service stopped: hirdir admin reset" in result.output
    with make_sessions(make_engine(installed.database_url))() as db:
        jobs = db.scalars(
            select(ImportJob).where(ImportJob.status == "applied").order_by(ImportJob.created_at)
        ).all()
        assert [job.file_name for job in jobs] == [examples.file_name(e) for e in LOAD_ORDER]
        assert {(job.created_by, job.applied_by, job.rejected) for job in jobs} == {(None, None, 0)}
        made = db.scalars(select(AuditEvent).where(AuditEvent.record_type == "item")).all()
        assert made
        assert {(event.actor_hid, event.via) for event in made} == {(None, "import")}
        loaded = sum(job.created for job in jobs)
    assert f"loaded {loaded:,} records of the examples" in result.output
    assert held(installed, Item) > 0
    # Nothing of the accounts or the settings is touched.
    assert (held(installed, User), held(installed, Setting)) == (1, 1)


def test_a_reset_takes_the_examples_and_leaves_the_inventory_empty(installed: Config) -> None:
    assert runner.invoke(app, ["admin", "load-examples"]).exit_code == 0
    assert runner.invoke(app, ["admin", "reset", "--yes"]).exit_code == 0
    assert inventory(installed) == {}
    assert held(installed, User) == 1


def test_an_inventory_that_holds_a_record_is_refused(installed: Config) -> None:
    with make_sessions(make_engine(installed.database_url))() as db:
        tags.create_tag(db, audit.SYSTEM, {"label": "ours"})
        db.commit()
    jobs = held(installed, ImportJob)
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert "the inventory is not empty: it holds 1 tags" in result.output
    assert "hirdir admin reset" in result.output
    assert (held(installed, ImportJob), held(installed, Tag)) == (jobs, 1)


def test_a_second_load_is_refused_and_changes_nothing(installed: Config) -> None:
    assert runner.invoke(app, ["admin", "load-examples"]).exit_code == 0
    events = held(installed, AuditEvent)
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert "the inventory is not empty: it holds 4 tags, 11 vendors" in result.output
    assert "kinds of record more" in result.output
    assert held(installed, AuditEvent) == events


def test_it_refuses_while_the_service_is_running(installed: Config, monkeypatch) -> None:
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        serving = Config(
            state_dir=installed.state_dir, listen=f"127.0.0.1:{listening.getsockname()[1]}"
        )
        monkeypatch.setattr(admin, "_load", lambda: serving)
        result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert "stop it first" in result.output
    assert inventory(installed) == {}


def test_it_refuses_while_an_import_waits_to_be_applied(installed: Config) -> None:
    with make_sessions(make_engine(installed.database_url))() as db:
        db.execute(update(ImportJob).values(status="queued"))
        db.commit()
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert "1 imports wait to be applied" in result.output
    assert inventory(installed) == {}


def test_a_rejected_row_stops_the_load_there_and_a_reset_clears_what_came_before(
    installed: Config, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "examples"
    shutil.copytree(examples.folder(), source)
    vendors = source / "vendors.csv"
    vendors.write_text(vendors.read_text() + ",Nowhere Networks,,,maybe\n")
    monkeypatch.setattr(examples, "folder", lambda: source)
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert (
        "1 of the 12 rows of vendors.csv are rejected, so the load stopped there" in result.output
    )
    assert "review_status" in result.output
    assert "the 1 files before it stay loaded; to clear them: hirdir admin reset" in result.output
    assert (held(installed, Tag), held(installed, Vendor)) == (4, 0)
    assert runner.invoke(app, ["admin", "reset", "--yes"]).exit_code == 0
    assert inventory(installed) == {}


def test_a_folder_that_lacks_a_file_loads_nothing(
    installed: Config, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "examples"
    source.mkdir()
    shutil.copy(examples.folder() / "tags.csv", source)
    monkeypatch.setattr(examples, "folder", lambda: source)
    result = runner.invoke(app, ["admin", "load-examples"])
    assert result.exit_code == 1
    assert f"lacks {len(LOAD_ORDER) - 1} of the {len(LOAD_ORDER)} files" in result.output
    assert "the first vendors.csv" in result.output
    assert inventory(installed) == {}


def test_a_checkout_loads_the_files_that_make_examples_writes() -> None:
    assert examples.folder() == Path(__file__).resolve().parents[2] / "examples"


def test_no_route_of_the_api_loads_the_examples(installed: Config) -> None:
    paths = list(create_app(installed).openapi()["paths"])
    assert "/api/v1/imports/preview" in paths
    assert not [path for path in paths if "example" in path]
