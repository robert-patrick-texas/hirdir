"""The server's own measures of its load, its health, and what it refuses (P-262, P-265).

A meter holds the last ten minutes of one server in memory, in steps of five seconds:
what it answered and how, how long an answer took, and the processor time the process
used. Nothing of it is written anywhere, and it starts empty.

Two measures are read from it over the last `busy_over_seconds`: how long requests take,
which is the 95th percentile of their times, and the processor time the process used as
a percentage of one processor, which passes 100 where several threads of it work at
once. From them comes the health of the server, in one of four words, and what the
server refuses follows from its health alone: nothing while it is good or slow, what is
long by nature and can wait while it is very slow, and every read as well while it is
busy.

Nothing here reads a clock or the host. The time, in seconds that only go forward, and
the processor time the process has used so far are given by whoever asks, so the rules
are tried without waiting. `hirdir.io.measures` reads both for the server.
"""

import threading
from array import array
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from copy import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Final, Literal

# The meter keeps this long, in steps of this long.
WINDOW_SECONDS = 600
STEP_SECONDS = 5
STEPS = WINDOW_SECONDS // STEP_SECONDS
# How long requests take is this percentile of their times, at any count of them: the
# colour is there to catch slow pages on a quiet server, where one slow answer is what
# a person met. What is refused is decided by the reads alone, and only where there are
# this many of them in the time the measures look back: fewer are no load to shed, and
# of twenty or fewer the percentile is one request alone (P-265).
PERCENTILE = 95
FEWEST_REQUESTS = 21
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
# The slowest requests of the ten minutes that are listed: of the measure, and of what is
# long by nature. A step keeps as many of its own, so the slowest of all are among them.
MOST_SLOWEST = 10
MOST_SLOWEST_LONG = 5
# The accounts one step counts each by itself, and the accounts that are listed: past
# either, the rest are counted together.
MOST_PEOPLE_OF_A_STEP = 50
MOST_PEOPLE = 50
# The accounts remembered by their HID, for a request that is refused before anything
# looks who asks; past so many, all are forgotten and learnt again.
MOST_KNOWN = 1000

# The three settings of the ceiling, and what each is unless set (P-265).
RESPONSE_SETTING = "busy_response_ms"
PROCESSOR_SETTING = "busy_cpu_percent"
OVER_SETTING = "busy_over_seconds"
SETTINGS = (RESPONSE_SETTING, PROCESSOR_SETTING, OVER_SETTING)
DEFAULT_RESPONSE_MS = 3000
DEFAULT_CPU_PERCENT = 95
DEFAULT_OVER_SECONDS = 30
# What the settings take: a measure at 0 is not looked at; the measures are read over
# no less than a step and no more than half of what the meter keeps, so that the while
# after a server refused its reads is within it too. The share of the processor is of
# one processor, and a process whose threads work at once uses more than one: the
# setting takes 100 for each processor of the host, which `hirdir.domain.settings`
# counts.
MOST_RESPONSE_MS = WINDOW_SECONDS * 1000
CPU_PERCENT_OF_A_PROCESSOR = 100
FEWEST_OVER_SECONDS = STEP_SECONDS
MOST_OVER_SECONDS = WINDOW_SECONDS // 2

# The two measures, as an answer names the one its health stands on.
Measure = Literal["response_ms", "cpu_percent"]
RESPONSE: Final = "response_ms"
PROCESSOR: Final = "cpu_percent"

# The health of the server in a word, for a mark that is green, yellow, orange or red:
# how long requests take against the thirds of its ceiling. In order, the worst last.
Health = Literal["good", "slow", "very_slow", "busy"]
GOOD: Final = "good"
SLOW: Final = "slow"
VERY_SLOW: Final = "very_slow"
BUSY: Final = "busy"
HEALTHS: tuple[Health, ...] = (GOOD, SLOW, VERY_SLOW, BUSY)
ORANGE = HEALTHS.index(VERY_SLOW)
RED = HEALTHS.index(BUSY)

# What a server refuses, which follows from its health: nothing while it is good or
# slow, what is long by nature while it is very slow, and every read as well while it
# is busy.
Refusing = Literal["nothing", "long", "reads"]
NOTHING: Final = "nothing"
THE_LONG: Final = "long"
THE_READS: Final = "reads"
REFUSINGS: tuple[Refusing, ...] = (NOTHING, NOTHING, THE_LONG, THE_READS)

