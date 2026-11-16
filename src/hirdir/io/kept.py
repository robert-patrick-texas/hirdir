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

import dataclasses
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import AuditEvent
from hirdir.domain import audit, contracts
from hirdir.domain.audit import AuditContext

# At most so many answers are kept, the least used dropped first.
MOST = 64


@dataclass
class Kept:
    """One kept answer: what it answers, how it is worked out again, and its use."""

    report: str
    request: str
    answer: Any
    work: Callable[[Session], Any]
    kept_at: datetime
    uses: int = field(default=0)


_lock = threading.Lock()
_kept: OrderedDict[tuple[Any, ...], Kept] = OrderedDict()


# What changes none of the records a kept answer is worked out of, and so leaves it
# good: signing in, seeing the alert, a preview, checking what is kept, and the
# accounts (the role of the person asking is applied to a kept answer, never kept in it).
CHECKED = "kept_answers_checked"
# A download of a reference file changes nothing (P-162).
UNKEPT_ACTIONS = ("sign_in", "sign_in_failed", "alert_seen", "preview", "download", CHECKED)
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


def answer[T](db: Session, name: str, request: str, work: Callable[[Session], T]) -> T:
    """Return the kept answer to a request, or work it out and keep it.

    `work` is given the session to work in, so that the answer can be worked out
    again by a check, in a session of its own.
    """
    key = (name, request, *stamp(db))
    with _lock:
        if key in _kept:
            _kept.move_to_end(key)
            _kept[key].uses += 1
            return _kept[key].answer
    found = work(db)
    _keep(key, Kept(name, request, found, work, clock.now()))
    return found


def _keep(key: tuple[Any, ...], entry: Kept) -> None:
    with _lock:
        _kept[key] = entry
        _kept.move_to_end(key)
        while len(_kept) > MOST:
            _kept.popitem(last=False)


def _good(db: Session) -> list[tuple[tuple[Any, ...], Kept]]:
    """Return the kept answers that would be given now: those of the present stamp."""
    now = stamp(db)
    with _lock:
        return [(key, entry) for key, entry in _kept.items() if key[2:] == now]


def listing(db: Session) -> list[Kept]:
    """Return the kept answers that would be given now, the most recently used last."""
    return [entry for _, entry in _good(db)]


def _plain(value: Any) -> Any:
    """Return an answer as plain data, to compare one with another."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal | date | datetime):
        return str(value)
    return value


@dataclass(frozen=True)
class Differed:
    """A kept answer that was not the same as the one worked out anew."""

    report: str
    request: str
    kept_at: datetime


@dataclass(frozen=True)
class Checked:
    """What a check of the kept answers found (P-157)."""

    checked_at: datetime
    checked: int
    differed: list[Differed]


def check(db: Session, context: AuditContext) -> Checked:
    """Work out each kept answer anew, compare it with what was kept, and keep the new.

    None should differ: one that did is a defect, and the check names its report and
    its request. The check is audited, and leaves the kept answers good, since it
    changes no record.
    """
    differed: list[Differed] = []
    good = _good(db)
    for key, entry in good:
        anew = entry.work(db)
        if json.dumps(_plain(anew), sort_keys=True, default=str) != json.dumps(
            _plain(entry.answer), sort_keys=True, default=str
        ):
            differed.append(Differed(entry.report, entry.request, entry.kept_at))
        _keep(key, Kept(entry.report, entry.request, anew, entry.work, clock.now(), entry.uses))
    found = Checked(clock.now(), len(good), differed)
    audit.record(
        db,
        context,
        CHECKED,
        "kept_answers",
        None,
        [
            audit.change("checked", None, found.checked),
            audit.change(
                "differed", None, [{"report": d.report, "request": d.request} for d in differed]
            ),
        ],
    )
    return found


def drop() -> None:
    """Drop every kept answer."""
    with _lock:
        _kept.clear()
