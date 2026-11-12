"""The migrations, the connection settings and the configuration."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from hirdir import config as config_module
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine
from hirdir.db.models import Base


def test_migrations_build_exactly_the_schema_of_the_models(config: Config) -> None:
    engine = make_engine(config.database_url)
    assert migrate.current(engine) == migrate.head(config.database_url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


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
