"""The server's own measures and the ceiling (P-265): the rules, with the time and the
processor time given, so that nothing here waits."""

from datetime import UTC, datetime, timedelta

import pytest

from hirdir.domain import load
from hirdir.domain.load import Ceiling, Meter

STARTED = datetime(2027, 3, 2, 14, 0, 0, tzinfo=UTC)
# A ceiling of each measure alone, read over ten seconds.
SLOW = Ceiling(response_ms=1000, cpu_percent=0, over_seconds=10)
HOT = Ceiling(response_ms=0, cpu_percent=50, over_seconds=10)


def meter(ceiling: Ceiling = load.NO_CEILING) -> Meter:
    return Meter(0.0, 0.0, started_at=STARTED, ceiling=ceiling)


def answer(
    measured: Meter,
    began: float,
    took: float,
    status: int = 200,
    counted: bool = True,
    cpu: float = 0.0,
    kept: bool = False,
) -> None:
    """Have a request arrive and be answered `took` seconds later. `counted` says
    whether its time is in the measure of time, and `kept` that it is a change that is
    stored and not a read."""
    token = measured.began(began, cpu, measured=counted, kept=kept)
    measured.ended(token, began + took, cpu, status=status)


def at_once(
    measured: Meter,
    at: float,
    took_ms: list[float],
    counted: bool = True,
    answered: bool = True,
    kept: bool = False,
) -> list[int]:
    """Have requests come at one moment, each answered after its own time, told to the
    meter in the order it all happens. Unless `answered`, they stay in flight. Reads,
    unless `kept` says that they are changes that are stored. Return what each is ended
    with."""
    tokens = [measured.began(at, 0.0, measured=counted, kept=kept) for _ in took_ms]
    if answered:
        for token, taken in sorted(zip(tokens, took_ms, strict=True), key=lambda one: one[1]):
            measured.ended(token, at + taken / 1000, 0.0, status=200)
    return tokens


# --- the steps -----------------------------------------------------------------------


def test_a_meter_starts_empty_with_one_step_under_way() -> None:
    picture = meter().picture(0.0, 0.0)
    assert (picture.requests, picture.ok, picture.not_accepted, picture.failed) == (0, 0, 0, 0)
    assert picture.busy == 0
    assert picture.response_ms == load.Spread(None, None, None)
    assert (picture.in_flight, picture.oldest_ms) == (0, None)
    assert picture.started_at == STARTED
    points = picture.points
    assert points.at == STARTED
    assert points.requests == [0]
    assert points.average_ms == points.high_ms == points.cpu_percent == [None]
    assert points.p50_ms == points.p95_ms == [None]
    assert picture.percentiles == load.Percentiles(None, None, None)
    assert (picture.bands, picture.bounds_ms) == ((0, 0, 0, 0), (1000.0, 2000.0, 3000.0))
    assert picture.reading == load.Reading(load.GOOD, (), load.NOTHING, None, 0.0)


def test_each_answer_is_counted_in_its_step_by_how_it_was_answered() -> None:
    measured = meter()
    answer(measured, 0.0, 0.010)
    answer(measured, 1.0, 0.030, status=201)
    answer(measured, 2.0, 0.020, status=404)
    answer(measured, 6.0, 0.500, status=500)
    answer(measured, 7.0, 0.100, status=503)
    # Whatever is not of the API, the page and its files, is counted as well.
    answer(measured, 11.0, 0.002, status=304, counted=False)
    picture = measured.picture(12.0, 0.0)
    assert (picture.requests, picture.ok, picture.not_accepted, picture.failed) == (6, 3, 1, 2)
    assert picture.points.requests == [3, 2, 1]
    assert picture.points.average_ms == pytest.approx([20.0, 300.0, 2.0])
    assert picture.points.high_ms == pytest.approx([30.0, 500.0, 2.0])
    assert picture.response_ms.low == pytest.approx(2.0)
    assert picture.response_ms.high == pytest.approx(500.0)
    assert picture.response_ms.average == pytest.approx((10 + 30 + 20 + 500 + 100 + 2) / 6)


def test_an_answer_is_counted_in_the_step_its_last_byte_was_sent_in() -> None:
    measured = meter()
    answer(measured, 4.0, 7.0)
    picture = measured.picture(11.0, 0.0)
    assert picture.points.requests == [0, 0, 1]
    assert picture.points.high_ms == [None, None, pytest.approx(7000.0)]


def test_the_steps_roll_over_and_the_oldest_drop() -> None:
    measured = meter()
    answer(measured, 1.0, 0.010)
    answer(measured, 6.0, 0.010)
    # 599 seconds in, the first step is the oldest of 120.
    picture = measured.picture(599.0, 0.0)
    assert len(picture.points.requests) == load.STEPS == 120
    assert picture.points.requests[:2] == [1, 1]
    assert picture.requests == 2
    assert picture.points.at == STARTED
    # A second later it is gone, and the window begins a step later.
    picture = measured.picture(600.0, 0.0)
    assert len(picture.points.requests) == 120
    assert picture.points.requests[0] == 1
    assert picture.requests == 1
    assert picture.points.at == STARTED + timedelta(seconds=5)
    picture = measured.picture(605.0, 0.0)
    assert picture.requests == 0
    assert picture.points.at == STARTED + timedelta(seconds=10)


def test_a_gap_with_no_request_is_steps_in_which_nothing_was_answered() -> None:
    measured = meter()
    answer(measured, 1.0, 0.010)
    answer(measured, 61.0, 0.010)
    picture = measured.picture(62.0, 0.0)
    assert picture.points.requests == [1, *[0] * 11, 1]
    assert picture.points.average_ms[1:12] == [None] * 11
    assert picture.points.busy == [0] * 13


def test_the_processor_time_of_a_gap_is_spread_evenly_over_it() -> None:
    measured = meter()
    # Nothing asks for twenty seconds, in which the process used ten of the processor.
    picture = measured.picture(20.0, 10.0)
    assert picture.points.cpu_percent[:4] == pytest.approx([50.0] * 4)
    assert picture.cpu_percent.average == pytest.approx(50.0)
    # Then two and a half seconds flat out: the step under way is at 100%.
    picture = measured.picture(22.5, 12.5)
    assert picture.points.cpu_percent == pytest.approx([50.0, 50.0, 50.0, 50.0, 100.0])
    assert picture.cpu_percent.low == pytest.approx(50.0)
    # The lowest and the highest are of whole steps: the one under way is not compared.
    assert picture.cpu_percent.high == pytest.approx(50.0)
    assert picture.cpu_percent.average == pytest.approx(50.0)


def test_the_step_under_way_has_no_share_until_a_second_of_it_has_passed() -> None:
    measured = meter()
    assert measured.picture(5.5, 2.0).points.cpu_percent[-1] is None
    assert measured.picture(6.0, 2.5).points.cpu_percent[-1] == pytest.approx(
        (2.0 * 0.5 / 5.5 + 0.5) / 1.0 * 100
    )


def test_a_gap_longer_than_the_window_leaves_nothing_of_before() -> None:
    measured = meter()
    answer(measured, 1.0, 0.010)
    token = measured.began(2.0, 0.0, measured=True)
    # An hour in which nothing asked, and the process used a tenth of the processor.
    picture = measured.picture(3602.0, 360.0)
    assert picture.requests == 0
    assert len(picture.points.requests) == 120
    assert picture.points.at == STARTED + timedelta(seconds=3600 - 595)
    assert picture.points.cpu_percent[:-1] == pytest.approx([10.0] * 119)
    # What was in flight before it still is.
    assert (picture.in_flight, picture.oldest_ms) == (1, pytest.approx(3_600_000.0))
    measured.ended(token, 3603.0, 360.0, status=200)
    assert measured.picture(3603.0, 360.0).requests == 1


def test_a_clock_that_went_back_changes_nothing() -> None:
    measured = meter()
    answer(measured, 10.0, 1.0, cpu=2.0)
    # Neither the time nor the processor time is taken as less than it was.
    answer(measured, 3.0, 0.0, cpu=1.0)
    picture = measured.picture(4.0, 0.0)
    assert picture.points.requests == [0, 0, 2]
    assert picture.cpu_percent.average == pytest.approx(20.0)


