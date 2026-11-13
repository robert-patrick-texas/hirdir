"""Alembic's environment: how a migration run connects to the database."""

from alembic import context
from sqlalchemy import create_engine

from hirdir.db.models import Base

target_metadata = Base.metadata


def run() -> None:
    """Run the migrations against the configured database."""
    url = context.config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("no database URL was given to the migration run")
    # A migration is all or nothing. Left to itself, Python's SQLite driver runs each
    # CREATE TABLE outside any transaction, so a migration that failed half-way would
    # leave half its tables behind. With autocommit off, the driver keeps one
    # transaction open from the first statement to the commit.
    sqlite = url.startswith("sqlite")
    engine = create_engine(url, connect_args={"autocommit": False} if sqlite else {})
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
