"""`hirdir admin reset`: clearing the inventory on the server, to start over."""

import socket
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from hirdir.app import create_app
from hirdir.cli import admin
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import (
    Address,
    AuditEvent,
    Base,
    Choice,
    DeviceGroup,
    DeviceGroupMember,
    ImportJob,
    Item,
    ItemReplacement,
    LifecycleRule,
    Network,
    Setting,
    Tag,
    User,
    Vendor,
)
from hirdir.domain import (
    accounts,
    addresses,
    audit,
    catalog,
    groups,
    items,
    replacements,
    reset,
    settings,
    tags,
)
from hirdir.io import imports

runner = CliRunner()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch) -> Config:
    """An installation that is not serving, with accounts, a setting and an inventory."""
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
        tags.create_tag(db, context, {"label": "refresh-2030"})
        vendor = catalog.create_vendor(db, context, {"name": "Cisco"})
        old = catalog.create_entry(db, context, {"vendor_hid": vendor.hid, "pid": "C9200L-48P-4G"})
        new = catalog.create_entry(db, context, {"vendor_hid": vendor.hid, "pid": "C9300-48P"})
        catalog.update_entry(db, context, old.hid, 1, {"successor_hid": new.hid})
        for number in (1, 2):
            items.create_item(
                db,
                context,
                {
                    "catalog_entry_hid": new.hid,
                    "serial_number": f"FCW0000X00{number}",
                    "tags": ["refresh-2030"],
                },
            )
        imports.preview(
            db, context, None, data=b"name\nJuniper\n", format_="csv", entity_name="vendors"
        )
        db.commit()
    return config


def held(config: Config, model) -> int:
    with make_sessions(make_engine(config.database_url))() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def test_every_table_is_one_that_a_reset_clears_or_one_that_it_keeps() -> None:
    named = {model.__tablename__ for model in (*reset.CLEARED, *reset.KEPT)}
    assert named == set(Base.metadata.tables)
    assert not {m.__tablename__ for m in reset.CLEARED} & {m.__tablename__ for m in reset.KEPT}


def test_reset_clears_the_inventory_and_keeps_accounts_and_settings(installed: Config) -> None:
    result = runner.invoke(app, ["admin", "reset"], input="reset\n")
    assert result.exit_code == 0, result.output
    assert "2  items" in result.output
    for model in (Item, Vendor, Tag, ImportJob):
        assert held(installed, model) == 0, model
    assert held(installed, User) == 1
    assert held(installed, LifecycleRule) == 9
    assert held(installed, Choice) > 0
    assert held(installed, Setting) == 1
    with make_sessions(make_engine(installed.database_url))() as db:
        assert settings.value(db, "stack_discount_pct") == 40
        events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.at, AuditEvent.hid)))
    kinds = {event.record_type for event in events}
    assert {"user", "setting", "inventory"} <= kinds
    assert not kinds & set(reset.RECORD_TYPES)
    said = {entry["field"]: entry for entry in events[-1].changes}
    assert (events[-1].action, events[-1].via) == ("reset", "system")
    assert (said["items"]["old"], said["items"]["new"]) == (2, 0)

    # The backup it took first holds what was there, and its name is in the event.
    backup = installed.backup_dir / said["backup"]["new"]
    assert f"backup: {backup}" in result.output
    with sqlite3.connect(backup) as before:
        assert before.execute("SELECT count(*) FROM items").fetchone()[0] == 2
    assert oct(backup.stat().st_mode & 0o777) == "0o600"


STRUCTURE = (Address, Network, DeviceGroupMember, DeviceGroup, ItemReplacement)