# --- the requests in flight ----------------------------------------------------------


def test_the_requests_in_flight_are_counted_but_for_the_one_that_asks() -> None:
    measured = meter()
    first = measured.began(1.0, 0.0, measured=True)
    second = measured.began(3.0, 0.0, measured=False)
    asks = measured.began(4.0, 0.0, measured=True)
    picture = measured.picture(4.0, 0.0, but=asks)
    assert (picture.in_flight, picture.oldest_ms) == (2, pytest.approx(3000.0))
    assert measured.picture(4.0, 0.0).in_flight == 3
    measured.ended(first, 5.0, 0.0, status=200)
    measured.ended(second, 5.0, 0.0, status=200)
    # Ending a request twice counts it once.
    measured.ended(second, 5.0, 0.0, status=200)
    picture = measured.picture(5.0, 0.0, but=asks)
    assert (picture.in_flight, picture.oldest_ms, picture.requests) == (0, None, 2)


# --- how long requests take ----------------------------------------------------------


def said(reading: load.Reading) -> tuple[str, tuple[str, ...], str]:
    """Return the health a reading says, the measures it stands on and what is refused."""
    return reading.health, reading.because, reading.refusing


def test_a_percentile_is_one_of_the_times() -> None:
    assert load.percentile([], 95) is None
    assert load.percentile([7.0], 95) == 7.0
    times = [float(n) for n in range(1, 101)]
    # The k-th longest, k being what the percentile leaves above it, rounded up.
    assert [load.percentile(times, percent) for percent in (50, 95, 99)] == [51.0, 96.0, 100.0]
    # Of twenty or fewer the 95th is the longest; of twenty-one the second longest.
    assert load.percentile(times[:5], 95) == 5.0
    assert load.percentile(times[:20], 95) == 20.0
    assert load.percentile(times[:21], 95) == 20.0
    assert load.percentile(times[:40], 95) == 39.0
    assert load.percentile(times[:41], 95) == 39.0
    assert load.percentile(times[:60], 95) == 58.0
    assert load.percentile(times[:20], 99) == 20.0
    assert load.percentile(times[:4], 50) == 3.0


def slow_among(quick: int, *slow_ms: float, ceiling: Ceiling = SLOW) -> load.Reading:
    """Return what a meter reads of so many quick answers and some slow ones, all come
    at once, a moment after the last of them was given."""
    measured = meter(ceiling)
    at_once(measured, 0.0, [*[10.0] * quick, *slow_ms])
    return measured.reading(max(slow_ms, default=0.0) / 1000 + 1.0, 0.0)


def test_with_no_request_there_is_no_measure_of_time_and_the_health_is_good() -> None:
    reading = meter(SLOW).reading(1.0, 0.0)
    assert (reading.response_ms, reading.requests) == (None, 0)
    assert said(reading) == (load.GOOD, (), load.NOTHING)


def test_one_slow_answer_among_five_is_the_colour_and_refuses_nothing() -> None:
    # On a quiet server one slow page is what a person met: the measure is the slowest.
    for slow_ms, health in ((500.0, load.SLOW), (800.0, load.VERY_SLOW), (5000.0, load.BUSY)):
        reading = slow_among(4, slow_ms)
        assert (reading.response_ms, reading.requests) == (pytest.approx(slow_ms), 5)
        # Five requests are no load: nothing is refused, whatever the colour.
        assert said(reading) == (health, (load.RESPONSE,), load.NOTHING)


def test_one_slow_answer_among_twenty_is_the_colour_and_refuses_nothing() -> None:
    # Of twenty the percentile is the slowest of them, one request alone: the colour is
    # its, and no read is refused for one answer.
    for slow_ms, health in ((500.0, load.SLOW), (800.0, load.VERY_SLOW), (5000.0, load.BUSY)):
        reading = slow_among(19, slow_ms)
        assert (reading.response_ms, reading.requests) == (pytest.approx(slow_ms), 20)
        assert (reading.reads_ms, reading.reads) == (pytest.approx(slow_ms), 20)
        assert said(reading) == (health, (load.RESPONSE,), load.NOTHING)


def test_one_slow_answer_among_twenty_one_is_not_the_measure_and_two_refuse_by_it() -> None:
    # Of twenty-one the measure is the second slowest: one may take as long as it likes.
    reading = slow_among(20, 5000.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(10.0), 21)
    assert said(reading) == (load.GOOD, (), load.NOTHING)
    # Two slow among twenty-one are the measure, and there are reads enough to refuse.
    for slow_ms, health, refusing in (
        (500.0, load.SLOW, load.NOTHING),
        (800.0, load.VERY_SLOW, load.THE_LONG),
        (2000.0, load.BUSY, load.THE_READS),
    ):
        reading = slow_among(19, slow_ms, 5000.0)
        assert (reading.reads_ms, reading.reads) == (pytest.approx(slow_ms), 21)
        assert said(reading) == (health, (load.RESPONSE,), refusing)
    # And of sixty the third: two past the ceiling are not, three are.
    assert slow_among(58, 2000.0, 5000.0).health == load.GOOD
    assert said(slow_among(57, 1500.0, 2000.0, 5000.0)) == (
        load.BUSY,
        (load.RESPONSE,),
        load.THE_READS,
    )


def test_a_single_request_in_flight_past_the_ceiling_is_busy_and_refuses_nothing() -> None:
    measured = meter(SLOW)
    measured.began(0.0, 0.0, measured=True)
    assert measured.reading(0.5, 0.0).health == load.SLOW
    reading = measured.reading(2.0, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(2000.0), 1)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


def test_what_is_refused_follows_the_reads_from_twenty_one_of_them_on() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [3000.0] * 19)
    reading = measured.picture(4.0, 0.0).reading
    assert reading.response_ms == pytest.approx(3000.0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
    answer(measured, 4.0, 1.5)
    reading = measured.picture(6.0, 0.0).reading
    assert (reading.reads_ms, reading.reads) == (pytest.approx(3000.0), 20)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
    answer(measured, 6.0, 0.5)
    reading = measured.picture(7.0, 0.0).reading
    assert (reading.reads_ms, reading.reads) == (pytest.approx(3000.0), 21)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_READS)


def test_the_wait_of_the_requests_in_flight_is_in_the_percentile() -> None:
    measured = meter(SLOW)
    # Two requests from which nothing comes back, among nineteen quick answers.
    at_once(measured, 0.0, [0.0, 0.0], answered=False)
    at_once(measured, 0.0, [10.0] * 19)
    reading = measured.reading(0.5, 0.0)
    assert reading.response_ms == pytest.approx(500.0)
    assert said(reading) == (load.SLOW, (load.RESPONSE,), load.NOTHING)
    reading = measured.reading(2.5, 0.0)
    assert reading.response_ms == pytest.approx(2500.0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_READS)
    # The nineteen that were answered came longer ago than the measure looks back. Two
    # in flight alone are the colour, and no load; it refused its reads eight seconds
    # ago, and so refuses what is long for two more.
    reading = measured.reading(10.5, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(10_500.0), 2)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_LONG)
    assert said(measured.reading(12.5, 0.0)) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


def test_what_is_long_by_nature_or_apart_is_in_no_measure_of_time() -> None:
    measured = meter(SLOW)
    # Reports and exports of five seconds each, and one still being worked out.
    at_once(measured, 0.0, [0.0], counted=False, answered=False)
    at_once(measured, 0.0, [5000.0] * 20, counted=False)
    picture = measured.picture(9.0, 0.0)
    assert (picture.reading.response_ms, picture.reading.requests) == (None, 0)
    assert picture.reading.health == load.GOOD
    assert picture.percentiles == load.Percentiles(None, None, None)
    assert picture.bands == (0, 0, 0, 0)
    assert picture.points.p50_ms == picture.points.p95_ms == [None, None]
    # They are counted, and in the times of the steps, all the same.
    assert (picture.requests, picture.ok) == (20, 20)
    assert picture.response_ms.high == pytest.approx(5000.0)
    assert picture.points.high_ms == [None, pytest.approx(5000.0)]
    assert (picture.in_flight, picture.oldest_ms) == (1, pytest.approx(9000.0))
    # Among twenty quick reads they change nothing of what the reads say.
    at_once(measured, 9.0, [10.0] * 20)
    reading = measured.picture(9.5, 0.0).reading
    assert reading.response_ms == pytest.approx(10.0)
    assert said(reading) == (load.GOOD, (), load.NOTHING)


