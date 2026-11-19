"""The server's own measures of its load, and the ceiling past which it is busy (P-262, P-265).

A meter holds the last ten minutes of one server in memory, in steps of five seconds:
what it answered and how, how long an answer took, and the processor time the process
used. Nothing of it is written anywhere, and it starts empty.

Two measures are read from it over the last `busy_over_seconds`: how long requests take,
which is the 95th percentile of their times, and the processor time the process used as
a percentage of one processor, which passes 100 where several threads of it work at
once. Past the ceiling of either the server is busy, and what is long by nature and can
wait is turned away at once; still busy a further `busy_over_seconds` later, by what
came after it became busy, it is very busy, and every read is. The same percentile
against the thirds of its ceiling is the health of the server, in a word.

Nothing here reads a clock or the host. The time, in seconds that only go forward, and
the processor time the process has used so far are given by whoever asks, so the rules
are tried without waiting. `hirdir.io.measures` reads both for the server.
"""

import threading
from array import array
from collections import deque
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal

# The meter keeps this long, in steps of this long.
WINDOW_SECONDS = 600
STEP_SECONDS = 5
STEPS = WINDOW_SECONDS // STEP_SECONDS
# How long requests take is this percentile of their times, read of this many requests
# at the least (P-265): one request in twenty may take as long as it likes.
PERCENTILE = 95
FEWEST_REQUESTS = 20
# The measures are read again this often at the most, however many requests ask.
READ_EVERY_SECONDS = 1.0
# The answers whose times are kept for the measure, at the most: the last given.
MOST_TIMES = 20_000
# The times of the answers of one step that are kept, for the percentiles and the bands
# of the ten minutes: the first so many of the step. A step of more is two hundred
# requests a second, and its percentiles are of its first thousand.
MOST_TIMES_OF_A_STEP = 1000
# What an answer of busy says to wait, in seconds: a step, in which the measures move.
RETRY_SECONDS = STEP_SECONDS

# The three settings of the ceiling, and what each is unless set (P-265).
RESPONSE_SETTING = "busy_response_ms"
PROCESSOR_SETTING = "busy_cpu_percent"
OVER_SETTING = "busy_over_seconds"
SETTINGS = (RESPONSE_SETTING, PROCESSOR_SETTING, OVER_SETTING)
DEFAULT_RESPONSE_MS = 3000
DEFAULT_CPU_PERCENT = 95
DEFAULT_OVER_SECONDS = 30
# What the settings take: a measure at 0 is not looked at; a load counts as sustained
# over no less than a step and no more than half of what the meter keeps, so that the
# second step is always within it. The share of the processor is of one processor, and
# a process whose threads work at once uses more than one: the setting takes 100 for
# each processor of the host, which `hirdir.domain.settings` counts.
MOST_RESPONSE_MS = WINDOW_SECONDS * 1000
CPU_PERCENT_OF_A_PROCESSOR = 100
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

# The health of the server in a word, for a mark that is green, yellow, orange or red:
# how long requests take against the thirds of its ceiling, and whether it is busy.
Health = Literal["good", "slow", "very_slow", "busy"]
GOOD: Final = "good"
SLOW: Final = "slow"
VERY_SLOW: Final = "very_slow"
HEALTHS: tuple[Health, ...] = (GOOD, SLOW, VERY_SLOW, BUSY)

# What a request is, to the meter and to a server that is busy.
Kind = Literal["long", "read", "kept", "apart"]
# Long by nature, a report, an export or a preview: turned away while the server is
# busy, and its time in no measure, since seconds of it say nothing of the server.
LONG: Final = "long"
# Any other read of the API: in the measure, and turned away once it is very busy.
READ: Final = "read"
# A sign-in or a change that is stored: in the measure, and never turned away.
KEPT: Final = "kept"
# Never turned away and in no measure: the health routes, About, the settings and the
# contract, which are asked for by the clock and answered from memory, and a request
# that no route answers.
APART: Final = "apart"


