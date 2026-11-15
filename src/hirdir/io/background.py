"""The worker that applies imports and bulk edits beside the requests (D-185).

It is a thread of the server's one process, with a database session of its own, and it
applies one job at a time: the one applying, then the queued ones in the order they were
asked for. The rules of an apply are in `hirdir.io.imports`; this is when they are run.

A route that asks for an apply wakes the worker once the request is stored. The worker
also looks for work by itself now and then, so a job is never left waiting for a
signal that went astray. When the server starts, a job found applying was stopped by
the stop, and is marked so before anything else is done; when the server stops, the
job being applied stops after the batch it is in, to be resumed.
"""

import logging
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from hirdir.io import imports

log = logging.getLogger("hirdir")
# How long the worker waits for a signal before it looks for work by itself, in seconds.
LOOK_EVERY = 5.0
# How long the server waits at its stop for the batch being applied to be stored.
STOP_WITHIN = 60.0


class Worker:
    """Applies the jobs of one database, one at a time, in a thread of its own."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
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
            log.warning("%d imports were stopped by the server's stop: %s", len(stopped), stopped)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hirdir-imports", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Tell the worker that a job is waiting."""
        self._wake.set()

    def stop(self, within: float = STOP_WITHIN) -> None:
        """Stop after the batch being applied, and wait for that, at most `within` seconds.

        A job that is cut short so is stopped, to be resumed. One whose batch takes
        longer still is found applying when the server starts again, and is stopped then.
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
                self._wake.wait(LOOK_EVERY)
                self._wake.clear()

    def once(self) -> bool:
        """Apply the next job, if there is one. Say whether there was."""
        with self.sessions() as db:
            hid = imports.next_job(db)
            db.rollback()
            if hid is None:
                return False
            imports.work_job(db, hid, self._stop)
            return True


@contextmanager
def running(state: Any) -> Generator[Worker]:
    """Run a worker for the database of an application's state while the block lasts.

    The worker is kept on the state, for the routes to wake. An application that is
    started again inside its own block, as a test may do, shares the worker that runs.
    """
    worker = getattr(state, "worker", None)
    if isinstance(worker, Worker) and worker.running and worker.sessions is state.sessions:
        yield worker
        return
    worker = Worker(state.sessions)
    worker.start()
    state.worker = worker
    try:
        yield worker
    finally:
        worker.stop()


def wake(state: Any) -> None:
    """Tell the worker of an application's state that a job is waiting."""
    worker = getattr(state, "worker", None)
    if isinstance(worker, Worker):
        worker.wake()
