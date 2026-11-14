"""Say how many tests may run at once on this host, and wait for it to be quiet first.

The build host is shared with other work. A run of tests that starts while the host is
busy slows everything on it, itself included, and one that starts as many workers as
there are cores takes what others are using. So before a run:

    uv run python scripts/test_load.py --wait     wait for a quiet host, then print the number
    uv run python scripts/test_load.py            print the number for the host as it is now

`--wait` waits while the host is busy, but no longer than ten minutes: other work on
the host may go on for hours, and the tests are then run all the same, with fewer
workers. The number is as wide as the free cores and the free memory allow and never
less than one. `HIRDIR_TEST_WORKERS` sets it outright, and `HIRDIR_TEST_WAIT` the
longest wait in seconds; 0 does not wait at all.

How busy the host is, is measured over a moment and not read from the load average:
the load average is of the last minute, so it would still tell of the run of tests
that has just ended, and one run would wait for the one before it.
"""

import os
import sys
import time
from pathlib import Path

LONGEST_WAIT = 600
LOOK_EVERY = 10
# How long the processors are watched to say how busy they are, in seconds.
WATCHED = 1.5
# A host is quiet when at least this share of its cores is free.
QUIET_SHARE = 0.5
# What one worker may need: a server, its database and the test's own data.
MEMORY_EACH = 768 * 1024 * 1024


def cores() -> int:
    """Return the number of cores this process may use."""
    return len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1


def _ticks() -> tuple[int, int] | None:
    """Return the ticks the processors have spent busy, and in all, since the host started."""
    try:
        first = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
        spent = [int(value) for value in first[1:9]]
    except OSError, ValueError, IndexError:
        return None
    # The fourth and fifth are idle and waiting for a disk.
    return sum(spent) - spent[3] - spent[4], sum(spent)


def busy_cores() -> float:
    """Return how many cores are busy now, watched over a moment."""
    before = _ticks()
    if before is None:
        return os.getloadavg()[0]
    time.sleep(WATCHED)
    after = _ticks()
    if after is None or after[1] == before[1]:
        return os.getloadavg()[0]
    share = (after[0] - before[0]) / (after[1] - before[1])
    return share * (os.cpu_count() or 1)


def free_cores(busy: float) -> float:
    """Return how many of the cores this process may use are free."""
    return max(0.0, cores() - busy)


def free_memory() -> int:
    """Return the memory that is available, in bytes, or a great deal where it is not told."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        pass
    return MEMORY_EACH * cores()


def workers(busy: float) -> int:
    """Return how many tests may run at once: as the free cores and memory allow."""
    given = os.environ.get("HIRDIR_TEST_WORKERS", "").strip()
    if given.isdigit() and int(given) > 0:
        return int(given)
    by_cores = int(free_cores(busy) + 0.5)
    by_memory = free_memory() // MEMORY_EACH
    return max(1, min(cores(), by_cores, by_memory))


def is_quiet(busy: float) -> bool:
    """Say whether enough of the host is free to start a run of tests."""
    return free_cores(busy) >= cores() * QUIET_SHARE and free_memory() >= 2 * MEMORY_EACH


def wait(longest: int) -> tuple[float, float]:
    """Wait for a quiet host, at most `longest` seconds. Return the wait and the busy cores."""
    started = time.monotonic()
    told = False
    busy = busy_cores()
    while not is_quiet(busy) and time.monotonic() - started < longest:
        if not told:
            print(
                f"test_load: the host is busy ({busy:.1f} of {cores()} cores): "
                f"waiting for it to be quiet, at most {longest // 60} minutes",
                file=sys.stderr,
            )
            told = True
        time.sleep(LOOK_EVERY)
        busy = busy_cores()
    return time.monotonic() - started, busy


def main() -> int:
    """Print the number of workers, after waiting for a quiet host when asked to."""
    if "--wait" in sys.argv:
        given = os.environ.get("HIRDIR_TEST_WAIT", "").strip()
        waited, busy = wait(int(given) if given.isdigit() else LONGEST_WAIT)
        if waited >= LOOK_EVERY:
            state = (
                "is quiet" if is_quiet(busy) else "is still busy; the tests are run all the same"
            )
            print(f"test_load: waited {waited:.0f} s; the host {state}", file=sys.stderr)
    else:
        busy = busy_cores()
    count = workers(busy)
    print(
        f"test_load: {count} at once ({busy:.1f} of {cores()} cores busy, "
        f"{free_memory() // (1024 * 1024)} MB free)",
        file=sys.stderr,
    )
    print(count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
