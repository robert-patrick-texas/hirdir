"""The server's own measures of its load, and the ceiling past which it is busy (P-262, P-265).

A meter holds the last ten minutes of one server in memory, in steps of five seconds:
what it answered and how, how long an answer took, and the processor time the process
used. Nothing of it is written anywhere, and it starts empty.

Two measures are read from it over the last `busy_over_seconds`: how long requests take,
and the share of one processor the process used. Past the ceiling of either the server
is busy, and what costs most and can wait is turned away at once; still busy a further
`busy_over_seconds` later it is very busy, and every read is.

Nothing here reads a clock or the host. The time, in seconds that only go forward, and
the processor time the process has used so far are given by whoever asks, so the rules
are tried without waiting. `hirdir.io.measures` reads both for the server.
"""

import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal

# The meter keeps this long, in steps of this long.
WINDOW_SECONDS = 600
STEP_SECONDS = 5
STEPS = WINDOW_SECONDS // STEP_SECONDS
# How long requests take is read of this many requests at the least (P-265).
FEWEST_REQUESTS = 5
# The measures are read again this often at the most, however many requests ask.
READ_EVERY_SECONDS = 1.0
# The answers whose times are kept for the median, at the most: the newest.
MOST_TIMES = 20_000
# What an answer of busy says to wait, in seconds: a step, in which the measures move.
RETRY_SECONDS = STEP_SECONDS

# The three settings of the ceiling, and what each is unless set (P-265).
RESPONSE_SETTING = "busy_response_ms"
PROCESSOR_SETTING = "busy_cpu_percent"
OVER_SETTING = "busy_over_seconds"
SETTINGS = (RESPONSE_SETTING, PROCESSOR_SETTING, OVER_SETTING)
DEFAULT_RESPONSE_MS = 5000
DEFAULT_CPU_PERCENT = 95
DEFAULT_OVER_SECONDS = 30
# What the settings take: a measure at 0 is not looked at; a load counts as sustained
# over no less than a step and no more than half of what the meter keeps, so that the
# second step is always within it.
MOST_RESPONSE_MS = WINDOW_SECONDS * 1000
MOST_CPU_PERCENT = 100
FEWEST_OVER_SECONDS = STEP_SECONDS
MOST_OVER_SECONDS = WINDOW_SECONDS // 2

# What the server is.
State = Literal["ok", "busy", "very_busy"]
OK: Final = "ok"
BUSY: Final = "busy"
VERY_BUSY: Final = "very_busy"
# The two measures, as an answer names the one that is past its ceiling.
Measure = Literal["response_ms", "cpu_percent"]
RESPONSE: Final = "response_ms"
PROCESSOR: Final = "cpu_percent"

# What a request is, to a server that is busy.
Kind = Literal["costly", "read", "kept"]
COSTLY: Final = "costly"  # costs most and can wait: turned away while the server is busy
READ: Final = "read"  # any other read of the API: turned away once it is very busy
KEPT: Final = "kept"  # never turned away


def refuses(state: State, kind: Kind) -> bool:
    """Say whether a server in a state turns a request of a kind away."""
    if kind == COSTLY:
        return state in (BUSY, VERY_BUSY)
    return kind == READ and state == VERY_BUSY


@dataclass(frozen=True)
class Ceiling:
    """The ceiling: what each measure may reach, and over how long each is read."""

    response_ms: int = DEFAULT_RESPONSE_MS
    cpu_percent: int = DEFAULT_CPU_PERCENT
    over_seconds: int = DEFAULT_OVER_SECONDS

    @property
    def none(self) -> bool:
        """Say whether neither measure is looked at, which is no ceiling."""
        return not self.response_ms and not self.cpu_percent


NO_CEILING = Ceiling(response_ms=0, cpu_percent=0)


@dataclass(frozen=True)
class Reading:
    """The two measures as the ceiling reads them at one moment, and what they say."""

    state: State = OK
    # The measures that are past the ceiling.
    because: tuple[Measure, ...] = ()
    # None with fewer than `FEWEST_REQUESTS` requests.
    response_ms: float | None = None
    cpu_percent: float = 0.0


# What a meter with no ceiling says to a request, without a look at anything.
UNREAD = Reading()


@dataclass(frozen=True)
class Spread:
    """The lowest, the average and the highest of a value; None where there was none."""

    low: float | None = None
    average: float | None = None
    high: float | None = None


@dataclass(frozen=True)
class Points:
    """The steps a meter holds as lists side by side, the oldest first, for a graph."""

    at: datetime
    requests: list[int]
    average_ms: list[float | None]
    high_ms: list[float | None]
    cpu_percent: list[float | None]
    busy: list[int]


@dataclass(frozen=True)
class Picture:
    """Everything a meter says at one moment."""

    reading: Reading
    ceiling: Ceiling
    started_at: datetime
    requests: int
    ok: int
    not_accepted: int
    failed: int
    busy: int
    response_ms: Spread
    cpu_percent: Spread
    in_flight: int
    oldest_ms: float | None
    points: Points


