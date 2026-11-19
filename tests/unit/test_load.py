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
    api: bool = True,
    cpu: float = 0.0,
) -> None:
    """Have a request arrive and be answered `took` seconds later."""
    token = measured.began(began, cpu, api=api)
    measured.ended(token, began + took, cpu, status=status)


def several(measured: Meter, took: float, begins: int = 5, api: bool = True) -> None:
    """Have requests arrive a second apart from 0, each answered `took` seconds later,
    told to the meter in the order it all happens."""
    events = sorted(
        [(float(at), 0, at) for at in range(begins)] + [(at + took, 1, at) for at in range(begins)]
    )
    tokens = {}
    for moment, ends, which in events:
        if ends:
            measured.ended(tokens[which], moment, 0.0, status=200)
        else:
            tokens[which] = measured.began(moment, 0.0, api=api)


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
    assert picture.reading == load.Reading(load.OK, (), None, 0.0)


def test_each_answer_is_counted_in_its_step_by_how_it_was_answered() -> None:
    measured = meter()
    answer(measured, 0.0, 0.010)
    answer(measured, 1.0, 0.030, status=201)
    answer(measured, 2.0, 0.020, status=404)
    answer(measured, 6.0, 0.500, status=500)
    answer(measured, 7.0, 0.100, status=503)
    # Whatever is not of the API, the page and its files, is counted as well.
    answer(measured, 11.0, 0.002, status=304, api=False)
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
    token = measured.began(2.0, 0.0, api=True)
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
    first = measured.began(1.0, 0.0, api=True)
    second = measured.began(3.0, 0.0, api=False)
    asks = measured.began(4.0, 0.0, api=True)
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


def test_how_long_requests_take_is_the_median_and_not_the_average() -> None:
    measured = meter(SLOW)
    for at in range(4):
        answer(measured, at, 0.010)
    # One long export among quick answers is not a busy server.
    answer(measured, 4.0, 5.0)
    reading = measured.picture(9.5, 0.0).reading
    assert reading.response_ms == pytest.approx(10.0)
    assert reading.state == load.OK


def test_with_fewer_than_five_requests_there_is_no_such_measure() -> None:
    measured = meter(SLOW)
    several(measured, 3.0, begins=4)
    reading = measured.picture(8.0, 0.0).reading
    assert (reading.response_ms, reading.state, reading.because) == (None, load.OK, ())
    answer(measured, 8.0, 1.5)
    reading = measured.picture(9.9, 0.0).reading
    assert reading.response_ms == pytest.approx(3000.0)
    assert (reading.state, reading.because) == (load.BUSY, (load.RESPONSE,))


def test_the_wait_of_the_requests_in_flight_is_in_the_median() -> None:
    measured = meter(SLOW)
    answer(measured, 0.0, 0.010)
    answer(measured, 0.0, 0.020)
    # Three requests from which nothing comes back: an idle server it is not.
    for _ in range(3):
        measured.began(1.0, 0.0, api=True)
    assert measured.reading(1.5, 0.0).response_ms == pytest.approx(500.0)
    reading = measured.reading(3.5, 0.0)
    assert reading.response_ms == pytest.approx(2500.0)
    assert (reading.state, reading.because) == (load.BUSY, (load.RESPONSE,))
    # The two that were answered are older than the measure looks back: with three in
    # flight alone there is no measure, however long they have waited.
    reading = measured.reading(10.5, 0.0)
    assert (reading.response_ms, reading.state) == (None, load.OK)


def test_only_the_requests_of_the_api_are_in_the_median() -> None:
    measured = meter(SLOW)
    several(measured, 2.0, api=False)
    measured.began(6.0, 0.0, api=False)
    assert measured.picture(9.0, 0.0).reading.response_ms is None
    # They are in the times of the steps all the same.
    assert measured.picture(9.0, 0.0).response_ms.high == pytest.approx(2000.0)


def test_only_the_requests_that_came_in_the_last_while_are_in_the_median() -> None:
    measured = meter(SLOW)
    several(measured, 2.0)
    assert measured.reading(7.0, 0.0).state == load.BUSY
    for tenth in range(5):
        answer(measured, 12.0 + tenth / 10, 0.010)
    # At 12.5 the three that came before 2.5 are out, whenever they were answered,
    # and two slow ones are left of seven.
    reading = measured.reading(12.5, 0.0)
    assert reading.response_ms == pytest.approx(10.0)
    assert reading.state == load.OK


