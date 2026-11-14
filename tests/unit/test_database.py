"""The migrations, the connection settings and the configuration."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from hirdir import config as config_module
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions, trial
from hirdir.db.models import Base


def test_migrations_build_exactly_the_schema_of_the_models(config: Config) -> None:
    engine = make_engine(config.database_url)
    assert migrate.current(engine) == migrate.head(config.database_url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def test_migration_that_fails_part_way_leaves_the_database_as_it_was(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0001")
    engine = make_engine(url)
    before = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        # In the way of the last table that migration 0002 creates.
        connection.execute(text("CREATE TABLE items (x INTEGER)"))
        connection.execute(
            text(
                "INSERT INTO users (hid, username, username_key, display_name,"
                " email, is_service_account, tokens_valid_after, disabled,"
                " created_at, updated_at, row_version) VALUES ('u1', 'ada', 'ada',"
                " '', '', 0, 0, 0, '2026-01-01', '2026-01-01', 1)"
            )
        )
    engine.dispose()

    with pytest.raises(OperationalError, match="already exists"):
        migrate.upgrade(url)

    engine = make_engine(url)
    assert migrate.current(engine) == "0001"
    assert set(inspect(engine).get_table_names()) == before | {"items"}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT username FROM users")).scalars().all() == ["ada"]
        connection.execute(text("DROP TABLE items"))
    engine.dispose()
    # With what was in the way gone, the same database migrates, and is loaded once.
    migrate.upgrade(url)
    engine = make_engine(url)
    assert migrate.current(engine) == migrate.head(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM lifecycle_rules")).scalar() == 9
        assert connection.execute(text("SELECT username FROM users")).scalars().all() == ["ada"]


def test_every_connection_gets_the_pragmas(config: Config) -> None:
    with make_engine(config.database_url).connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000


def test_missing_config_file_gives_the_defaults(tmp_path: Path) -> None:
    loaded = config_module.load(tmp_path / "absent.toml")
    assert loaded.listen == "127.0.0.1:8715"
    assert loaded.session_hours == 12
    assert loaded.host_port == ("127.0.0.1", 8715)
    assert loaded.source is None
    assert loaded.state_dir == Path("/var/lib/hirdir")


def test_config_file_overrides_and_a_relative_state_dir_is_beside_it(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[server]\nlisten = "127.0.0.1:9000"\nstate_dir = "."\n[access]\nsession_hours = 2\n'
    )
    loaded = config_module.load(path)
    assert loaded.host_port == ("127.0.0.1", 9000)
    assert loaded.session_hours == 2
    assert loaded.state_dir == tmp_path
    assert loaded.database_path == tmp_path / "hirdir.db"


def test_the_upgrade_to_0006_keeps_what_is_held_and_ends_what_d103_ends(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0005")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO items (hid, name, quantity, lifecycle_state, record_status,"
                " created_at, updated_at, row_version)"
                " VALUES (:hid, :hid, 1, :state, 'active', '2026-01-01', '2026-01-01', 1)"
            ),
            [
                {"hid": "i-prod", "state": "Prod"},
                {"hid": "i-archived", "state": "Archived"},
                {"hid": "i-released", "state": "Released"},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO device_groups (hid, type, name, name_key, record_status,"
                " created_at, updated_at, row_version)"
                " VALUES (:hid, :kind, :hid, :hid, 'active', '2026-01-01', '2026-01-01', 1)"
            ),
            [{"hid": "g-stack", "kind": "stack"}, {"hid": "g-cluster", "kind": "cluster"}],
        )
        connection.execute(
            text(
                "INSERT INTO device_group_members (hid, group_hid, item_hid, role, joined_on,"
                " created_at, updated_at, row_version)"
                " VALUES (:hid, :group_hid, :item, 'member', '2024-01-01',"
                " '2026-01-01', '2026-01-01', 1)"
            ),
            [
                {"hid": "m-1", "group_hid": "g-stack", "item": "i-prod"},
                {"hid": "m-2", "group_hid": "g-stack", "item": "i-archived"},
                {"hid": "m-3", "group_hid": "g-cluster", "item": "i-released"},
            ],
        )
        # A condition of the site's own, entered before the list had its defaults.
        connection.execute(
            text(
                "INSERT INTO choices (hid, list, value, value_key, label, sort, active,"
                " created_at, updated_at, row_version) VALUES ('c-1', 'item_condition',"
                " 'good', 'good', 'Works', 5, 1, '2026-01-01', '2026-01-01', 1)"
            )
        )
    engine.dispose()

    migrate.upgrade(url)

    engine = make_engine(url)
    with engine.connect() as connection:
        assert migrate.current(engine) == migrate.head(url)
        # Every item is as it was, with nothing said yet of how it is doing.
        items = connection.execute(
            text("SELECT hid, lifecycle_state, condition, observed_status FROM items ORDER BY hid")
        ).all()
        assert [tuple(row) for row in items] == [
            ("i-archived", "Archived", None, None),
            ("i-prod", "Prod", None, None),
            ("i-released", "Released", None, None),
        ]
        # A cluster is managed as one node, as it was counted, and a stack says nothing.
        managed = connection.execute(
            text("SELECT hid, managed_as FROM device_groups ORDER BY hid")
        ).all()
        assert [tuple(row) for row in managed] == [("g-cluster", "one"), ("g-stack", None)]
        # The memberships of the items that had left the team's hands are ended, each on
        # record; the one of the item in service stands.
        left = dict(
            connection.execute(text("SELECT hid, left_on IS NULL FROM device_group_members")).all()
        )
        assert left == {"m-1": 1, "m-2": 0, "m-3": 0}
        ended = connection.execute(
            text(
                "SELECT record_hid, via, action FROM audit_events"
                " WHERE record_type = 'device_group_member' ORDER BY record_hid"
            )
        ).all()
        assert [tuple(row) for row in ended] == [
            ("m-2", "system", "update"),
            ("m-3", "system", "update"),
        ]
        # The list of conditions has its defaults, beside the one the site had entered.
        conditions = dict(
            connection.execute(
                text("SELECT value, label FROM choices WHERE list = 'item_condition'")
            ).all()
        )
        assert conditions["good"] == "Works"
        assert set(conditions) == {"untested", "good", "degraded", "suspect", "failed", "dead"}
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
    # And back: the schema of 0.4.0, with the rows still there.
    command.downgrade(migrate.alembic_config(url), "0005")
    engine = make_engine(url)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(items)"))}
        assert "condition" not in columns
        assert connection.execute(text("SELECT count(*) FROM items")).scalar() == 3
    engine.dispose()


def test_a_database_copied_for_a_test_is_one_that_was_migrated(config: Config) -> None:
    # The fixtures copy one database that was migrated once: it is whole, and at the head.
    engine = make_engine(config.database_url)
    try:
        assert migrate.current(engine) == migrate.head(config.database_url)
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
            assert connection.execute(text("SELECT count(*) FROM choices")).scalar() != 0
            assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "Etc/GMT+12"])
def test_the_upgrade_to_0006_ends_a_membership_on_the_applications_day(
    tmp_path: Path, zone: str
) -> None:
    # The two zones are 26 hours apart, so at any moment the day of at least one of them
    # is not the day in UTC.
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0005")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO settings (hid, key, value, created_at, updated_at, row_version)"
                " VALUES ('s-1', 'time_zone', :zone, '2026-01-01', '2026-01-01', 1)"
            ),
            {"zone": json.dumps(zone)},
        )
        connection.execute(
            text(
                "INSERT INTO items (hid, name, quantity, lifecycle_state, record_status,"
                " created_at, updated_at, row_version)"
                " VALUES ('i-1', 'i-1', 1, 'Released', 'active', '2026-01-01', '2026-01-01', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO device_groups (hid, type, name, name_key, record_status,"
                " created_at, updated_at, row_version)"
                " VALUES ('g-1', 'stack', 'g-1', 'g-1', 'active', '2026-01-01', '2026-01-01', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO device_group_members (hid, group_hid, item_hid, role, joined_on,"
                " created_at, updated_at, row_version)"
                " VALUES ('m-1', 'g-1', 'i-1', 'member', '2024-01-01',"
                " '2026-01-01', '2026-01-01', 1)"
            )
        )
    engine.dispose()

    before = datetime.now(UTC).astimezone(ZoneInfo(zone)).date()
    migrate.upgrade(url)
    after = datetime.now(UTC).astimezone(ZoneInfo(zone)).date()

    engine = make_engine(url)
    with engine.connect() as connection:
        left = connection.execute(text("SELECT left_on FROM device_group_members")).scalar()
    engine.dispose()
    assert str(left) in {before.isoformat(), after.isoformat()}


def test_the_upgrade_to_0007_keeps_what_is_held_and_puts_nothing_anywhere(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0006")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO owners (hid, label, label_key, is_external, exception_reason,"
                " record_status, created_at, updated_at, row_version)"
                " VALUES ('o-out', 'Facilities', 'facilities', 1, 'Runs the plant rooms',"
                " 'active', '2026-01-01', '2026-01-01', 3)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO items (hid, name, quantity, lifecycle_state, condition, owner_hid,"
                " parent_item_hid, record_status, created_at, updated_at, row_version)"
                " VALUES (:hid, :hid, 1, :state, 'good', :owner, :parent, 'active',"
                " '2026-01-01', '2026-01-01', :version)"
            ),
            [
                {"hid": "i-1", "state": "Prod", "owner": "o-out", "parent": None, "version": 7},
                {"hid": "i-2", "state": None, "owner": None, "parent": "i-1", "version": 2},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO device_groups (hid, type, name, name_key, owner_hid, managed_as,"
                " observed_master_hid, record_status, created_at, updated_at, row_version)"
                " VALUES ('g-1', 'stack', 'Stack', 'stack', 'o-out', NULL, 'i-1', 'active',"
                " '2026-01-01', '2026-01-01', 4)"
            )
        )
        # What refers to the two tables that the upgrade makes anew.
        connection.execute(
            text(
                "INSERT INTO device_group_members (hid, group_hid, item_hid, role, joined_on,"
                " created_at, updated_at, row_version) VALUES ('m-1', 'g-1', 'i-1', 'master',"
                " '2024-01-01', '2026-01-01', '2026-01-01', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO addresses (hid, item_hid, group_hid, address, role, is_primary,"
                " created_at, updated_at, row_version) VALUES (:hid, :item, :group_hid,"
                " :address, 'management', 1, '2026-01-01', '2026-01-01', 1)"
            ),
            [
                {"hid": "a-1", "item": "i-1", "group_hid": None, "address": "192.0.2.10"},
                {"hid": "a-2", "item": None, "group_hid": "g-1", "address": "192.0.2.1"},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO item_replacements (hid, old_item_hid, new_item_hid, reason,"
                " replaced_on, created_at, updated_at, row_version) VALUES ('r-1', 'i-2',"
                " 'i-1', 'rma', '2026-01-01', '2026-01-01', '2026-01-01', 1)"
            )
        )
        # A role of the site's own, entered before the list had its defaults.
        connection.execute(
            text(
                "INSERT INTO choices (hid, list, value, value_key, label, sort, active,"
                " created_at, updated_at, row_version) VALUES ('c-1', 'contact_role',"
                " 'technical', 'technical', 'Engineer on call', 5, 1, '2026-01-01',"
                " '2026-01-01', 1)"
            )
        )
        events = connection.execute(text("SELECT count(*) FROM audit_events")).scalar()
    engine.dispose()

    migrate.upgrade(url)

    engine = make_engine(url)
    with engine.connect() as connection:
        assert migrate.current(engine) == migrate.head(url)
        # Every item and group is as it was, at the version it had, and is nowhere.
        items = connection.execute(
            text(
                "SELECT hid, lifecycle_state, condition, owner_hid, parent_item_hid, row_version,"
                " location_hid FROM items ORDER BY hid"
            )
        ).all()
        assert [tuple(row) for row in items] == [
            ("i-1", "Prod", "good", "o-out", None, 7, None),
            ("i-2", None, "good", None, "i-1", 2, None),
        ]
        groups = connection.execute(
            text(
                "SELECT hid, type, owner_hid, observed_master_hid, row_version, location_hid"
                " FROM device_groups"
            )
        ).all()
        assert [tuple(row) for row in groups] == [("g-1", "stack", "o-out", "i-1", 4, None)]
        # What refers to them still does: the member, the addresses and the replacement.
        held = connection.execute(
            text(
                "SELECT (SELECT item_hid FROM device_group_members WHERE hid = 'm-1'),"
                " (SELECT item_hid FROM addresses WHERE hid = 'a-1'),"
                " (SELECT group_hid FROM addresses WHERE hid = 'a-2'),"
                " (SELECT new_item_hid FROM item_replacements WHERE hid = 'r-1')"
            )
        ).one()
        assert tuple(held) == ("i-1", "i-1", "g-1", "i-1")
        # The six tables are there, and empty; the upgrade wrote no event.
        for table in (
            "regions",
            "sites",
            "locations",
            "contacts",
            "contact_assignments",
            "owner_members",
        ):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0  # noqa: S608
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar() == events
        # The two lists have their defaults, beside the role the site had entered.
        roles = dict(
            connection.execute(
                text("SELECT value, label FROM choices WHERE list = 'contact_role'")
            ).all()
        )
        assert roles["technical"] == "Engineer on call"
        assert set(roles) == {"shipping", "technical", "federal", "operational", "escalation"}
        kinds = connection.execute(
            text("SELECT value FROM choices WHERE list = 'location_kind' ORDER BY sort")
        ).scalars()
        assert list(kinds) == ["building", "floor", "room", "rack", "warehouse", "other"]
        # The indexes of the two tables that were made anew are the ones they had, and more.
        indexes = {row[1] for row in connection.execute(text("PRAGMA index_list(items)"))}
        assert {"ix_items_owner_hid", "ix_items_condition", "ix_items_location_hid"} <= indexes
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
    # And back: the schema of 0.4.2, with the rows still there.
    command.downgrade(migrate.alembic_config(url), "0006")
    engine = make_engine(url)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(items)"))}
        assert "location_hid" not in columns
        assert connection.execute(text("SELECT count(*) FROM items")).scalar() == 2
        tables = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        assert "regions" not in tables
    engine.dispose()


def test_a_small_preview_takes_its_turn_before_it_looks(config: Config) -> None:
    """Tried in place, work reads and then writes. Had another change been stored in
    between, SQLite would refuse the write at once, without waiting: so the writer's
    place is taken first, and the other change waits for the preview instead."""
    engine = make_engine(config.database_url)
    path = engine.url.database
    assert path is not None
    with make_sessions(engine)() as db, trial(db, in_place=True) as trying:
        trying.execute(text("SELECT count(*) FROM settings")).scalar()
        with (
            closing(sqlite3.connect(path, timeout=0)) as other,
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            other.execute("UPDATE settings SET row_version = row_version")
        # And the work that was tried may write, having read.
        trying.execute(text("UPDATE settings SET row_version = row_version"))
    engine.dispose()