# What a request is, to the meter and to a server that refuses.
Kind = Literal["long", "read", "kept", "apart"]
# Long by nature, a report, an export or a preview: turned away from very slow on, and
# its time in no measure, since seconds of it say nothing of the server.
LONG: Final = "long"
# Any other read of the API: in the measure, and turned away while the server is busy.
READ: Final = "read"
# A sign-in or a change that is stored: in the measure, and never turned away.
KEPT: Final = "kept"
# Never turned away and in no measure: the health routes, About, the settings and the
# contract, which are asked for by the clock and answered from memory, and a request
# that no route answers.
APART: Final = "apart"


# Who asked: a person, a service account, an agent (P-316), nobody that is known, or
# the rest together.
WhoKind = Literal["person", "service", "agent", "unnamed", "others"]
PERSON: Final = "person"
SERVICE: Final = "service"
AGENT: Final = "agent"
UNNAMED: Final = "unnamed"
OTHERS: Final = "others"


def kind_of(account_kind: str) -> WhoKind:
    """Return how the measures name an account of a kind, as `users.kind` has it."""
    return SERVICE if account_kind == SERVICE else AGENT if account_kind == AGENT else PERSON


@dataclass(frozen=True)
class Who:
    """Who asked: an account, by its HID and its username, a person's, a service's or an
    agent's."""

    hid: str
    username: str
    kind: WhoKind = PERSON


@dataclass(frozen=True)
class Asked:
    """What was asked, as much as is kept of it: the method, the route as its pattern,
    `/api/v1/items/{hid}`, and the ID of the request. Never the path as it was asked nor
    its query: no identifier and no word of a search is kept."""

    method: str
    route: str | None
    request_id: str


@dataclass(frozen=True)
class Slow:
    """One of the slowest requests of the ten minutes."""

    at: datetime
    method: str
    route: str | None
    ms: float
    status: int
    request_id: str
    # None where nothing verifiable said who asked.
    who: Who | None


@dataclass(frozen=True)
class Person:
    """What one account met in the ten minutes; or those nobody is named for, or the
    rest together."""

    kind: WhoKind
    hid: str | None
    username: str | None
    # Every request of the API, those that were refused among them.
    requests: int
    # Of its requests of the measure, how many in each band of time.
    bands: tuple[int, int, int, int]
    slowest_ms: float | None
    busy: int
    failed: int
    last_at: datetime


@dataclass
class _Slow:
    """A request that is among the slowest of its step."""

    began: float
    taken_ms: float
    status: int
    asked: Asked
    who: Who | None


@dataclass
class _Met:
    """What one account met in one step."""

    who: Who | None
    requests: int = 0
    bands: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    slowest_ms: float | None = None
    busy: int = 0
    failed: int = 0
    # When the last of its requests came.
    last: float = 0.0

    def add(self, other: _Met) -> None:
        if other.last >= self.last and other.who is not None:
            # The username as it was when the account last asked.
            self.who = other.who
        self.requests += other.requests
        self.bands = [mine + its for mine, its in zip(self.bands, other.bands, strict=True)]
        if other.slowest_ms is not None:
            self.slowest_ms = max(self.slowest_ms or 0.0, other.slowest_ms)
        self.busy += other.busy
        self.failed += other.failed
        self.last = max(self.last, other.last)

    @property
    def worst(self) -> tuple[int, float]:
        """How bad it was: the requests past the ceiling and those refused, and then
        the slowest time."""
        return self.bands[3] + self.busy, self.slowest_ms or 0.0


def _keep(kept: list[_Slow], slow: _Slow, most: int) -> None:
    """Keep a request among the slowest of a step, where it is one of them."""
    if len(kept) < most:
        kept.append(slow)
        return
    least = min(range(len(kept)), key=lambda at: kept[at].taken_ms)
    if slow.taken_ms > kept[least].taken_ms:
        kept[least] = slow


def slowest_of(slow: Iterable[_Slow], most: int, when: Callable[[float], datetime]) -> list[Slow]:
    """Return the slowest of some requests, the slowest first, and of two that took as
    long the one that came first."""
    ordered = sorted(slow, key=lambda one: (-one.taken_ms, one.began))
    return [
        Slow(
            at=when(one.began),
            method=one.asked.method,
            route=one.asked.route,
            ms=one.taken_ms,
            status=one.status,
            request_id=one.asked.request_id,
            who=one.who,
        )
        for one in ordered[:most]
    ]