def test_only_the_requests_that_came_in_the_last_while_are_in_the_percentile() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [800.0] * 20)
    assert measured.reading(3.0, 0.0).health == load.VERY_SLOW
    at_once(measured, 12.0, [10.0] * 20)
    # At 12.5 the twenty that came at 0 are out, and the twenty quick ones are in.
    reading = measured.reading(12.5, 0.0)
    assert reading.response_ms == pytest.approx(10.0)
    assert said(reading) == (load.GOOD, (), load.NOTHING)


def test_a_request_leaves_the_measure_a_while_after_it_came_not_after_its_answer() -> None:
    measured = meter(SLOW)
    # Twenty that came at 0 and one at 1, all answered at 8.
    tokens = at_once(measured, 0.0, [0.0] * 20, answered=False)
    tokens += at_once(measured, 1.0, [0.0], answered=False)
    for token in tokens:
        measured.ended(token, 8.0, 0.0, status=200)
    assert measured.reading(9.0, 0.0).response_ms == pytest.approx(8000.0)
    # At 10.5 the twenty that came at 0 are out, though answered two and a half seconds
    # ago: the measure is of the one that came at 1.
    reading = measured.reading(10.5, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(7000.0), 1)
    # And one in flight is in it however long ago it came.
    at_once(measured, 14.0, [0.0] * 20, answered=False)
    assert measured.reading(74.0, 0.0).response_ms == pytest.approx(60_000.0)


def test_requests_from_which_nothing_comes_back_are_a_busy_server_for_as_long() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [0.0] * 21, answered=False)
    assert measured.reading(0.5, 0.0).health == load.SLOW
    assert measured.reading(2.0, 0.0).health == load.BUSY
    assert said(measured.reading(3600.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.THE_READS)


def test_a_few_requests_left_in_flight_are_the_colour_and_no_load() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [0.0] * 21, answered=False)
    assert measured.reading(2.0, 0.0).refusing == load.THE_READS
    # Fifteen of them are answered. Six in flight are load with them for as long as
    # the fifteen are in the measure, and none alone.
    for token in range(1, 16):
        measured.ended(token, 3.0, 0.0, status=200)
    assert measured.reading(9.0, 0.0).refusing == load.THE_READS
    reading = measured.reading(12.0, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(12_000.0), 6)
    # Red still, by the six that wait. It refused its reads three seconds ago, and so
    # refuses what is long; ten seconds after it last did, nothing.
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_LONG)
    assert said(measured.reading(19.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


# --- what is refused is decided by the reads alone -----------------------------------


def served(measured: Meter, seconds: int, save_every: int) -> tuple[int, int, set[str]]:
    """Three reads of ten milliseconds a second for so long, and beside them a save
    every so many seconds that waits three and a half for another to be stored. A read
    that the server refuses is refused. Return how many reads were answered and how
    many refused, and every health that was said."""
    events: list[tuple[float, int, str, int]] = []
    for second in range(seconds):
        events += [(second + third / 3, 2, "read", 0) for third in range(3)]
        if second % save_every == 0:
            events += [(float(second), 1, "save", second), (second + 3.5, 0, "saved", second)]
    saves: dict[int, int] = {}
    answered = refused = 0
    healths: set[str] = set()
    for at, _, what, which in sorted(events):
        if what == "save":
            saves[which] = measured.began(at, 0.0, measured=True, kept=True)
        elif what == "saved":
            measured.ended(saves.pop(which), at, 0.0, status=200)
        else:
            reading = measured.reading(at, 0.0)
            healths.add(reading.health)
            if load.refuses(reading.refusing, load.READ):
                measured.turned_away(at, 0.0)
                refused += 1
            else:
                answer(measured, at, 0.010)
                answered += 1
    return answered, refused, healths


def test_saves_that_wait_for_another_refuse_no_read() -> None:
    """The first sequence of the second review: something holds the one writer, and a
    save every four seconds waits three and a half. The mark is red for it, and no read
    is refused: no read waits for a writer."""
    answered, refused, healths = served(meter(Ceiling()), 300, save_every=4)
    assert (answered, refused) == (900, 0)
    assert load.BUSY in healths


def test_saves_that_all_wait_refuse_no_read_and_are_red_for_as_long() -> None:
    """The second: a save a second, each waiting three and a half. Red without end, as
    it is; and every read is answered."""
    measured = meter(Ceiling())
    answered, refused, healths = served(measured, 300, save_every=1)
    assert (answered, refused) == (900, 0)
    assert load.BUSY in healths
    reading = measured.reading(303.0, 0.0)
    assert reading.response_ms == pytest.approx(3500.0)
    assert reading.reads_ms == pytest.approx(10.0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


def test_changes_that_are_slow_with_no_read_at_all_refuse_nothing() -> None:
    measured = meter(Ceiling())
    at_once(measured, 0.0, [3500.0] * 25, kept=True)
    reading = measured.reading(4.0, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(3500.0), 25)
    assert (reading.reads_ms, reading.reads) == (None, 0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


def test_the_health_is_never_better_than_what_is_refused_says() -> None:
    measured = meter(Ceiling())
    # Two slow reads among twenty-one, and a hundred quick saves beside them: of all of
    # them the percentile is a quarter of a second, and of the reads it is not.
    reads = at_once(measured, 0.0, [0.0] * 21, answered=False)
    at_once(measured, 0.0, [10.0] * 100, kept=True)
    for token in reads[:19]:
        measured.ended(token, 0.25, 0.0, status=200)
    for token in reads[19:]:
        measured.ended(token, 3.5, 0.0, status=200)
    reading = measured.reading(4.0, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(250.0), 121)
    assert (reading.reads_ms, reading.reads) == (pytest.approx(3500.0), 21)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_READS)


def test_reads_that_are_slow_are_refused_and_refused_do_not_hold_the_server_red() -> None:
    measured = meter(Ceiling())
    at_once(measured, 0.0, [3500.0] * 25)
    told = {}
    answered = refused = 0
    for second in range(4, 100):
        reading = measured.reading(float(second), 0.0)
        told[second] = (reading.health, reading.refusing)
        if load.refuses(reading.refusing, load.READ):
            measured.turned_away(float(second), 0.0)
            refused += 1
        else:
            answer(measured, float(second), 0.010)
            answered += 1
    # Refused for as long as the slow reads are reads that came in the last half minute.
    assert {told[second] for second in range(4, 30)} == {(load.BUSY, load.THE_READS)}
    assert refused == 26
    # They are out half a minute after they came, and with them the red: what was
    # refused is in no measure, and holds nothing. What is long waits a window more.
    assert {told[second] for second in range(30, 59)} == {(load.VERY_SLOW, load.THE_LONG)}
    assert {told[second] for second in range(59, 100)} == {(load.GOOD, load.NOTHING)}
    assert answered == 70


def test_slow_reads_and_slow_saves_together_and_then_the_saves_alone() -> None:
    measured = meter(Ceiling())
    reads = at_once(measured, 0.0, [0.0] * 25, answered=False)
    saves = at_once(measured, 0.0, [0.0] * 25, answered=False, kept=True)
    for token in (*reads, *saves):
        measured.ended(token, 3.5, 0.0, status=200)
    # Both are slow: the reads are refused, by themselves.
    reading = measured.reading(20.0, 0.0)
    assert (reading.requests, reading.reads) == (50, 25)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_READS)
    # Half a minute after they came all are out. It refused its reads eleven seconds
    # ago: what is long is refused, and nothing else.
    assert said(measured.reading(31.0, 0.0)) == (load.VERY_SLOW, (load.RESPONSE,), load.THE_LONG)
    # Slow saves again, and no read: red by them, and they refuse nothing; what is long
    # is refused until half a minute after the reads last were.
    at_once(measured, 31.0, [3500.0] * 25, kept=True)
    assert said(measured.reading(35.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.THE_LONG)
    reading = measured.reading(50.0, 0.0)
    assert (reading.reads_ms, reading.reads) == (None, 0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


# --- the health as an answer begins --------------------------------------------------


def test_an_answer_that_was_slow_says_so_itself() -> None:
    """The case of the second review: one request on a server that has seen nothing,
    answered after three and a third seconds."""
    measured = meter(Ceiling())
    token = measured.began(0.0, 0.0, measured=True)
    assert said(measured.reading(0.0, 0.0)) == (load.GOOD, (), load.NOTHING)
    reading = measured.answering(token, 3.3, 0.0)
    assert (reading.response_ms, reading.requests) == (pytest.approx(3300.0), 1)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)


def test_a_quick_answer_is_given_what_is_held_in_memory() -> None:
    measured = meter(Ceiling())
    token = measured.began(0.0, 0.0, measured=True)
    held = measured.reading(0.0, 0.0)
    # Within the second, and its own time in no higher band than the health held.
    assert measured.answering(token, 0.5, 0.0) is held
    assert measured.answering(token, 0.99, 0.0) is held
    # A second on, the measures are read again as for any request.
    assert measured.answering(token, 1.0, 0.0) is not held


def test_an_answer_whose_own_time_is_in_a_higher_band_is_read_again_for() -> None:
    measured = meter(Ceiling())
    token = measured.began(0.0, 0.0, measured=True)
    held = measured.reading(0.95, 0.0)
    assert held.health == load.GOOD
    # A tenth of a second later it has taken more than a second: slow, by itself.
    reading = measured.answering(token, 1.05, 0.0)
    assert reading is not held
    assert said(reading) == (load.SLOW, (load.RESPONSE,), load.NOTHING)
    # What is in no measure is given what is held, however long it took.
    report = measured.began(1.05, 0.0, measured=False, long=True)
    held = measured.reading(9.5, 0.0)
    assert measured.answering(report, 9.9, 0.0) is held
    # And so is a request that is gone.
    assert measured.answering(12345, 9.9, 0.0) is held


# --- a stall, and coming back from it -------------------------------------------------


def asked_every_five_seconds(measured: Meter, since: int, until: int) -> dict[int, tuple]:
    """Have About ask every five seconds, as the page does, and return the health it
    was told at each, with what was refused. It stands apart: answered at once, and in
    no measure."""
    told = {}
    for at in range(since, until + 1, 5):
        token = measured.began(float(at), 0.0, measured=False)
        reading = measured.picture(float(at), 0.0, but=token).reading
        told[at] = (reading.health, reading.refusing)
        measured.ended(token, float(at), 0.0, status=200)
    return told


def stall(measured: Meter, requests: int, until: int) -> dict[int, tuple]:
    """Some reads come at once and are all answered twenty seconds later, after which
    nothing but About asks. Return what About was told every five seconds."""
    tokens = [measured.began(0.0, 0.0, measured=True) for _ in range(requests)]
    told = asked_every_five_seconds(measured, 5, 20)
    for token in tokens:
        measured.ended(token, 20.0, 0.0, status=200)
    return told | asked_every_five_seconds(measured, 25, until)


RED_AND_REFUSING = (load.BUSY, load.THE_READS)
RED_ALONE = (load.BUSY, load.NOTHING)
ORANGE_AFTER_RED = (load.VERY_SLOW, load.THE_LONG)
GREEN = (load.GOOD, load.NOTHING)


def test_ten_requests_that_stand_for_twenty_seconds_are_red_and_refuse_nothing() -> None:
    """The sequence of the review: ten requests come at 0 and all end at 20, and About
    asks every five seconds. Red while they stand, and for as long as they are requests
    that came in the last half minute; ten are no load, so nothing is refused, and
    nothing is left behind: green within one window of their coming."""
    told = stall(meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30)), 10, 120)
    assert told == {
        # Five seconds of waiting are past three.
        **dict.fromkeys((5, 10, 15, 20), RED_ALONE),
        # Answered at 20, they are still requests that came in the last half minute.
        25: RED_ALONE,
        # Half a minute after they came they are out, and the server is what it is: idle.
        **dict.fromkeys(range(30, 125, 5), GREEN),
    }


def test_thirty_requests_that_stand_are_load_and_good_again_within_two_windows() -> None:
    """The same with thirty requests, which are load: the reads are refused while it is
    red; what is long for half a minute after it last refused the reads; and green
    from there, on an idle server."""
    told = stall(meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30)), 30, 120)
    assert told == {
        **dict.fromkeys((5, 10, 15, 20, 25), RED_AND_REFUSING),
        # Half a minute after they came they are out: no request, and red a moment ago.
        **dict.fromkeys((30, 35, 40, 45, 50), ORANGE_AFTER_RED),
        # Half a minute after it last refused its reads, at 25, it is green.
        **dict.fromkeys(range(55, 125, 5), GREEN),
    }
    # Good again within one window of the last arrival and the one window after red.
    assert min(at for at, said_then in told.items() if said_then == GREEN) <= 60