def asked_every_five_seconds(measured: Meter, until: int) -> dict[int, str]:
    """Have About ask every five seconds, as the page does, and return what it was told
    at each: a request of the API that is answered at once, like any other."""
    told = {}
    for at in range(5, until + 1, 5):
        token = measured.began(float(at), 0.0, api=True)
        told[at] = measured.picture(float(at), 0.0, but=token).reading.state
        measured.ended(token, float(at), 0.0, status=200)
    return told


def stall(measured: Meter, until: int) -> dict[int, str]:
    """Ten requests of the API come at once and are all answered twenty seconds later,
    after which nothing but About asks. Return what About was told every five seconds."""
    tokens = [measured.began(0.0, 0.0, api=True) for _ in range(10)]
    told = asked_every_five_seconds(measured, 20)
    for token in tokens:
        measured.ended(token, 20.0, 0.0, status=200)
    for at in range(25, until + 1, 5):
        token = measured.began(float(at), 0.0, api=True)
        told[at] = measured.picture(float(at), 0.0, but=token).reading.state
        measured.ended(token, float(at), 0.0, status=200)
    return told


def test_a_stall_that_is_over_is_over_and_never_the_second_step() -> None:
    told = stall(meter(Ceiling(response_ms=5000, cpu_percent=0, over_seconds=30)), 120)
    # Five seconds of waiting are not past five seconds; ten are.
    assert told[5] == load.OK
    assert [told[at] for at in (10, 15, 20)] == [load.BUSY] * 3
    # Answered at 20, the ten are still requests that came in the last half minute.
    assert told[25] == load.BUSY
    # Half a minute after they came they are out, and the server is what it is: idle.
    assert [told[at] for at in range(30, 125, 5)] == [load.OK] * 19
    assert load.VERY_BUSY not in told.values()


def test_a_stall_that_is_over_with_the_longest_while_the_setting_takes() -> None:
    told = stall(meter(Ceiling(response_ms=5000, cpu_percent=0, over_seconds=300)), 700)
    assert told[10] == load.BUSY
    # The ten stay in the measure for five minutes after they came, and are outnumbered
    # by what About alone asks before one minute is out.
    assert told[50] == load.BUSY
    assert [told[at] for at in range(55, 705, 5)] == [load.OK] * 130
    assert load.VERY_BUSY not in told.values()


def test_a_request_leaves_the_measure_a_while_after_it_came_not_after_its_answer() -> None:
    measured = meter(SLOW)
    several(measured, 8.0)
    # They came at 0 to 4 and were answered at 8 to 12. At 12 the three that came by 2
    # are out, though they were answered two to four seconds ago: two are no measure.
    assert measured.reading(12.0, 0.0).response_ms is None
    # And one in flight is in it however long ago it came.
    for _ in range(5):
        measured.began(14.0, 0.0, api=True)
    assert measured.reading(74.0, 0.0).response_ms == pytest.approx(60_000.0)


def test_requests_from_which_nothing_comes_back_are_the_second_step() -> None:
    measured = meter(SLOW)
    for _ in range(5):
        measured.began(0.0, 0.0, api=True)
    assert measured.reading(2.0, 0.0).state == load.BUSY
    assert measured.reading(11.0, 0.0).state == load.BUSY
    # Ten seconds on they wait still: what is in flight is evidence of now.
    assert measured.reading(12.0, 0.0).state == load.VERY_BUSY
    assert measured.reading(3600.0, 0.0).state == load.VERY_BUSY


# --- a request whose body has not all come -------------------------------------------


def test_requests_whose_body_never_comes_hold_nothing_busy() -> None:
    measured = meter(Ceiling())
    # Five senders give the headers of a sign-in and no body.
    for _ in range(5):
        measured.began(0.0, 0.0, api=True, whole=False)
    for at in range(5, 3605, 5):
        picture = measured.picture(float(at), 0.0)
        assert picture.reading.state == load.OK, at
        assert picture.reading.response_ms is None
        # They are in flight, which they are, and have no age.
        assert (picture.in_flight, picture.oldest_ms) == (5, None)
    # The same five with nothing more to come would be a server that answers nothing.
    stuck = meter(Ceiling())
    for _ in range(5):
        stuck.began(0.0, 0.0, api=True)
    assert stuck.picture(3600.0, 0.0).reading.state == load.BUSY
    assert stuck.picture(3600.0, 0.0).oldest_ms == pytest.approx(3_600_000.0)


