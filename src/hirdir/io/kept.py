"""Answers that are worked out once and given again until they could differ (D-184).

The coverage report, the renewal worklist, the summary of the renewal alert and the
capacity balance are kept with the newest audit event there is, the day in the
application's time zone and the request whole. Every change writes an audit event, a
setting's among them, so a newer event, or another day, leaves a kept answer unused:
one that a change has made wrong is never given. An event that changes none of the
records an answer is worked out of, a sign-in, seeing the alert, a preview or a change
of an account, leaves it good. What is kept is no record: it may be dropped at any
time, and is worked out again from the records, so nothing inherited is copied down.

They are kept in two places. Every answer that is given is kept in the memory of the
process that gave it, at most `MOST` of them, the least used dropped first, and a
restart drops them. And each report is **worked out ahead** for the view its page opens
with and kept in the database, in `kept_answers`, a row to a report (P-275): by the
second process of the service, which works them out on a processor of its own, when it
starts, just after midnight and, by day, once nothing has changed for a while (P-276),
so that the first person to ask is not kept waiting. A process that is asked looks in
its memory, then at the row, and works the answer out itself where neither has it. A
row is good for its request, its newest event, its day and the version of `hirdir`
that worked it out, since an upgrade may change how a report is worked out and writes
no event. Only `work_ahead`, and a check that found a row to differ, write the table.

A report is worked out ahead where its module says so with `worked_ahead`, which names
the form its answer is read back in and what gives the view its page opens with.
"""

import dataclasses
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hirdir import __version__, clock
from hirdir.db import dialect
from hirdir.db.models import AuditEvent, KeptAnswer
from hirdir.domain import audit, contracts, settings
from hirdir.domain.audit import AuditContext

log = logging.getLogger("hirdir")
# At most so many answers are kept in the memory of a process, the least used dropped
# first.
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


@dataclass(frozen=True)
class Ahead:
    """A report that is worked out ahead (P-275): the form its answer is written in
    and read back in, and what gives the view its page opens with, which answers
    through `answer`, once."""

    report: str
    form: TypeAdapter[Any]
    view: Callable[[Session], Any]


_lock = threading.Lock()
_kept: OrderedDict[tuple[Any, ...], Kept] = OrderedDict()
_ahead: dict[str, Ahead] = {}
# One thread of a process works ahead at a time: what is done by the clock and what is
# done after a change may come due together, and the second finds the work done.
_working = threading.Lock()
# What `answer` gave while the reports were worked out ahead, by report.
_noted: ContextVar[dict[str, tuple[tuple[Any, ...], Kept]] | None] = ContextVar(
    "hirdir_kept_noted", default=None
)


# What changes none of the records a kept answer is worked out of, and so leaves it
# good: signing in, seeing the alert, a preview, checking what is kept, and the
# accounts (the role of the person asking is applied to a kept answer, never kept in it).
CHECKED = "kept_answers_checked"
# A download of a reference file changes nothing (P-162).
UNKEPT_ACTIONS = ("sign_in", "sign_in_failed", "alert_seen", "preview", "download", CHECKED)
UNKEPT_RECORDS = ("user", "user_group", "role_grant", "service_token")


def worked_ahead(report: str, form: Any, view: Callable[[Session], Any]) -> None:
    """Say that a report is worked out ahead and kept in the database (P-275): `form`
    is the type of its answer, and `view` gives the answer of the view its page opens
    with, through `answer`."""
    _ahead[report] = Ahead(report, TypeAdapter(form), view)


def _newest(db: Session) -> tuple[str | None, datetime | None]:
    """Return the newest audit event of a change of the inventory or its settings, and
    when it was; neither where nothing has changed yet."""
    found = db.execute(
        select(AuditEvent.hid, AuditEvent.at)
        .where(
            AuditEvent.action.not_in(UNKEPT_ACTIONS),
            AuditEvent.record_type.not_in(UNKEPT_RECORDS),
        )
        .order_by(AuditEvent.hid.desc())
        .limit(1)
    ).first()
    return (None, None) if found is None else (found.hid, found.at)


def _stamp(db: Session, newest: str | None) -> tuple[Any, ...]:
    return str(db.get_bind().engine.url), newest, contracts.today(db).isoformat()


def stamp(db: Session) -> tuple[Any, ...]:
    """Return what a kept answer is good for: the database, the newest audit event of
    a change of the inventory or its settings, and the day."""
    return _stamp(db, _newest(db)[0])