def _with_structure(config: Config) -> None:
    """Add what refers to other records of its own kind: an item in an item, a group in
    a group, a replacement, and an address under a network."""
    with make_sessions(make_engine(config.database_url))() as db:
        context = audit.AuditContext(actor_hid=None, via="api", request_id="r-2")
        first, second = db.scalars(select(Item).order_by(Item.serial_key)).all()
        items.create_item(db, context, {"name": "PS-A", "parent_item_hid": first.hid})
        domain = groups.create_group(db, context, {"type": "custom", "name": "site2"})
        stack = groups.create_group(
            db,
            context,
            {
                "type": "stack",
                "name": "site2-sw-stack1",
                "parent_group_hid": domain.hid,
                "members": [
                    {"item_hid": first.hid, "role": "master"},
                    {"item_hid": second.hid, "role": "member"},
                ],
            },
        )
        red = addresses.create_network(db, context, {"label": "Red"})
        for holder in ({"item_hid": first.hid}, {"group_hid": stack.hid}):
            addresses.create_address(
                db, context, {**holder, "address": "192.0.2.10", "network_hid": red.hid}
            )
        replacements.replace(
            db, context, second.hid, second.row_version, reason="rma", new_item={"name": "new"}
        )
        db.commit()


@pytest.mark.parametrize("arguments", [[], ["--everything"]])
def test_reset_clears_the_records_that_refer_to_one_another(
    installed: Config, arguments: list[str]
) -> None:
    _with_structure(installed)
    assert [held(installed, model) for model in STRUCTURE] == [2, 1, 3, 2, 1]
    assert held(installed, Item) == 4

    result = runner.invoke(app, ["admin", "reset", "--yes", *arguments])

    assert result.exit_code == 0, result.output
    for name in ("addresses", "networks", "device groups", "device group members"):
        assert name in result.output
    for model in (*STRUCTURE, Item):
        assert held(installed, model) == 0, model
    with make_sessions(make_engine(installed.database_url))() as db:
        left = set(db.scalars(select(AuditEvent.record_type)))
    assert not left & set(reset.RECORD_TYPES)


def test_reset_does_nothing_unless_the_word_is_typed(installed: Config) -> None:
    for typed in ("\n", "yes\n", "RESET \n"):
        result = runner.invoke(app, ["admin", "reset"], input=typed)
        assert result.exit_code == 1, result.output
        assert "nothing was changed" in result.output
    assert held(installed, Item) == 2
    assert not installed.backup_dir.exists()
    assert runner.invoke(app, ["admin", "reset", "--yes"]).exit_code == 0
    assert held(installed, Item) == 0


def test_reset_refuses_while_the_service_is_running(installed: Config, monkeypatch) -> None:
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        serving = Config(
            state_dir=installed.state_dir, listen=f"127.0.0.1:{listening.getsockname()[1]}"
        )
        assert admin._is_serving(serving)
        monkeypatch.setattr(admin, "_load", lambda: serving)
        result = runner.invoke(app, ["admin", "reset", "--yes", "--everything"])
    assert result.exit_code == 1
    assert "stop it first" in result.output
    assert held(installed, Item) == 2
    assert not admin._is_serving(installed)


def test_reset_everything_leaves_a_fresh_installation(installed: Config) -> None:
    result = runner.invoke(app, ["admin", "reset", "--everything"], input="reset\n")
    assert result.exit_code == 0, result.output
    assert "the 1 accounts" in result.output
    for model in (Item, Vendor, User, Setting, AuditEvent):
        assert held(installed, model) == 0, model
    assert held(installed, LifecycleRule) == 9
    engine = make_engine(installed.database_url)
    assert migrate.current(engine) == migrate.head(installed.database_url)
    database = installed.database_path
    assert database is not None
    assert oct(database.stat().st_mode & 0o777) == "0o600"
    # The way back is printed, and it works.
    backup = result.output.split("hirdir admin restore ")[1].strip()
    engine.dispose()
    assert runner.invoke(app, ["admin", "restore", backup]).exit_code == 0
    assert (held(installed, Item), held(installed, User)) == (2, 1)


def test_no_route_of_the_api_resets_anything(installed: Config) -> None:
    paths = list(create_app(installed).openapi()["paths"])
    assert "/api/v1/items" in paths
    assert not [path for path in paths if "reset" in path]
