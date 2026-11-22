"""The server's own measures and the ceiling, through the API (P-265, P-266): every
request measured, what a busy server refuses and what it never does, the settings of
the ceiling, and `GET /about/load`.

A test inside this process starts with no ceiling (see `tests/conftest.py`). The tests
here that want a busy server take the clock of the measures into their own hands and
give the application a meter with a ceiling, so that none of them waits.
"""

import asyncio
import os
import threading
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hirdir.api import busy
from hirdir.app import API_PREFIX, ROUTERS, Gateway
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit, load, settings
from hirdir.domain.load import Ceiling
from hirdir.io import measures
from tests.api.inventory import API
from tests.conftest import AT_START, application, sign_in

STARTED = datetime(2027, 3, 2, 14, 0, 0, tzinfo=UTC)
# The processor alone, past half of one over ten seconds.
HOT = Ceiling(response_ms=0, cpu_percent=50, over_seconds=10)
NOWHERE = "00000000-0000-7000-8000-000000000000"
PROCESSORS = os.cpu_count() or 1


class Clock:
    """The clock of the server's measures, in the hands of a test."""

    def __init__(self) -> None:
        self.now = 0.0
        self.cpu = 0.0

    def __call__(self) -> tuple[float, float]:
        return self.now, self.cpu

    def busy(self) -> None:
        """Ten seconds on, nine of them of the processor: past the ceiling of `HOT`."""
        self.now += 10
        self.cpu += 9

    def idle(self) -> None:
        """Ten seconds on in which the processor did nothing."""
        self.now += 10