def asked(*parts: Any) -> str:
    """Return a request whole, as the key it is kept by."""
    return json.dumps(parts, sort_keys=True, default=str)


def _of_stamp(now: tuple[Any, ...]) -> tuple[Any, ...]:
    """Return what picks the rows of the database that are good for a stamp."""
    _, newest, day = now
    event = KeptAnswer.newest_event_hid
    return (
        event.is_(None) if newest is None else event == newest,
        KeptAnswer.day == date.fromisoformat(day),
        KeptAnswer.version == __version__,
    )


def _held(db: Session, key: tuple[Any, ...], work: Callable[[Session], Any]) -> Kept | None:
    """Return the answer the database holds for a request, where it is good now."""
    name, request, *now = key
    ahead = _ahead.get(name)
    if ahead is None:
        return None
    row = db.execute(
        select(KeptAnswer.answer, KeptAnswer.kept_at).where(
            KeptAnswer.report == name, KeptAnswer.request == request, *_of_stamp(tuple(now))
        )
    ).first()
    if row is None:
        return None
    try:
        found = ahead.form.validate_json(row.answer)
    except ValueError:
        # Not what this version reads: worked out anew, as if it were not there.
        log.warning("the kept answer of the report %s cannot be read, and is not given", name)
        return None
    return Kept(name, request, found, work, row.kept_at)


def answer[T](db: Session, name: str, request: str, work: Callable[[Session], T]) -> T:
    """Return the kept answer to a request, or work it out and keep it.

    The memory of the process is looked in first, then the database, where the report
    is one worked out ahead. `work` is given the session to work in, so that the answer
    can be worked out again by a check, in a session of its own.
    """
    key = (name, request, *stamp(db))
    with _lock:
        entry = _kept.get(key)
        if entry is not None:
            _kept.move_to_end(key)
            entry.uses += 1
    if entry is None:
        entry = _held(db, key, work)
        if entry is None:
            entry = Kept(name, request, work(db), work, clock.now())
        else:
            entry.uses = 1
        _keep(key, entry)
    noted = _noted.get()
    if noted is not None:
        noted[name] = (key, entry)
    return entry.answer


def _keep(key: tuple[Any, ...], entry: Kept) -> None:
    with _lock:
        _kept[key] = entry
        _kept.move_to_end(key)
        while len(_kept) > MOST:
            _kept.popitem(last=False)


def _good(db: Session, now: tuple[Any, ...] | None = None) -> list[tuple[tuple[Any, ...], Kept]]:
    """Return the answers kept in memory that would be given now: those of the present
    stamp."""
    now = stamp(db) if now is None else now
    with _lock:
        return [(key, entry) for key, entry in _kept.items() if key[2:] == now]


def _rows(db: Session, now: tuple[Any, ...]) -> dict[tuple[str, str], datetime]:
    """Return the rows of the database that would be given now: when each was worked
    out, by its report and its request."""
    rows = db.execute(
        select(KeptAnswer.report, KeptAnswer.request, KeptAnswer.kept_at).where(*_of_stamp(now))
    )
    return {(row.report, row.request): row.kept_at for row in rows if row.report in _ahead}


# --- worked out ahead ----------------------------------------------------------------


def _missing(db: Session, now: tuple[Any, ...]) -> list[str]:
    held = {report for report, _ in _rows(db, now)}
    return [report for report in _ahead if report not in held]


def missing(db: Session) -> list[str]:
    """Return the reports worked out ahead that the database does not hold good now."""
    return _missing(db, stamp(db))


def due(db: Session) -> bool:
    """Say whether the reports are to be worked out ahead now, after a change (P-276):
    one of them is missing, and the newest change of the inventory or its settings is
    `reports_ahead_after_seconds` old or older. Never, where that is 0. It is asked at
    every look of the second process, and costs three small reads."""
    after = int(settings.value(db, settings.AHEAD_SETTING))
    if after <= 0:
        return False
    newest, at = _newest(db)
    if not _missing(db, _stamp(db, newest)):
        return False
    return at is None or clock.now() - at >= timedelta(seconds=after)


def _write(db: Session, key: tuple[Any, ...], entry: Kept) -> None:
    """Write the row of a report: the answer of one request, good for one stamp."""
    _, newest, day = key[2:]
    values = {
        "request": entry.request,
        "newest_event_hid": newest,
        "day": date.fromisoformat(day),
        "version": __version__,
        "answer": _ahead[entry.report].form.dump_json(entry.answer).decode(),
        "kept_at": entry.kept_at,
    }
    row = db.get(KeptAnswer, entry.report)
    if row is None:
        db.add(KeptAnswer(report=entry.report, **values))
    else:
        for name, value in values.items():
            setattr(row, name, value)


