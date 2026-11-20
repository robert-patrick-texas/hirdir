"""The long reports worked out ahead and kept in the database, where every process
reads them (P-275), and worked out again by day once nothing has changed for a while
(P-276).

The memory of a process is `hirdir.io.kept`'s own, and these tests run in one process:
`kept.drop()` is the server that has given nothing yet, or another process altogether.
The second process is `reports.work_out_ahead` on a session of its own, as its job of
the clock and its worker call it.
"""

import json
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from hirdir import __version__, clock, schedule
from hirdir.api import reports
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import KeptAnswer
from hirdir.domain import audit, reset
from hirdir.io import background, balance, examples, kept, planning
from tests.api.inventory import API, Maker

FOUR = ["capacity", "coverage", "renewal_alert", "renewals"]
SETTING = "reports_ahead_after_seconds"


@pytest.fixture(autouse=True)
def nothing_kept() -> None:
    kept.drop()


def _line(make: Maker, name: str, units: str = "1") -> dict[str, Any]:
    return make.post(
        "/capacity-lines",
        {"side": "supply", "category": "staff", "name": name, "quantity": "1", "units_each": units},
    )


def _as_admin(client: TestClient, admin: dict[str, str], path: str, method: str = "get") -> Any:
    response = client.request(method, f"{API}{path}", headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


def _set(client: TestClient, admin: dict[str, str], value: Any, expect: int = 200) -> Any:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=admin).json()}
    answer = client.put(
        f"{API}/settings/{SETTING}",
        json={"row_version": now[SETTING]["row_version"], "value": value},
        headers=admin,
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


def _held(db: Session) -> list[str]:
    db.rollback()
    return sorted(db.scalars(select(KeptAnswer.report)))


def _made_wrong(db: Session) -> None:
    """Make the row of the capacity balance wrong behind the back of every process, as
    a defect would: it still reads, and says a supply that nothing has."""
    row = db.scalars(select(KeptAnswer).where(KeptAnswer.report == "capacity")).one()
    held = json.loads(row.answer)
    held["active"]["supply"] = "99"
    row.answer = json.dumps(held)
    db.commit()


def _never(*_: Any, **__: Any) -> Any:
    raise AssertionError("worked out, where the answer that is kept was to be given")


def _nothing_is_worked_out(monkeypatch: pytest.MonkeyPatch) -> None:
    for module, name in ((balance, "balance"), (planning, "coverage"), (planning, "renewals")):
        monkeypatch.setattr(module, name, _never)


# --- kept in the database, and given by the server -------------------------------------


def test_each_report_is_kept_in_a_row_and_the_server_gives_it_without_working_it_out(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session, monkeypatch
) -> None:
    _line(make, "Network engineer", "3")
    assert sorted(reports.work_out_ahead(db)) == FOUR
    assert _held(db) == FOUR
    # What the database holds good is left as it is.
    assert reports.work_out_ahead(db) == []
    # The server has given nothing yet, and gives what the rows hold.
    kept.drop()
    _nothing_is_worked_out(monkeypatch)
    assert make.get("/reports/capacity")["active"]["supply"] == "3"
    assert make.get("/reports/coverage")["as_of"]
    assert make.get("/reports/renewals")["as_of"]
    assert "lapsed" in make.get("/renewals/alert")
    listed = _as_admin(client, admin, "/kept-answers")
    assert sorted(one["report"] for one in listed) == FOUR
    assert all(one["ahead"] and one["uses"] == 1 for one in listed)
    # A view that is not the one its page opens with is the server's own, in its memory.
    monkeypatch.undo()
    make.get("/reports/coverage", within_days=7)
    listed = _as_admin(client, admin, "/kept-answers")
    assert [one["ahead"] for one in listed if one["report"] == "coverage"] == [True, False]
    assert _held(db) == FOUR


def test_a_change_leaves_the_rows_unused_until_they_are_worked_out_again(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session
) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    _line(make, "Senior network engineer", "2")
    db.rollback()
    assert sorted(kept.missing(db)) == FOUR
    # Asked before the second process has come to it, the server works it out itself
    # and keeps it in its memory alone.
    kept.drop()
    assert make.get("/reports/capacity")["active"]["supply"] == "5"
    (capacity,) = _as_admin(client, admin, "/kept-answers")
    assert (capacity["report"], capacity["ahead"]) == ("capacity", False)
    # Worked out again, a report has the one row it had, and the server's is of it.
    assert sorted(reports.work_out_ahead(db)) == FOUR
    assert _held(db) == FOUR
    listed = _as_admin(client, admin, "/kept-answers")
    assert sorted(one["report"] for one in listed) == FOUR
    assert all(one["ahead"] for one in listed)
    kept.drop()
    assert make.get("/reports/capacity")["active"]["supply"] == "5"


@pytest.mark.parametrize(
    "stale",
    [
        {"day": clock.today() - timedelta(days=1)},
        {"version": "0.0.1"},
        {"newest_event_hid": None},
        {"request": "[1]"},
    ],
    ids=["another day", "another version", "another event", "another request"],
)
def test_a_row_of_another_day_version_event_or_request_is_not_given(
    make: Maker, db: Session, monkeypatch, stale: dict[str, Any]
) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    db.execute(update(KeptAnswer).where(KeptAnswer.report == "capacity").values(**stale))
    db.commit()
    kept.drop()
    worked: list[int] = []
    real = balance.balance
    monkeypatch.setattr(balance, "balance", lambda *a, **k: worked.append(1) or real(*a, **k))
    assert make.get("/reports/capacity")["active"]["supply"] == "3"
    assert worked == [1]


def test_a_row_that_cannot_be_read_is_not_given_and_a_check_writes_it_again(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session, monkeypatch, caplog
) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    db.execute(
        update(KeptAnswer).where(KeptAnswer.report == "capacity").values(answer='{"as_of": 3}')
    )
    db.commit()
    kept.drop()
    with caplog.at_level(logging.WARNING, logger="hirdir"):
        assert make.get("/reports/capacity")["active"]["supply"] == "3"
    assert "the kept answer of the report capacity cannot be read" in caplog.text
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert [(one["report"], one["request"]) for one in found["differed"]] == [("capacity", "[]")]
    kept.drop()
    _nothing_is_worked_out(monkeypatch)
    assert make.get("/reports/capacity")["active"]["supply"] == "3"


def test_an_answer_worked_out_across_a_change_is_thrown_away(
    make: Maker, db: Session, monkeypatch
) -> None:
    _line(make, "Network engineer", "3")
    last = list(kept._ahead)[-1]
    real = kept._ahead[last]

    def view_and_a_change(session: Session) -> Any:
        found = real.view(session)
        _line(make, "Senior network engineer", "2")
        return found

    monkeypatch.setitem(kept._ahead, last, kept.Ahead(last, real.form, view_and_a_change))
    # Every answer was worked out with a newest event that is the newest no more.
    assert reports.work_out_ahead(db) == []
    assert _held(db) == []
    monkeypatch.undo()
    assert sorted(reports.work_out_ahead(db)) == FOUR
    kept.drop()
    assert make.get("/reports/capacity")["active"]["supply"] == "5"


def test_a_reset_clears_what_is_kept(make: Maker, db: Session) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    reset.clear_inventory(db, audit.SYSTEM, "before-reset.db")
    db.commit()
    assert _held(db) == []


def test_an_inventory_that_holds_nothing_but_what_is_kept_is_empty(db: Session) -> None:
    """The second process fills the table when it starts, on an installation that has
    nothing yet: `hirdir admin load-examples` takes it for empty all the same."""
    assert sorted(reports.work_out_ahead(db)) == FOUR
    examples.check(db)
    assert reset.held(db) == {}


# --- listed and checked ----------------------------------------------------------------


def test_what_the_database_holds_is_listed_and_checked_before_anybody_has_asked(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session, monkeypatch
) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    kept.drop()
    listed = _as_admin(client, admin, "/kept-answers")
    assert sorted(one["report"] for one in listed) == FOUR
    assert all(one["ahead"] and one["uses"] == 0 for one in listed)
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert (found["checked"], found["differed"]) == (4, [])
    # Taking them up for the check is no use of them.
    assert all(one["uses"] == 0 for one in _as_admin(client, admin, "/kept-answers"))

    # A row made wrong behind the server's back, as a defect would make it, is named,
    # and written again as it is worked out anew.
    _made_wrong(db)
    kept.drop()
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert [(one["report"], one["request"]) for one in found["differed"]] == [("capacity", "[]")]
    kept.drop()
    _nothing_is_worked_out(monkeypatch)
    assert make.get("/reports/capacity")["active"]["supply"] == "3"


def test_a_check_compares_the_row_where_the_server_worked_its_own_answer_out_first(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session
) -> None:
    _line(make, "Network engineer", "3")
    # The server is asked first, then the second process writes the row.
    make.get("/reports/capacity")
    reports.work_out_ahead(db)
    _made_wrong(db)
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert [one["report"] for one in found["differed"]] == ["capacity"]
    assert _as_admin(client, admin, "/kept-answers/check", "post")["differed"] == []


# --- written and read back the same -----------------------------------------------------


@pytest.fixture(scope="module")
def stocked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Session]:
    """The fictional examples, loaded once for this module."""
    config = Config(state_dir=tmp_path_factory.mktemp("ahead"))
    migrate.upgrade(config.database_url)
    engine = make_engine(config.database_url)
    with make_sessions(engine)() as session:
        examples.load(session, examples.folder())
        session.commit()
        yield session
    engine.dispose()