def test_a_stall_that_is_over_with_the_longest_while_the_setting_takes() -> None:
    told = stall(meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=300)), 30, 700)
    # The thirty stay in the measure for five minutes after they came; then what is
    # long is refused for five minutes more; and then it is green.
    assert told == {
        **dict.fromkeys(range(5, 300, 5), RED_AND_REFUSING),
        **dict.fromkeys(range(300, 595, 5), ORANGE_AFTER_RED),
        **dict.fromkeys(range(595, 705, 5), GREEN),
    }


def test_after_refusing_its_reads_the_server_refuses_what_is_long_for_a_while() -> None:
    measured = meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30))
    at_once(measured, 0.0, [3500.0] * 21)
    assert said(measured.reading(4.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.THE_READS)
    # Quick answers from there: of forty-one the measure is the third slowest, still slow.
    at_once(measured, 4.0, [10.0] * 20)
    assert measured.reading(20.0, 0.0).refusing == load.THE_READS
    # The slow ones are out at 30, and what is left is quick. It last refused its reads
    # at 20: what is long does not come back with the reads, but half a minute after.
    at_once(measured, 30.0, [10.0] * 20)
    reading = measured.reading(31.0, 0.0)
    assert reading.response_ms == pytest.approx(10.0)
    assert said(reading) == (load.VERY_SLOW, (load.RESPONSE,), load.THE_LONG)
    assert measured.reading(49.0, 0.0).health == load.VERY_SLOW
    assert said(measured.reading(50.0, 0.0)) == (load.GOOD, (), load.NOTHING)


def test_a_red_that_refused_nothing_leaves_nothing_behind() -> None:
    measured = meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30))
    at_once(measured, 0.0, [3500.0] * 5)
    assert said(measured.reading(4.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
    assert said(measured.reading(29.0, 0.0)) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
    # The five are out half a minute after they came, and it is green at once.
    assert said(measured.reading(30.0, 0.0)) == (load.GOOD, (), load.NOTHING)


def test_nothing_else_of_before_is_remembered() -> None:
    measured = meter(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30))
    # Very slow for an hour is very slow, and never busy for having lasted.
    for minute in range(60):
        at_once(measured, minute * 60.0, [2500.0] * 21)
        assert said(measured.reading(minute * 60.0 + 3, 0.0)) == (
            load.VERY_SLOW,
            (load.RESPONSE,),
            load.THE_LONG,
        )
    # And good the moment the percentile is: it was not busy.
    at_once(measured, 3600.0, [10.0] * 20)
    assert measured.reading(3601.0, 0.0).health == load.GOOD


# --- a request whose body has not all come -------------------------------------------


def test_requests_whose_body_never_comes_hold_nothing_busy() -> None:
    measured = meter(Ceiling())
    # Twenty senders give the headers of a sign-in and no body.
    for _ in range(20):
        measured.began(0.0, 0.0, measured=True, whole=False)
    for at in range(5, 3605, 5):
        picture = measured.picture(float(at), 0.0)
        assert picture.reading.health == load.GOOD, at
        assert picture.reading.response_ms is None
        # They are in flight, which they are, and have no age.
        assert (picture.in_flight, picture.oldest_ms) == (20, None)
    # The same twenty with nothing more to come would be a server that answers nothing.
    stuck = meter(Ceiling())
    at_once(stuck, 0.0, [0.0] * 20, answered=False)
    assert stuck.picture(3600.0, 0.0).reading.health == load.BUSY
    assert stuck.picture(3600.0, 0.0).oldest_ms == pytest.approx(3_600_000.0)


def test_the_time_of_a_request_begins_when_the_server_has_the_whole_of_it() -> None:
    measured = meter(SLOW)
    # An upload that takes its sender nine seconds, and the server a fifth of one.
    token = measured.began(0.0, 0.0, measured=True, whole=False)
    measured.heard(token, 3.0, 0.0, whole=False)
    measured.heard(token, 6.0, 0.0, whole=False)
    assert measured.picture(8.0, 0.0).oldest_ms is None
    measured.heard(token, 9.0, 0.0, whole=True)
    # Whole, it waits for the server, from there.
    assert measured.picture(9.125, 0.0).oldest_ms == pytest.approx(125.0)
    # A piece told again changes nothing of one that is whole.
    measured.heard(token, 9.2, 0.0, whole=True)
    measured.ended(token, 9.25, 0.0, status=201)
    picture = measured.picture(9.25, 0.0)
    assert picture.response_ms.low == picture.response_ms.high == pytest.approx(250.0)
    assert picture.percentiles.p95 == pytest.approx(250.0)
    # Twenty more of them at once, and the measure is of the server's part alone.
    slow = [measured.began(9.5, 0.0, measured=True, whole=False) for _ in range(20)]
    for token in slow:
        measured.heard(token, 19.0, 0.0, whole=True)
    for token in slow:
        measured.ended(token, 19.25, 0.0, status=201)
    reading = measured.picture(19.5, 0.0).reading
    assert reading.response_ms == pytest.approx(250.0)
    assert said(reading) == (load.GOOD, (), load.NOTHING)


def test_an_answer_given_before_the_body_came_is_timed_from_what_did_come() -> None:
    measured = meter()
    # Not signed in: answered at once, with nothing of the body read.
    refused = measured.began(0.0, 0.0, measured=True, whole=False)
    measured.ended(refused, 0.25, 0.0, status=401)
    # A sender that went away after its second piece.
    gone = measured.began(1.0, 0.0, measured=True, whole=False)
    measured.heard(gone, 3.0, 0.0, whole=False)
    measured.ended(gone, 3.5, 0.0, status=500)
    picture = measured.picture(4.0, 0.0)
    assert picture.response_ms.low == pytest.approx(250.0)
    assert picture.response_ms.high == pytest.approx(500.0)
    assert (picture.not_accepted, picture.failed, picture.in_flight) == (1, 1, 0)


# --- the percentiles and the bands of the ten minutes --------------------------------


def test_the_percentiles_of_the_ten_minutes_and_of_each_step() -> None:
    measured = meter(Ceiling())
    # A report of four seconds among them is in no percentile.
    report = measured.began(0.0, 0.0, measured=False)
    at_once(measured, 0.0, [500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0])
    measured.ended(report, 4.0, 0.0, status=200)
    picture = measured.picture(4.5, 0.0)
    assert picture.percentiles == load.Percentiles(p50=2000.0, p95=3500.0, p99=3500.0)
    assert (picture.points.p50_ms, picture.points.p95_ms) == ([2000.0], [3500.0])
    assert picture.response_ms.high == 4000.0
    # A later step has its own, and a step of nothing in the measure has none.
    at_once(measured, 10.0, [250.0, 250.0, 250.0])
    picture = measured.picture(11.0, 0.0)
    assert picture.points.p50_ms == [2000.0, None, 250.0]
    assert picture.points.p95_ms == [3500.0, None, 250.0]
    assert picture.percentiles == load.Percentiles(p50=1500.0, p95=3500.0, p99=3500.0)
    # They are of the ten minutes: ten minutes on, of nothing.
    assert measured.picture(611.0, 0.0).percentiles == load.Percentiles(None, None, None)


def test_the_bands_of_time_and_their_bounds_follow_the_setting() -> None:
    measured = meter(Ceiling())
    report = measured.began(0.0, 0.0, measured=False)
    at_once(measured, 0.0, [500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0])
    measured.ended(report, 4.0, 0.0, status=200)
    picture = measured.picture(4.5, 0.0)
    # Under a third of the ceiling, from it to under two thirds, to the ceiling, past it.
    assert picture.bounds_ms == (1000.0, 2000.0, 3000.0)
    assert picture.bands == (1, 2, 3, 1)
    # Another ceiling, and the same requests are counted by its thirds.
    measured.hold(Ceiling(response_ms=1500))
    picture = measured.picture(4.5, 0.0)
    assert picture.bounds_ms == (500.0, 1000.0, 1500.0)
    assert picture.bands == (0, 1, 2, 4)
    measured.hold(Ceiling(response_ms=1000))
    assert measured.picture(4.5, 0.0).bounds_ms == pytest.approx(
        (333.333, 666.667, 1000.0), abs=0.001
    )
    # A measure that is not looked at has the bands of the ceiling unless set.
    for ceiling in (Ceiling(response_ms=0), load.NO_CEILING):
        measured.hold(ceiling)
        picture = measured.picture(4.5, 0.0)
        assert (picture.bounds_ms, picture.bands) == ((1000.0, 2000.0, 3000.0), (1, 2, 3, 1))


def test_the_times_of_a_step_are_kept_up_to_its_first_thousand() -> None:
    measured = meter()
    at_once(measured, 0.0, [*[10.0] * 1000, *[20.0] * 5])
    picture = measured.picture(1.0, 0.0)
    assert (picture.requests, sum(picture.bands)) == (1005, 1000)
    assert picture.percentiles == load.Percentiles(p50=10.0, p95=10.0, p99=10.0)
    assert picture.response_ms.high == pytest.approx(20.0)


# --- the health of the server, and what it refuses -----------------------------------


@pytest.mark.parametrize(
    ("took_ms", "health", "refusing"),
    [
        (500.0, load.GOOD, load.NOTHING),
        (999.0, load.GOOD, load.NOTHING),
        (1000.0, load.SLOW, load.NOTHING),
        (1999.0, load.SLOW, load.NOTHING),
        (2000.0, load.VERY_SLOW, load.THE_LONG),
        (3000.0, load.VERY_SLOW, load.THE_LONG),
        (3001.0, load.BUSY, load.THE_READS),
        (9000.0, load.BUSY, load.THE_READS),
    ],
)
def test_the_health_is_how_long_requests_take_against_the_thirds_of_the_ceiling(
    took_ms: float, health: load.Health, refusing: load.Refusing
) -> None:
    measured = meter(Ceiling())
    at_once(measured, 0.0, [took_ms] * 21)
    reading = measured.reading(10.0, 0.0)
    # Nothing is refused until orange; what is long at orange; every read at red.
    assert said(reading) == (health, () if health == load.GOOD else (load.RESPONSE,), refusing)


def test_the_colour_is_the_same_with_few_requests_and_nothing_is_refused_for_it() -> None:
    for took_ms, health in ((500.0, load.GOOD), (2500.0, load.VERY_SLOW), (3500.0, load.BUSY)):
        measured = meter(Ceiling())
        at_once(measured, 0.0, [took_ms] * 19)
        reading = measured.reading(5.0, 0.0)
        assert (reading.health, reading.refusing) == (health, load.NOTHING), took_ms


def test_the_health_follows_the_ceiling_that_is_set() -> None:
    measured = meter(Ceiling(response_ms=600, cpu_percent=0))
    at_once(measured, 0.0, [250.0] * 21)
    assert measured.reading(1.0, 0.0).health == load.SLOW
    measured.hold(Ceiling(response_ms=6000))
    assert measured.reading(1.0, 0.0).health == load.GOOD
    measured.hold(Ceiling(response_ms=300))
    assert said(measured.reading(1.0, 0.0)) == (load.VERY_SLOW, (load.RESPONSE,), load.THE_LONG)


def test_the_processor_past_its_ceiling_is_very_slow_at_the_least_and_never_busy() -> None:
    measured = meter(Ceiling(response_ms=3000, cpu_percent=50, over_seconds=10))
    assert said(measured.reading(10.0, 4.0)) == (load.GOOD, (), load.NOTHING)
    reading = measured.reading(20.0, 13.0)
    assert reading.cpu_percent == pytest.approx(90.0)
    assert said(reading) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    # Three processors' worth is no more than very slow: the reads go on.
    assert said(measured.reading(30.0, 43.0)) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    # And good as soon as it is under: the processor leaves nothing to come back from.
    assert said(measured.reading(40.0, 43.0)) == (load.GOOD, (), load.NOTHING)


def test_the_processor_refuses_what_is_long_whatever_the_count_of_requests() -> None:
    measured = meter(Ceiling(response_ms=3000, cpu_percent=50, over_seconds=10))
    at_once(measured, 0.0, [10.0] * 4)
    reading = measured.reading(9.0, 8.0)
    assert reading.requests == 4
    assert said(reading) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    # And with four slow requests the colour is theirs, and what is refused its own.
    at_once(measured, 9.0, [3500.0] * 4)
    assert said(measured.reading(13.0, 12.0)) == (load.BUSY, (load.RESPONSE,), load.THE_LONG)


def test_the_measures_the_health_stands_on_are_named() -> None:
    hot = 9.0
    for took_ms, health, because in (
        # Slow by time, and very slow by the processor: it stands on the processor.
        (1500.0, load.VERY_SLOW, (load.PROCESSOR,)),
        # Very slow by both.
        (2500.0, load.VERY_SLOW, (load.RESPONSE, load.PROCESSOR)),
        # Busy by time, which the processor never is.
        (3500.0, load.BUSY, (load.RESPONSE,)),
    ):
        measured = meter(Ceiling(response_ms=3000, cpu_percent=50, over_seconds=10))
        at_once(measured, 0.0, [took_ms] * 20)
        reading = measured.reading(9.0, hot)
        assert (reading.health, reading.because) == (health, because), took_ms


def test_a_measure_at_its_ceiling_is_not_past_it() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 5.0).health == load.GOOD
    assert measured.reading(20.0, 10.5).health == load.VERY_SLOW