def people_of(met: Iterable[tuple[str, _Met]], when: Callable[[float], datetime]) -> list[Person]:
    """Return what each account met, from what it met in each step: whoever had it
    worst first, by the requests past the ceiling and those refused, then by the
    slowest time, then by name. After the accounts, the requests that nothing
    verifiable named an account for, in one row; and last the rest together, where
    there were more accounts than are counted or listed each by itself."""
    by_key: dict[str, _Met] = {}
    for key, one in met:
        whole = by_key.get(key)
        if whole is None:
            by_key[key] = replace(one, bands=list(one.bands))
        else:
            whole.add(one)
    unnamed, others = by_key.pop(UNNAMED, None), by_key.pop(OTHERS, None)
    named = sorted(
        by_key.values(),
        key=lambda one: (-one.worst[0], -one.worst[1], one.who.username if one.who else ""),
    )
    for one in named[MOST_PEOPLE:]:
        if others is None:
            others = _Met(None)
        others.add(replace(one, who=None))
    rows = [(one.who.kind if one.who else PERSON, one) for one in named[:MOST_PEOPLE]]
    rows += [(kind, one) for kind, one in ((UNNAMED, unnamed), (OTHERS, others)) if one]
    return [
        Person(
            kind=kind,
            hid=one.who.hid if one.who else None,
            username=one.who.username if one.who else None,
            requests=one.requests,
            bands=(one.bands[0], one.bands[1], one.bands[2], one.bands[3]),
            slowest_ms=one.slowest_ms,
            busy=one.busy,
            failed=one.failed,
            last_at=when(one.last),
        )
        for kind, one in rows
    ]


def refuses(refusing: Refusing, kind: Kind) -> bool:
    """Say whether a server that refuses so much turns a request of a kind away."""
    if kind == LONG:
        return refusing in (THE_LONG, THE_READS)
    return kind == READ and refusing == THE_READS


def measured(kind: Kind) -> bool:
    """Say whether the time of a request of a kind is in the measure of time."""
    return kind in (READ, KEPT)


