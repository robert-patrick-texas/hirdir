"""Answers that are worked out once and given again until they could differ (D-184).

The coverage report, the renewal worklist and the summary of the renewal alert are
kept in the memory of the server with the newest audit event there is, the day in the
application's time zone and the request whole. Every change writes an audit event, a
setting's among them, so a newer event, or another day, leaves a kept answer unused:
one that a change has made wrong is never given. An event that changes none of the
records an answer is worked out of, a sign-in, seeing the alert, a preview or a change
of an account, leaves it good. What is kept is no record: it may be
dropped at any time, is dropped at a restart, and is worked out again from the records,
so nothing inherited is copied down.
"""

import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent
from hirdir.domain import contracts

# At most so many answers are kept, the least used dropped first.
MOST = 64

_lock = threading.Lock()
_kept: OrderedDict[tuple[Any, ...], Any] = OrderedDict()


# What changes none of the records a kept answer is worked out of, and so leaves it
# good: signing in, seeing the alert, a preview, and the accounts (the role of the
# person asking is applied to a kept answer, never kept in it).
UNKEPT_ACTIONS = ("sign_in", "sign_in_failed", "alert_seen", "preview")
UNKEPT_RECORDS = ("user", "user_group", "role_grant", "service_token")


def stamp(db: Session) -> tuple[Any, ...]:
    """Return what a kept answer is good for: the database, the newest audit event of
    a change of the inventory or its settings, and the day."""
    newest = db.scalar(
        select(AuditEvent.hid)
        .where(
            AuditEvent.action.not_in(UNKEPT_ACTIONS),
            AuditEvent.record_type.not_in(UNKEPT_RECORDS),
        )
        .order_by(AuditEvent.hid.desc())
        .limit(1)
    )
    return str(db.get_bind().engine.url), newest, contracts.today(db).isoformat()


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