# --- a ceiling of 0 -------------------------------------------------------------------


def test_with_no_ceiling_of_time_nothing_is_refused_for_it_and_the_health_is_said() -> None:
    for ceiling in (load.NO_CEILING, Ceiling(response_ms=0, cpu_percent=95)):
        measured = meter(ceiling)
        at_once(measured, 0.0, [1500.0] * 20)
        assert said(measured.reading(2.0, 0.0)) == (load.SLOW, (load.RESPONSE,), load.NOTHING)
        at_once(measured, 2.0, [2500.0] * 20)
        reading = measured.reading(5.0, 0.0)
        assert said(reading) == (load.VERY_SLOW, (load.RESPONSE,), load.NOTHING)
        # Past three seconds the mark is red, by the bands of the ceiling unless set.
        at_once(measured, 5.0, [3500.0] * 20)
        reading = measured.reading(9.0, 0.0)
        assert reading.response_ms == pytest.approx(3500.0)
        assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
        # It refused nothing, and so nothing is left of it once they are out.
        assert said(measured.reading(38.0, 0.0)) == (load.GOOD, (), load.NOTHING)


def test_with_no_ceiling_of_time_the_processor_still_refuses_what_is_long() -> None:
    measured = meter(Ceiling(response_ms=0, cpu_percent=50, over_seconds=10))
    at_once(measured, 0.0, [3500.0] * 20)
    reading = measured.reading(9.0, 8.0)
    # Red by time, which refuses nothing here; the processor refuses what is long.
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.THE_LONG)