def test_the_time_of_a_request_begins_when_the_server_has_the_whole_of_it() -> None:
    measured = meter(SLOW)
    # An upload that takes its sender nine seconds, and the server half of one.
    token = measured.began(0.0, 0.0, api=True, whole=False)
    measured.heard(token, 3.0, 0.0, whole=False)
    measured.heard(token, 6.0, 0.0, whole=False)
    assert measured.picture(8.0, 0.0).oldest_ms is None
    measured.heard(token, 9.0, 0.0, whole=True)
    # Whole, it waits for the server, from there.
    assert measured.picture(9.25, 0.0).oldest_ms == pytest.approx(250.0)
    # A piece told again changes nothing of one that is whole.
    measured.heard(token, 9.3, 0.0, whole=True)
    measured.ended(token, 9.5, 0.0, status=201)
    picture = measured.picture(9.5, 0.0)
    assert picture.response_ms.low == picture.response_ms.high == pytest.approx(500.0)
    # Five more of them at once, and the measure is of the server's part alone.
    slow = [measured.began(9.5, 0.0, api=True, whole=False) for _ in range(5)]
    for token in slow:
        measured.heard(token, 19.0, 0.0, whole=True)
    for token in slow:
        measured.ended(token, 19.5, 0.0, status=201)
    reading = measured.picture(19.5, 0.0).reading
    assert reading.response_ms == pytest.approx(500.0)
    assert reading.state == load.OK


def test_an_answer_given_before_the_body_came_is_timed_from_what_did_come() -> None:
    measured = meter()
    # Not signed in: answered at once, with nothing of the body read.
    refused = measured.began(0.0, 0.0, api=True, whole=False)
    measured.ended(refused, 0.25, 0.0, status=401)
    # A sender that went away after its second piece.
    gone = measured.began(1.0, 0.0, api=True, whole=False)
    measured.heard(gone, 3.0, 0.0, whole=False)
    measured.ended(gone, 3.5, 0.0, status=500)
    picture = measured.picture(4.0, 0.0)
    assert picture.response_ms.low == pytest.approx(250.0)
    assert picture.response_ms.high == pytest.approx(500.0)
    assert (picture.not_accepted, picture.failed, picture.in_flight) == (1, 1, 0)


# --- the processor -------------------------------------------------------------------


def test_the_processor_is_the_share_of_one_used_over_the_last_while() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 4.0).cpu_percent == pytest.approx(40.0)
    # Six of the next ten seconds: past the ceiling.
    reading = measured.reading(20.0, 10.0)
    assert reading.cpu_percent == pytest.approx(60.0)
    assert (reading.state, reading.because) == (load.BUSY, (load.PROCESSOR,))
    # Only the last ten seconds are read: seven and a half of them idle.
    reading = measured.reading(27.5, 10.0)
    assert reading.cpu_percent == pytest.approx(15.0)
    assert reading.state == load.OK


def test_a_server_that_just_started_used_nothing_before() -> None:
    measured = meter(HOT)
    # Flat out for its first three seconds is three seconds of ten, and not busy.
    reading = measured.reading(3.0, 3.0)
    assert reading.cpu_percent == pytest.approx(30.0)
    assert reading.state == load.OK
    assert measured.reading(6.0, 6.0).state == load.BUSY


def test_the_share_of_the_processor_passes_100_where_threads_work_at_once() -> None:
    # Four threads each in a query use two processors' worth: nothing holds it to 100.
    measured = meter(Ceiling(response_ms=0, cpu_percent=150, over_seconds=10))
    reading = measured.reading(10.0, 12.0)
    assert reading.cpu_percent == pytest.approx(120.0)
    assert reading.state == load.OK
    reading = measured.reading(20.0, 32.0)
    assert reading.cpu_percent == pytest.approx(200.0)
    assert (reading.state, reading.because) == (load.BUSY, (load.PROCESSOR,))
    picture = measured.picture(30.0, 52.0)
    assert picture.reading.state == load.VERY_BUSY
    assert picture.points.cpu_percent[:6] == pytest.approx([120.0, 120.0, *[200.0] * 4])
    assert picture.cpu_percent.high == pytest.approx(200.0)
    assert picture.cpu_percent.average == pytest.approx((240.0 + 800.0) / 6)


def test_the_processor_is_read_whatever_the_requests_are() -> None:
    measured = meter(HOT)
    reading = measured.reading(10.0, 9.0)
    assert (reading.state, reading.because, reading.response_ms) == (
        load.BUSY,
        (load.PROCESSOR,),
        None,
    )


# --- the ceiling ---------------------------------------------------------------------