def work_ahead(db: Session) -> list[str]:
    """Work out each report that is worked out ahead and that the database does not
    hold good, for the view its page opens with, and keep it there (P-275). Return the
    reports kept.

    The session is the caller's own, for this alone: what it has read is let go, and
    what is kept is stored before this returns. A row is written with the writer's
    place taken and the stamp read again: an answer worked out while something changed
    is of no stamp for certain, and is thrown away, to be worked out again.
    """
    with _working:
        wanted = missing(db)
        if not wanted:
            return []
        noted: dict[str, tuple[tuple[Any, ...], Kept]] = {}
        token = _noted.set(noted)
        try:
            for report in wanted:
                _ahead[report].view(db)
        finally:
            _noted.reset(token)
        db.rollback()
        dialect.hold_other_writers(db)
        now = stamp(db)
        kept = []
        for report in wanted:
            key, entry = noted.get(report, (None, None))
            if key is not None and entry is not None and key[2:] == now:
                _write(db, key, entry)
                kept.append(report)
        db.commit()
        return kept


# --- what is kept, listed and checked ------------------------------------------------


@dataclass(frozen=True)
class Listed:
    """A kept answer that would be given now: `ahead`, where the database holds it,
    worked out ahead; `uses`, how often this process has given it."""

    report: str
    request: str
    kept_at: datetime
    uses: int
    ahead: bool


def listing(db: Session) -> list[Listed]:
    """Return the kept answers that would be given now: those this process has given,
    the most recently used last, and then those the database holds that nobody has
    asked this process for yet."""
    now = stamp(db)
    rows = _rows(db, now)
    found = [
        Listed(e.report, e.request, e.kept_at, e.uses, (e.report, e.request) in rows)
        for _, e in _good(db, now)
    ]
    given = {(e.report, e.request) for e in found}
    return found + [
        Listed(report, request, kept_at, 0, True)
        for (report, request), kept_at in rows.items()
        if (report, request) not in given
    ]


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


def same(one: Any, other: Any) -> bool:
    """Say whether two answers are the same, as plain data."""
    return json.dumps(_plain(one), sort_keys=True, default=str) == json.dumps(
        _plain(other), sort_keys=True, default=str
    )


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


def _take_up(db: Session, now: tuple[Any, ...]) -> None:
    """Take into the memory of this process what the database holds good and nobody has
    asked it for yet, so that a check has how each is worked out. Nothing is worked out
    for it, and it is not counted as a use."""
    with _lock:
        given = {(key[0], key[1]) for key in _kept if key[2:] == now}
    for report, request in _rows(db, now):
        if (report, request) in given:
            continue
        noted: dict[str, tuple[tuple[Any, ...], Kept]] = {}
        token = _noted.set(noted)
        try:
            _ahead[report].view(db)
        finally:
            _noted.reset(token)
        if report in noted:
            noted[report][1].uses = 0


def check(db: Session, context: AuditContext) -> Checked:
    """Work out each kept answer anew, compare it with what was kept, and keep the new.

    Those the database holds, worked out ahead, are checked with those this process
    has given, and a row that differed, or could not be read, is written again. None
    should differ: one that did is a defect, and the check names its report and its
    request. The check is audited, and leaves the kept answers good, since it changes
    no record.
    """
    differed: list[Differed] = []
    now = stamp(db)
    _take_up(db, now)
    good = _good(db, now)
    rows = _rows(db, now)
    for key, entry in good:
        anew = entry.work(db)
        fresh = Kept(entry.report, entry.request, anew, entry.work, clock.now(), entry.uses)
        wrong = not same(anew, entry.answer)
        if (entry.report, entry.request) in rows:
            # The row is compared too: this process may have worked its own answer out
            # before the row was written, and never have read it.
            held = _held(db, key, entry.work)
            if held is None or not same(anew, held.answer):
                wrong = True
                _write(db, key, fresh)
        if wrong:
            differed.append(Differed(entry.report, entry.request, entry.kept_at))
        _keep(key, fresh)
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
    """Drop every answer kept in the memory of this process. What the database holds
    stays."""
    with _lock:
        _kept.clear()


def forget(db: Session) -> None:
    """Take away what the database holds, worked out ahead. Nothing the service does
    needs it, a row that is good for no present moment being passed over: it is for a
    timing that is to work every answer out anew, and for a test."""
    db.execute(delete(KeptAnswer))