def test_a_processor_at_0_is_not_looked_at() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [10.0] * 20)
    # Flat out, and its ceiling is 0.
    reading = measured.picture(9.0, 27.0).reading
    assert reading.cpu_percent == pytest.approx(270.0)
    assert said(reading) == (load.GOOD, (), load.NOTHING)


def test_both_at_0_is_no_ceiling_and_nothing_is_ever_refused() -> None:
    assert load.NO_CEILING.none
    assert not SLOW.none
    assert not HOT.none
    measured = meter(Ceiling(response_ms=0, cpu_percent=0, over_seconds=10))
    at_once(measured, 0.0, [4000.0] * 20)
    reading = measured.reading(9.0, 9.0)
    assert reading.response_ms == pytest.approx(4000.0)
    assert reading.cpu_percent == pytest.approx(90.0)
    assert said(reading) == (load.BUSY, (load.RESPONSE,), load.NOTHING)
    # However long it lasts.
    for second in range(10, 120):
        assert measured.reading(float(second), float(second) * 3).refusing == load.NOTHING
    assert measured.picture(120.0, 360.0).reading.refusing == load.NOTHING


# --- the processor -------------------------------------------------------------------


def test_the_processor_is_the_share_of_one_used_over_the_last_while() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 4.0).cpu_percent == pytest.approx(40.0)
    # Six of the next ten seconds: past the ceiling.
    reading = measured.reading(20.0, 10.0)
    assert reading.cpu_percent == pytest.approx(60.0)
    assert said(reading) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    # Only the last ten seconds are read: seven and a half of them idle.
    reading = measured.reading(27.5, 10.0)
    assert reading.cpu_percent == pytest.approx(15.0)
    assert reading.health == load.GOOD


def test_a_server_that_just_started_used_nothing_before() -> None:
    measured = meter(HOT)
    # Flat out for its first three seconds is three seconds of ten, and in good health.
    reading = measured.reading(3.0, 3.0)
    assert reading.cpu_percent == pytest.approx(30.0)
    assert reading.health == load.GOOD
    assert measured.reading(6.0, 6.0).health == load.VERY_SLOW


def test_the_share_of_the_processor_passes_100_where_threads_work_at_once() -> None:
    # Four threads each in a query use two processors' worth: nothing holds it to 100.
    measured = meter(Ceiling(response_ms=0, cpu_percent=150, over_seconds=10))
    reading = measured.reading(10.0, 12.0)
    assert reading.cpu_percent == pytest.approx(120.0)
    assert reading.health == load.GOOD
    reading = measured.reading(20.0, 32.0)
    assert reading.cpu_percent == pytest.approx(200.0)
    assert said(reading) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    picture = measured.picture(30.0, 52.0)
    assert picture.reading.health == load.VERY_SLOW
    assert picture.points.cpu_percent[:6] == pytest.approx([120.0, 120.0, *[200.0] * 4])
    assert picture.cpu_percent.high == pytest.approx(200.0)
    assert picture.cpu_percent.average == pytest.approx((240.0 + 800.0) / 6)


def test_the_processor_is_read_whatever_the_requests_are() -> None:
    measured = meter(HOT)
    reading = measured.reading(10.0, 9.0)
    assert said(reading) == (load.VERY_SLOW, (load.PROCESSOR,), load.THE_LONG)
    assert reading.response_ms is None


# --- when the measures are read ------------------------------------------------------


def test_the_measures_are_read_once_a_second_at_the_most() -> None:
    measured = meter(HOT)
    first = measured.reading(10.0, 9.0)
    assert first.health == load.VERY_SLOW
    # Within the second the same reading is given, whatever the clocks say meanwhile.
    assert measured.reading(10.9, 0.0) is first
    assert measured.reading(11.0, 9.0) is not first
    # The picture reads afresh, and a request after it is given that reading.
    fresh = measured.picture(11.2, 9.0).reading
    assert measured.reading(11.3, 9.0) is fresh


