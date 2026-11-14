"""The database engine and its sessions."""

import sqlite3
import tempfile
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path

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


@contextmanager
def trial(db: Session, in_place: bool = False) -> Generator[Session]:
    """Yield a session in which work can be tried, and of which nothing is ever kept.

    SQLite has one writer at a time, and whoever writes holds every other writer up
    until the transaction ends, even when it ends by being undone. So work that takes
    long is tried on a copy of the database, made with SQLite's own online backup and
    thrown away afterwards, and nobody waits for it. Work that is short is tried
    `in_place`, in a savepoint that is undone, which costs no copy. A database where
    writers do not hold each other up is always tried in place.

    Work that is tried in place takes the one writer's place before it looks. It reads
    and then writes, and SQLite refuses at once, without waiting, a transaction that
    has read and wants to write after another has written in between. Having taken its
    turn first, it waits for it like any other change and is then let through.
    """
    bind = db.get_bind()
    path = bind.engine.url.database if bind.dialect.name == "sqlite" else None
    if in_place or not path or path == ":memory:":
        dialect.hold_other_writers(db)
        savepoint = db.begin_nested()
        try:
            yield db
        finally:
            savepoint.rollback()
        return
    with tempfile.TemporaryDirectory(prefix="hirdir-trial-") as folder:
        target = Path(folder) / "trial.db"
        source = db.connection().connection.driver_connection
        if not isinstance(source, sqlite3.Connection):
            raise TypeError("a SQLite database is reached through Python's own sqlite3")
        with closing(sqlite3.connect(target)) as copy:
            source.backup(copy)
        engine = make_engine(f"sqlite:///{target}")
        try:
            with make_sessions(engine)() as session:
                yield session
                session.rollback()
        finally:
            engine.dispose()
