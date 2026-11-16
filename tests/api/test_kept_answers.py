"""The long reports kept and worked out ahead, and an Admin's check of them (P-142, P-157)."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.io import balance, kept
from hirdir.schedule import LONG_REPORTS, Scheduler
from tests.api.inventory import API, Maker


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


def test_the_capacity_balance_is_kept_until_a_change(
    make: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _line(make, "Network engineer", "3")
    worked: list[int] = []
    real = balance.balance
    monkeypatch.setattr(balance, "balance", lambda *a, **k: worked.append(1) or real(*a, **k))
    first = make.get("/reports/capacity")
    assert make.get("/reports/capacity") == first
    assert worked == [1]
    # A change leaves it stale, and it is worked out again.
    _line(make, "Senior network engineer", "2")
    assert make.get("/reports/capacity")["active"]["supply"] == "5"
    assert worked == [1, 1]


def test_the_coverage_report_asked_with_and_without_the_warning_period_is_one_answer(
    make: Maker,
) -> None:
    make.get("/reports/coverage")
    make.get("/reports/coverage", within_days=90)
    assert len([one for one in kept._kept if one[0] == "coverage"]) == 1


def test_an_admin_lists_what_is_kept_and_nobody_else_may(
    make: Maker, client: TestClient, admin: dict[str, str], viewer: dict[str, str]
) -> None:
    make.get("/reports/capacity")
    make.get("/reports/capacity")
    make.get("/reports/coverage")
    listed = _as_admin(client, admin, "/kept-answers")
    assert {one["report"] for one in listed} == {"capacity", "coverage"}
    assert next(one for one in listed if one["report"] == "capacity")["uses"] == 1
    for headers in (viewer, make.headers):
        assert client.get(f"{API}/kept-answers", headers=headers).status_code == 403
        assert client.post(f"{API}/kept-answers/check", headers=headers).status_code == 403


def test_a_check_finds_nothing_differs_is_audited_and_leaves_them_good(
    make: Maker, client: TestClient, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _line(make, "Network engineer", "3")
    make.get("/reports/capacity")
    make.get("/reports/renewals")
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert found["checked"] == 2
    assert found["differed"] == []
    events = make.get("/audit-events", action="kept_answers_checked")["items"]
    assert len(events) == 1
    assert {"field": "checked", "old": None, "new": 2} in events[0]["changes"]
    # The check's own audit event leaves what it kept good: nothing is worked out again.
    worked: list[int] = []
    real = balance.balance
    monkeypatch.setattr(balance, "balance", lambda *a, **k: worked.append(1) or real(*a, **k))
    make.get("/reports/capacity")
    assert worked == []
    assert len(_as_admin(client, admin, "/kept-answers")) == 2


def test_a_check_names_a_kept_answer_that_had_fallen_out_of_step(
    make: Maker, client: TestClient, admin: dict[str, str]
) -> None:
    _line(make, "Network engineer", "3")
    make.get("/reports/capacity")
    # What is kept is made wrong behind the server's back, as a defect would make it.
    (key,) = [one for one in kept._kept if one[0] == "capacity"]
    held = kept._kept[key].answer
    kept._kept[key].answer = replace(held, active=replace(held.active, supply=Decimal("99")))
    found = _as_admin(client, admin, "/kept-answers/check", "post")
    assert [(one["report"], one["request"]) for one in found["differed"]] == [("capacity", "[]")]
    # The check keeps the answer worked out anew.
    assert make.get("/reports/capacity")["active"]["supply"] == "3"
    assert _as_admin(client, admin, "/kept-answers/check", "post")["differed"] == []


def test_the_long_reports_are_worked_out_just_after_midnight_and_at_start(
    make: Maker, config: Config
) -> None:
    _line(make, "Network engineer", "3")
    sessions = make_sessions(make_engine(config.database_url))
    scheduler = Scheduler(sessions, (LONG_REPORTS,))
    assert scheduler.run_due(datetime.now(UTC), starting=True) == ["long reports"]
    with sessions() as db:
        reports = {entry.report for entry in kept.listing(db)}
    assert reports == {"coverage", "renewals", "renewal_alert", "capacity"}
    # The pages' first requests are answered from them.
    before = len(kept._kept)
    make.get("/reports/coverage")
    make.get("/reports/renewals")
    make.get("/reports/capacity")
    assert len(kept._kept) == before