def percentile(ordered: Sequence[float], percent: int) -> float | None:
    """Return the percentile of some times that are in order, the shortest first, by
    the nearest rank from the top: the k-th longest of them, where k is as many in a
    hundred of them as the percentile leaves above it, rounded up, and one at the
    least. So the 95th of twenty or fewer is the longest, of twenty-one the second
    longest, and of a hundred the fifth. It is one of the times, never a value between
    two. None of no times."""
    if not ordered:
        return None
    above = max(-(-len(ordered) * (100 - percent) // 100), 1)
    return ordered[len(ordered) - above]


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

    health: Health = GOOD
    # The measures the health stands on: none while it is good.
    because: tuple[Measure, ...] = ()
    refusing: Refusing = NOTHING
    # None with no request.
    response_ms: float | None = None
    cpu_percent: float = 0.0
    # How many requests `response_ms` is of.
    requests: int = 0
    # The same of the reads alone, by which what is refused is decided: a change that
    # is stored is in the colour, and is never what a read is refused for.
    reads_ms: float | None = None
    reads: int = 0


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
    # The slowest requests of the ten minutes, of the measure and of what is long by
    # nature, and what each account met in them.
    slowest: list[Slow]
    slowest_long: list[Slow]
    people: list[Person]


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
    # The slowest of its requests, of the measure and of what is long by nature; and
    # what each account met in it, by the HID of the account.
    slowest: list[_Slow] = field(default_factory=list)
    slowest_long: list[_Slow] = field(default_factory=list)
    people: dict[str, _Met] = field(default_factory=dict)

    def met(self, who: Who | None) -> _Met:
        """Return what an account met in the step, to add to: that of the requests
        nobody is named for, where there is no account; and that of the rest together,
        where the step counts as many accounts as it may."""
        key = UNNAMED if who is None else who.hid
        one = self.people.get(key)
        if one is None:
            if who is not None and len(self.people) >= MOST_PEOPLE_OF_A_STEP:
                key, who = OTHERS, None
                one = self.people.get(key)
            if one is None:
                one = self.people[key] = _Met(who)
        elif who is not None:
            one.who = who
        return one

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
    # Whether it is long by nature, and whether it is of the API at all.
    long: bool = False
    api: bool = True
    # Whether it is a sign-in or a change that is stored: in the measure of time, and
    # not among the reads, by which what is refused is decided.
    kept: bool = False


@dataclass
class Meter:
    """The last ten minutes of one server, its health and what it refuses.

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
    # When the server had each request of the measure that it has answered, how long
    # the answer took and whether it was a read, in the order they were answered.
    _times: deque[tuple[float, float, bool]] = field(
        default_factory=lambda: deque(maxlen=MOST_TIMES), repr=False
    )
    # When the server last refused its reads, while that is no longer ago than the
    # measures look back: the one thing remembered of before.
    _busy_at: float | None = None
    # The accounts that asked of late, by their HID.
    _known: dict[str, Who] = field(default_factory=dict, repr=False)
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

    def began(
        self,
        now: float,
        cpu: float,
        measured: bool,
        whole: bool = True,
        long: bool = False,
        api: bool = True,
        kept: bool = False,
    ) -> int:
        """Note that a request arrived, and return what to end it with. `measured` says
        whether its time is in the measure of time, as that of a read or a change of
        the API is, and `whole` whether the server has all of it: a request that
        declares a body is not whole until the body has come. `long` says that it is
        long by nature, `api` that it is of the API, whose requests are counted for
        who asked them, and `kept` that it is a sign-in or a change that is stored,
        which is never refused and is not among the reads."""
        with self._lock:
            now = self._advance(now, cpu)
            self._tokens += 1
            self._flights[self._tokens] = _Flight(now, measured, whole, long, api, kept)
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

    def ended(
        self,
        token: int,
        now: float,
        cpu: float,
        status: int,
        who: Who | None = None,
        asked: Asked | None = None,
    ) -> None:
        """Note that the last byte of the answer to a request was sent, with its
        status; and for a request of the API who asked, where the check of the sign-in
        found an account, and what was asked. It costs the request a few additions:
        the lists are worked out when they are asked for."""
        with self._lock:
            flight = self._flights.pop(token, None)
            if flight is None:
                return
            now = self._advance(now, cpu)
            taken_ms = (now - flight.began) * 1000
            step = self._steps[-1]
            step.count(status, taken_ms, flight.measured)
            if flight.measured:
                self._times.append((flight.began, taken_ms, not flight.kept))
                self._forget(now)
            if not flight.api:
                return
            one = step.met(who)
            one.requests += 1
            one.last = max(one.last, flight.began)
            if status >= 500:
                one.failed += 1
            if flight.measured:
                one.bands[band_of(taken_ms, bounds_of(self.ceiling.response_ms))] += 1
                one.slowest_ms = max(one.slowest_ms or 0.0, taken_ms)
            if asked is not None and (flight.measured or flight.long):
                slow = _Slow(flight.began, taken_ms, status, asked, who)
                if flight.long:
                    _keep(step.slowest_long, slow, MOST_SLOWEST_LONG)
                else:
                    _keep(step.slowest, slow, MOST_SLOWEST)
            if who is not None:
                if len(self._known) >= MOST_KNOWN and who.hid not in self._known:
                    self._known.clear()
                self._known[who.hid] = who

    def turned_away(self, now: float, cpu: float, who: Who | None = None) -> None:
        """Note a request that was refused, which is counted and is in neither measure;
        for who asked, where that is known."""
        with self._lock:
            now = self._advance(now, cpu)
            step = self._steps[-1]
            step.busy += 1
            one = step.met(who)
            one.requests += 1
            one.busy += 1
            one.last = max(one.last, now)

    def known(self, hid: str) -> Who | None:
        """Return the account of a HID, where it asked of late: what a request that is
        refused before anything looks who asks is counted for."""
        with self._lock:
            return self._known.get(hid)

    # --- what it says -----------------------------------------------------------------

    def reading(self, now: float, cpu: float) -> Reading:
        """Return what the measures say to a request that arrives now: the health of
        the server, and what it refuses. The measures are read once a second at the
        most, and what was read is given from memory otherwise. With no ceiling
        nothing is refused, and the health is read all the same."""
        with self._lock:
            if self._read_at is not None and 0 <= now - self._read_at < READ_EVERY_SECONDS:
                return self._reading
            return self._read(self._advance(now, cpu))

    def answering(self, token: int, now: float, cpu: float) -> Reading:
        """Return what the measures say as the answer to a request begins, the
        request's own time counted: an answer that was slow says so itself, and not
        only the one after it. What is held in memory is given, unless it is a second
        old, or the time this request has taken so far is in a higher band than the
        health it says: only then are the measures read again, with this request in
        them, which is in flight still."""
        with self._lock:
            if self._read_at is None or not 0 <= now - self._read_at < READ_EVERY_SECONDS:
                return self._read(self._advance(now, cpu))
            flight = self._flights.get(token)
            if flight is not None and flight.measured and flight.whole:
                taken_ms = (now - flight.began) * 1000
                band = band_of(taken_ms, bounds_of(self.ceiling.response_ms))
                if band > HEALTHS.index(self._reading.health):
                    return self._read(self._advance(now, cpu))
            return self._reading

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
            slow = [one for step in steps for one in step.slowest]
            slow_long = [one for step in steps for one in step.slowest_long]
            met = [
                (key, replace(one, bands=list(one.bands)))
                for step in steps
                for key, one in step.people.items()
            ]
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
            slowest=slowest_of(slow, MOST_SLOWEST, self._when),
            slowest_long=slowest_of(slow_long, MOST_SLOWEST_LONG, self._when),
            people=people_of(met, self._when),
        )

    def _when(self, moment: float) -> datetime:
        """Return the moment of the clock that only goes forward as a time of day."""
        return self.started_at + timedelta(seconds=moment - self._origin)

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

    def _response(self, now: float) -> tuple[list[float], list[float]]:
        """Return the times that how long requests take is read of, in order: of the
        requests of the measure that came in the last `over_seconds`, whatever each
        took, with the time waited so far by those in flight, however long ago they
        came; and the same of the reads alone. A request is in them from when the
        server had the whole of it, so one leaves `over_seconds` after it came and not
        after it was answered: a stall that is over is not read as one that lasts.
        Those in flight are in them so that a server from which nothing comes back is
        not taken for an idle one."""
        since = now - self.ceiling.over_seconds
        every: list[float] = []
        reads: list[float] = []
        for began, taken, read in self._times:
            if began > since:
                every.append(taken)
                if read:
                    reads.append(taken)
        for flight in self._flights.values():
            if flight.measured and flight.whole:
                waited = (now - flight.began) * 1000
                every.append(waited)
                if not flight.kept:
                    reads.append(waited)
        every.sort()
        reads.sort()
        return every, reads

    def _read(self, now: float) -> Reading:
        """Read the measures, and say the health of the server and what it refuses.

        The health is of everything a person meets. How long requests take, reads and
        changes alike, says it by the band it is in, against the thirds of its ceiling,
        at any count of requests: good with none. The processor past its ceiling makes
        it very slow at the least, and never busy by itself.

        What is refused is decided by the reads alone, which are what can be refused.
        A change that waits for another to be stored is slow, and the mark says so; no
        read waits for it, and to refuse the reads for it would shed nothing and, the
        reads once gone from the measure, keep the server red on the changes alone. So
        the same percentile is read of the reads of the same time, and it refuses by
        its band only where `response_ms` has a ceiling and there are twenty-one reads
        or more: fewer are a quiet server whose pages are slow, and of twenty the
        percentile is one request alone. The health is never better than what is
        refused says. The processor refuses what is long whatever the count. And a
        server that refused its reads refuses what is long, and is very slow at the
        best, until `over_seconds` have passed since it last did: what is long does not
        come back in the same moment as the reads. Nothing else of before is
        remembered.
        """
        ceiling = self.ceiling
        bounds = bounds_of(ceiling.response_ms)
        self._forget(now)
        every, reads = self._response(now)
        response, reads_ms = percentile(every, PERCENTILE), percentile(reads, PERCENTILE)
        processor = self._processor(now)
        loaded = bool(ceiling.response_ms) and len(reads) >= FEWEST_REQUESTS
        time_refuses = band_of(reads_ms, bounds) if loaded and reads_ms is not None else 0
        if time_refuses == RED:
            self._busy_at = now
        elif self._busy_at is not None:
            if ceiling.response_ms and now - self._busy_at < ceiling.over_seconds:
                time_refuses = max(time_refuses, ORANGE)
            else:
                self._busy_at = None
        by_time = max(0 if response is None else band_of(response, bounds), time_refuses)
        by_processor = ORANGE if ceiling.cpu_percent and processor > ceiling.cpu_percent else 0
        level = max(by_time, by_processor)
        because: tuple[Measure, ...] = tuple(
            measure
            for measure, its in ((RESPONSE, by_time), (PROCESSOR, by_processor))
            if level and its == level
        )
        refusing = REFUSINGS[max(time_refuses, by_processor)]
        self._reading = Reading(
            HEALTHS[level], because, refusing, response, processor, len(every), reads_ms, len(reads)
        )
        self._read_at = now
        return self._reading
