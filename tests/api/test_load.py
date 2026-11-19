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


# --- what each route is to a busy server ---------------------------------------------


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
    assert posts >= busy.COSTLY_POSTS
    assert gets >= busy.AUDITED_READS
    assert gets >= busy.ALWAYS_ROUTES
    for prefix in busy.ALWAYS:
        assert any(route.path.startswith(prefix) for route in routes), prefix


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
    costly = {where for where, kind in kinds.items() if kind == load.COSTLY}
    # The pages of lists, by what they answer, however they are asked for.
    for where in (
        ("GET", "/items"),
        ("POST", "/items/query"),
        ("GET", "/items/{hid}/children"),
        ("GET", "/audit-events"),
        ("GET", "/users"),
        ("GET", "/imports"),
        ("GET", "/imports/{hid}/rows"),
        ("GET", "/contracts/{hid}/coverage"),
        ("POST", "/circuit-groups/query"),
        # The reports, the exports and the previews.
        ("GET", "/reports/summary"),
        ("GET", "/reports/capacity"),
        ("POST", "/reports/capacity/try"),
        ("GET", "/reports/duplicates"),
        ("POST", "/exports"),
        ("POST", "/imports/preview"),
        ("POST", "/items/bulk-update"),
        ("POST", "/kept-answers/check"),
    ):
        assert where in costly, where
    for where in (
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
    for where in (
        ("POST", "/auth/sign-in"),
        ("GET", "/auth/me"),
        ("POST", "/auth/sign-out-everywhere"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/about"),
        ("GET", "/about/load"),
        ("GET", "/openapi.json"),
        ("GET", "/settings"),
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
    # Nothing but a GET and the POSTs that are named is ever turned away.
    assert {where for where in costly if where[0] != "GET"} == {
        ("POST", path) for path in busy.COSTLY_POSTS
    }
    assert {method for (method, _), kind in kinds.items() if kind == load.READ} == {"GET"}


def test_a_request_is_what_the_route_that_answers_it_is() -> None:
    kinds = busy.Kinds(ROUTERS, API_PREFIX)
    assert kinds.of("GET", f"{API}/items") == load.COSTLY
    assert kinds.of("GET", f"{API}/items/{NOWHERE}") == load.READ
    assert kinds.of("PATCH", f"{API}/items/{NOWHERE}") == load.KEPT
    # A path of one route to one method and of another to another.
    assert kinds.of("POST", f"{API}/items/query") == load.COSTLY
    assert kinds.of("GET", f"{API}/items/query") == load.READ
    assert kinds.of("POST", f"{API}/items/retire") == load.KEPT
    assert kinds.of("GET", f"{API}/items/{NOWHERE}/children") == load.COSTLY
    assert kinds.of("GET", f"{API}/about/load") == load.KEPT
    # What no route answers is left to the router, which says so at once.
    assert kinds.of("GET", f"{API}/nothing/here") == load.KEPT
    assert kinds.of("DELETE", f"{API}/items") == load.KEPT


# --- what a busy server refuses ------------------------------------------------------

COSTLY = (
    ("GET", "/items"),
    ("POST", "/items/query"),
    ("GET", f"/items/{NOWHERE}/children"),
    ("GET", "/audit-events"),
    ("GET", "/reports/summary"),
    ("POST", "/reports/capacity/try"),
    ("POST", "/exports"),
    ("POST", "/imports/preview"),
    ("POST", "/items/bulk-update"),
)
READS = (
    ("GET", "/tags"),
    ("GET", "/choices"),
    ("GET", f"/items/{NOWHERE}"),
    ("GET", "/geography/tree"),
    ("GET", "/renewals/alert"),
)
KEPT = (
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


def refused(client: TestClient, headers: dict, asked: tuple[tuple[str, str], ...]) -> set:
    """Return which of the requests asked are answered as busy. What a request is
    answered otherwise does not matter here: found or not, well formed or not."""
    return {
        (method, path)
        for method, path in asked
        if client.request(method, API + path, headers=headers, json={}).status_code == 503
    }


def test_each_kind_of_request_at_each_step(client: TestClient, admin: dict, clock: Clock) -> None:
    everything = (*COSTLY, *READS, *KEPT)
    assert measured(client, admin)["state"] == "ok"
    assert refused(client, admin, everything) == set()
    # Past the ceiling: what costs most and can wait is refused, and nothing else.
    clock.busy()
    assert measured(client, admin)["state"] == "busy"
    assert refused(client, admin, everything) == set(COSTLY)
    # Still so a further ten seconds later: every read is.
    clock.busy()
    assert measured(client, admin)["state"] == "very_busy"
    assert refused(client, admin, everything) == {*COSTLY, *READS}
    # Under the ceiling again, everything is answered again.
    clock.idle()
    assert measured(client, admin)["state"] == "ok"
    assert refused(client, admin, everything) == set()
    # And busy anew begins at the first step.
    clock.busy()
    assert refused(client, admin, everything) == set(COSTLY)


def test_a_very_busy_server_still_signs_in_stores_a_change_and_serves_the_page(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    clock.busy()
    assert measured(client, admin)["state"] == "busy"
    clock.busy()
    assert measured(client, admin)["state"] == "very_busy"
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


def test_the_answer_of_a_busy_server(client: TestClient, admin: dict, clock: Clock) -> None:
    clock.busy()
    answer = client.get(f"{API}/items", headers=admin)
    assert answer.status_code == 503
    assert answer.headers["content-type"] == "application/problem+json"
    assert answer.headers["retry-after"] == "5"
    assert answer.json() == {
        "type": "about:blank",
        "title": "Busy",
        "status": 503,
        "detail": "the server is busy and this request was not answered; try again shortly",
        "errors": [],
        "busy": {"state": "busy", "because": ["cpu_percent"], "retry_after": 5},
    }
    # It carries what every answer carries, and is no more kept than any other.
    assert answer.headers["x-request-id"]
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in answer.headers
    clock.busy()
    answer = client.get(f"{API}/tags", headers=admin)
    assert answer.json()["busy"] == {
        "state": "very_busy",
        "because": ["cpu_percent"],
        "retry_after": 5,
    }


def test_a_refusal_is_given_before_who_asks_is_looked_at(client: TestClient, clock: Clock) -> None:
    # Nothing of the request is done, and nothing is asked of the database for it.
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    assert client.get(f"{API}/items").status_code == 401
    clock.busy()
    app: Any = client.app
    event.listen(app.state.engine, "before_cursor_execute", note)
    try:
        assert client.get(f"{API}/items").status_code == 503
        assert client.get(f"{API}/items", headers={"Authorization": "Bearer x"}).status_code == 503
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
    assert answer.json()["busy"]["state"] == "busy"
    # Nothing of it was kept.
    clock.idle()
    assert client.get(f"{API}/imports", headers=inventory).json()["total"] == 0


def test_a_request_under_a_prefix_is_what_its_route_is(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    under = {**admin, "X-Forwarded-Prefix": "/inventory"}
    clock.busy()
    assert client.get(f"{API}/items", headers=under).status_code == 503
    assert client.get(f"/inventory{API}/items", headers=under).status_code == 503
    assert client.get(f"{API}/tags", headers=under).status_code == 200
    assert client.get(f"{API}/about/load", headers=under).status_code == 200


def test_an_answer_of_busy_is_counted_and_is_in_no_time(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    clock.busy()
    before = measured(client, admin)["totals"]
    for _ in range(7):
        assert client.get(f"{API}/items", headers=admin).status_code == 503
    after = measured(client, admin)
    assert after["totals"]["busy"] == before["busy"] + 7 == 7
    assert after["points"]["busy"] == [0, 0, 7]
    # The seven and the read before them, and nothing else, were answered meanwhile.
    assert after["totals"]["requests"] == before["requests"] + 8
    assert after["totals"]["ok"] == before["ok"] + 1
    assert after["totals"]["failed"] == before["failed"] == 0


def test_no_ceiling_refuses_nothing_however_busy(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    meter_of(client).hold(load.NO_CEILING)
    clock.busy()
    clock.busy()
    clock.busy()
    assert refused(client, admin, (*COSTLY, *READS, *KEPT)) == set()
    now = measured(client, admin)
    assert (now["state"], now["because"]) == ("ok", [])
    assert now["measures"]["cpu_percent"] == 90.0
    assert now["ceiling"] == {"response_ms": 0, "cpu_percent": 0, "over_seconds": 30}


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
    client: TestClient, admin: dict, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirdir.domain import tags

    listed = tags.list_tags

    def slow(db: Session) -> Any:
        # The answer takes a quarter of a second of the clock to work out.
        clock.now += 0.25
        return listed(db)

    monkeypatch.setattr(tags, "list_tags", slow)
    assert client.get(f"{API}/tags", headers=admin).status_code == 200
    now = measured(client, admin)
    assert now["totals"]["response_ms"]["high"] == 250.0
    assert now["points"]["high_ms"] == [250.0]


def test_how_long_requests_take_is_read_of_the_requests_of_the_api(
    client: TestClient, admin: dict, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirdir.domain import tags

    listed = tags.list_tags

    def slow(db: Session) -> Any:
        clock.now += 2.0
        return listed(db)

    meter_of(client).hold(Ceiling(response_ms=1000, cpu_percent=0, over_seconds=30))
    monkeypatch.setattr(tags, "list_tags", slow)
    # Four slow answers are not five: there is no measure yet.
    for _ in range(4):
        assert client.get(f"{API}/tags", headers=admin).status_code == 200
    assert client.get(f"{API}/items", headers=admin).status_code == 200
    for _ in range(3):
        assert client.get(f"{API}/tags", headers=admin).status_code == 200
    # Seven slow ones among the reads of sign-in and of the list: the median is theirs.
    clock.now += 1.0
    now = measured(client, admin)
    assert now["measures"]["response_ms"] == 2000.0
    assert (now["state"], now["because"]) == ("busy", ["response_ms"])
    assert client.get(f"{API}/items", headers=admin).status_code == 503


def test_a_share_of_the_processor_past_100_is_shown_as_it_is(
    client: TestClient, admin: dict, clock: Clock
) -> None:
    meter_of(client).hold(Ceiling(response_ms=0, cpu_percent=150, over_seconds=10))
    # Several requests in the database at once: two processors' worth, for ten seconds.
    clock.now, clock.cpu = 10.0, 20.0
    now = measured(client, admin)
    assert now["measures"]["cpu_percent"] == 200.0
    assert (now["state"], now["because"]) == ("busy", ["cpu_percent"])
    assert now["points"]["cpu_percent"][:2] == [200.0, 200.0]
    assert now["totals"]["cpu_percent"] == {"low": 200.0, "average": 200.0, "high": 200.0}
    assert now["ceiling"]["cpu_percent"] == 150


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


def through(inner: ASGIApp, wire: Wire) -> None:
    """Send one request through the gateway to an application, to its end."""
    gateway = Gateway(inner, trusted_proxies=(), limits=lambda: (100, 100))
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
        await _begin(send, 201)
        await send({"type": "http.response.body", "body": b"{}"})

    meter = a_meter()
    through(inner, Wire(meter))
    assert counted(meter, ticking) == (1, 0, 0, 0)


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
    through(inner, Wire(meter, path="/assets/app.js"))
    assert counted(meter, ticking) == (1, 0, 0, 0)


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
    """Five senders give the headers of a sign-in and no body. They are in flight for
    as long as they hold on, and the server is not busy for them."""

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        raise AssertionError("no body ever comes")

    meter = load.Meter(0.0, 0.0, started_at=STARTED, ceiling=Ceiling())

    async def an_hour() -> None:
        gateway = Gateway(inner, trusted_proxies=(), limits=lambda: (100, 100))
        wires = [
            Wire(meter, method="POST", path=f"{API}/auth/sign-in", length=40, pieces=())
            for _ in range(5)
        ]
        held = [
            asyncio.ensure_future(gateway(wire.scope, wire.receive, wire.send)) for wire in wires
        ]
        await asyncio.sleep(0)
        for _ in range(720):
            ticking.now += 5
            picture = meter.picture(*ticking())
            assert picture.reading.state == load.OK
            assert (picture.in_flight, picture.oldest_ms) == (5, None)
            assert meter.reading(*ticking()).state == load.OK
        for one in held:
            one.cancel()
        await asyncio.gather(*held, return_exceptions=True)

    asyncio.run(an_hour())
    assert ticking.now == 3600
    assert counted(meter, ticking) == (0, 0, 5, 0)


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
        (5000, True),
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
        5,
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
    assert meter.ceiling == Ceiling(response_ms=5000, cpu_percent=60, over_seconds=30)
    put(client, admin, "busy_response_ms", 2500)
    put(client, admin, "busy_over_seconds", 45)
    assert meter.ceiling == Ceiling(response_ms=2500, cpu_percent=60, over_seconds=45)
    assert measured(client, admin)["ceiling"] == {
        "response_ms": 2500,
        "cpu_percent": 60,
        "over_seconds": 45,
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
    assert app.state.load.ceiling == Ceiling(response_ms=5000, cpu_percent=95, over_seconds=30)
    settings.set_setting(db, audit.SYSTEM, "busy_cpu_percent", 0, 80)
    settings.set_setting(db, audit.SYSTEM, "busy_over_seconds", 0, 20)
    db.commit()
    app = application(config, built)
    assert app.state.load.ceiling == Ceiling(response_ms=5000, cpu_percent=80, over_seconds=20)
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
    # Signed in with no role at all, as About is read.
    client.post(f"{API}/users", headers=admin, json={"username": "nia", "access_code": "nia-code"})
    nia = sign_in(client, "nia", "nia-code")
    assert client.get(f"{API}/about/load", headers=nia).status_code == 200
    assert client.get(f"{API}/about", headers=nia).status_code == 200
    # And by nobody who is not.
    answer = client.get(f"{API}/about/load")
    assert answer.status_code == 401
    assert answer.headers["content-type"] == "application/problem+json"


def test_the_shape_of_the_measures(client: TestClient, viewer: dict) -> None:
    for _ in range(5):
        client.get(f"{API}/tags", headers=viewer)
    answer = client.get(f"{API}/about/load", headers=viewer)
    now = answer.json()
    assert set(now) == {
        "state",
        "because",
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
    }
    assert (now["state"], now["because"]) == ("ok", [])
    assert set(now["ceiling"]) == {"response_ms", "cpu_percent", "over_seconds"}
    assert set(now["measures"]) == {"response_ms", "cpu_percent"}
    assert now["measures"]["response_ms"] > 0
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
        "cpu_percent",
    }
    assert totals["requests"] == totals["ok"] >= 6
    for spread in (totals["response_ms"], totals["cpu_percent"]):
        assert set(spread) == {"low", "average", "high"}
        assert 0 <= spread["low"] <= spread["average"] <= spread["high"]
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
    assert set(points) == {"at", "requests", "average_ms", "high_ms", "cpu_percent", "busy"}
    assert datetime.fromisoformat(points["at"]) == started
    steps = len(points["requests"])
    assert 1 <= steps <= 120
    for name in ("average_ms", "high_ms", "cpu_percent", "busy"):
        assert len(points[name]) == steps, name
    assert sum(points["requests"]) == totals["requests"]
    assert sum(points["busy"]) == totals["busy"] == 0


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
    assert len(answer.content) < 6000
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