@pytest.fixture
def clock(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Clock:
    """A clock that stands still unless the test moves it, and a meter that starts with
    it, with a ceiling."""
    held = Clock()
    monkeypatch.setattr(measures, "clock", held)
    app: Any = client.app
    app.state.load = load.Meter(0.0, 0.0, started_at=STARTED, ceiling=HOT)
    return held


def said(answer: Any) -> str:
    """Return what an answer says of the health of the server and of what it refuses."""
    return answer.headers["x-hirdir-health"]


GOOD = "good; refusing=nothing"


def meter_of(client: TestClient) -> load.Meter:
    app: Any = client.app
    return app.state.load


def measured(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    answer = client.get(f"{API}/about/load", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def put(client: TestClient, admin: dict, key: str, value: Any, expect: int = 200) -> Any:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=admin).json()}
    answer = client.put(
        f"{API}/settings/{key}",
        json={"row_version": now[key]["row_version"], "value": value},
        headers=admin,
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


# --- what each route is ---------------------------------------------------------------


def test_no_route_is_left_as_what_nobody_decided() -> None:
    """A route is what it declares itself to be: a GET that takes no audit context
    reads, and anything else that takes one stores a change. A POST that stores nothing
    and a GET that is audited are decided by name, in `hirdir.api.busy`. A new route
    that is neither fails here until somebody decides."""
    routes = busy.routes_of(ROUTERS)
    assert len(routes) > 250
    assert {route.path: busy.undecided(route) for route in routes if busy.undecided(route)} == {}
    # Every name in the lists is a route that is there, with the method it is listed for.
    posts = {route.path for route in routes if "POST" in busy.methods_of(route)}
    gets = {route.path for route in routes if "GET" in busy.methods_of(route)}
    assert posts >= busy.LONG_POSTS
    assert posts >= busy.READ_POSTS
    assert busy.LONG_POSTS.isdisjoint(busy.READ_POSTS)
    assert gets >= busy.AUDITED_READS
    assert gets >= busy.APART_ROUTES
    for under in (busy.ALWAYS, busy.APART_UNDER, busy.REPORTS):
        assert any(route.path.startswith(under) for route in routes), under


def test_every_route_of_the_contract_is_among_those_that_are_decided(
    built: tuple[FastAPI, Config],
) -> None:
    """The routes that are decided are found by walking the routers. Were a route added
    some other way, the contract would have it and the walk would not."""
    walked = {
        (method, route.path)
        for route in busy.routes_of(ROUTERS)
        if route.include_in_schema
        for method in busy.methods_of(route)
    }
    paths = built[0].openapi()["paths"]
    contract = {
        (method.upper(), path.removeprefix(API_PREFIX))
        for path, operations in paths.items()
        for method in operations
    }
    assert walked == contract


def test_what_each_route_is_by_what_it_declares() -> None:
    kinds = {
        (method, route.path): busy.kind_of(route)
        for route in busy.routes_of(ROUTERS)
        for method in busy.methods_of(route)
    }
    # Long by nature: the reports, the exports and the previews, and nothing else.
    assert {where for where, kind in kinds.items() if kind == load.LONG} == {
        *(where for where in kinds if where[0] == "GET" and where[1].startswith("/reports/")),
        ("POST", "/reports/capacity/try"),
        ("POST", "/exports"),
        ("POST", "/exports/all"),
        ("POST", "/users/export"),
        ("POST", "/imports/preview"),
        ("POST", "/items/bulk-update"),
        ("POST", "/kept-answers/check"),
    }
    assert kinds[("GET", "/reports/summary")] == kinds[("GET", "/reports/duplicates")] == load.LONG
    # Every other read, the pages of lists among them, however they are asked for.
    for where in (
        ("GET", "/items"),
        ("POST", "/items/query"),
        ("POST", "/circuit-groups/query"),
        ("GET", "/items/{hid}/children"),
        ("GET", "/audit-events"),
        ("GET", "/users"),
        ("GET", "/exports/tables"),
        ("GET", "/imports"),
        ("GET", "/imports/{hid}/rows"),
        ("GET", "/contracts/{hid}/coverage"),
        ("GET", "/items/{hid}"),
        ("GET", "/items/{hid}/hosted"),
        ("GET", "/tags"),
        ("GET", "/choices"),
        ("GET", "/lifecycle-rules"),
        ("GET", "/geography/tree"),
        ("GET", "/renewals/alert"),
        ("GET", "/kept-answers"),
        ("GET", "/imports/{hid}"),
        ("GET", "/reference-files/{hid}/content"),
    ):
        assert kinds[where] == load.READ, where
    assert {where for where, kind in kinds.items() if kind == load.READ and where[0] != "GET"} == {
        ("POST", path) for path in busy.READ_POSTS
    }
    # A sign-in and every change that is stored: never refused, and in the measure.
    for where in (
        ("POST", "/auth/sign-in"),
        ("GET", "/auth/me"),
        ("POST", "/auth/sign-out-everywhere"),
        ("PUT", "/settings/{key}"),
        ("POST", "/items"),
        ("PATCH", "/items/{hid}"),
        ("POST", "/items/retire"),
        ("POST", "/items/delete"),
        ("POST", "/imports/{hid}/apply"),
        ("POST", "/items/bulk-update/{hid}/apply"),
        ("DELETE", "/addresses/{hid}"),
        ("PUT", "/reference-files/{hid}/content"),
        ("POST", "/renewals/alert/seen"),
    ):
        assert kinds[where] == load.KEPT, where
    # What stands apart, all of it: never refused, and in no measure.
    assert {where for where, kind in kinds.items() if kind == load.APART} == {
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/about"),
        ("GET", "/about/load"),
        ("GET", "/openapi.json"),
        ("GET", "/settings"),
    }


def test_a_request_is_what_the_route_that_answers_it_is() -> None:
    kinds = busy.Kinds(ROUTERS, API_PREFIX)
    assert kinds.of("GET", f"{API}/items") == load.READ
    assert kinds.of("GET", f"{API}/items/{NOWHERE}") == load.READ
    assert kinds.of("PATCH", f"{API}/items/{NOWHERE}") == load.KEPT
    # A path of one route to one method and of another to another.
    assert kinds.of("POST", f"{API}/items/bulk-update") == load.LONG
    assert kinds.of("GET", f"{API}/items/bulk-update") == load.READ
    assert kinds.of("POST", f"{API}/items/query") == load.READ
    assert kinds.of("POST", f"{API}/items/retire") == load.KEPT
    assert kinds.of("GET", f"{API}/reports/coverage") == load.LONG
    assert kinds.of("GET", f"{API}/about/load") == load.APART
    assert kinds.of("PUT", f"{API}/settings/busy_cpu_percent") == load.KEPT
    # What no route answers is left to the router, which says so at once.
    assert kinds.of("GET", f"{API}/nothing/here") == load.APART
    assert kinds.of("DELETE", f"{API}/items") == load.APART


def test_what_a_request_is_is_remembered_and_what_is_remembered_has_an_end() -> None:
    kinds = busy.Kinds(ROUTERS, API_PREFIX)
    for number in range(busy.MOST_REMEMBERED + 10):
        assert kinds.of("GET", f"{API}/items/{number}") == load.READ
    assert len(kinds._found) <= busy.MOST_REMEMBERED
    assert kinds.of("GET", f"{API}/items/0") == load.READ
    assert kinds.of("GET", f"{API}/reports/summary") == load.LONG


# --- what a server refuses, by its health ---------------------------------------------

LONG = (
    ("GET", "/reports/summary"),
    ("GET", "/reports/duplicates"),
    ("POST", "/reports/capacity/try"),
    ("POST", "/exports"),
    ("POST", "/exports/all"),
    ("POST", "/users/export"),
    ("POST", "/imports/preview"),
    ("POST", "/items/bulk-update"),
    ("POST", "/kept-answers/check"),
)
READS = (
    ("GET", "/items"),
    ("POST", "/items/query"),
    ("GET", f"/items/{NOWHERE}/children"),
    ("GET", "/audit-events"),
    ("GET", "/tags"),
    ("GET", "/choices"),
    ("GET", f"/items/{NOWHERE}"),
    ("GET", "/geography/tree"),
    ("GET", "/renewals/alert"),
)
NEVER = (
    ("GET", "/auth/me"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("GET", "/about"),
    ("GET", "/about/load"),
    ("GET", "/settings"),
    ("GET", "/openapi.json"),
    ("POST", "/tags"),
    ("PATCH", f"/items/{NOWHERE}"),
    ("DELETE", f"/addresses/{NOWHERE}"),
    ("POST", f"/imports/{NOWHERE}/apply"),
    ("GET", "/no-such-route"),
)


@pytest.fixture
def tags_take(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Have the list of the tags take as long as a test says, by the clock of the
    measures: `tags_take["seconds"]`, a quarter of a second unless said."""
    from hirdir.domain import tags

    listed = tags.list_tags
    takes = {"seconds": 0.25}

    def slow(db: Session) -> Any:
        clock.now += takes["seconds"]
        return listed(db)

    monkeypatch.setattr(tags, "list_tags", slow)
    return takes


def reads(
    client: TestClient, headers: dict, clock: Clock, takes: dict[str, float], seconds: float
) -> list[int]:
    """Have twenty-one reads of the tags take so long each, which are reads enough to
    be load, then let a second pass, so that the measures are read again. Return how
    each was answered."""
    takes["seconds"] = seconds
    answers = [client.get(f"{API}/tags", headers=headers).status_code for _ in range(21)]
    takes["seconds"] = 0.0
    clock.now += 1.0
    return answers


# The measure of time alone, of thirds of a tenth of a second, over half a minute.
QUICK_TO_TIRE = Ceiling(response_ms=300, cpu_percent=0, over_seconds=30)


def refused(client: TestClient, headers: dict, asked: tuple[tuple[str, str], ...]) -> set:
    """Return which of the requests asked are answered as busy. What a request is
    answered otherwise does not matter here: found or not, well formed or not."""
    return {
        (method, path)
        for method, path in asked
        if client.request(method, API + path, headers=headers, json={}).status_code == 503
    }


def test_what_is_refused_at_each_word_of_the_health(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    """Nothing is refused until orange; at orange what is long by nature; at red every
    read as well. And never a sign-in, a change, health, About, the settings."""
    everything = (*LONG, *READS, *NEVER)
    tags_take["seconds"] = 0.0
    meter_of(client).hold(QUICK_TO_TIRE)

    def now() -> tuple[str, list[str], str]:
        said = measured(client, admin)
        return said["health"], said["because"], said["refusing"]

    assert now() == ("good", [], "nothing")
    assert refused(client, admin, everything) == set()
    # Yellow: reads of 150 ms against thirds of 100. Nothing is refused.
    clock.now += 31
    assert set(reads(client, admin, clock, tags_take, 0.15)) == {200}
    assert now() == ("slow", ["response_ms"], "nothing")
    assert refused(client, admin, everything) == set()
    # Orange: what is long by nature is refused, and the lists go on.
    clock.now += 31
    assert set(reads(client, admin, clock, tags_take, 0.25)) == {200}
    assert now() == ("very_slow", ["response_ms"], "long")
    assert refused(client, admin, everything) == set(LONG)
    # Red: every read is refused as well.
    clock.now += 31
    assert set(reads(client, admin, clock, tags_take, 0.5)) == {200}
    assert now() == ("busy", ["response_ms"], "reads")
    assert refused(client, admin, everything) == {*LONG, *READS}
    answer = client.get(f"{API}/items", headers=admin)
    assert answer.status_code == 503
    assert said(answer) == "busy; refusing=reads"
    assert answer.json()["busy"] == {
        "health": "busy",
        "because": ["response_ms"],
        "refusing": "reads",
        "retry_after": 5,
    }
    # The slow reads are out of the measure half a minute after they came. It was red
    # a moment ago: the reads come back, and what is long does not yet.
    clock.now += 29
    assert now() == ("very_slow", ["response_ms"], "long")
    assert refused(client, admin, everything) == set(LONG)
    # Half a minute after it was last red, everything is answered again.
    clock.now += 2
    assert now() == ("good", [], "nothing")
    assert refused(client, admin, everything) == set()


def test_the_processor_refuses_what_is_long_and_never_the_reads(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    everything = (*LONG, *READS, *NEVER)
    assert refused(client, admin, everything) == set()
    # Past its ceiling the health is orange at the least.
    clock.busy()
    said = measured(client, admin)
    assert (said["health"], said["because"], said["refusing"]) == (
        "very_slow",
        ["cpu_percent"],
        "long",
    )
    assert refused(client, admin, everything) == set(LONG)
    # However long it lasts, the processor alone never refuses a read.
    for _ in range(6):
        clock.busy()
        assert measured(client, admin)["health"] == "very_slow"
    assert refused(client, admin, everything) == set(LONG)
    # Under the ceiling again, everything is answered again, at once.
    clock.idle()
    assert measured(client, admin)["refusing"] == "nothing"
    assert refused(client, admin, everything) == set()


def test_a_busy_server_still_signs_in_stores_a_change_and_serves_the_page(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    meter_of(client).hold(QUICK_TO_TIRE)
    reads(client, admin, clock, tags_take, 0.5)
    assert measured(client, admin)["refusing"] == "reads"
    ivy = sign_in(client, "ivy", "inventory-code")
    made = client.post(f"{API}/tags", json={"label": "kept"}, headers=ivy)
    assert made.status_code == 201, made.text
    changed = client.patch(
        f"{API}/tags/{made.json()['hid']}",
        json={"row_version": made.json()["row_version"], "label": "kept on"},
        headers=ivy,
    )
    assert changed.status_code == 200, changed.text
    assert client.get(f"{API}/tags", headers=ivy).status_code == 503
    # The page itself and what is not of the API.
    assert client.get("/").status_code == 200
    assert client.get("/items").status_code == 200
    # The ceiling itself is reached and set, by the Admin who set it too low.
    listed = client.get(f"{API}/settings", headers=admin)
    assert listed.status_code == 200
    put(client, admin, "busy_cpu_percent", 0)
    put(client, admin, "busy_response_ms", 0)
    assert meter_of(client).ceiling.none
    assert client.get(f"{API}/tags", headers=ivy).status_code == 200


def test_the_answer_to_a_request_that_is_refused(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    clock.busy()
    answer = client.get(f"{API}/reports/summary", headers=admin)
    assert answer.status_code == 503
    assert answer.headers["content-type"] == "application/problem+json"
    assert answer.headers["retry-after"] == "5"
    assert answer.json() == {
        "type": "about:blank",
        "title": "Busy",
        "status": 503,
        "detail": "the server is busy and this request was not answered; try again shortly",
        "errors": [],
        "busy": {
            "health": "very_slow",
            "because": ["cpu_percent"],
            "refusing": "long",
            "retry_after": 5,
        },
    }
    # It carries what every answer carries, and is no more kept than any other.
    assert answer.headers["x-request-id"]
    # The header of an answer that is a refusal says what its body says.
    assert said(answer) == "very_slow; refusing=long"
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in answer.headers
    # A page of a list is answered while the health is orange.
    assert client.get(f"{API}/items", headers=admin).status_code == 200


def test_a_refusal_is_given_before_who_asks_is_looked_at(client: TestClient, clock: Clock) -> None:
    # Nothing of the request is done, and nothing is asked of the database for it.
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    assert client.get(f"{API}/reports/summary").status_code == 401
    clock.busy()
    app: Any = client.app
    event.listen(app.state.engine, "before_cursor_execute", note)
    try:
        assert client.get(f"{API}/reports/summary").status_code == 503
        anyone = {"Authorization": "Bearer x"}
        assert client.get(f"{API}/reports/summary", headers=anyone).status_code == 503
    finally:
        event.remove(app.state.engine, "before_cursor_execute", note)
    assert statements == []


def test_a_body_that_is_refused_is_read_and_the_answer_given(
    client: TestClient, inventory: dict, clock: Clock
) -> None:
    clock.busy()
    file = "name,serial_number\n" + "".join(f"sw-{n},SN{n:06}\n" for n in range(5000))
    answer = client.post(
        f"{API}/imports/preview",
        params={"entity": "items"},
        content=file,
        headers={**inventory, "Content-Type": "text/csv"},
    )
    assert answer.status_code == 503
    assert answer.json()["busy"]["refusing"] == "long"
    # Nothing of it was kept.
    clock.idle()
    assert client.get(f"{API}/imports", headers=inventory).json()["total"] == 0


def test_a_request_under_a_prefix_is_what_its_route_is(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    under = {**admin, "X-Forwarded-Prefix": "/inventory"}
    clock.busy()
    assert client.get(f"{API}/reports/summary", headers=under).status_code == 503
    assert client.get(f"/inventory{API}/reports/summary", headers=under).status_code == 503
    assert client.get(f"{API}/tags", headers=under).status_code == 200
    assert client.get(f"{API}/about/load", headers=under).status_code == 200


def test_an_answer_of_busy_is_counted_and_is_in_no_time(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    clock.busy()
    before = measured(client, admin)["totals"]
    for _ in range(7):
        assert client.get(f"{API}/reports/summary", headers=admin).status_code == 503
    after = measured(client, admin)
    assert after["totals"]["busy"] == before["busy"] + 7 == 7
    assert after["points"]["busy"] == [0, 0, 7]
    # The seven and the read before them, and nothing else, were answered meanwhile.
    assert after["totals"]["requests"] == before["requests"] + 8
    assert after["totals"]["ok"] == before["ok"] + 1
    assert after["totals"]["failed"] == before["failed"] == 0
    assert after["totals"]["bands"]["counts"] == [0, 0, 0, 0]


def test_no_ceiling_refuses_nothing_however_busy(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    meter_of(client).hold(load.NO_CEILING)
    clock.busy()
    clock.busy()
    clock.busy()
    assert refused(client, admin, (*LONG, *READS, *NEVER)) == set()
    now = measured(client, admin)
    assert (now["health"], now["because"], now["refusing"]) == ("good", [], "nothing")
    assert now["measures"]["cpu_percent"] == 90.0
    assert now["ceiling"] == {
        "response_ms": 0,
        "cpu_percent": 0,
        "over_seconds": 30,
        "fewest_requests": 21,
    }


def test_the_tests_of_this_process_start_with_no_ceiling(client: TestClient) -> None:
    assert meter_of(client).ceiling == load.NO_CEILING


# --- every request is measured -------------------------------------------------------


def test_every_request_is_counted_by_how_it_was_answered(
    client: TestClient, admin: dict, viewer: dict, clock: Clock
) -> None:
    meter_of(client).hold(load.NO_CEILING)
    start = measured(client, admin)["totals"]
    assert client.get(f"{API}/tags", headers=viewer).status_code == 200
    assert client.post(f"{API}/tags", json={"label": "a"}, headers=admin).status_code == 201
    assert client.get(f"{API}/items/{NOWHERE}", headers=viewer).status_code == 404
    assert client.post(f"{API}/tags", json={"label": "b"}, headers=viewer).status_code == 403
    assert client.get(f"{API}/tags").status_code == 401
    assert client.get(f"{API}/nothing").status_code == 404
    # The page and its files are counted too.
    assert client.get("/").status_code == 200
    now = measured(client, admin)["totals"]
    assert now["ok"] - start["ok"] == 4  # the three, and the read of the measures before
    assert now["not_accepted"] - start["not_accepted"] == 4
    assert (now["failed"], now["busy"]) == (0, 0)
    assert now["requests"] == now["ok"] + now["not_accepted"]
    # The reads and the changes of the API are in the bands of time, however they were
    # answered: not the measures themselves, what no route answers, or the page.
    assert now["bands"]["counts"] == [5, 0, 0, 0]


def test_a_request_that_fails_is_counted_as_failed(
    client: TestClient, admin: dict, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("as nobody foresaw")

    from hirdir.domain import tags

    monkeypatch.setattr(tags, "list_tags", broken)
    assert client.get(f"{API}/tags", headers=admin).status_code == 500
    now = measured(client, admin)
    assert now["totals"]["failed"] == 1
    assert now["in_flight"] == {"count": 0, "oldest_ms": None}


def test_the_time_of_an_answer_is_to_its_last_byte(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    assert client.get(f"{API}/tags", headers=admin).status_code == 200
    now = measured(client, admin)
    assert now["totals"]["response_ms"] == {
        "low": 250.0,
        "average": 250.0,
        "high": 250.0,
        "p50": 250.0,
        "p95": 250.0,
        "p99": 250.0,
    }
    assert (now["points"]["high_ms"], now["points"]["p95_ms"]) == ([250.0], [250.0])


def test_one_slow_page_is_the_colour_and_twenty_one_reads_are_load(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    meter_of(client).hold(Ceiling(response_ms=300, cpu_percent=0, over_seconds=300))
    tags_take["seconds"] = 0.5
    # One slow page on a quiet server: the mark is red, the slow answer says so itself,
    # and nothing is refused.
    slow = client.get(f"{API}/tags", headers=admin)
    assert (slow.status_code, said(slow)) == (200, "busy; refusing=nothing")
    clock.now += 1.0
    now = measured(client, admin)
    assert (now["measures"]["response_ms"], now["measures"]["requests"]) == (500.0, 1)
    assert (now["health"], now["because"], now["refusing"]) == ("busy", ["response_ms"], "nothing")
    # About and the settings, asked for as often as one likes, are in no measure.
    for _ in range(30):
        measured(client, admin)
        assert client.get(f"{API}/settings", headers=admin).status_code == 200
    assert measured(client, admin)["measures"]["requests"] == 1
    # Nineteen of them are red still, and too few to be load: a report and a page of a
    # list are answered, and said to be answered by a server that is slow.
    for _ in range(18):
        assert client.get(f"{API}/tags", headers=admin).status_code == 200
    clock.now += 1.0
    report = client.get(f"{API}/reports/summary", headers=admin)
    assert (report.status_code, said(report)) == (200, "busy; refusing=nothing")
    now = measured(client, admin)
    assert now["measures"]["reads"] == 19 < now["ceiling"]["fewest_requests"]
    assert (now["health"], now["refusing"]) == ("busy", "nothing")
    # A twentieth read, a quick one: of twenty the measure is one request alone, the
    # slowest, and one request refuses nothing.
    tags_take["seconds"] = 0.0
    assert client.get(f"{API}/choices", headers=admin).status_code == 200
    clock.now += 1.0
    now = measured(client, admin)
    assert (now["measures"]["reads_ms"], now["measures"]["reads"]) == (500.0, 20)
    assert (now["health"], now["refusing"]) == ("busy", "nothing")
    # A twenty-first, and they are load: the second slowest of them is the measure.
    assert client.get(f"{API}/choices", headers=admin).status_code == 200
    clock.now += 1.0
    now = measured(client, admin)
    assert (now["measures"]["response_ms"], now["measures"]["requests"]) == (500.0, 21)
    assert (now["measures"]["reads_ms"], now["measures"]["reads"]) == (500.0, 21)
    assert (now["health"], now["because"], now["refusing"]) == ("busy", ["response_ms"], "reads")
    assert now["totals"]["response_ms"]["p50"] == now["totals"]["response_ms"]["p95"] == 500.0
    # A third and two thirds of the ceiling, and the ceiling; all nineteen are past it.
    assert now["totals"]["bands"] == {
        "bounds_ms": [100.0, 200.0, 300.0],
        "counts": [2, 0, 0, 19],
    }
    # A report and a page of a list are refused, and a change is stored.
    assert client.get(f"{API}/reports/summary", headers=admin).status_code == 503
    refusal = client.get(f"{API}/items", headers=admin)
    assert (refusal.status_code, said(refusal)) == (503, "busy; refusing=reads")
    busy = refusal.json()["busy"]
    assert said(refusal) == f"{busy['health']}; refusing={busy['refusing']}"
    assert client.post(f"{API}/tags", json={"label": "a"}, headers=admin).status_code == 201


def test_saves_that_are_slow_make_the_mark_red_and_refuse_no_read(
    client: TestClient, admin: dict, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Something holds the one writer, and the saves wait behind it: the health is of
    everything a person meets, and what is refused of the reads alone."""
    from hirdir.domain import tags

    created = tags.create_tag

    def waits(*arguments: Any) -> Any:
        clock.now += 3.5
        return created(*arguments)

    meter_of(client).hold(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=300))
    for _ in range(30):
        assert client.get(f"{API}/choices", headers=admin).status_code == 200
    monkeypatch.setattr(tags, "create_tag", waits)
    for number in range(5):
        saved = client.post(f"{API}/tags", json={"label": f"tag {number}"}, headers=admin)
        assert saved.status_code == 201, saved.text
    # The save that waited says red itself, and that nothing is refused.
    assert said(saved) == "busy; refusing=nothing"
    clock.now += 1.0
    now = measured(client, admin)
    assert (now["measures"]["response_ms"], now["measures"]["requests"]) == (3500.0, 35)
    assert (now["measures"]["reads_ms"], now["measures"]["reads"]) == (0.0, 30)
    assert (now["health"], now["because"], now["refusing"]) == ("busy", ["response_ms"], "nothing")
    # Enough reads to be load, and they are quick: every read and every report is taken.
    for path in ("/items", "/tags", "/reports/summary"):
        answer = client.get(API + path, headers=admin)
        assert (answer.status_code, said(answer)) == (200, "busy; refusing=nothing"), path


# --- the health of the server on every answer ----------------------------------------


def test_every_answer_of_the_api_carries_the_health_and_the_page_carries_none(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    well = client.get(f"{API}/tags", headers=viewer)
    assert (well.status_code, said(well)) == (200, GOOD)
    for answer, status in (
        (client.get(f"{API}/tags"), 401),
        (client.post(f"{API}/tags", json={"label": "b"}, headers=viewer), 403),
        (client.get(f"{API}/items/{NOWHERE}", headers=viewer), 404),
        (client.get(f"{API}/no-such-route"), 404),
        (client.post(f"{API}/tags", json={}, headers=admin), 422),
        (client.get(f"{API}/health/live"), 200),
        (client.get(f"{API}/about/load", headers=viewer), 200),
    ):
        assert answer.status_code == status
        assert said(answer) == GOOD, status
    # The page itself and its files say nothing of it.
    for path in ("/", "/items", "/assets/no-such-file.js", "/favicon.ico"):
        assert "x-hirdir-health" not in client.get(path).headers, path


def test_the_health_on_an_answer_is_each_of_its_four_words(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    meter_of(client).hold(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=300))

    def after_reads_of(seconds: float) -> tuple[list[int], int, str, dict[str, Any]]:
        """Have twenty reads take so long each, and return how they were answered, how
        the next read is and what it says, with what the measures say."""
        answers = reads(client, admin, clock, tags_take, seconds)
        answer = client.get(f"{API}/choices", headers=admin)
        return answers, answer.status_code, said(answer), measured(client, admin)

    answers, status, health, now = after_reads_of(0.5)
    assert (set(answers), status, health) == ({200}, 200, GOOD)
    assert (now["health"], now["measures"]["response_ms"]) == ("good", 500.0)
    answers, status, health, now = after_reads_of(1.5)
    assert (set(answers), status, health) == ({200}, 200, "slow; refusing=nothing")
    assert (now["health"], now["refusing"]) == ("slow", "nothing")
    answers, status, health, now = after_reads_of(2.5)
    assert (set(answers), status, health) == ({200}, 200, "very_slow; refusing=long")
    assert (now["health"], now["refusing"]) == ("very_slow", "long")
    refusal = client.get(f"{API}/reports/summary", headers=admin)
    assert (refusal.status_code, said(refusal)) == (503, "very_slow; refusing=long")
    # Red: of sixty-one and more the measure is the fourth slowest, so the fifth read
    # that would take three and a half seconds is refused, and every read after it.
    answers, status, health, now = after_reads_of(3.5)
    assert answers == [200] * 4 + [503] * 17
    assert (status, health) == (503, "busy; refusing=reads")
    assert (now["health"], now["refusing"]) == ("busy", "reads")
    assert now["measures"]["response_ms"] == 3500.0
    assert now["totals"]["bands"] == {
        "bounds_ms": [1000.0, 2000.0, 3000.0],
        "counts": [24, 21, 21, 4],
    }


def test_the_health_is_very_slow_where_the_processor_is_past_its_ceiling(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    assert said(client.get(f"{API}/tags", headers=admin)) == GOOD
    clock.busy()
    answer = client.get(f"{API}/tags", headers=admin)
    assert (answer.status_code, said(answer)) == (200, "very_slow; refusing=long")
    now = measured(client, admin)
    # A request or two in the measure: the processor refuses what is long whatever the count.
    assert (now["health"], now["because"], now["refusing"]) == (
        "very_slow",
        ["cpu_percent"],
        "long",
    )
    assert now["measures"]["reads"] < now["ceiling"]["fewest_requests"]
    clock.idle()
    assert said(client.get(f"{API}/tags", headers=admin)) == GOOD


def test_with_no_ceiling_the_health_is_said_all_the_same(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    meter_of(client).hold(Ceiling(response_ms=0, cpu_percent=0, over_seconds=300))
    reads(client, admin, clock, tags_take, 1.5)
    assert said(client.get(f"{API}/choices", headers=admin)) == "slow; refusing=nothing"
    assert set(reads(client, admin, clock, tags_take, 4.0)) == {200}
    # Red past three seconds, with more than twenty requests, and nothing is refused.
    for path in ("/reports/summary", "/items"):
        answer = client.get(API + path, headers=admin)
        assert (answer.status_code, said(answer)) == (200, "busy; refusing=nothing"), path
    now = measured(client, admin)
    assert (now["health"], now["because"], now["refusing"]) == (
        "busy",
        ["response_ms"],
        "nothing",
    )
    assert now["measures"]["reads"] > now["ceiling"]["fewest_requests"]
    assert now["totals"]["bands"]["bounds_ms"] == [1000.0, 2000.0, 3000.0]


def test_an_answer_that_was_slow_says_so_itself(
    client: TestClient, admin: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    """The case of the second review: on a server that has seen nothing, an answer that
    took three and a third seconds. A page's requests arrive together: were the header
    what it was when they arrived, a page of four seconds would show green."""
    meter_of(client).hold(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30))
    tags_take["seconds"] = 3.3
    slow = client.get(f"{API}/tags", headers=admin)
    assert (slow.status_code, said(slow)) == (200, "busy; refusing=nothing")
    # And so says what is asked after it, for as long as it is in the measure.
    tags_take["seconds"] = 0.0
    assert said(client.get(f"{API}/choices", headers=admin)) == "busy; refusing=nothing"
    clock.now += 27
    assert said(client.get(f"{API}/choices", headers=admin)) == GOOD
    # Each band of time is said by the answer that was in it.
    for seconds, health in ((1.5, "slow"), (2.5, "very_slow")):
        clock.now += 31
        tags_take["seconds"] = seconds
        assert said(client.get(f"{API}/tags", headers=admin)) == f"{health}; refusing=nothing"


def test_the_header_is_one_of_twelve_values_made_once() -> None:
    from hirdir.app import HEALTH_SAID

    assert len(HEALTH_SAID) == len(set(HEALTH_SAID.values())) == 12
    for (health, refusing), value in HEALTH_SAID.items():
        assert value == f"{health}; refusing={refusing}"
        # Read by splitting at the first semicolon and at the equals sign.
        word, _, rest = value.partition("; ")
        assert (word, rest.partition("=")) == (health, ("refusing", "=", refusing))


def test_the_health_costs_a_request_nothing_it_is_read_from_memory(
    client: TestClient, admin: dict, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = meter_of(client)
    read = []
    reads = meter._read

    def counting(now: float) -> load.Reading:
        read.append(now)
        return reads(now)

    monkeypatch.setattr(meter, "_read", counting)
    for _ in range(50):
        assert said(client.get(f"{API}/tags", headers=admin)) == GOOD
    # Fifty answers within one second of the clock: worked out once, and given fifty times.
    assert len(read) == 1
    clock.now += 1.0
    assert client.get(f"{API}/tags", headers=admin).status_code == 200
    assert len(read) == 2


def test_a_share_of_the_processor_past_100_is_shown_as_it_is(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    meter_of(client).hold(Ceiling(response_ms=0, cpu_percent=150, over_seconds=10))
    # Several requests in the database at once: two processors' worth, for ten seconds.
    clock.now, clock.cpu = 10.0, 20.0
    now = measured(client, admin)
    assert now["measures"]["cpu_percent"] == 200.0
    assert (now["health"], now["because"], now["refusing"]) == (
        "very_slow",
        ["cpu_percent"],
        "long",
    )
    assert now["points"]["cpu_percent"][:2] == [200.0, 200.0]
    assert now["totals"]["cpu_percent"] == {"low": 200.0, "average": 200.0, "high": 200.0}
    assert now["ceiling"]["cpu_percent"] == 150


# --- the slowest requests, and who met what ------------------------------------------


def test_a_slow_request_is_listed_by_its_route_and_never_by_its_path(
    client: TestClient, admin: dict, viewer: dict, clock: Clock, tags_take: dict[str, float]
) -> None:
    slow = client.get(f"{API}/tags", params={"q": "a-word-of-a-search"}, headers=viewer)
    assert slow.status_code == 200
    missing = client.get(f"{API}/items/{NOWHERE}", headers=admin)
    assert missing.status_code == 404
    answer = client.get(f"{API}/about/load", headers=admin)
    first, second = answer.json()["slowest"]
    assert first == {
        "at": "2027-03-02T14:00:00Z",
        "method": "GET",
        # The route as its pattern: not the path as it was asked, and not the query.
        "route": f"{API}/tags",
        "ms": 250.0,
        "status": 200,
        "request_id": slow.headers["x-request-id"],
        "who": {"kind": "person", "hid": hid_of(client, admin, "vic"), "username": "vic"},
    }
    assert (second["route"], second["status"], second["who"]["username"]) == (
        f"{API}/items/{{hid}}",
        404,
        "ada",
    )
    assert second["request_id"] == missing.headers["x-request-id"]
    assert NOWHERE not in answer.text
    assert "a-word-of-a-search" not in answer.text


def hid_of(client: TestClient, admin: dict, username: str) -> str:
    users = client.get(f"{API}/users", headers=admin).json()["items"]
    return next(user["hid"] for user in users if user["username"] == username)


def test_what_is_long_by_nature_is_listed_apart_and_about_in_neither_list(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    assert client.get(f"{API}/reports/summary", headers=admin).status_code == 200
    assert client.get(f"{API}/tags", headers=admin).status_code == 200
    for _ in range(3):
        measured(client, admin)
    now = measured(client, admin)
    assert [(one["route"], one["who"]["username"]) for one in now["slowest_long"]] == [
        (f"{API}/reports/summary", "ada")
    ]
    assert [one["route"] for one in now["slowest"]] == [f"{API}/tags"]


def test_who_asked_and_what_each_met(
    client: TestClient,
    admin: dict,
    inventory: dict,
    viewer: dict,
    clock: Clock,
    tags_take: dict[str, float],
) -> None:
    meter_of(client).hold(Ceiling(response_ms=3000, cpu_percent=0, over_seconds=30))
    tags_take["seconds"] = 0.0
    # The viewer meets one read in each band, the last of them past the ceiling.
    for seconds in (0.5, 1.5, 2.5, 3.5):
        tags_take["seconds"] = seconds
        assert client.get(f"{API}/tags", headers=viewer).status_code == 200
    tags_take["seconds"] = 0.0
    # The Inventory user: two quick reads, and a change that is refused them: a 403.
    for _ in range(2):
        assert client.get(f"{API}/tags", headers=inventory).status_code == 200
    assert (
        client.put(
            f"{API}/settings/currency", json={"row_version": 0, "value": "EUR"}, headers=inventory
        ).status_code
        == 403
    )
    # A sign-in that fails, and a token that does not hold: nobody is named for them.
    wrong = client.post(f"{API}/auth/sign-in", json={"username": "ada", "access_code": "no"})
    assert wrong.status_code == 401
    assert (
        client.get(f"{API}/tags", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    )
    measured(client, admin)
    now = measured(client, admin)
    assert [(one["username"], one["kind"]) for one in now["people"]] == [
        # Whoever had it worst first: the viewer met a read past the ceiling. The other
        # two met nothing slow, and are listed by name.
        ("vic", "person"),
        ("ada", "person"),
        ("ivy", "person"),
        (None, "unnamed"),
    ]
    vic, ada, ivy, unnamed = now["people"]
    assert (vic["requests"], vic["bands"], vic["slowest_ms"]) == (4, [1, 1, 1, 1], 3500.0)
    assert (vic["busy"], vic["failed"]) == (0, 0)
    assert vic["hid"] == hid_of(client, admin, "vic")
    assert (ivy["requests"], ivy["bands"], ivy["slowest_ms"]) == (3, [3, 0, 0, 0], 0.0)
    # The Admin has only read the measures, which are in none of the bands.
    assert (ada["requests"], ada["bands"], ada["slowest_ms"]) == (1, [0, 0, 0, 0], None)
    assert (unnamed["hid"], unnamed["requests"], unnamed["bands"]) == (None, 2, [2, 0, 0, 0])
    assert vic["last_at"] == "2027-03-02T14:00:04.500000Z"


def test_a_service_token_is_listed_as_the_service_account_it_is_of(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    made = client.post(
        f"{API}/users",
        headers=admin,
        json={"username": "collector", "kind": "service", "role": "viewer"},
    )
    assert made.status_code == 201, made.text
    account = made.json()["user"]["hid"]
    token = client.post(
        f"{API}/users/{account}/service-tokens", headers=admin, json={"name": "nightly"}
    )
    assert token.status_code == 201, token.text
    service = {"Authorization": f"Bearer {token.json()['secret']}"}
    assert client.get(f"{API}/tags", headers=service).status_code == 200
    now = measured(client, admin)
    row = next(one for one in now["people"] if one["username"] == "collector")
    assert (row["kind"], row["hid"], row["requests"]) == ("service", account, 1)
    listed = next(one for one in now["slowest"] if one["who"]["username"] == "collector")
    assert listed["who"] == {"kind": "service", "hid": account, "username": "collector"}


def test_a_request_that_is_refused_is_counted_for_who_asked_where_that_is_known(
    client: TestClient, admin: dict, viewer: dict, clock: Clock
) -> None:
    # The Admin has asked of this server of late, and is remembered; the viewer has not.
    assert client.get(f"{API}/tags", headers=admin).status_code == 200
    clock.busy()
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    app: Any = client.app
    event.listen(app.state.engine, "before_cursor_execute", note)
    try:
        for headers in (admin, admin, viewer, {"Authorization": "Bearer nonsense"}, {}):
            assert client.get(f"{API}/reports/summary", headers=headers).status_code == 503
    finally:
        event.remove(app.state.engine, "before_cursor_execute", note)
    # Who asked was learnt without the database.
    assert statements == []
    now = measured(client, admin)
    by_name = {one["username"]: one for one in now["people"]}
    assert (by_name["ada"]["busy"], by_name["ada"]["requests"]) == (2, 3)
    # The viewer's token holds, and nobody has seen its account: it is not named.
    assert "vic" not in by_name
    assert (by_name[None]["busy"], by_name[None]["requests"]) == (3, 3)
    assert now["totals"]["busy"] == 5
    # Once the viewer has asked, what is refused them is counted for them.
    assert client.get(f"{API}/tags", headers=viewer).status_code == 200
    assert client.get(f"{API}/reports/summary", headers=viewer).status_code == 503
    by_name = {one["username"]: one for one in measured(client, admin)["people"]}
    assert (by_name["vic"]["busy"], by_name["vic"]["requests"]) == (1, 2)


# --- the ways out of the gateway -----------------------------------------------------


class Wire:
    """One request given to the gateway by hand: what it is, what its sender sends,
    piece by piece, and what is sent back."""

    def __init__(
        self,
        meter: load.Meter,
        method: str = "GET",
        path: str = f"{API}/tags",
        length: int | None = None,
        pieces: tuple[Message, ...] = ({"type": "http.request", "body": b"", "more_body": False},),
    ) -> None:
        headers = [] if length is None else [(b"content-length", str(length).encode())]
        self.scope: Scope = {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("192.0.2.10", 40000),
            "app": SimpleNamespace(state=SimpleNamespace(load=meter)),
        }
        self.pieces = list(pieces)
        self.sent: list[Message] = []
        self.gone = asyncio.Event()

    async def receive(self) -> Message:
        if self.pieces:
            return self.pieces.pop(0)
        # Nothing more comes, for as long as the request lasts.
        await self.gone.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    @property
    def status(self) -> int | None:
        return self.sent[0]["status"] if self.sent else None


KINDS = busy.Kinds(ROUTERS, API_PREFIX)


def through(inner: ASGIApp, wire: Wire) -> None:
    """Send one request through the gateway to an application, to its end."""
    gateway = Gateway(inner, trusted_proxies=(), limits=lambda: (100, 100), kinds=KINDS)
    asyncio.run(gateway(wire.scope, wire.receive, wire.send))


def counted(meter: load.Meter, clock: Clock) -> tuple[int, int, int, int]:
    """Return what a meter has counted as answered well, not taken as asked and failed,
    and how many requests it still holds in flight."""
    picture = meter.picture(*clock())
    return picture.ok, picture.not_accepted, picture.failed, picture.in_flight


@pytest.fixture
def ticking(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The clock of the measures in the hands of a test that has no application."""
    held = Clock()
    monkeypatch.setattr(measures, "clock", held)
    return held


def a_meter() -> load.Meter:
    return load.Meter(0.0, 0.0, started_at=STARTED, ceiling=load.NO_CEILING)


async def _begin(send: Send, status: int = 200) -> None:
    await send({"type": "http.response.start", "status": status, "headers": []})


def test_an_answer_that_is_sent_to_its_last_byte_is_counted_once(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        # As the check of the sign-in leaves who asks.
        scope["state"]["who"] = load.Who("hid-ada", "ada")
        await _begin(send, 201)
        await send({"type": "http.response.body", "body": b"{}"})

    meter = a_meter()
    wire = Wire(meter, path=f"{API}/items/{NOWHERE}")
    through(inner, wire)
    assert counted(meter, ticking) == (1, 0, 0, 0)
    # What is kept of it is its route, and who asked where the application left that.
    (slow,) = meter.picture(*ticking()).slowest
    assert (slow.method, slow.route, slow.status, slow.who) == (
        "GET",
        f"{API}/items/{{hid}}",
        201,
        load.Who("hid-ada", "ada"),
    )
    assert slow.request_id == wire.scope["state"]["request_id"]
    # It is a read of the API: in the bands of time, and with the health on it.
    assert meter.picture(*ticking()).bands == (1, 0, 0, 0)
    assert (b"x-hirdir-health", GOOD.encode()) in wire.sent[0]["headers"]


def test_a_report_that_takes_long_is_in_no_measure_of_time(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        # A report takes nine seconds, and a read of the tags a hundredth of one.
        ticking.now += 9.0 if scope["path"].endswith("/reports/summary") else 0.0078125
        await _begin(send)
        await send({"type": "http.response.body", "body": b"{}"})

    meter = load.Meter(0.0, 0.0, started_at=STARTED, ceiling=Ceiling(over_seconds=300))
    for _ in range(20):
        through(inner, Wire(meter))
    for _ in range(5):
        wire = Wire(meter, path=f"{API}/reports/summary")
        through(inner, wire)
        assert (b"x-hirdir-health", GOOD.encode()) in wire.sent[0]["headers"]
    picture = meter.picture(*ticking())
    assert (picture.requests, sum(picture.bands)) == (25, 20)
    assert picture.response_ms.high == 9000.0
    assert picture.percentiles == load.Percentiles(p50=7.8125, p95=7.8125, p99=7.8125)
    assert (picture.reading.response_ms, picture.reading.health) == (7.8125, load.GOOD)


def test_a_streamed_answer_is_timed_to_its_last_byte_and_no_further(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        ticking.now += 1
        await _begin(send)
        for last in (False, False, True):
            ticking.now += 1
            await send({"type": "http.response.body", "body": b"rows", "more_body": not last})
        # What the application does once the answer is sent is not the answer's time.
        ticking.now += 60

    meter = a_meter()
    through(inner, Wire(meter))
    picture = meter.picture(*ticking())
    assert (picture.ok, picture.in_flight) == (1, 0)
    assert picture.response_ms.high == 4000.0


def test_a_file_the_server_sends_whole_is_an_answer_sent(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await _begin(send)
        await send({"type": "http.response.pathsend", "path": "/nowhere"})

    meter = a_meter()
    wire = Wire(meter, path="/assets/app.js")
    through(inner, wire)
    assert counted(meter, ticking) == (1, 0, 0, 0)
    # A file of the page is in no measure of time, and says nothing of the health.
    assert meter.picture(*ticking()).bands == (0, 0, 0, 0)
    assert not [name for name, _ in wire.sent[0]["headers"] if name == b"x-hirdir-health"]


def test_an_answer_cut_short_after_it_began_is_counted_as_failed(ticking: Clock) -> None:
    async def stops(scope: Scope, receive: Receive, send: Send) -> None:
        await _begin(send)
        await send({"type": "http.response.body", "body": b"half", "more_body": True})

    async def breaks(scope: Scope, receive: Receive, send: Send) -> None:
        await stops(scope, receive, send)
        raise RuntimeError("as nobody foresaw")

    # It began with 200, and is not counted as answered well: its last byte never went.
    meter = a_meter()
    through(stops, Wire(meter))
    assert counted(meter, ticking) == (0, 0, 1, 0)
    # An error after the answer began cannot be answered again, and is raised.
    wire = Wire(meter)
    with pytest.raises(RuntimeError):
        through(breaks, wire)
    assert [message["type"] for message in wire.sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert counted(meter, ticking) == (0, 0, 2, 0)


def test_an_error_before_any_answer_is_the_500_and_is_counted(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("as nobody foresaw")

    meter = a_meter()
    wire = Wire(meter)
    through(inner, wire)
    assert wire.status == 500
    assert b"something went wrong" in wire.sent[1]["body"]
    assert counted(meter, ticking) == (0, 0, 1, 0)


def test_an_application_that_answers_nothing_leaves_nothing_in_flight(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        return

    meter = a_meter()
    through(inner, Wire(meter))
    assert counted(meter, ticking) == (0, 0, 1, 0)


def test_a_client_that_goes_away_mid_request_leaves_nothing_in_flight(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        # It reads the body, as a route does, until the sender is gone.
        while (await receive())["type"] == "http.request":
            ticking.now += 2

    meter = a_meter()
    wire = Wire(
        meter,
        method="POST",
        length=100,
        pieces=(
            {"type": "http.request", "body": b"a" * 50, "more_body": True},
            {"type": "http.request", "body": b"a" * 50, "more_body": True},
            {"type": "http.disconnect"},
        ),
    )
    through(inner, wire)
    assert wire.sent == []
    assert counted(meter, ticking) == (0, 0, 1, 0)
    # Its time is from the last piece that came: what its sender took is not in it.
    assert meter.picture(*ticking()).response_ms.high == 2000.0


def test_a_request_that_is_given_up_leaves_nothing_in_flight(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError

    meter = a_meter()
    with pytest.raises(asyncio.CancelledError):
        through(inner, Wire(meter))
    assert counted(meter, ticking) == (0, 0, 1, 0)


def test_a_request_refused_as_too_large_is_counted_from_its_arrival(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError("a request that is too large reaches no application")

    class Slow(Wire):
        async def receive(self) -> Message:
            # The proxy is still sending what will be thrown away.
            ticking.now += 1.5
            return await super().receive()

    meter = a_meter()
    wire = Slow(
        meter,
        method="POST",
        length=101,
        pieces=(
            {"type": "http.request", "body": b"a" * 50, "more_body": True},
            {"type": "http.request", "body": b"a" * 51, "more_body": False},
        ),
    )
    through(inner, wire)
    assert wire.status == 413
    assert counted(meter, ticking) == (0, 1, 0, 0)
    assert meter.picture(*ticking()).response_ms.high == 3000.0


def test_the_time_of_an_upload_is_the_server_s_part_of_it(ticking: Clock) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive()).get("more_body"):
            pass
        # The server has the whole of it, and takes a quarter of a second over it.
        ticking.now += 0.25
        await _begin(send, 201)
        await send({"type": "http.response.body", "body": b"{}"})

    class Slow(Wire):
        async def receive(self) -> Message:
            # Each piece takes its sender ten seconds.
            ticking.now += 10
            assert meter.picture(*ticking()).oldest_ms is None
            return await super().receive()

    meter = a_meter()
    pieces = tuple(
        {"type": "http.request", "body": b"a" * 30, "more_body": more}
        for more in (True, True, False)
    )
    through(inner, Slow(meter, method="POST", length=90, pieces=pieces))
    picture = meter.picture(*ticking())
    assert (picture.ok, picture.in_flight) == (1, 0)
    assert picture.response_ms == load.Spread(250.0, 250.0, 250.0)


def test_requests_whose_body_never_comes_hold_nothing_busy_and_end_when_given_up(
    ticking: Clock,
) -> None:
    """Twenty senders give the headers of a sign-in and no body. They are in flight
    for as long as they hold on, and the server is not busy for them."""

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        raise AssertionError("no body ever comes")

    meter = load.Meter(0.0, 0.0, started_at=STARTED, ceiling=Ceiling())

    async def an_hour() -> None:
        gateway = Gateway(inner, trusted_proxies=(), limits=lambda: (100, 100), kinds=KINDS)
        wires = [
            Wire(meter, method="POST", path=f"{API}/auth/sign-in", length=40, pieces=())
            for _ in range(20)
        ]
        held = [
            asyncio.ensure_future(gateway(wire.scope, wire.receive, wire.send)) for wire in wires
        ]
        await asyncio.sleep(0)
        for _ in range(720):
            ticking.now += 5
            picture = meter.picture(*ticking())
            assert picture.reading.health == load.GOOD
            assert (picture.in_flight, picture.oldest_ms) == (20, None)
            assert meter.reading(*ticking()).refusing == load.NOTHING
        for one in held:
            one.cancel()
        await asyncio.gather(*held, return_exceptions=True)

    asyncio.run(an_hour())
    assert ticking.now == 3600
    assert counted(meter, ticking) == (0, 0, 20, 0)


def test_a_request_that_declares_no_body_is_whole_when_it_arrives(ticking: Clock) -> None:
    seen: list[float | None] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        ticking.now += 3
        seen.append(meter.picture(*ticking()).oldest_ms)
        await _begin(send)
        await send({"type": "http.response.body", "body": b"[]"})

    meter = a_meter()
    through(inner, Wire(meter))
    through(inner, Wire(meter, method="POST", length=0))
    assert seen == [3000.0, 3000.0]


# --- the settings of the ceiling -----------------------------------------------------


def test_the_settings_of_the_ceiling_are_listed_with_what_they_are_unless_set(
    client: TestClient, viewer: dict
) -> None:
    listed = {one["key"]: one for one in client.get(f"{API}/settings", headers=viewer).json()}
    assert [(listed[key]["value"], listed[key]["is_default"]) for key in load.SETTINGS] == [
        (3000, True),
        (95, True),
        (30, True),
    ]
    assert listed["busy_response_ms"]["accepts"] == (
        "a whole number of milliseconds from 0 to 600,000"
    )
    # A process whose threads work at once uses more than one processor: 100 for each.
    assert listed["busy_cpu_percent"]["accepts"] == (
        f"a whole number from 0 to {100 * PROCESSORS:,}"
    )
    assert listed["busy_over_seconds"]["accepts"] == "a whole number of seconds from 5 to 300"
    # And what is fixed of it.
    assert (
        listed["busy_fewest_requests"]["value"],
        listed["busy_fewest_requests"]["decision"],
    ) == (
        21,
        "P-265",
    )
    assert listed["busy_retry_seconds"]["value"] == 5
    assert listed["load_window_seconds"]["value"] == 600
    assert listed["load_step_seconds"]["value"] == 5
    for key in ("busy_fewest_requests", "busy_retry_seconds", "load_window_seconds"):
        assert listed[key]["fixed"] is True


def test_a_setting_of_the_ceiling_holds_from_the_moment_it_is_saved(
    client: TestClient, admin: dict
) -> None:
    meter = meter_of(client)
    assert meter.ceiling == load.NO_CEILING
    # One of them saved, and the ceiling is what the three say: the others as they are
    # unless set.
    put(client, admin, "busy_cpu_percent", 60)
    assert meter.ceiling == Ceiling(response_ms=3000, cpu_percent=60, over_seconds=30)
    put(client, admin, "busy_response_ms", 2500)
    put(client, admin, "busy_over_seconds", 45)
    assert meter.ceiling == Ceiling(response_ms=2500, cpu_percent=60, over_seconds=45)
    assert measured(client, admin)["ceiling"] == {
        "response_ms": 2500,
        "cpu_percent": 60,
        "over_seconds": 45,
        "fewest_requests": 21,
    }
    # Returned to what it is unless set.
    put(client, admin, "busy_cpu_percent", None)
    assert meter.ceiling == Ceiling(response_ms=2500, cpu_percent=95, over_seconds=45)
    # Both at 0 is no ceiling.
    put(client, admin, "busy_cpu_percent", 0)
    put(client, admin, "busy_response_ms", 0)
    assert meter.ceiling.none
    # Another setting leaves the ceiling alone.
    meter.hold(HOT)
    put(client, admin, "renewal_warning_days", 30)
    assert meter.ceiling == HOT


def test_a_setting_that_was_not_saved_changes_no_ceiling(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    meter = meter_of(client)
    for key, value in (
        ("busy_response_ms", -1),
        ("busy_response_ms", 600_001),
        ("busy_response_ms", 2.5),
        ("busy_cpu_percent", 100 * PROCESSORS + 1),
        ("busy_cpu_percent", -1),
        ("busy_cpu_percent", "95"),
        ("busy_over_seconds", 4),
        ("busy_over_seconds", 301),
        ("busy_over_seconds", 0),
    ):
        refusal = put(client, admin, key, value, expect=422)
        assert refusal["errors"][0]["field"] == "value", key
    stale = client.put(
        f"{API}/settings/busy_cpu_percent", json={"row_version": 7, "value": 50}, headers=admin
    )
    assert stale.status_code == 422
    forbidden = client.put(
        f"{API}/settings/busy_cpu_percent", json={"row_version": 0, "value": 50}, headers=viewer
    )
    assert forbidden.status_code == 403
    assert meter.ceiling == load.NO_CEILING
    # The edges are taken.
    for key, value in (
        ("busy_response_ms", 600_000),
        ("busy_cpu_percent", 100 * PROCESSORS),
        ("busy_over_seconds", 5),
        ("busy_over_seconds", 300),
    ):
        put(client, admin, key, value)
    assert meter.ceiling == Ceiling(
        response_ms=600_000, cpu_percent=100 * PROCESSORS, over_seconds=300
    )


def test_saving_a_setting_of_the_ceiling_is_audited(client: TestClient, admin: dict) -> None:
    put(client, admin, "busy_over_seconds", 60)
    events = client.get(
        f"{API}/audit-events", params={"record_type": "setting"}, headers=admin
    ).json()["items"]
    assert events[0]["action"] == "update"
    assert {"field": "value", "old": None, "new": 60} in events[0]["changes"]


def test_a_server_starts_with_the_ceiling_its_settings_have(
    ceiling_at_start: None, config: Config, db: Session, built: tuple[FastAPI, Config]
) -> None:
    # Unless set, a server has a ceiling: it is on for every server that is started.
    app = application(config, built)
    assert app.state.load.ceiling == Ceiling(response_ms=3000, cpu_percent=95, over_seconds=30)
    settings.set_setting(db, audit.SYSTEM, "busy_cpu_percent", 0, 80)
    settings.set_setting(db, audit.SYSTEM, "busy_over_seconds", 0, 20)
    db.commit()
    app = application(config, built)
    assert app.state.load.ceiling == Ceiling(response_ms=3000, cpu_percent=80, over_seconds=20)
    app.state.engine.dispose()


def test_a_database_that_cannot_be_read_leaves_a_server_its_ceiling(tmp_path: Path) -> None:
    # No database yet, as where the application is built before anything is installed:
    # the ceiling is what it is unless set, and no database is made by asking.
    config = Config(state_dir=tmp_path)
    engine = make_engine(config.database_url)
    state = SimpleNamespace(config=config, sessions=make_sessions(engine))
    assert AT_START(state) == Ceiling()
    assert list(tmp_path.iterdir()) == []
    # A database with nothing in it, as before its first migration.
    assert config.database_path is not None
    config.database_path.touch()
    assert AT_START(state) == Ceiling()
    # And a ceiling that cannot be read again stays as it was.
    measures.start(state)
    state.load.hold(HOT)
    measures.renew(state)
    assert state.load.ceiling == HOT
    engine.dispose()


def test_of_two_saves_at_the_same_moment_the_ceiling_of_the_last_read_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading the settings and giving the meter what was read are one step. Were they
    two, a save that read first and gave last would leave the older ceiling in force."""
    older = Ceiling(response_ms=1000, cpu_percent=10, over_seconds=10)
    newer = Ceiling(response_ms=2000, cpu_percent=20, over_seconds=20)
    state = SimpleNamespace(load=a_meter(), sessions=nullcontext)
    reads = iter((older, newer))
    reading, go_on = threading.Event(), threading.Event()

    def read(_db: object) -> Ceiling:
        mine = next(reads)
        if mine is older:
            # The first has read, and is held up before it gives what it read.
            reading.set()
            assert go_on.wait(10)
        return mine

    monkeypatch.setattr(settings, "ceiling", read)
    first = threading.Thread(target=measures.renew, args=(state,))
    first.start()
    assert reading.wait(10)
    second = threading.Thread(target=measures.renew, args=(state,))
    second.start()
    # The second waits for the first, where it would otherwise read and give at once.
    second.join(0.3)
    assert second.is_alive()
    go_on.set()
    first.join(10)
    second.join(10)
    assert state.load.ceiling == newer


# --- GET /about/load -----------------------------------------------------------------


def test_the_measures_are_read_by_everyone_signed_in(
    client: TestClient, admin: dict, inventory: dict, viewer: dict
) -> None:
    for headers in (admin, inventory, viewer):
        assert client.get(f"{API}/about/load", headers=headers).status_code == 200
    # One more, made by the Admin: an account with no role is signed in nowhere from
    # 0.9.15 (P-299), where it read them as About is read, so it is made View-only.
    client.post(
        f"{API}/users",
        headers=admin,
        json={"username": "nia", "access_code": "nia-code-0001", "role": "viewer"},
    )
    nia = sign_in(client, "nia", "nia-code-0001")
    assert client.get(f"{API}/about/load", headers=nia).status_code == 200
    # Each of them reads the slowest requests and who met what, the others by name:
    # every signed-in person is one of the team's own.
    for headers in (admin, inventory, viewer, nia):
        now = measured(client, headers)
        assert {one["who"]["username"] for one in now["slowest"]} >= {"ada", None}
        assert [one["username"] for one in now["people"]][-1] is None
        assert {one["username"] for one in now["people"]} == {"ada", "ivy", "vic", "nia", None}
    # And by nobody who is not.
    answer = client.get(f"{API}/about/load")
    assert answer.status_code == 401
    assert answer.headers["content-type"] == "application/problem+json"


def test_the_shape_of_the_measures(client: TestClient, viewer: dict) -> None:
    for _ in range(25):
        client.get(f"{API}/tags", headers=viewer)
    answer = client.get(f"{API}/about/load", headers=viewer)
    now = answer.json()
    assert set(now) == {
        "health",
        "because",
        "refusing",
        "ceiling",
        "measures",
        "window_seconds",
        "step_seconds",
        "started_at",
        "at",
        "totals",
        "in_flight",
        "process",
        "host",
        "worker",
        "points",
        "slowest",
        "slowest_long",
        "people",
    }
    assert (now["health"], now["because"], now["refusing"]) == ("good", [], "nothing")
    assert said(answer) == GOOD
    assert set(now["ceiling"]) == {"response_ms", "cpu_percent", "over_seconds", "fewest_requests"}
    assert now["ceiling"]["fewest_requests"] == 21
    assert set(now["measures"]) == {"response_ms", "requests", "reads_ms", "reads", "cpu_percent"}
    assert now["measures"]["response_ms"] > 0
    # The sign-in is in the health, and is not one of the reads.
    assert (now["measures"]["requests"], now["measures"]["reads"]) == (26, 25)
    assert 0 < now["measures"]["reads_ms"] <= now["measures"]["response_ms"]
    assert now["measures"]["cpu_percent"] >= 0
    assert (now["window_seconds"], now["step_seconds"]) == (600, 5)
    started = datetime.fromisoformat(now["started_at"])
    assert started <= datetime.fromisoformat(now["at"])
    totals = now["totals"]
    assert set(totals) == {
        "requests",
        "ok",
        "not_accepted",
        "failed",
        "busy",
        "response_ms",
        "bands",
        "cpu_percent",
    }
    assert totals["requests"] == totals["ok"] >= 26
    times = totals["response_ms"]
    assert set(times) == {"low", "average", "high", "p50", "p95", "p99"}
    assert 0 <= times["low"] <= times["p50"] <= times["p95"] <= times["p99"] <= times["high"]
    assert times["low"] <= times["average"] <= times["high"]
    assert set(totals["cpu_percent"]) == {"low", "average", "high"}
    assert 0 <= totals["cpu_percent"]["low"] <= totals["cpu_percent"]["high"]
    assert set(totals["bands"]) == {"bounds_ms", "counts"}
    assert totals["bands"]["bounds_ms"] == [1000.0, 2000.0, 3000.0]
    # The sign-in and the twenty-five reads are in the bands, and the measure of time.
    assert len(totals["bands"]["counts"]) == 4
    assert sum(totals["bands"]["counts"]) == 26
    # The request that asks is not among those in flight.
    assert now["in_flight"] == {"count": 0, "oldest_ms": None}
    assert now["process"]["memory_bytes"] > 1_000_000
    host = now["host"]
    assert set(host) == {
        "memory_total_bytes",
        "memory_used_bytes",
        "memory_free_bytes",
        "disk_total_bytes",
        "disk_free_bytes",
        "processors",
        "load_1m",
    }
    assert host["memory_total_bytes"] == host["memory_used_bytes"] + host["memory_free_bytes"]
    assert 0 < host["disk_free_bytes"] <= host["disk_total_bytes"]
    assert host["processors"] >= 1
    assert host["load_1m"] >= 0
    # The routes of a test are worked by a thread of the process itself (P-267).
    assert now["worker"] == "in_process"
    points = now["points"]
    assert set(points) == {
        "at",
        "requests",
        "average_ms",
        "high_ms",
        "p50_ms",
        "p95_ms",
        "cpu_percent",
        "busy",
    }
    assert datetime.fromisoformat(points["at"]) == started
    steps = len(points["requests"])
    assert 1 <= steps <= 120
    for name in ("average_ms", "high_ms", "p50_ms", "p95_ms", "cpu_percent", "busy"):
        assert len(points[name]) == steps, name
    assert sum(points["requests"]) == totals["requests"]
    assert sum(points["busy"]) == totals["busy"] == 0
    # The slowest of the measure, the slowest first, ten at the most.
    assert len(now["slowest"]) == 10
    assert now["slowest_long"] == []
    times = [one["ms"] for one in now["slowest"]]
    assert times == sorted(times, reverse=True)
    for one in now["slowest"]:
        assert set(one) == {"at", "method", "route", "ms", "status", "request_id", "who"}
        assert set(one["who"]) == {"kind", "hid", "username"}
        assert one["route"] in (f"{API}/tags", f"{API}/auth/sign-in")
        assert started <= datetime.fromisoformat(one["at"]) <= datetime.fromisoformat(now["at"])
    # Who asked: the viewer, and the sign-in, which nothing names an account for.
    vic, unnamed = now["people"]
    assert set(vic) == {
        "kind",
        "hid",
        "username",
        "requests",
        "bands",
        "slowest_ms",
        "busy",
        "failed",
        "last_at",
    }
    assert (vic["kind"], vic["username"], vic["requests"], vic["bands"]) == (
        "person",
        "vic",
        25,
        [25, 0, 0, 0],
    )
    assert (unnamed["kind"], unnamed["hid"], unnamed["username"], unnamed["requests"]) == (
        "unnamed",
        None,
        None,
        1,
    )
    assert sum(one["requests"] for one in now["people"]) == totals["requests"]


def test_ten_minutes_of_measures_are_a_few_kilobytes(
    client: TestClient, viewer: dict, clock: Clock
) -> None:
    meter_of(client).hold(load.NO_CEILING)
    for step in range(130):
        clock.now = step * 5 + 1.234567
        clock.cpu += 1.234567
        assert client.get(f"{API}/tags", headers=viewer).status_code == 200
    answer = client.get(f"{API}/about/load", headers=viewer)
    now = answer.json()
    assert len(now["points"]["requests"]) == 120
    assert now["points"]["at"] == "2027-03-02T14:00:50Z"
    assert now["totals"]["requests"] == 120
    assert len(answer.content) < 10_000
    # Every time and every share is to a tenth.
    assert now["points"]["cpu_percent"][5] == 24.7
    assert now["totals"]["cpu_percent"]["average"] == 24.7


def test_the_measures_ask_the_database_only_who_is_signed_in(
    client: TestClient, viewer: dict
) -> None:
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    app: Any = client.app
    token = viewer["Authorization"].removeprefix("Bearer ")
    event.listen(app.state.engine, "before_cursor_execute", note)
    try:
        assert client.get(f"{API}/about/load", headers=viewer).status_code == 200
        asked = list(statements)
        statements.clear()
        # What the check of a sign-in asks, alone.
        with app.state.sessions() as db:
            accounts.authenticate(db, app.state.signing_key, token)
        sign_in_alone = list(statements)
    finally:
        event.remove(app.state.engine, "before_cursor_execute", note)
    assert asked == sign_in_alone
    assert asked


def test_what_the_host_says_is_null_where_it_does_not_say(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said = measures.host(tmp_path)
    assert said.memory_total_bytes is not None
    assert said.memory_free_bytes is not None
    assert said.memory_used_bytes == said.memory_total_bytes - said.memory_free_bytes
    assert said.process_memory_bytes is not None
    # A host that keeps its figures elsewhere, and a directory that is not there.
    monkeypatch.setattr(measures, "MEMORY_OF_THE_HOST", tmp_path / "meminfo")
    monkeypatch.setattr(measures, "MEMORY_OF_THE_PROCESS", tmp_path / "status")
    said = measures.host(tmp_path / "nowhere")
    assert (said.memory_total_bytes, said.memory_used_bytes, said.memory_free_bytes) == (
        None,
        None,
        None,
    )
    assert (said.disk_total_bytes, said.disk_free_bytes) == (None, None)
    # The process says the most it has held, where not what it holds now.
    assert said.process_memory_bytes is not None
    (tmp_path / "meminfo").write_text("MemTotal:       2048 kB\nMemAvailable:    512 kB\n")
    (tmp_path / "status").write_text("Name:\thirdir\nVmRSS:\t    100 kB\n")
    said = measures.host(tmp_path)
    assert (said.memory_total_bytes, said.memory_used_bytes, said.memory_free_bytes) == (
        2048 * 1024,
        1536 * 1024,
        512 * 1024,
    )
    assert said.process_memory_bytes == 100 * 1024