def refuses(state: State, kind: Kind) -> bool:
    """Say whether a server in a state turns a request of a kind away."""
    if kind == LONG:
        return state in (BUSY, VERY_BUSY)
    return kind == READ and state == VERY_BUSY


def measured(kind: Kind) -> bool:
    """Say whether the time of a request of a kind is in the measure of time."""
    return kind in (READ, KEPT)


def percentile(ordered: Sequence[float], percent: int) -> float | None:
    """Return the percentile of some times that are in order, the shortest first: the
    shortest of them that at least `percent` in a hundred of them are no longer than.
    It is one of the times, never a value between two. None of no times."""
    if not ordered:
        return None
    return ordered[max(-(-len(ordered) * percent // 100), 1) - 1]


def bounds_of(ceiling_ms: int) -> tuple[float, float, float]:
    """Return the bounds of the four bands of time, in milliseconds: a third of the
    ceiling of time, two thirds of it, and the ceiling. Those of the ceiling unless
    set, where it is 0 and not looked at."""
    limit = ceiling_ms or DEFAULT_RESPONSE_MS
    return limit / 3, limit * 2 / 3, float(limit)


def band_of(taken_ms: float, bounds: tuple[float, float, float]) -> int:
    """Return which of the four bands a time is in: under a third of the ceiling, under
    two thirds, no more than the ceiling, or past it."""
    low, middle, limit = bounds
    if taken_ms < low:
        return 0
    if taken_ms < middle:
        return 1
    return 2 if taken_ms <= limit else 3


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
    # Busy where the state is; otherwise the band `response_ms` is in, good with none.
    health: Health = GOOD


# What a meter says before anything has asked.
UNREAD = Reading()


@dataclass(frozen=True)
class Percentiles:
    """Three percentiles of the times of the requests of the measure; None with none."""

    p50: float | None = None
    p95: float | None = None
    p99: float | None = None


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
    p50_ms: list[float | None]
    p95_ms: list[float | None]
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
    # Of the requests of the measure answered in the ten minutes: their percentiles, and
    # how many are in each band of time, with the bounds of the bands in milliseconds.
    percentiles: Percentiles
    bands: tuple[int, int, int, int]
    bounds_ms: tuple[float, float, float]
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
    # The times of the answers that are in the measure, the first of the step.
    times: array[float] = field(default_factory=lambda: array("d"))

    @property
    def timed(self) -> int:
        """How many answers the times are of: every one but an answer of busy."""
        return self.ok + self.not_accepted + self.failed

    def count(self, status: int, taken_ms: float, measured: bool) -> None:
        if measured and len(self.times) < MOST_TIMES_OF_A_STEP:
            self.times.append(taken_ms)
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

    # When the server had the request: when it arrived, or when the last piece of its
    # body that came was handed to the application.
    began: float
    # Whether its time is in the measure of time.
    measured: bool
    # Whether the server has the whole of it. One whose body has not all come waits
    # for its sender and not for the server: it is in flight, and in neither measure.
    whole: bool


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
    # When the server had each request of the measure that it has answered, and how
    # long the answer took, in the order they were answered.
    _times: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=MOST_TIMES), repr=False
    )
    # Since when the server is busy, the processor time the process had used by then,
    # and whether it is at the second step.
    _busy_since: float | None = None
    _busy_cpu: float = 0.0
    _very_busy: bool = False
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

    def began(self, now: float, cpu: float, measured: bool, whole: bool = True) -> int:
        """Note that a request arrived, and return what to end it with. `measured` says
        whether its time is in the measure of time, as that of a read or a change of
        the API is, and `whole` whether the server has all of it: a request that
        declares a body is not whole until the body has come."""
        with self._lock:
            now = self._advance(now, cpu)
            self._tokens += 1
            self._flights[self._tokens] = _Flight(now, measured, whole)
            return self._tokens

    def heard(self, token: int, now: float, cpu: float, whole: bool) -> None:
        """Note that a piece of the body of a request was handed to the application,
        and whether it was the last. The time of the request begins here, at the last
        piece that came: what its sender took to send it is not the server's time."""
        with self._lock:
            flight = self._flights.get(token)
            if flight is None or flight.whole:
                return
            flight.began = self._advance(now, cpu)
            flight.whole = whole

    def ended(self, token: int, now: float, cpu: float, status: int) -> None:
        """Note that the last byte of the answer to a request was sent, with its status."""
        with self._lock:
            flight = self._flights.pop(token, None)
            if flight is None:
                return
            now = self._advance(now, cpu)
            taken_ms = (now - flight.began) * 1000
            self._steps[-1].count(status, taken_ms, flight.measured)
            if flight.measured:
                self._times.append((flight.began, taken_ms))
                self._forget(now)

    def turned_away(self, now: float, cpu: float) -> None:
        """Note an answer of busy, which is counted and is in neither measure."""
        with self._lock:
            self._advance(now, cpu)
            self._steps[-1].busy += 1

    # --- what it says -----------------------------------------------------------------

    def reading(self, now: float, cpu: float) -> Reading:
        """Return what the measures say to a request that arrives now: whether the
        server is busy, and its health. The measures are read once a second at the
        most, and what was read is given from memory otherwise. With no ceiling the
        server is never busy, and its health is read all the same."""
        with self._lock:
            if self._read_at is not None and 0 <= now - self._read_at < READ_EVERY_SECONDS:
                return self._reading
            return self._read(self._advance(now, cpu))

    def picture(self, now: float, cpu: float, but: int | None = None) -> Picture:
        """Return everything the meter says now, the measures read afresh. `but` is the
        request that asks, which is not counted among those in flight. One whose body
        has not all come is counted, and has no age: it waits for its sender."""
        with self._lock:
            now = self._advance(now, cpu)
            reading = self._read(now)
            flying = [flight for token, flight in self._flights.items() if token != but]
            waits = [(now - flight.began) * 1000 for flight in flying if flight.whole]
            # What the steps count is taken as it stands, under the lock.
            steps = [copy(step) for step in self._steps]
            ceiling = self.ceiling
            first = self._first
            # The times are taken as they are, and put in order once the lock is let go.
            kept = [step.times.tolist() for step in steps]
            shares = [self._share(offset, now) for offset in range(len(steps))]
            under_way = now - self._begins(len(steps) - 1)
        for times in kept:
            times.sort()
        every = sorted(taken for times in kept for taken in times)
        bounds = bounds_of(ceiling.response_ms)
        bands = [0, 0, 0, 0]
        for taken in every:
            bands[band_of(taken, bounds)] += 1
        timed = sum(step.timed for step in steps)
        lows = [step.low_ms for step in steps if step.low_ms is not None]
        highs = [step.high_ms for step in steps if step.high_ms is not None]
        # A step under way says little of the processor: the whole ones are read, and
        # the one under way only while there is no other.
        whole = shares[:-1] if len(shares) > 1 else shares
        return Picture(
            reading=reading,
            ceiling=ceiling,
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
            percentiles=Percentiles(
                p50=percentile(every, 50), p95=percentile(every, 95), p99=percentile(every, 99)
            ),
            bands=(bands[0], bands[1], bands[2], bands[3]),
            bounds_ms=bounds,
            cpu_percent=Spread(
                low=min(whole),
                average=sum(whole) / len(whole),
                high=max(whole),
            ),
            in_flight=len(flying),
            oldest_ms=max(waits) if waits else None,
            points=Points(
                at=self.started_at + timedelta(seconds=first * STEP_SECONDS),
                requests=[step.timed + step.busy for step in steps],
                average_ms=[step.total_ms / step.timed if step.timed else None for step in steps],
                high_ms=[step.high_ms for step in steps],
                p50_ms=[percentile(times, 50) for times in kept],
                p95_ms=[percentile(times, 95) for times in kept],
                # The step under way has no share until a second of it has passed.
                cpu_percent=[*shares[:-1], shares[-1] if under_way >= 1 else None],
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
        """Drop the times of requests that came longer ago than the measure looks back,
        as far as they are the first of those kept: one that is kept behind a later one
        is not read, and goes when its turn comes."""
        oldest = now - self.ceiling.over_seconds
        while self._times and self._times[0][0] <= oldest:
            self._times.popleft()

    def _share(self, offset: int, now: float) -> float:
        """Return the processor time used in a step as a percentage of the part of it
        that has passed, on one processor: more than 100 where threads worked at once."""
        passed = min(now - self._begins(offset), STEP_SECONDS)
        return self._steps[offset].cpu_seconds / passed * 100 if passed > 0 else 0.0

    def _processor(self, now: float) -> float:
        """Return the processor time the process used over the last `over_seconds`, as
        a percentage of that time on one processor. Nothing holds it to 100. A server
        that started later than that used nothing before."""
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

    def _response(self, now: float, since: float) -> float | None:
        """Return how long requests take: the 95th percentile of the time taken by the
        requests of the measure that the server has had since a moment, whatever each
        took, and of the time waited so far by those in flight, however long ago they
        came; or None where they are fewer than twenty. A request is in it from when
        the server had the whole of it, so one leaves the measure `over_seconds` after
        it came and not after it was answered: a stall that is over is not read as one
        that lasts. The percentile, so that one request in twenty may take as long as
        it likes, and a second one may not; those in flight, so that a server from
        which nothing comes back is not taken for an idle one."""
        times = [taken for began, taken in self._times if began > since]
        times += [
            (now - flight.began) * 1000
            for flight in self._flights.values()
            if flight.measured and flight.whole
        ]
        if len(times) < FEWEST_REQUESTS:
            return None
        times.sort()
        return percentile(times, PERCENTILE)

    def _health(self, state: State, response: float | None) -> Health:
        """Return the health of the server in a word: busy where it is busy, by either
        measure, and otherwise the band of time that how long requests take is in,
        which past the ceiling is busy too. Good where there is no such measure."""
        if state != OK:
            return BUSY
        if response is None:
            return GOOD
        return HEALTHS[band_of(response, bounds_of(self.ceiling.response_ms))]

    def _past(self, response: float | None, processor: float) -> tuple[Measure, ...]:
        """Return which of the two measures are past the ceiling. One at 0 is not
        looked at."""
        ceiling = self.ceiling
        past: list[Measure] = []
        if ceiling.response_ms and response is not None and response > ceiling.response_ms:
            past.append(RESPONSE)
        if ceiling.cpu_percent and processor > ceiling.cpu_percent:
            past.append(PROCESSOR)
        return tuple(past)

    def _read(self, now: float) -> Reading:
        """Read the two measures, and say whether the server is busy and at which step.

        The second step is not reached by the passing of time alone. A server that has
        been busy for a further `over_seconds` is very busy only where what came after
        it became busy says so: twenty or more requests had since then and those in
        flight, whose 95th percentile is past the ceiling, or the processor time used
        since then,
        which is counted and not read from the steps. Where neither does, what kept it
        busy was the echo of before, and the further while is counted again from here.
        """
        over = self.ceiling.over_seconds
        self._forget(now)
        response, processor = self._response(now, now - over), self._processor(now)
        because = self._past(response, processor)
        if not because:
            self._busy_since = None
            self._very_busy = False
        elif self._busy_since is None:
            self._busy_since, self._busy_cpu = now, self.cpu
        elif not self._very_busy and now - self._busy_since >= over:
            since = self._busy_since
            used = (self.cpu - self._busy_cpu) / (now - since) * 100
            if self._past(self._response(now, max(since, now - over)), used):
                self._very_busy = True
            else:
                self._busy_since, self._busy_cpu = now, self.cpu
        state: State = OK if not because else VERY_BUSY if self._very_busy else BUSY
        self._reading = Reading(state, because, response, processor, self._health(state, response))
        self._read_at = now
        return self._reading