def test_a_measure_at_0_is_not_looked_at() -> None:
    slow_only = meter(SLOW)
    for at in range(5):
        answer(slow_only, at, 0.010)
    # The processor is flat out, and its ceiling is 0.
    reading = slow_only.picture(9.0, 9.0).reading
    assert reading.cpu_percent == pytest.approx(90.0)
    assert (reading.state, reading.because) == (load.OK, ())
    hot_only = meter(HOT)
    several(hot_only, 4.0)
    reading = hot_only.picture(9.0, 0.0).reading
    assert reading.response_ms == pytest.approx(4000.0)
    assert (reading.state, reading.because) == (load.OK, ())


def test_both_at_0_is_no_ceiling_and_nothing_is_read_for_it() -> None:
    assert load.NO_CEILING.none
    assert not SLOW.none
    assert not HOT.none
    measured = meter(Ceiling(response_ms=0, cpu_percent=0, over_seconds=10))
    several(measured, 4.0)
    # A request is told nothing was read; the picture reads the measures all the same.
    assert measured.reading(9.0, 9.0) is load.UNREAD
    reading = measured.picture(9.0, 9.0).reading
    assert reading.response_ms == pytest.approx(4000.0)
    assert reading.cpu_percent == pytest.approx(90.0)
    assert (reading.state, reading.because) == (load.OK, ())
    assert measured.reading(9.5, 9.5) is load.UNREAD


def test_both_measures_past_their_ceilings_are_both_named() -> None:
    measured = meter(Ceiling(response_ms=1000, cpu_percent=50, over_seconds=10))
    several(measured, 3.0)
    assert measured.reading(9.0, 8.0).because == (load.RESPONSE, load.PROCESSOR)


def test_a_measure_at_its_ceiling_is_not_past_it() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 5.0).state == load.OK
    assert measured.reading(20.0, 10.5).state == load.BUSY


def test_the_second_step_comes_after_a_further_while_of_being_busy() -> None:
    measured = meter(HOT)
    cpu = 0.0
    states = {}
    for second in range(1, 31):
        cpu += 0.9
        states[second] = measured.reading(float(second), cpu).state
    # Past 50% of ten seconds once 5.4 seconds of the processor are used, at the sixth.
    assert [states[second] for second in (5, 6, 10, 15)] == [
        load.OK,
        load.BUSY,
        load.BUSY,
        load.BUSY,
    ]
    # Busy since the sixth second: very busy from the sixteenth.
    assert [states[second] for second in (16, 30)] == [load.VERY_BUSY, load.VERY_BUSY]


def test_the_echo_of_being_busy_is_never_the_second_step() -> None:
    measured = meter(Ceiling(response_ms=0, cpu_percent=20, over_seconds=5))
    # Flat out for twelve seconds in which nothing asked, and idle from the moment the
    # first to ask finds it busy.
    assert measured.reading(12.0, 12.0).state == load.BUSY
    # Five seconds on, the steps still say 24%: the step from 10 to 15 holds the two
    # seconds used before 12, read as spread over the whole of it. Nothing was used
    # since the server became busy, so it is busy on the echo, and not very busy.
    reading = measured.reading(17.0, 12.0)
    assert reading.cpu_percent == pytest.approx(24.0)
    assert reading.state == load.BUSY
    assert measured.reading(18.0, 12.0).state == load.OK


def test_the_further_while_is_counted_again_where_nothing_after_says_busy() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 9.0).state == load.BUSY
    # Idle for fourteen seconds in which nothing asked whether it is busy, and then
    # flat out for six: 60% of the last ten seconds, and 30% of the twenty since it
    # became busy. Time alone would make this the second step: it is the first, anew.
    answer(measured, 24.0, 0.0, cpu=9.0)
    reading = measured.reading(30.0, 15.0)
    assert reading.cpu_percent == pytest.approx(60.0)
    assert reading.state == load.BUSY
    # Flat out from there: very busy ten seconds after that, and not before.
    assert measured.reading(39.0, 24.0).state == load.BUSY
    assert measured.reading(40.0, 25.0).state == load.VERY_BUSY
    # Once at the second step it stays there for as long as it is busy.
    assert measured.reading(44.0, 25.0).state == load.VERY_BUSY
    assert measured.reading(46.0, 25.0).state == load.OK


def test_being_busy_begins_when_something_asks_and_finds_it_so() -> None:
    measured = meter(HOT)
    # Flat out for a minute in which nothing asked: the first to ask finds it busy, and
    # the further while is counted from there.
    assert measured.reading(60.0, 60.0).state == load.BUSY
    assert measured.reading(69.0, 69.0).state == load.BUSY
    assert measured.reading(70.0, 70.0).state == load.VERY_BUSY