@pytest.mark.parametrize("report", FOUR)
def test_an_answer_read_back_from_its_row_is_the_answer_that_was_worked_out(
    stocked: Session, report: str
) -> None:
    ahead = kept._ahead[report]
    found = ahead.view(stocked)
    written = ahead.form.dump_json(found)
    back = ahead.form.validate_json(written)
    assert type(back) is type(found)
    assert kept.same(back, found)
    assert ahead.form.dump_json(back) == written
    # And it is an answer with something in it.
    assert len(written) > 200


def test_the_examples_are_given_from_their_rows_as_they_were_worked_out(
    stocked: Session,
) -> None:
    worked = {report: kept._ahead[report].view(stocked) for report in FOUR}
    kept.drop()
    assert sorted(kept.work_ahead(stocked)) == FOUR
    kept.drop()
    for report in FOUR:
        given = kept._ahead[report].view(stocked)
        assert kept.same(given, worked[report]), report
    assert all(one.ahead and one.uses == 1 for one in kept.listing(stocked))


# --- by day, once nothing has changed for a while --------------------------------------


def test_the_reports_are_due_once_the_newest_change_is_as_old_as_the_setting_says(
    make: Maker, client: TestClient, admin: dict[str, str], db: Session, monkeypatch
) -> None:
    # Nothing has changed yet, and nothing is kept: due at once.
    assert kept.due(db)
    _line(make, "Network engineer", "3")
    db.rollback()
    assert not kept.due(db)
    real = clock.now
    monkeypatch.setattr(clock, "now", lambda: real() + timedelta(seconds=29))
    assert not kept.due(db)
    monkeypatch.setattr(clock, "now", lambda: real() + timedelta(seconds=31))
    assert kept.due(db)
    # Worked out, nothing is due until the next change.
    assert schedule.work_out_ahead_if_due(db)
    assert not kept.due(db)
    assert not schedule.work_out_ahead_if_due(db)
    monkeypatch.undo()

    # The setting is an Admin's: a change of it is a change, and 0 is never by day.
    _set(client, admin, 5)
    db.rollback()
    assert not kept.due(db)
    monkeypatch.setattr(clock, "now", lambda: real() + timedelta(seconds=6))
    assert kept.due(db)
    monkeypatch.undo()
    _set(client, admin, 0)
    db.rollback()
    monkeypatch.setattr(clock, "now", lambda: real() + timedelta(hours=1))
    assert not kept.due(db)


