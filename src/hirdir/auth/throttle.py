"""Slowing down guesses at access codes.

After a number of failures in a row for one key (a username, or a source address), each
further failure doubles the wait before the next attempt is looked at, up to a ceiling.
A success clears the count. The state is kept in memory: it protects a running server,
and a restart is not something a person guessing codes can cause.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

MAX_DELAY_SECONDS = 300.0
FORGET_AFTER_SECONDS = 3600.0
MAX_KEYS = 10_000


@dataclass
class _Entry:
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: float = 0.0


class Throttle:
    """Counts failures per key and says how long each key must wait."""

    def __init__(self, threshold: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._threshold = max(1, threshold)
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def retry_after(self, *keys: str) -> float:
        """Return the seconds until every one of keys may try again; zero means now."""
        now = self._clock()
        with self._lock:
            waits = (self._entries[key].blocked_until - now for key in keys if key in self._entries)
            return max(0.0, *waits, 0.0)

    def failure(self, *keys: str) -> None:
        """Record a failed attempt for each of keys."""
        now = self._clock()
        with self._lock:
            if len(self._entries) > MAX_KEYS:
                self._forget_old(now)
            for key in keys:
                entry = self._entries.setdefault(key, _Entry())
                entry.failures += 1
                entry.last_failure = now
                over = entry.failures - self._threshold
                if over >= 0:
                    entry.blocked_until = now + min(MAX_DELAY_SECONDS, 2.0 ** min(over, 16))

    def success(self, *keys: str) -> None:
        """Clear the count for each of keys."""
        with self._lock:
            for key in keys:
                self._entries.pop(key, None)

    def _forget_old(self, now: float) -> None:
        stale = [k for k, e in self._entries.items() if now - e.last_failure > FORGET_AFTER_SECONDS]
        for key in stale:
            del self._entries[key]