def test_a_server_comes_back_under_and_begins_again_at_the_first_step() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 9.0).state == load.BUSY
    assert measured.reading(20.0, 18.0).state == load.VERY_BUSY
    # Idle from there: at 25 half of the last ten seconds were at 90%, at 26 less.
    assert measured.reading(24.0, 18.0).state == load.VERY_BUSY
    assert measured.reading(26.0, 18.0).state == load.OK
    # Busy anew is the first step anew, however long it was busy before.
    assert measured.reading(36.0, 27.0).state == load.BUSY
    assert measured.reading(45.0, 35.1).state == load.BUSY
    assert measured.reading(46.0, 36.0).state == load.VERY_BUSY


def test_the_measures_are_read_once_a_second_at_the_most() -> None:
    measured = meter(HOT)
    first = measured.reading(10.0, 9.0)
    assert first.state == load.BUSY
    # Within the second the same reading is given, whatever the clocks say meanwhile.
    assert measured.reading(10.9, 0.0) is first
    assert measured.reading(11.0, 9.0) is not first
    # The picture reads afresh, and a request after it is given that reading.
    fresh = measured.picture(11.2, 9.0).reading
    assert measured.reading(11.3, 9.0) is fresh


def test_a_ceiling_that_is_given_holds_from_the_next_request() -> None:
    measured = meter(HOT)
    assert measured.reading(10.0, 9.0).state == load.BUSY
    measured.hold(Ceiling(response_ms=0, cpu_percent=95, over_seconds=10))
    assert measured.reading(10.1, 9.0).state == load.OK
    measured.hold(HOT)
    assert measured.reading(10.2, 9.0).state == load.BUSY
    measured.hold(load.NO_CEILING)
    assert measured.reading(10.3, 9.0) is load.UNREAD
    # With a ceiling again, being busy begins again.
    measured.hold(HOT)
    assert measured.reading(21.0, 19.0).state == load.BUSY


# --- the answers of busy -------------------------------------------------------------


def test_an_answer_of_busy_is_counted_and_is_in_neither_measure() -> None:
    measured = meter(SLOW)
    several(measured, 2.0)
    assert measured.reading(7.0, 0.0).state == load.BUSY
    for _ in range(20):
        measured.turned_away(7.5, 0.0)
    picture = measured.picture(8.0, 0.0)
    assert (picture.requests, picture.ok, picture.busy) == (25, 5, 20)
    assert picture.points.busy == [0, 20]
    assert picture.points.requests == [3, 22]
    # Twenty answers at once would have made the median nothing: they are not in it,
    # nor in the times of the step.
    assert picture.reading.response_ms == pytest.approx(2000.0)
    assert picture.reading.state == load.BUSY
    assert picture.response_ms.low == pytest.approx(2000.0)
    assert picture.points.average_ms == pytest.approx([2000.0, 2000.0])


def test_a_step_of_nothing_but_answers_of_busy_has_no_times() -> None:
    measured = meter()
    measured.turned_away(1.0, 0.0)
    picture = measured.picture(2.0, 0.0)
    assert (picture.points.requests, picture.points.busy) == ([1], [1])
    assert picture.points.average_ms == picture.points.high_ms == [None]
    assert picture.response_ms == load.Spread(None, None, None)


# --- what is turned away -------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "kind", "turned_away"),
    [
        (load.OK, load.COSTLY, False),
        (load.OK, load.READ, False),
        (load.OK, load.KEPT, False),
        (load.BUSY, load.COSTLY, True),
        (load.BUSY, load.READ, False),
        (load.BUSY, load.KEPT, False),
        (load.VERY_BUSY, load.COSTLY, True),
        (load.VERY_BUSY, load.READ, True),
        (load.VERY_BUSY, load.KEPT, False),
    ],
)
def test_what_a_server_turns_away_in_each_state(
    state: load.State, kind: load.Kind, turned_away: bool
) -> None:
    assert load.refuses(state, kind) is turned_away


def test_the_ceiling_unless_set_and_what_the_meter_keeps() -> None:
    assert Ceiling() == Ceiling(response_ms=5000, cpu_percent=95, over_seconds=30)
    assert (load.WINDOW_SECONDS, load.STEP_SECONDS, load.FEWEST_REQUESTS) == (600, 5, 5)
    # The second step is always within what the meter keeps.
    assert load.MOST_OVER_SECONDS * 2 <= load.WINDOW_SECONDS
