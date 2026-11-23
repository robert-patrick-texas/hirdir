"""What an apply waits for between two batches: a change by somebody else under way, and
nothing else (P-143, P-324).

Every connection that changes something holds a shared lock on `writing.lock` beside the
database, from its first change until its transaction ends. Between two batches the
worker asks for that lock alone, and waits while it is refused, a second at the most.
"""

import fcntl
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from hirdir.db import engine as engines
from hirdir.io import imports


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Engine]:
    made = engines.make_engine(f"sqlite:///{tmp_path / 'hirdir.db'}")
    with made.begin() as conn:
        conn.execute(text("CREATE TABLE things (name TEXT)"))
    yield made
    made.dispose()


def changing(lock: Path) -> bool:
    """Say whether a change is under way: whether a lock of one's own, alone, is refused."""
    held = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(held)
    return False


def test_a_connection_holds_the_lock_from_its_first_change_until_its_transaction_ends(
    database: Engine, tmp_path: Path
) -> None:
    lock = tmp_path / engines.WRITING_LOCK
    assert engines.writing_lock(database) == lock
    with database.connect() as conn:
        conn.execute(text("SELECT count(*) FROM things"))
        # Reading is no change.
        assert not lock.exists() or not changing(lock)
        conn.execute(text("INSERT INTO things VALUES ('one')"))
        assert changing(lock)
        conn.execute(text("UPDATE things SET name = 'two'"))
        assert changing(lock)
        conn.commit()
        assert not changing(lock)
        conn.execute(text("DELETE FROM things"))
        assert changing(lock)
        conn.rollback()
        assert not changing(lock)
        conn.execute(text("INSERT INTO things VALUES ('three')"))
        assert changing(lock)
    # A connection given back to the pool in the middle of a change lets go of it.
    assert not changing(lock)
    # A file with nothing in it, which only its owner may read.
    assert lock.stat().st_size == 0
    assert lock.stat().st_mode & 0o077 == 0


def test_two_connections_that_change_something_each_hold_a_lock_of_their_own(
    database: Engine, tmp_path: Path
) -> None:
    lock = tmp_path / engines.WRITING_LOCK
    with Session(database) as one, Session(database) as two:
        one.execute(text("INSERT INTO things VALUES ('one')"))
        one.commit()
        two.execute(text("SELECT count(*) FROM things"))
        one.execute(text("UPDATE things SET name = 'uno'"))
        assert changing(lock)
        one.commit()
        assert not changing(lock)


def test_between_two_batches_an_apply_goes_on_at_once_when_nobody_changes_anything(
    database: Engine,
) -> None:
    with Session(database) as db:
        began = time.monotonic()
        assert engines.wait_for_changes(db, threading.Event()) is False
        assert time.monotonic() - began < 0.05


def test_it_waits_for_a_change_under_way_until_it_is_done(database: Engine, tmp_path: Path) -> None:
    other = database.connect()
    other.execute(text("INSERT INTO things VALUES ('somebody else')"))
    done = threading.Timer(0.3, other.commit)
    with Session(database) as db:
        began = time.monotonic()
        done.start()
        assert engines.wait_for_changes(db, threading.Event()) is False
        waited = time.monotonic() - began
    done.join()
    other.close()
    assert 0.25 <= waited < 0.9
    assert not changing(tmp_path / engines.WRITING_LOCK)


def test_it_waits_a_second_at_the_most_and_a_stop_ends_the_wait(database: Engine) -> None:
    other = database.connect()
    other.execute(text("INSERT INTO things VALUES ('a long change')"))
    try:
        with Session(database) as db:
            began = time.monotonic()
            assert engines.wait_for_changes(db, threading.Event(), within=0.3) is False
            assert 0.25 <= time.monotonic() - began < 0.8
            assert engines.WAIT_FOR_CHANGES == 1.0
            stop = threading.Event()
            threading.Timer(0.1, stop.set).start()
            began = time.monotonic()
            assert engines.wait_for_changes(db, stop) is True
            assert time.monotonic() - began < 0.6
    finally:
        other.rollback()
        other.close()


def test_a_database_not_in_a_file_waits_for_nothing() -> None:
    made = engines.make_engine("sqlite://")
    try:
        assert engines.writing_lock(made) is None
        with Session(made) as db:
            assert engines.wait_for_changes(db, threading.Event()) is False
    finally:
        made.dispose()


def test_a_batch_that_waited_too_long_for_the_writer_is_tried_again_after_a_pause() -> None:
    # SQLite's busy handler tries again every tenth of a second at the longest: a batch
    # tried again sooner than that could take the place from a change that waits for it.
    assert imports.AGAIN_AFTER_BUSY > 0.1
