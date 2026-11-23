"""The worker that applies imports and bulk edits beside the requests (D-185), and
previews those of more than a hundred rows (P-325), and the process of the background
work that it runs in (P-263, P-267).

The worker is a thread with a database session of its own, and it works one job at a
time: the one applying, then the previews that wait and the queued applies, in the
order they were asked for. The rules of a preview and of an apply are in
`hirdir.io.imports`; this is when they are run.

It runs in the second process of the service, `hirdir admin work`, which answers
nothing on the network and finds its work by looking in the database every second:
nothing passes between it and the server but the database and the state directory.
With it, in that process, runs what is done by the clock (`hirdir.schedule`), and when
the worker has nothing to apply it works the long reports out again where a change has
left them stale and nothing has changed since for a while (P-276): the one thread does
both, so nothing is worked out ahead while an import is applied, each batch of which
is a change. Where one process does both, `hirdir admin serve --work` and the
tests of the routes, the worker is a thread of the server: a route that asks for an
apply wakes it once the request is stored, and it also looks for work by itself now
and then, so a job is never left waiting for a signal that went astray.

One worker works a database. When it starts, a job found applying is marked stopped
before anything else is done, since the stop of the process that applied it cut it
short; when it stops, the job being applied stops after the batch it is in, to be
resumed. A preview that a stop cut short keeps nothing, and is worked again from its
first row. Two workers on one database would each take for stopped what the other is
applying, so the process of the background work holds a lock on `worker.lock` in the
state directory for as long as it runs, as the server holds `server.lock`.
"""

import fcntl
import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Literal

from sqlalchemy.orm import Session, sessionmaker

from hirdir import schedule
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.io import imports

log = logging.getLogger("hirdir")
# How long the worker of a server that does both waits for a signal before it looks for
# work by itself, in seconds.
LOOK_EVERY = 5.0
# How often the process of the background work looks for work, in seconds: nothing
# wakes it, so an apply begins within this long of being asked for (P-267), or once the
# long reports that are being worked out ahead are done (P-276).
LOOK_EVERY_ALONE = 1.0
# The file in the state directory that the process of the background work holds a lock
# on while it runs (P-267).
WORKER_LOCK = "worker.lock"
# How long a process that starts asks for that lock before it takes another to be
# running, in seconds, and how long it waits between two tries: the server's question
# whether the process runs holds the file for an instant.
LOCK_WITHIN = 2.0
LOCK_AGAIN_AFTER = 0.05
# How long the stop of a process waits for the batch being applied to be stored.
STOP_WITHIN = 60.0
# How long after working the long reports out ahead has failed it is tried again: not
# at every look, which would fill the log (P-276).
AHEAD_AGAIN_AFTER = 60.0


class AnotherWorks(Exception):
    """Another process does the background work of the state directory."""


class Worker:
    """Applies the jobs of one database, one at a time, in a thread of its own."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        look_every: float = LOOK_EVERY,
        ahead: bool = False,
    ) -> None:
        self.sessions = sessions
        self.look_every = look_every
        # Whether it works the long reports out again by day, when it has nothing to
        # apply (P-276): for the service, and not for a test of the routes.
        self.ahead = ahead
        self._ahead_not_before = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Say whether the worker's thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Mark stopped what the last stop interrupted, then start applying."""
        with self.sessions() as db:
            stopped = imports.recover(db)
            db.commit()
        if stopped:
            log.warning(
                "%d imports were found applying and are marked stopped, to be resumed: %s",
                len(stopped),
                stopped,
            )
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hirdir-imports", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Tell the worker that a job is waiting."""
        self._wake.set()

    def stop(self, within: float = STOP_WITHIN) -> None:
        """Stop after the batch being applied, and wait for that, at most `within` seconds.

        A job that is cut short so is stopped, to be resumed. One whose batch takes
        longer still is found applying when a worker starts again, and is stopped then.
        A preview in the background stops after the rows it is in, keeps nothing, and is
        worked again from its first row when a worker starts again (P-325).
        """
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(within)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.once()
            except Exception:
                log.exception("the worker that applies imports failed, and goes on")
                worked = False
            if not worked:
                self._wake.wait(self.look_every)
                self._wake.clear()

    def once(self) -> bool:
        """Work the next job, a preview or an apply, if there is one. Say whether there
        was. With none, the long reports are worked out again where they are due, which
        is no job: the worker waits for its next look after it as after nothing."""
        with self.sessions() as db:
            hid = imports.next_job(db)
            db.rollback()
            if hid is None:
                self._work_ahead(db)
                return False
            imports.work(db, hid, self._stop)
            return True

    def _work_ahead(self, db: Session) -> None:
        """Work the long reports out again where a change has left them stale and
        nothing has changed since for as long as the setting says (P-276). A failure is
        logged and not tried again for a minute."""
        if not self.ahead or time.monotonic() < self._ahead_not_before:
            return
        try:
            schedule.work_out_ahead_if_due(db)
        except Exception:
            log.exception(
                "the long reports could not be worked out ahead; it is tried again in %d seconds",
                AHEAD_AGAIN_AFTER,
            )
            self._ahead_not_before = time.monotonic() + AHEAD_AGAIN_AFTER
        finally:
            db.rollback()


