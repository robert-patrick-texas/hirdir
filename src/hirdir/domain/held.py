"""What a file of items cannot change, looked up once while the file is worked (P-324).

A row of a file of items reads the places and their paths, the operators they give and
those that are retired, the settings and the time zone, the lifecycle rules and the
kinds of the models again and again, and none of them is anything a row of items
writes. A run of such a file opens `holding` for its session, and each of those lookups
is made once and kept until the run lets go of the records it has worked on, as it does
every so many rows, or until the batch of an apply ends, after which another request may
have changed any of them. What is kept is no record of its own: it is thrown away with
the run, and outside `holding`, or for another session, every lookup is made as always.

A page of records shaped for one request opens `reading` instead, for the length of the
shaping, which writes nothing: it holds the same, and besides it what a row of a file
might change but a page never does, such as the groups of each item (P-326).
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session


class Held:
    """What is held for the work of one session. `reading` is true while a page of
    records is shaped, which writes nothing (P-326)."""

    def __init__(self, db: Session, reading: bool = False) -> None:
        self.db = db
        self.reading = reading
        self.values: dict[Any, Any] = {}

    def drop(self) -> None:
        """Forget everything held, so that each is looked up again when it is asked."""
        self.values.clear()


_HELD: ContextVar[Held | None] = ContextVar("held_for_a_file", default=None)


@contextmanager
def holding(db: Session) -> Generator[Held]:
    """Hold, for the work of a session while the block lasts, what is looked up once."""
    held = Held(db)
    token = _HELD.set(held)
    try:
        yield held
    finally:
        _HELD.reset(token)


def of(db: Session) -> Held | None:
    """Return what is held for the work of a session, or None where nothing is."""
    held = _HELD.get()
    return held if held is not None and held.db is db else None


def kept[T](db: Session, key: Any, look_up: Callable[[], T]) -> T:
    """Return what `look_up` returns, looked up once while the session's work holds."""
    held = of(db)
    if held is None:
        return look_up()
    if key not in held.values:
        held.values[key] = look_up()
    return held.values[key]


def kept_many[T](
    db: Session, key: Any, wanted: set[str], look_up: Callable[[set[str]], dict[str, T]]
) -> dict[str, T]:
    """Return what `look_up` returns for each of several HIDs, each looked up once while
    the session's work holds: only those not held yet are asked for, together."""
    held = of(db)
    if held is None:
        return look_up(wanted)
    known: dict[str, T] = held.values.setdefault(key, {})
    missing = {hid for hid in wanted if hid not in known}
    if missing:
        found = look_up(missing)
        for hid in missing:
            known[hid] = found.get(hid, _NONE)
    return {hid: known[hid] for hid in wanted if known[hid] is not _NONE}


_NONE: Any = object()


# --- while a page of records is shaped (P-326) -----------------------------------------


@contextmanager
def reading(db: Session) -> Generator[Held]:
    """Hold, while a page of records is shaped for one request, what is looked up once.

    Shaping writes nothing, so what one part of a page reads is what another would read
    again: what `holding` holds, and besides it what `kept_while_reading` and
    `kept_many_while_reading` hold, such as the groups of each item and the walk up from
    it. It is let go at the end of the block, and is never another request's or another
    session's. Inside a run that holds already, the run's holder stands, with its own
    rules, and nothing more is held.
    """
    already = of(db)
    if already is not None:
        yield already
        return
    held = Held(db, reading=True)
    token = _HELD.set(held)
    try:
        yield held
    finally:
        _HELD.reset(token)


def _reading(db: Session) -> Held | None:
    held = of(db)
    return held if held is not None and held.reading else None


def kept_while_reading[T](db: Session, key: Any, look_up: Callable[[], T]) -> T:
    """Return what `look_up` returns, looked up once while a page is shaped (`reading`),
    and anew at any other time: what a row of a file may change is held only for a
    page, which changes nothing."""
    return kept(db, key, look_up) if _reading(db) is not None else look_up()


def kept_many_while_reading[T](
    db: Session, key: Any, wanted: set[str], look_up: Callable[[set[str]], dict[str, T]]
) -> dict[str, T]:
    """Return what `look_up` returns for each of several HIDs, each looked up once while
    a page is shaped (`reading`), and anew at any other time."""
    if _reading(db) is None:
        return look_up(wanted)
    return kept_many(db, key, wanted, look_up)
