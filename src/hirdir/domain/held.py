"""What a file of items cannot change, looked up once while the file is worked (P-324).

A row of a file of items reads the places and their paths, the operators they give and
those that are retired, the settings and the time zone, the lifecycle rules and the
kinds of the models again and again, and none of them is anything a row of items
writes. A run of such a file opens `holding` for its session, and each of those lookups
is made once and kept until the run lets go of the records it has worked on, as it does
every so many rows, or until the batch of an apply ends, after which another request may
have changed any of them. What is kept is no record of its own: it is thrown away with
the run, and outside `holding`, or for another session, every lookup is made as always.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session


class Held:
    """What is held for the work of one session."""

    def __init__(self, db: Session) -> None:
        self.db = db
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
