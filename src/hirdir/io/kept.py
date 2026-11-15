"""Answers that are worked out once and given again until they could differ (P-133).

The coverage report, the renewal worklist and the summary of the renewal alert are
kept in the memory of the server with the newest audit event there is, the day in the
application's time zone and the request whole. Every change writes an audit event, a
setting's among them, so a newer event, or another day, leaves a kept answer unused:
one that a change has made wrong is never given. What is kept is no record: it may be
dropped at any time, is dropped at a restart, and is worked out again from the records,
so nothing inherited is copied down.
"""

import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent
from hirdir.domain import contracts

# At most so many answers are kept, the least used dropped first.
MOST = 64

_lock = threading.Lock()
_kept: OrderedDict[tuple[Any, ...], Any] = OrderedDict()


def stamp(db: Session) -> tuple[Any, ...]:
    """Return what a kept answer is good for: the database, its newest audit event and
    the day."""
    return (
        str(db.get_bind().engine.url),
        db.scalar(select(func.max(AuditEvent.hid))),
        contracts.today(db).isoformat(),
    )


def asked(*parts: Any) -> str:
    """Return a request whole, as the key it is kept by."""
    return json.dumps(parts, sort_keys=True, default=str)


def answer[T](db: Session, name: str, request: str, work: Callable[[], T]) -> T:
    """Return the kept answer to a request, or work it out and keep it."""
    key = (name, request, *stamp(db))
    with _lock:
        if key in _kept:
            _kept.move_to_end(key)
            return _kept[key]
    found = work()
    with _lock:
        _kept[key] = found
        _kept.move_to_end(key)
        while len(_kept) > MOST:
            _kept.popitem(last=False)
    return found


def drop() -> None:
    """Drop every kept answer."""
    with _lock:
        _kept.clear()