@dataclass
class _Step:
    """Five seconds of a server."""

    ok: int = 0
    not_accepted: int = 0
    failed: int = 0
    busy: int = 0
    total_ms: float = 0.0
    low_ms: float | None = None
    high_ms: float | None = None
    cpu_seconds: float = 0.0

    @property
    def timed(self) -> int:
        """How many answers the times are of: every one but an answer of busy."""
        return self.ok + self.not_accepted + self.failed

    def count(self, status: int, taken_ms: float) -> None:
        if status >= 500:
            self.failed += 1
        elif status >= 400:
            self.not_accepted += 1
        else:
            self.ok += 1
        self.total_ms += taken_ms
        self.low_ms = taken_ms if self.low_ms is None else min(self.low_ms, taken_ms)
        self.high_ms = taken_ms if self.high_ms is None else max(self.high_ms, taken_ms)


@dataclass
class _Flight:
    """A request that is being answered."""

    began: float
    api: bool


@dataclass
class Meter:
    """The last ten minutes of one server, and whether it is busy.

    `now` is the time in seconds, from a clock that only goes forward, and `cpu` the
    processor time the process has used so far, in seconds. The lock is held for
    arithmetic only: the requests are counted on the event loop, and the measures are
    read by a thread as well.
    """

    now: float
    cpu: float
    started_at: datetime
    ceiling: Ceiling = Ceiling()
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _steps: deque[_Step] = field(default_factory=lambda: deque([_Step()]), repr=False)
    # Which step since the start the oldest one held is.
    _first: int = 0
    _origin: float = field(init=False, repr=False)
    _flights: dict[int, _Flight] = field(default_factory=dict, repr=False)
    _tokens: int = 0
    # When each request of the API was answered and how long it took, the oldest first.
    _times: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=MOST_TIMES), repr=False
    )
    _busy_since: float | None = None
    _reading: Reading = UNREAD
    _read_at: float | None = None

    def __post_init__(self) -> None:
        self._origin = self.now

    # --- what the server tells it ---------------------------------------------------

    def hold(self, ceiling: Ceiling) -> None:
        """Take another ceiling, which is in force from the next request."""
        with self._lock:
            self.ceiling = ceiling
            self._read_at = None

    def began(self, now: float, cpu: float, api: bool) -> int:
        """Note that a request arrived, and return what to end it with. `api` says
        whether it is a request of the API, whose time is in the measure."""
        with self._lock:
            now = self._advance(now, cpu)
            self._tokens += 1
            self._flights[self._tokens] = _Flight(now, api)
            return self._tokens

    def ended(self, token: int, now: float, cpu: float, status: int) -> None:
        """Note that the last byte of the answer to a request was sent, with its status."""
        with self._lock:
            flight = self._flights.pop(token, None)
            if flight is None:
                return
            now = self._advance(now, cpu)
            taken_ms = (now - flight.began) * 1000
            self._steps[-1].count(status, taken_ms)
            if flight.api:
                self._times.append((now, taken_ms))
                self._forget(now)

    def turned_away(self, now: float, cpu: float) -> None:
        """Note an answer of busy, which is counted and is in neither measure."""
        with self._lock:
            self._advance(now, cpu)
            self._steps[-1].busy += 1

    # --- what it says -----------------------------------------------------------------

    def reading(self, now: float, cpu: float) -> Reading:
        """Return what the measures say to a request that arrives now. With no ceiling
        nothing is looked at; with one, the measures are read once a second at the most."""
        with self._lock:
            if self.ceiling.none:
                self._busy_since = None
                self._read_at = None
                return UNREAD
            if self._read_at is not None and 0 <= now - self._read_at < READ_EVERY_SECONDS:
                return self._reading
            return self._read(self._advance(now, cpu))

    def picture(self, now: float, cpu: float, but: int | None = None) -> Picture:
        """Return everything the meter says now, the measures read afresh. `but` is the
        request that asks, which is not counted among those in flight."""
        with self._lock:
            now = self._advance(now, cpu)
            reading = self._read(now)
            waits = [
                (now - flight.began) * 1000
                for token, flight in self._flights.items()
                if token != but
            ]
            steps = list(self._steps)
            timed = sum(step.timed for step in steps)
            lows = [step.low_ms for step in steps if step.low_ms is not None]
            highs = [step.high_ms for step in steps if step.high_ms is not None]
            shares = [self._share(offset, now) for offset in range(len(steps))]
            # A step under way says little of the processor: the whole ones are read,
            # and the one under way only while there is no other.
            whole = shares[:-1] if len(shares) > 1 else shares
            return Picture(
                reading=reading,
                ceiling=self.ceiling,
                started_at=self.started_at,
                requests=timed + sum(step.busy for step in steps),
                ok=sum(step.ok for step in steps),
                not_accepted=sum(step.not_accepted for step in steps),
                failed=sum(step.failed for step in steps),
                busy=sum(step.busy for step in steps),
                response_ms=Spread(
                    low=min(lows) if lows else None,
                    average=sum(step.total_ms for step in steps) / timed if timed else None,
                    high=max(highs) if highs else None,
                ),
                cpu_percent=Spread(
                    low=min(whole),
                    average=sum(whole) / len(whole),
                    high=max(whole),
                ),
                in_flight=len(waits),
                oldest_ms=max(waits) if waits else None,
                points=Points(
                    at=self.started_at + timedelta(seconds=self._first * STEP_SECONDS),
                    requests=[step.timed + step.busy for step in steps],
                    average_ms=[
                        step.total_ms / step.timed if step.timed else None for step in steps
                    ],
                    high_ms=[step.high_ms for step in steps],
                    # The step under way has no share until a second of it has passed.
                    cpu_percent=[
                        *shares[:-1],
                        shares[-1] if now - self._begins(len(steps) - 1) >= 1 else None,
                    ],
                    busy=[step.busy for step in steps],
                ),
            )

    # --- the arithmetic, under the lock -----------------------------------------------

    def _begins(self, offset: int) -> float:
        """Return when the step at an offset among those held began."""
        return self._origin + (self._first + offset) * STEP_SECONDS

    def _advance(self, now: float, cpu: float) -> float:
        """Bring the steps up to now and give them the processor time used since the
        last look, spread evenly over the time since: a gap in which nothing asked is
        filled with what was used in it. Return now, which never goes back."""
        now = max(now, self.now)
        newest = self._first + len(self._steps) - 1
        current = int((now - self._origin) // STEP_SECONDS)
        if current - newest >= STEPS:
            # Nothing has asked for longer than is kept: nothing of before is left.
            self._steps.clear()
            self._first = current - STEPS + 1
            self._steps.extend(_Step() for _ in range(STEPS))
        else:
            self._steps.extend(_Step() for _ in range(current - newest))
            while len(self._steps) > STEPS:
                self._steps.popleft()
                self._first += 1
        used = max(cpu - self.cpu, 0.0)
        since = now - self.now
        if used and since <= 0:
            self._steps[-1].cpu_seconds += used
        elif used:
            for offset in range(len(self._steps) - 1, -1, -1):
                begins = self._begins(offset)
                if begins + STEP_SECONDS <= self.now:
                    break
                within = min(now, begins + STEP_SECONDS) - max(self.now, begins)
                if within > 0:
                    self._steps[offset].cpu_seconds += used * within / since
        self.now, self.cpu = now, max(cpu, self.cpu)
        return now

    def _forget(self, now: float) -> None:
        """Drop the times of answers given longer ago than the measure looks back."""
        oldest = now - self.ceiling.over_seconds
        while self._times and self._times[0][0] <= oldest:
            self._times.popleft()

    def _share(self, offset: int, now: float) -> float:
        """Return the processor time used in a step as a percentage of the part of it
        that has passed, on one processor."""
        passed = min(now - self._begins(offset), STEP_SECONDS)
        return self._steps[offset].cpu_seconds / passed * 100 if passed > 0 else 0.0

    def _processor(self, now: float) -> float:
        """Return the share of one processor the process used over the last
        `over_seconds`. A server that started later than that used nothing before."""
        over = self.ceiling.over_seconds
        oldest = now - over
        used = 0.0
        for offset in range(len(self._steps) - 1, -1, -1):
            begins = self._begins(offset)
            ends = min(begins + STEP_SECONDS, now)
            if ends <= oldest:
                break
            if ends > begins:
                used += (
                    self._steps[offset].cpu_seconds * (ends - max(begins, oldest)) / (ends - begins)
                )
        return used / over * 100

    def _response(self, now: float) -> float | None:
        """Return how long requests take: the median of the time taken by the requests
        of the API answered in the last `over_seconds` and of the time waited so far by
        those in flight, or None where they are fewer than five. The median, so that
        one long export among quick answers is not a busy server; those in flight, so
        that a server from which nothing comes back is not taken for an idle one."""
        self._forget(now)
        times = [taken for _, taken in self._times]
        times += [(now - flight.began) * 1000 for flight in self._flights.values() if flight.api]
        return statistics.median(times) if len(times) >= FEWEST_REQUESTS else None

    def _read(self, now: float) -> Reading:
        """Read the two measures, and say whether the server is busy and at which step."""
        ceiling = self.ceiling
        response, processor = self._response(now), self._processor(now)
        because = tuple(
            name
            for name, value, limit in (
                (RESPONSE, response, ceiling.response_ms),
                (PROCESSOR, processor, ceiling.cpu_percent),
            )
            # A measure at 0 is not looked at.
            if limit and value is not None and value > limit
        )
        if not because:
            self._busy_since = None
            state = OK
        else:
            if self._busy_since is None:
                self._busy_since = now
            state = VERY_BUSY if now - self._busy_since >= ceiling.over_seconds else BUSY
        self._reading = Reading(state, because, response, processor)
        self._read_at = now
        return self._reading