@contextmanager
def running(state: Any, ahead: bool = False) -> Generator[Worker]:
    """Run a worker for the database of an application's state while the block lasts.

    The worker is kept on the state, for the routes to wake. An application that is
    started again inside its own block, as a test may do, shares the worker that runs.
    With `ahead` it works the long reports out again by day as well (P-276), as a
    server that does both does, `hirdir admin serve --work`.
    """
    worker = getattr(state, "worker", None)
    if isinstance(worker, Worker) and worker.running and worker.sessions is state.sessions:
        yield worker
        return
    worker = Worker(state.sessions, ahead=ahead)
    worker.start()
    state.worker = worker
    try:
        yield worker
    finally:
        worker.stop()


# --- the process of the background work -----------------------------------------------


def is_held(path: Path) -> bool:
    """Say whether a process holds its lock on a file, `server.lock` or `worker.lock`
    of a state directory. The lock is asked for, shared, and let go at once: being
    refused is how the process is known to run, and nothing is read or written. A file
    that is not there, or cannot be opened, is held by nobody."""
    try:
        with path.open("rb") as held:
            try:
                fcntl.flock(held, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(held, fcntl.LOCK_UN)
    except OSError:
        pass
    return False


def hold_lock(state_dir: Path, within: float | None = None) -> BinaryIO:
    """Hold the lock that the one process of the background work holds on a state
    directory, and return the file, which lets the lock go when it is closed.

    Somebody who asks whether the process runs holds the file for an instant, so the
    lock is asked for again for `within` seconds, `LOCK_WITHIN` unless given. Refused
    for as long as that, another process does the work, and `AnotherWorks` is raised.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    held = (state_dir / WORKER_LOCK).open("ab")
    until = time.monotonic() + (LOCK_WITHIN if within is None else within)
    while True:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= until:
                held.close()
                raise AnotherWorks(state_dir) from None
            time.sleep(LOCK_AGAIN_AFTER)
        else:
            return held


@contextmanager
def working(config: Config) -> Generator[Worker]:
    """Do the background work of one installation while the block lasts (P-267): apply
    the imports and bulk edits that wait, looking for them every second, do what is
    done by the clock, and work the long reports out ahead, by the clock and after a
    change (P-275, P-276).

    Call it holding the lock of `hold_lock`: it marks stopped what it finds applying.
    The database is opened as the server opens it, so this is one writer among the
    others. What runs at start is done before the block begins. When the block ends the
    scheduler stops, and the worker after the batch it is applying, whose job is then
    stopped, to be resumed.
    """
    engine = make_engine(config.database_url)
    sessions = make_sessions(engine)
    worker = Worker(sessions, look_every=LOOK_EVERY_ALONE, ahead=True)
    scheduler = schedule.Scheduler(sessions, schedule.BACKGROUND_JOBS)
    worker.start()
    try:
        scheduler.start()
        yield worker
    finally:
        scheduler.stop()
        worker.stop()
        engine.dispose()


def worker_state(state: Any) -> Literal["running", "not_running", "in_process"]:
    """Say whether the background work of an application's database is being done, and
    where: by a thread of this process, by the process of its own (P-267), or by nothing.

    The process of its own holds a lock on `worker.lock` in the state directory for as
    long as it runs. Asking for that lock and being refused is how it is known to run:
    nothing is read or written.
    """
    worker = getattr(state, "worker", None)
    if isinstance(worker, Worker) and worker.running:
        return "in_process"
    if is_held(state.config.state_dir / WORKER_LOCK):
        return "running"
    return "not_running"


def wake(state: Any) -> None:
    """Tell the worker of an application's state that a job is waiting. Where the worker
    is a process of its own there is none to tell, and it finds the job by itself."""
    worker = getattr(state, "worker", None)
    if isinstance(worker, Worker):
        worker.wake()
