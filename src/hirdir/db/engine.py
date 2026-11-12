"""The database engine and its sessions."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from hirdir.db import dialect

SQLITE_PRAGMAS = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": 5000,
    "synchronous": 1,
}


def make_engine(url: str) -> Engine:
    """Create the engine for url.

    A SQLite connection gets hirdir's pragmas and SQL functions every time.
    """
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            for name, value in SQLITE_PRAGMAS.items():
                cursor.execute(f"PRAGMA {name}={value}")
            cursor.close()
            dialect.prepare_sqlite(dbapi_connection)

    return engine


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    """Return the session factory for engine."""
    return sessionmaker(engine, expire_on_commit=False)
