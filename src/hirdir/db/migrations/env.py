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
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
