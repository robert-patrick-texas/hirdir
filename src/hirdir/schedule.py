"""What is done by the clock, at set times and not by a request: a small scheduler.

A job has a name, when it is due, and what it does. The scheduler wakes once a minute
in a thread of its own and runs each job that has come due since it last looked, with
a session of its own, by the clock of the application's time zone, the `time_zone`
setting. A job that fails is logged and tried again at the next wake, until it is done.
A job may also be run when its process starts. Nothing is run twice for one time it is
due, and a time that passed while the process was stopped is not made up for: a job
that must not miss one runs at the start as well, and finds there what is missing.

The service is two processes (P-267), and each runs a scheduler for its own jobs. What
a job writes to the database is the second process's, `hirdir admin work`:
`BACKGROUND_JOBS`. What a job keeps in the memory of the process that answers is the
server's own: `SERVER_JOBS`. A process that does both, `hirdir admin serve --work`,
runs them all, `JOBS`.

`run_due` runs what is due at a moment it is given, which is how the tests drive it
without waiting for a Monday.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.domain import audit, settings
from hirdir.io import balance

log = logging.getLogger("hirdir.schedule")
# How often the scheduler looks at the clock.
WAKE_SECONDS = 60.0
# Just after midnight: a minute in, so that a clock a little behind is past it too.
AFTER_MIDNIGHT = time(0, 1)
# And once what is due then is done: the long reports are worked out after the record
# of the week, which another process makes, and makes within the minute it is due in.
AFTER_THE_RECORD = time(0, 5)
MONDAY = 0

# When a job is due: given a moment and the application's time zone, the latest moment
# at or before it at which the job was due.
type When = Callable[[datetime, ZoneInfo], datetime]


@dataclass(frozen=True)
class Job:
    """One thing done by the clock: its name, when it is due, what it does with a
    session and the moment it is run for, and whether it is run at start as well."""

    name: str
    when: When
    run: Callable[[Session, datetime], Any]
    at_start: bool = False


def _at(day: date, at: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=zone)


def daily(at: time = AFTER_MIDNIGHT) -> When:
    """Return the times of a job that is due each day at a time of the day."""

    def last(moment: datetime, zone: ZoneInfo) -> datetime:
        day = moment.astimezone(zone).date()
        due = _at(day, at, zone)
        return due if due <= moment else _at(day - timedelta(days=1), at, zone)

    return last


def weekly(weekday: int = MONDAY, at: time = AFTER_MIDNIGHT) -> When:
    """Return the times of a job that is due once a week, on a day of the week (0 is
    Monday) at a time of the day."""

    def last(moment: datetime, zone: ZoneInfo) -> datetime:
        day = moment.astimezone(zone).date()
        day -= timedelta(days=(day.weekday() - weekday) % 7)
        due = _at(day, at, zone)
        return due if due <= moment else _at(day - timedelta(days=7), at, zone)

    return last


def record_balance(db: Session, moment: datetime) -> None:
    """Record the capacity balance of the week, when the week has no record yet."""
    balance.record_if_missing(db, audit.SYSTEM, moment)


def work_out_ahead(db: Session, moment: datetime) -> None:
    """Work out the long reports of the day and keep them, for the view each page opens
    with, so that the first person of the day is not kept waiting (D-179, P-157): the
    coverage report, the renewal worklist, the summary of the renewal alert and the
    capacity balance. It writes nothing."""
    from hirdir.api import reports

    reports.work_out_ahead(db)


# R14.7: the balance of each week, each Monday just after midnight, and when the
# process that records it starts in a week that has none.
CAPACITY_RECORD = Job("capacity record", weekly(MONDAY), record_balance, at_start=True)
# D-179, P-157: the long reports of the day, just after midnight and when the server
# starts. It runs after the record, whose audit event would otherwise leave them stale:
# in one process by its place in the list, and between two by the minutes between them.
LONG_REPORTS = Job("long reports", daily(AFTER_THE_RECORD), work_out_ahead, at_start=True)
JOBS: tuple[Job, ...] = (CAPACITY_RECORD, LONG_REPORTS)
# What the process of the background work does by the clock (P-267): what is written
# to the database, where the server finds it.
BACKGROUND_JOBS: tuple[Job, ...] = (CAPACITY_RECORD,)
# What the server does by the clock itself, whichever process does the rest: the long
# reports are kept in the memory of the process that answers (D-184, `hirdir.io.kept`),
# so worked out by another process they would be kept where no request reads them, and
# the first person of the day would wait for each all the same. Kept where both
# processes read them, the job is the second process's: move it to the list above.
SERVER_JOBS: tuple[Job, ...] = (LONG_REPORTS,)


class Scheduler:
    """Runs jobs when they are due, each with a session of its own."""

    def __init__(self, sessions: Callable[[], Session], jobs: Sequence[Job] = JOBS) -> None:
        self.sessions = sessions
        self.jobs = tuple(jobs)
        # The moment the scheduler last looked, and the jobs still owed from then.
        self.checked: datetime | None = None
        self.owed: dict[str, datetime] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _zone(self) -> ZoneInfo:
        with self.sessions() as db:
            return ZoneInfo(settings.time_zone(db))

    def _run(self, job: Job, moment: datetime) -> bool:
        """Run one job in a session of its own. Say whether it was done."""
        try:
            with self.sessions() as db:
                job.run(db, moment)
                db.commit()
        except Exception:
            log.exception("the scheduled job %s failed; it is tried again", job.name)
            return False
        return True

    def run_due(self, moment: datetime, starting: bool = False) -> list[str]:
        """Run every job that has come due since the scheduler last looked, and at
        start those that run then, for a moment. Return the names of those run."""
        try:
            zone = self._zone()
        except Exception:
            log.exception("the scheduler could not read the time zone")
            return []
        for job in self.jobs:
            due = job.when(moment, zone)
            if (starting and job.at_start) or (
                self.checked is not None and self.checked < due <= moment
            ):
                self.owed[job.name] = moment
        self.checked = moment
        done = []
        for job in self.jobs:
            if job.name in self.owed and self._run(job, moment):
                del self.owed[job.name]
                done.append(job.name)
        return done

    def start(self) -> None:
        """Run what runs at start, then look again once a minute in a thread of its own."""
        self.run_due(clock.now(), starting=True)
        self._thread = threading.Thread(target=self._loop, name="hirdir-schedule", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(WAKE_SECONDS):
            self.run_due(clock.now())

    def stop(self) -> None:
        """Stop looking, and wait for a job that is running to end."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
