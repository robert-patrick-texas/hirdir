"""The server's own measures, where they meet the host (P-265, P-266).

The rules are in `hirdir.domain.load`, which reads nothing. Here is what is read: the
clock and the processor time of the process, the ceiling as the settings of the database
have it, and what the host says of its memory, its disk and its processors. The meter of
an application is kept on its state, in memory, and nothing of it is written anywhere.
"""

import logging
import os
import resource
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from hirdir import clock as wall
from hirdir.domain import load, settings

log = logging.getLogger("hirdir")
MEMORY_OF_THE_HOST = Path("/proc/meminfo")
MEMORY_OF_THE_PROCESS = Path("/proc/self/status")


def clock() -> tuple[float, float]:
    """Return the time, in seconds that only go forward, and the processor time the
    process has used so far, every thread of it."""
    return time.monotonic(), time.process_time()


# --- the meter of an application ------------------------------------------------------


def start(state: Any) -> None:
    """Give an application's state a meter that starts empty now, with the ceiling its
    settings give."""
    now, cpu = clock()
    state.load = load.Meter(now, cpu, started_at=wall.now(), ceiling=at_start(state))


def at_start(state: Any) -> load.Ceiling:
    """Return the ceiling as the settings of an application's database have it, and as
    the defaults do where the database cannot be read yet: a server is never without a
    ceiling because its settings could not be read. A database that is not there is
    not made by asking."""
    path = state.config.database_path
    if path is not None and not path.is_file():
        return load.Ceiling()
    try:
        with state.sessions() as db:
            return settings.ceiling(db)
    except SQLAlchemyError:
        return load.Ceiling()


def renew(state: Any) -> None:
    """Give the meter of an application the ceiling as its settings have it now: what
    an Admin saved holds from here on, and no request reads the database to learn it."""
    try:
        with state.sessions() as db:
            ceiling = settings.ceiling(db)
    except SQLAlchemyError:
        log.exception("the ceiling could not be read again, and stays as it was")
        return
    state.load.hold(ceiling)


# --- the host -------------------------------------------------------------------------


@dataclass(frozen=True)
class Host:
    """What the host says of itself and of the process. None is what it did not say."""

    process_memory_bytes: int | None
    memory_total_bytes: int | None
    memory_used_bytes: int | None
    # What a new process could have, which is more than what nothing uses.
    memory_free_bytes: int | None
    disk_total_bytes: int | None
    disk_free_bytes: int | None
    processors: int | None
    load_1m: float | None


def _kilobytes(path: Path, names: tuple[str, ...]) -> dict[str, int]:
    """Return the values of the named lines of a file of /proc, in bytes."""
    found: dict[str, int] = {}
    try:
        with path.open(encoding="ascii", errors="replace") as lines:
            for line in lines:
                name, _, rest = line.partition(":")
                if name in names:
                    found[name] = int(rest.split()[0]) * 1024
                    if len(found) == len(names):
                        break
    except OSError, ValueError, IndexError:
        return {}
    return found


def _process_memory() -> int | None:
    """Return the memory the process holds now; the most it has held, where the host
    does not say what it holds now."""
    now = _kilobytes(MEMORY_OF_THE_PROCESS, ("VmRSS",)).get("VmRSS")
    if now is not None:
        return now
    most = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return most * 1024 if most > 0 else None


def host(state_dir: Path) -> Host:
    """Read what the host says now: its memory, the disk the state directory is on, its
    processors and its load, and the memory of this process."""
    memory = _kilobytes(MEMORY_OF_THE_HOST, ("MemTotal", "MemAvailable"))
    total, free = memory.get("MemTotal"), memory.get("MemAvailable")
    try:
        disk = shutil.disk_usage(state_dir)
    except OSError:
        disk = None
    try:
        load_1m: float | None = os.getloadavg()[0]
    except OSError:
        load_1m = None
    return Host(
        process_memory_bytes=_process_memory(),
        memory_total_bytes=total,
        memory_used_bytes=total - free if total is not None and free is not None else None,
        memory_free_bytes=free,
        disk_total_bytes=disk.total if disk is not None else None,
        disk_free_bytes=disk.free if disk is not None else None,
        processors=os.cpu_count(),
        load_1m=load_1m,
    )
