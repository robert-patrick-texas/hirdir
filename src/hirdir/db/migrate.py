"""Applying and inspecting schema migrations."""

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(url: str) -> AlembicConfig:
    """Return the Alembic configuration for the database at url."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str) -> None:
    """Bring the database at url to the newest schema."""
    command.upgrade(alembic_config(url), "head")


def head(url: str) -> str | None:
    """Return the newest revision the code knows."""
    return ScriptDirectory.from_config(alembic_config(url)).get_current_head()


def current(engine: Engine) -> str | None:
    """Return the revision the database is at, or None before the first migration."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