def test_the_setting_takes_whole_seconds_from_none_to_an_hour(
    client: TestClient, admin: dict[str, str]
) -> None:
    listed = {one["key"]: one for one in _as_admin(client, admin, "/settings")}
    assert (listed[SETTING]["value"], listed[SETTING]["default"]) == (30, 30)
    assert listed[SETTING]["accepts"] == "a whole number of seconds from 0 to 3,600"
    for value in (0, 1, 3600):
        assert _set(client, admin, value)["value"] == value
    for value in (-1, 3601, 2.5, "30", True):
        _set(client, admin, value, expect=422)
    # Left blank, it is the default again.
    assert _set(client, admin, None)["value"] == 30


def test_the_worker_works_them_out_when_it_has_nothing_to_apply_and_only_for_the_service(
    config: Config, db: Session
) -> None:
    sessions = make_sessions(make_engine(config.database_url))
    # A worker of the tests of the routes, and of a server that was not asked to.
    assert not background.Worker(sessions).once()
    assert _held(db) == []
    # The worker of the service: nothing has changed yet, so they are due.
    assert not background.Worker(sessions, ahead=True).once()
    assert _held(db) == FOUR
    sessions.kw["bind"].dispose()


def test_working_ahead_that_fails_is_logged_and_not_tried_again_at_every_look(
    config: Config, monkeypatch, caplog
) -> None:
    tried: list[int] = []

    def fails(_: Session) -> bool:
        tried.append(1)
        raise RuntimeError("the reports cannot be worked out")

    monkeypatch.setattr(schedule, "work_out_ahead_if_due", fails)
    sessions = make_sessions(make_engine(config.database_url))
    worker = background.Worker(sessions, ahead=True)
    with caplog.at_level(logging.ERROR, logger="hirdir"):
        assert not worker.once()
        assert not worker.once()
    assert tried == [1]
    assert caplog.text.count("the long reports could not be worked out ahead") == 1
    # A minute later it is tried again.
    worker._ahead_not_before -= background.AHEAD_AGAIN_AFTER
    assert not worker.once()
    assert tried == [1, 1]
    sessions.kw["bind"].dispose()


def test_a_row_names_the_version_that_worked_it_out(make: Maker, db: Session) -> None:
    _line(make, "Network engineer", "3")
    reports.work_out_ahead(db)
    db.rollback()
    assert set(db.scalars(select(KeptAnswer.version))) == {__version__}
    assert db.scalar(select(func.count()).select_from(KeptAnswer)) == 4
