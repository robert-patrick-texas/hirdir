"""The database engine and its sessions."""

import fcntl
import os
import sqlite3
import tempfile
import threading
import time
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from hirdir.db import dialect

# How long a change waits for the one writer before it is answered 503, to be sent
# again: the `busy_timeout` of SQLite, and the `Retry-After` of the answer.
WRITER_WAIT_SECONDS = 5
SQLITE_PRAGMAS = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": WRITER_WAIT_SECONDS * 1000,
    "synchronous": 1,
}


# As many connections are kept as the server has threads that answer requests, 40, with
# a few more to open beside them for what works in the background. With the five that
# SQLAlchemy keeps of itself, a page that asks for a dozen things at once had connections
# opened and thrown away for it, each set up anew, and with it what SQLite had prepared
# for each statement.
POOL = {"pool_size": 40, "max_overflow": 10}


def _pool(url: str) -> dict[str, int]:
    """Return how the connections of a database in a file, or on a server, are kept; a
    database in memory has the one connection it is."""
    made = make_url(url)
    in_memory = made.get_backend_name() == "sqlite" and made.database in (None, "", ":memory:")
    return {} if in_memory else dict(POOL)


def make_engine(url: str) -> Engine:
    """Create the engine for url.

    A SQLite connection gets hirdir's pragmas and SQL functions every time.
    """
    engine = create_engine(url, **_pool(url))
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            for name, value in SQLITE_PRAGMAS.items():
                cursor.execute(f"PRAGMA {name}={value}")
            cursor.close()
            dialect.prepare_sqlite(dbapi_connection)

        _mark_changes(engine)
    return engine


# --- a change under way, which an apply lets go first (P-143, P-324) ---------------------

# The file beside a database in a file that every connection holds a shared lock on, from
# its first change until its transaction ends, each connection a lock of its own; and
# what the statements that change something begin with.
WRITING_LOCK = "writing.lock"
CHANGES = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
_HELD = "hirdir.writing"
# How long a connection that is about to change something tries for its lock: refused
# only for the instant in which an apply looks whether anybody is changing anything.
MARK_WITHIN = 0.1
# Between two batches of an apply: the longest it waits for a change under way to be
# done, how often it looks again meanwhile, and how long it leaves the writer's place
# free where it cannot tell, in seconds.
WAIT_FOR_CHANGES = 1.0
LOOK_AGAIN = 0.005
PAUSE_UNTOLD = 0.12


def writing_lock(engine: Engine) -> Path | None:
    """Return the file whose lock says a change is under way on the database of an
    engine: beside a database in a file, and None for any other."""
    path = engine.url.database if engine.dialect.name == "sqlite" else None
    if not path or path == ":memory:" or path.startswith("file:"):
        return None
    return Path(path).parent / WRITING_LOCK


def _open(lock: Path) -> int | None:
    try:
        return os.open(lock, os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError:
        return None


def _mark_changes(engine: Engine) -> None:
    """Have every connection of the engine hold a shared lock on `writing.lock` from its
    first change until its transaction ends, so that an apply can tell that a change is
    under way (`wait_for_changes`). Nothing is written for it; a lock that cannot be had
    leaves the change as it would be without one."""
    lock = writing_lock(engine)
    if lock is None:
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _changing(conn, _cursor, statement, _parameters, _context, _many) -> None:
        if _HELD in conn.info or not statement.lstrip()[:7].upper().startswith(CHANGES):
            return
        held = _open(lock)
        until = time.monotonic() + MARK_WITHIN
        while held is not None:
            try:
                fcntl.flock(held, fcntl.LOCK_SH | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    os.close(held)
                    held = None
                else:
                    time.sleep(0.001)
            except OSError:
                os.close(held)
                held = None
        conn.info[_HELD] = held

    def _ended(info: dict[Any, Any]) -> None:
        held = info.pop(_HELD, None)
        if held is not None:
            os.close(held)

    @event.listens_for(engine, "commit")
    @event.listens_for(engine, "rollback")
    def _transaction_ended(conn) -> None:
        _ended(conn.info)

    @event.listens_for(engine, "reset")
    def _reset(_dbapi_connection, record, _state) -> None:
        _ended(record.info)

    @event.listens_for(engine, "close")
    @event.listens_for(engine, "detach")
    def _closed(_dbapi_connection, record) -> None:
        _ended(record.info)

    @event.listens_for(engine, "invalidate")
    def _invalidated(_dbapi_connection, record, _error) -> None:
        _ended(record.info)


def wait_for_changes(db: Session, stop: threading.Event, within: float = WAIT_FOR_CHANGES) -> bool:
    """Wait while a change by somebody else is under way on the session's database, until
    it is done, `within` seconds at the most: what an apply does between two batches, so
    that a change that waits for the one writer's place gets it as a batch ends, and an
    apply that nobody writes beside goes on at once (P-143, P-324). Say whether `stop`
    was set meanwhile.

    The change under way is told by the lock every connection holds while it changes
    something (`_mark_changes`): asked for alone, without waiting, it is refused while
    any holds it. Where the file cannot be opened, the writer's place is left free for
    `PAUSE_UNTOLD` seconds instead. A database that is not in a file, which has no one
    writer, waits for nothing.
    """
    bind = db.get_bind()
    lock = writing_lock(bind.engine)
    if lock is None:
        return stop.is_set()
    held = _open(lock)
    if held is None:
        return stop.wait(PAUSE_UNTOLD)
    until = time.monotonic() + within
    try:
        while True:
            try:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= until:
                    return stop.is_set()
                if stop.wait(LOOK_AGAIN):
                    return True
                continue
            fcntl.flock(held, fcntl.LOCK_UN)
            return stop.is_set()
    finally:
        os.close(held)


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
                # The work is one transaction on the copy, each row a savepoint within
                # it, as it is in place. Without a write first, the first savepoint
                # would be the transaction, and storing it would store it on the disk,
                # and so on for every row (P-324).
                dialect.hold_other_writers(session)
                yield session
                session.rollback()
        finally:
            engine.dispose()