def test_with_no_ceiling_the_measures_are_read_once_a_second_too() -> None:
    measured = meter()
    first = measured.reading(1.0, 0.0)
    assert measured.reading(1.5, 0.0) is first
    assert measured.reading(2.0, 0.0) is not first


def test_a_ceiling_that_is_given_holds_from_the_next_request() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 9.0).refusing == load.THE_LONG
    measured.hold(Ceiling(response_ms=0, cpu_percent=95, over_seconds=10))
    assert measured.reading(10.1, 9.0).refusing == load.NOTHING
    measured.hold(HOT)
    assert measured.reading(10.2, 9.0).refusing == load.THE_LONG
    measured.hold(load.NO_CEILING)
    assert measured.reading(10.3, 9.0).refusing == load.NOTHING
    measured.hold(HOT)
    assert measured.reading(21.0, 19.0).refusing == load.THE_LONG


# --- the requests that are refused ---------------------------------------------------


def test_a_request_that_is_refused_is_counted_and_is_in_neither_measure() -> None:
    measured = meter(SLOW)
    at_once(measured, 0.0, [2000.0] * 20)
    assert measured.reading(3.0, 0.0).health == load.BUSY
    for _ in range(40):
        measured.turned_away(6.0, 0.0)
    picture = measured.picture(7.0, 0.0)
    assert (picture.requests, picture.ok, picture.busy) == (60, 20, 40)
    assert picture.points.busy == [0, 40]
    assert picture.points.requests == [20, 40]
    # Forty answers at once would have made the percentile nothing: they are not in
    # it, nor in the times of the step, the percentiles or the bands.
    assert picture.reading.response_ms == pytest.approx(2000.0)
    assert picture.reading.health == load.BUSY
    assert picture.response_ms.low == pytest.approx(2000.0)
    assert picture.points.average_ms == [pytest.approx(2000.0), None]
    assert picture.points.p95_ms == [pytest.approx(2000.0), None]
    assert picture.percentiles.p50 == pytest.approx(2000.0)
    assert sum(picture.bands) == 20


def test_a_step_of_nothing_but_requests_refused_has_no_times() -> None:
    measured = meter()
    measured.turned_away(1.0, 0.0)
    picture = measured.picture(2.0, 0.0)
    assert (picture.points.requests, picture.points.busy) == ([1], [1])
    assert picture.points.average_ms == picture.points.high_ms == [None]
    assert picture.response_ms == load.Spread(None, None, None)
    assert picture.percentiles == load.Percentiles(None, None, None)


@pytest.mark.parametrize(
    ("refusing", "kind", "turned_away"),
    [
        (load.NOTHING, load.LONG, False),
        (load.NOTHING, load.READ, False),
        (load.NOTHING, load.KEPT, False),
        (load.NOTHING, load.APART, False),
        (load.THE_LONG, load.LONG, True),
        (load.THE_LONG, load.READ, False),
        (load.THE_LONG, load.KEPT, False),
        (load.THE_LONG, load.APART, False),
        (load.THE_READS, load.LONG, True),
        (load.THE_READS, load.READ, True),
        (load.THE_READS, load.KEPT, False),
        (load.THE_READS, load.APART, False),
    ],
)
def test_what_a_server_turns_away_by_what_it_refuses(
    refusing: load.Refusing, kind: load.Kind, turned_away: bool
) -> None:
    assert load.refuses(refusing, kind) is turned_away


def test_which_kinds_of_request_are_in_the_measure_of_time() -> None:
    assert [load.measured(kind) for kind in (load.LONG, load.READ, load.KEPT, load.APART)] == [
        False,
        True,
        True,
        False,
    ]


def test_the_ceiling_unless_set_and_what_the_meter_keeps() -> None:
    assert Ceiling() == Ceiling(response_ms=3000, cpu_percent=95, over_seconds=30)
    assert (load.WINDOW_SECONDS, load.STEP_SECONDS) == (600, 5)
    assert (load.PERCENTILE, load.FEWEST_REQUESTS) == (95, 21)
    assert load.bounds_of(3000) == load.bounds_of(0) == (1000.0, 2000.0, 3000.0)
    # Nothing is refused until orange; what is long at orange; every read at red.
    assert dict(zip(load.HEALTHS, load.REFUSINGS, strict=True)) == {
        "good": "nothing",
        "slow": "nothing",
        "very_slow": "long",
        "busy": "reads",
    }
    assert load.MOST_OVER_SECONDS * 2 <= load.WINDOW_SECONDS


# --- the slowest requests, and who met what ------------------------------------------

ADA = load.Who("hid-ada", "ada")
IVY = load.Who("hid-ivy", "ivy")
VIC = load.Who("hid-vic", "vic")
COLLECTOR = load.Who("hid-collector", "collector", load.SERVICE)
TAGS = "/api/v1/tags"
REPORT = "/api/v1/reports/summary"


def ask(
    measured: Meter,
    at: float,
    took_ms: float,
    who: load.Who | None = None,
    status: int = 200,
    route: str | None = TAGS,
    kind: load.Kind = load.READ,
) -> None:
    """Have one request of the API come and be answered, by somebody or by nobody known."""
    token = measured.began(at, 0.0, measured=load.measured(kind), long=kind == load.LONG)
    measured.ended(
        token,
        at + took_ms / 1000,
        0.0,
        status=status,
        who=who,
        asked=load.Asked("GET", route, f"request-{at:g}"),
    )


def test_the_slowest_requests_are_listed_the_slowest_first() -> None:
    measured = meter()
    # Fifteen requests ten seconds apart, each slower than the one before.
    for number in range(1, 16):
        ask(measured, number * 10.0, number * 100.0, ADA if number % 2 else None, route=TAGS)
    slowest = measured.picture(160.0, 0.0).slowest
    assert [one.ms for one in slowest] == pytest.approx([100.0 * n for n in range(15, 5, -1)])
    first = slowest[0]
    assert first == load.Slow(
        at=STARTED + timedelta(seconds=150),
        method="GET",
        route=TAGS,
        ms=1500.0,
        status=200,
        request_id="request-150",
        who=ADA,
    )
    # One that nothing verifiable named an account for has nobody.
    assert slowest[1].who is None
    assert slowest[1].request_id == "request-140"


def test_of_two_that_took_as_long_the_one_that_came_first_is_listed_first() -> None:
    measured = meter()
    ask(measured, 1.0, 250.0, IVY)
    ask(measured, 2.0, 500.0, ADA)
    ask(measured, 3.0, 250.0, VIC)
    assert [one.who for one in measured.picture(4.0, 0.0).slowest] == [ADA, IVY, VIC]


def test_the_slowest_leave_with_their_steps_after_ten_minutes() -> None:
    measured = meter()
    ask(measured, 1.0, 500.0, ADA)
    ask(measured, 301.0, 250.0, IVY)
    assert [one.who for one in measured.picture(599.0, 0.0).slowest] == [ADA, IVY]
    assert [one.who for one in measured.picture(600.0, 0.0).slowest] == [IVY]
    assert measured.picture(905.0, 0.0).slowest == []
    assert measured.picture(905.0, 0.0).people == []


def test_a_step_keeps_its_ten_slowest_and_they_are_the_slowest_of_all() -> None:
    measured = meter()
    # Forty requests in one step, and thirty slower ones in another.
    for number in range(40):
        ask(measured, 1.0 + number * 0.05, 1.0 + number, ADA)
    for number in range(30):
        ask(measured, 11.0 + number * 0.1, 50.0 + number, IVY)
    picture = measured.picture(14.5, 0.0)
    assert [one.ms for one in picture.slowest] == pytest.approx([79.0 - n for n in range(10)])
    # Ten of each step are kept, and no more: what is kept does not grow with the load.
    kept = [len(step.slowest) for step in measured._steps]
    assert kept == [10, 0, 10]
    assert max(kept) == load.MOST_SLOWEST


def test_what_is_long_by_nature_has_a_list_of_its_own() -> None:
    measured = meter()
    ask(measured, 1.0, 250.0, ADA)
    for number in range(7):
        ask(measured, 10.0 + number * 10, 2000.0 + number * 500, IVY, route=REPORT, kind=load.LONG)
    # What stands apart, About and the health routes, is in neither list.
    ask(measured, 90.0, 4000.0, VIC, route="/api/v1/about", kind=load.APART)
    picture = measured.picture(100.0, 0.0)
    assert [(one.route, one.ms) for one in picture.slowest] == [(TAGS, pytest.approx(250.0))]
    assert [one.ms for one in picture.slowest_long] == pytest.approx(
        [5000.0, 4500.0, 4000.0, 3500.0, 3000.0]
    )
    assert {one.route for one in picture.slowest_long} == {REPORT}
    assert len(picture.slowest_long) == load.MOST_SLOWEST_LONG == 5


def test_a_request_that_no_route_answers_has_no_pattern() -> None:
    measured = meter()
    ask(measured, 1.0, 250.0, None, status=404, route=None)
    assert measured.picture(2.0, 0.0).slowest[0].route is None


def test_what_each_account_met_in_the_ten_minutes() -> None:
    measured = meter(Ceiling())
    # Ada: one read in each band, the slowest of them failed, a look at About, and a
    # report that was refused.
    for at, took_ms, status in ((1.0, 500.0, 200), (2.0, 1500.0, 200), (4.0, 2500.0, 200)):
        ask(measured, at, took_ms, ADA, status=status)
    ask(measured, 10.0, 3500.0, ADA, status=500)
    ask(measured, 20.0, 9000.0, ADA, route="/api/v1/about", kind=load.APART)
    measured.turned_away(30.0, 0.0, who=ADA)
    # Ivy, in another step: two quick reads.
    ask(measured, 40.0, 250.0, IVY)
    ask(measured, 41.0, 125.0, IVY)
    picture = measured.picture(50.0, 0.0)
    ada, ivy = picture.people
    assert ada == load.Person(
        kind=load.PERSON,
        hid="hid-ada",
        username="ada",
        # Every request, the one that was refused among them.
        requests=6,
        # Its requests of the measure by band: About is in none, nor what was refused.
        bands=(1, 1, 1, 1),
        slowest_ms=3500.0,
        busy=1,
        failed=1,
        last_at=STARTED + timedelta(seconds=30),
    )
    assert ivy == load.Person(
        kind=load.PERSON,
        hid="hid-ivy",
        username="ivy",
        requests=2,
        bands=(2, 0, 0, 0),
        slowest_ms=250.0,
        busy=0,
        failed=0,
        last_at=STARTED + timedelta(seconds=41),
    )
    # What was counted for each is what the totals count.
    assert sum(one.requests for one in picture.people) == picture.requests == 8
    assert sum(one.busy for one in picture.people) == picture.busy == 1


def test_whoever_had_it_worst_is_first() -> None:
    measured = meter(Ceiling())
    # Vic: slow, and nothing past the ceiling. Ivy: one past it. Ada: one past it and
    # one refused. The collector: one past it, and slower than Ivy's.
    ask(measured, 1.0, 2900.0, VIC)
    ask(measured, 5.0, 3100.0, IVY)
    ask(measured, 10.0, 3200.0, ADA)
    measured.turned_away(15.0, 0.0, who=ADA)
    ask(measured, 20.0, 4000.0, COLLECTOR)
    ask(measured, 30.0, 10.0, None)
    people = measured.picture(40.0, 0.0).people
    assert [(one.username, one.kind) for one in people] == [
        ("ada", load.PERSON),
        ("collector", load.SERVICE),
        ("ivy", load.PERSON),
        ("vic", load.PERSON),
        # The requests nobody is named for come after the accounts, whatever they met.
        (None, load.UNNAMED),
    ]
    # As bad for two, and as slow: by name.
    again = meter(Ceiling())
    for at, who in ((1.0, VIC), (2.0, ADA), (3.0, IVY)):
        ask(again, at, 250.0, who)
    assert [one.username for one in again.picture(4.0, 0.0).people] == ["ada", "ivy", "vic"]


def test_requests_that_nothing_verifiable_names_an_account_for_are_one_row() -> None:
    measured = meter(Ceiling())
    ask(measured, 1.0, 250.0, None, status=401)
    ask(measured, 2.0, 3500.0, None, route="/api/v1/auth/sign-in", kind=load.KEPT)
    measured.turned_away(6.0, 0.0)
    ask(measured, 7.0, 4.0, None, status=500, route=None, kind=load.APART)
    assert measured.picture(8.0, 0.0).people == [
        load.Person(
            kind=load.UNNAMED,
            hid=None,
            username=None,
            requests=4,
            bands=(1, 0, 0, 1),
            slowest_ms=3500.0,
            busy=1,
            failed=1,
            last_at=STARTED + timedelta(seconds=7),
        )
    ]


def test_an_account_is_listed_by_the_username_it_last_asked_with() -> None:
    measured = meter()
    ask(measured, 1.0, 250.0, ADA)
    ask(measured, 11.0, 250.0, load.Who("hid-ada", "ada.lovelace"))
    (one,) = measured.picture(12.0, 0.0).people
    assert (one.hid, one.username, one.requests) == ("hid-ada", "ada.lovelace", 2)


def test_past_fifty_accounts_in_a_step_the_rest_are_counted_together() -> None:
    measured = meter()
    for number in range(60):
        who = load.Who(f"hid-{number:02}", f"user-{number:02}")
        ask(measured, 1.0 + number * 0.01, 5.0, who)
    ask(measured, 1.7, 5.0, None)
    # One of the fifty asks again, and is still counted by itself.
    ask(measured, 1.8, 500.0, load.Who("hid-07", "user-07"))
    assert len(measured._steps[-1].people) == load.MOST_PEOPLE_OF_A_STEP + 2
    people = measured.picture(3.0, 0.0).people
    assert len(people) == 52
    assert people[0].username == "user-07"
    assert [(one.kind, one.username, one.requests) for one in people[-2:]] == [
        (load.UNNAMED, None, 1),
        (load.OTHERS, None, 10),
    ]
    assert sum(one.requests for one in people) == 62


def test_past_fifty_accounts_in_the_ten_minutes_the_rest_are_listed_together() -> None:
    measured = meter()
    # Thirty accounts in one step and thirty others in another, the later ones slower.
    for number in range(60):
        at = (1.0 if number < 30 else 11.0) + (number % 30) * 0.1
        ask(measured, at, 10.0 + number, load.Who(f"hid-{number:02}", f"user-{number:02}"))
    people = measured.picture(14.5, 0.0).people
    assert len(people) == load.MOST_PEOPLE + 1 == 51
    # The fifty that had it worst, the slowest first; the ten quickest together.
    assert [one.username for one in people[:3]] == ["user-59", "user-58", "user-57"]
    assert people[49].username == "user-10"
    assert (people[50].kind, people[50].requests, people[50].username) == (load.OTHERS, 10, None)
    assert people[50].slowest_ms == pytest.approx(19.0)


def test_an_account_that_asked_of_late_is_remembered_by_its_hid() -> None:
    measured = meter()
    assert measured.known("hid-ada") is None
    ask(measured, 1.0, 250.0, ADA)
    ask(measured, 2.0, 250.0, None)
    assert measured.known("hid-ada") == ADA
    assert measured.known("hid-ivy") is None
    # No more are remembered than so many: past it all are forgotten, and learnt again.
    for number in range(load.MOST_KNOWN):
        ask(measured, 3.0, 1.0, load.Who(f"hid-{number}", f"user-{number}"))
    assert measured.known("hid-ada") is None
    assert len(measured._known) <= load.MOST_KNOWN
    ask(measured, 4.0, 250.0, ADA)
    assert measured.known("hid-ada") == ADA


def test_a_request_that_is_not_of_the_api_is_counted_for_nobody() -> None:
    measured = meter()
    token = measured.began(1.0, 0.0, measured=False, api=False)
    measured.ended(token, 1.5, 0.0, status=200)
    picture = measured.picture(2.0, 0.0)
    assert (picture.requests, picture.people, picture.slowest) == (1, [], [])
