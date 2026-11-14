"""What must hold when requests race, when input is hostile, and when something breaks.

Each of these was found wrong by review before release 0.2.0, and is kept right here.
The last sections hold what the reviews before releases 0.4.0 and 0.4.1 found.
"""

import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import Address
from hirdir.domain import groups, items, records
from tests.api.inventory import API, Maker, errors

UNKNOWN = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"


@pytest.fixture
def soft(client: TestClient) -> Iterator[TestClient]:
    """A client that is given the server's 500 answer instead of the exception behind it."""
    with TestClient(client.app, raise_server_exceptions=False) as caller:
        yield caller


def _together(client: TestClient, calls: list) -> list[int]:
    """Send each call from a thread of its own and return the status codes."""
    answers: list[int] = []

    def send(call) -> None:
        with TestClient(client.app, raise_server_exceptions=False) as caller:
            answers.append(call(caller).status_code)

    threads = [threading.Thread(target=send, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return sorted(answers)


# --- two requests at the same moment ---------------------------------------------------


def test_of_two_edits_against_one_version_only_the_first_is_applied(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    item = make.item(name="site2-sw-access-01", description="original")
    gate = threading.Barrier(2, timeout=5)
    real_apply = records.apply

    def apply(db, context, record_type, record, row_version, values, *more, **named):
        if record_type == "item" and "description" in values:
            gate.wait()  # both requests now hold the record as it was at version 1
        return real_apply(db, context, record_type, record, row_version, values, *more, **named)

    monkeypatch.setattr(records, "apply", apply)

    def save(text: str):
        body = {"row_version": 1, "description": text}
        return lambda caller: caller.patch(
            f"{API}/items/{item['hid']}", json=body, headers=make.headers
        )

    assert _together(client, [save("first"), save("second")]) == [200, 409]
    monkeypatch.setattr(records, "apply", real_apply)
    now = make.get(f"/items/{item['hid']}")
    assert now["row_version"] == 2
    assert now["description"] in ("first", "second")
    events = make.audit(record_type="item", action="update")
    assert [event["changes"][0]["new"] for event in events] == [now["description"]]


def test_of_two_creates_of_one_serial_number_one_is_a_conflict(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    entry = make.entry(make.vendor())
    gate = threading.Barrier(2, timeout=5)
    real_check = items._check_unique

    def check(*arguments, **named):
        real_check(*arguments, **named)
        gate.wait()  # both requests have passed the check, and neither has written

    monkeypatch.setattr(items, "_check_unique", check)
    body = {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X001"}

    def create(caller: TestClient):
        return caller.post(f"{API}/items", json=body, headers=make.headers)

    assert _together(client, [create, create]) == [201, 409]
    monkeypatch.setattr(items, "_check_unique", real_check)
    assert make.get("/items")["total"] == 1


# --- a change is stored before it is answered ---------------------------------------------


def test_a_change_that_cannot_be_stored_is_not_answered_as_stored(
    make: Maker, soft: TestClient, monkeypatch
) -> None:
    real_commit = Session.commit
    failing = {"now": False}

    def commit(self: Session) -> None:
        if failing["now"]:
            raise RuntimeError("the disk is full")
        real_commit(self)

    monkeypatch.setattr(Session, "commit", commit)
    failing["now"] = True
    response = soft.post(f"{API}/items", json={"name": "lost"}, headers=make.headers)
    failing["now"] = False
    assert response.status_code == 500
    assert make.get("/items")["total"] == 0


def test_an_unforeseen_error_is_a_problem_document_with_the_usual_headers(
    make: Maker, soft: TestClient, monkeypatch
) -> None:
    def broken(*arguments, **named):
        raise RuntimeError("something nobody foresaw, with a detail that stays in the log")

    monkeypatch.setattr(items, "get_item", broken)
    response = soft.get(f"{API}/items/{UNKNOWN}", headers=make.headers)
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] in response.json()["detail"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "set-cookie" not in response.headers
    assert "nobody foresaw" not in response.text


# --- every route, every method: never a cookie --------------------------------------------


def test_no_route_sets_a_cookie_whatever_the_method_or_the_outcome(
    client: TestClient, soft: TestClient, admin: dict, viewer: dict
) -> None:
    document = client.get(f"{API}/openapi.json", headers=admin).json()["paths"]
    seen = set()
    # Signing out everywhere ends the sessions this test is using, so it goes last.
    last = f"{API}/auth/sign-out-everywhere"
    for path, methods in sorted(document.items(), key=lambda entry: entry[0] == last):
        url = path.replace("{hid}", UNKNOWN).replace("{user_hid}", UNKNOWN).replace("{key}", "x")
        for method in methods:
            for headers in ({}, viewer, admin):
                response = soft.request(method, url, json={}, headers=headers)
                assert "set-cookie" not in response.headers, (method, path)
                assert response.headers["x-request-id"], (method, path)
                assert response.status_code != 500, (method, path)
                seen.add(response.status_code)
    assert {401, 403, 404, 422} <= seen


# --- a pattern is bounded before it is compiled ---------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    ["(?:a{1000}){1000}", "(?:a{2500}){2500}", "[a-z]{2000000}", "a{4294967294}", "((a{9}){9}){9}"],
)
def test_pattern_that_is_costly_to_compile_is_refused_at_once(make: Maker, pattern: str) -> None:
    dialect.compile_pattern.cache_clear()
    started = time.perf_counter()
    problem = make.get("/items", 422, filter=f"name:regex:{pattern}")
    assert time.perf_counter() - started < 0.5
    assert "counted repeats" in errors(problem)["filter"]


def test_patterns_people_write_are_still_accepted(make: Maker) -> None:
    make.item(hostname="site2-sw-core-01", mac_address="00:00:5e:00:53:01")
    for pattern in (
        "^site2-sw-(core|dist)-[0-9]{2}$",
        "^[a-z]{4}[0-9]-sw-.{1,20}$",
        "^([0-9a-f]{2}){6}$",
    ):
        field = "mac_address" if "0-9a-f" in pattern else "hostname"
        if field == "mac_address":
            continue  # a MAC address takes no regex; kept as a pattern the bound must allow
        assert make.get("/items", filter=f"{field}:regex:{pattern}")["total"] == 1, pattern
    dialect.compile_pattern("^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
    dialect.compile_pattern(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def test_the_server_answers_others_while_a_slow_pattern_runs(
    make: Maker, client: TestClient
) -> None:
    for n in range(30):
        make.item(name=f"long-{n}", comments="a" * 3000 + "b")
    waits: list[float] = []
    done = threading.Event()

    def probe() -> None:
        with TestClient(client.app) as caller:
            while not done.is_set():
                started = time.perf_counter()
                assert caller.get(f"{API}/health/live").status_code == 200
                waits.append(time.perf_counter() - started)

    watcher = threading.Thread(target=probe)
    watcher.start()
    try:
        make.get("/items", 422, filter="comments:regex:(a|aa)+$")
    finally:
        done.set()
        watcher.join()
    assert waits, "the probe never got an answer while the pattern ran"
    assert max(waits) < 0.5


# --- list input is answered or refused, never an error of the server ----------------------

HOSTILE = {
    "a number too large to store": {"filter": "est_value:gt:1e30"},
    "a number with more places than money has": {"filter": "est_value:gt:1.005"},
    "a weight with more places than weight has": {"filter": "effective.support_weight:lt:0.0001"},
    "a number with more places, in a list": {"filter": "est_value:in:1,2.123456"},
    "a whole number too large": {"filter": "quantity:eq:99999999999999999999"},
    "a time that leaves the calendar in UTC": {"filter": "created_at:gt:0001-01-01T00:00:00+14:00"},
    "an offset too large": {"offset": 2**63},
    "a lone surrogate": {"filter": '{"field":"name","op":"eq","value":"\\ud800"}'},
    "a NUL character": {"filter": '{"field":"name","op":"eq","value":"a\\u0000b"}'},
    "not a number at all": {"filter": "est_value:gt:NaN"},
}


@pytest.mark.parametrize("label", HOSTILE)
def test_hostile_list_input_is_refused_with_422(make: Maker, soft: TestClient, label: str) -> None:
    make.item(name="alpha")
    response = soft.get(f"{API}/items", params=HOSTILE[label], headers=make.headers)
    assert response.status_code == 422, (label, response.text)


def test_in_takes_as_many_values_as_it_says(make: Maker, soft: TestClient) -> None:
    make.item(name="n500")
    tree = {"field": "name", "op": "in", "value": [f"N{n}" for n in range(1000)]}
    answer = soft.post(f"{API}/items/query", json={"filter": tree}, headers=make.headers)
    assert (answer.status_code, answer.json()["total"]) == (200, 1)
    several = {"or": [tree, {"field": "serial_number", "op": "in", "value": ["x"] * 1000}]}
    answer = soft.post(f"{API}/items/query", json={"filter": several}, headers=make.headers)
    assert (answer.status_code, answer.json()["total"]) == (200, 1)
    tree["value"].append("one-too-many")
    answer = soft.post(f"{API}/items/query", json={"filter": tree}, headers=make.headers)
    assert answer.status_code == 422


def test_a_value_longer_than_any_field_is_refused(make: Maker, soft: TestClient) -> None:
    tree = {"field": "comments", "op": "contains", "value": "a" * 50_001}
    answer = soft.post(f"{API}/items/query", json={"filter": tree}, headers=make.headers)
    assert answer.status_code == 422
    assert "at most 1000 characters" in errors(answer.json())["filter"]


def test_history_offset_is_bounded_too(make: Maker, soft: TestClient) -> None:
    item = make.item(name="alpha")
    url = f"{API}/items/{item['hid']}/history"
    assert soft.get(url, params={"offset": 2**63}, headers=make.headers).status_code == 422
    assert (
        soft.get(f"{API}/audit-events", params={"offset": 2**63}, headers=make.headers).status_code
        == 422
    )


# --- text is compared without regard to case in any alphabet ------------------------------


@pytest.mark.parametrize(
    "short",
    [
        "name:eq:école-sw-01",
        "name:prefix:école",
        "name:contains:école",
        "name:glob:école*",
        "name:in:école-sw-01,x",
        "name:regex:^école",
        "asset_tag:eq:ät-000900",
    ],
)
def test_text_is_compared_without_case_beyond_ascii(make: Maker, short: str) -> None:
    make.item(name="ÉCOLE-sw-01", asset_tag="ÄT-000900")
    make.item(name="éclair")
    assert make.found(filter=short) == ["ÉCOLE-sw-01"]
    assert make.found(filter="name:ne:école-sw-01") == ["éclair"]
    # Sorted by letters and not by their case: É and é are the same letter.
    assert make.found(sort="name") == ["éclair", "ÉCOLE-sw-01"]
    make.post("/items", {"name": "twin", "asset_tag": "ät-000900"}, 409)


# --- the short form does not swallow a mistake ---------------------------------------------


@pytest.mark.parametrize(
    "short",
    [
        "hostname:prefix:site2 lifecycle_state:is:Prod",
        "hostname:prefix:site2 lifecycle_state:equals:Prod",
        "lifecycle_state:is:Prod",
    ],
)
def test_a_mistyped_operator_in_the_short_form_is_refused(make: Maker, short: str) -> None:
    make.item(hostname="site2-sw-01", lifecycle_state="Prod")
    assert "filter" in errors(make.get("/items", 422, filter=short))


def test_short_form_takes_an_operator_in_any_case_and_a_number_reads_as_text(make: Maker) -> None:
    make.item(hostname="site2-sw-01", serial_number="12345", catalog_entry_hid=None, name="x")
    assert make.found(filter="hostname:PREFIX:site2 name:Eq:X") == ["x"]
    tree = {"field": "serial_number", "op": "eq", "value": 12345}
    assert make.post("/items/query", {"filter": tree}, 200)["total"] == 1
    flags = {"field": "expected_online", "op": "in", "value": [True, False]}
    assert make.post("/items/query", {"filter": flags}, 200)["total"] == 0


def test_filter_nests_eight_deep_and_no_deeper(make: Maker) -> None:
    make.item(name="alpha")
    tree: dict = {"field": "name", "op": "eq", "value": "alpha"}
    for _ in range(8):
        tree = {"and": [tree]}
    assert make.post("/items/query", {"filter": tree}, 200)["total"] == 1
    assert (
        "nests at most 8"
        in errors(make.post("/items/query", {"filter": {"or": [tree]}}, 422))["filter"]
    )


# --- every write is in the history, under the names the documentation uses ------------------


def test_tags_given_when_a_record_is_created_are_in_its_history(make: Maker) -> None:
    make.tag("refresh-2030")
    item = make.item(name="site2-sw-core-01", tags=["refresh-2030"])
    created = make.get(f"/items/{item['hid']}/history")["items"][-1]
    assert created["action"] == "create"
    assert {"field": "tags", "old": [], "new": ["refresh-2030"]} in created["changes"]
    entry = make.entry(make.vendor(), tags=["refresh-2030"])
    event = make.audit(record_type="catalog_entry", record_hid=entry["hid"])[0]
    assert {"field": "tags", "old": [], "new": ["refresh-2030"]} in event["changes"]
    assert len(make.audit(record_type="item", record_hid=item["hid"])) == 1


def test_audit_names_only_documented_fields(make: Maker) -> None:
    vendor = make.vendor("Cisco")
    make.patch(f"/vendors/{vendor['hid']}", {"row_version": 1, "name": "Cisco Systems"})
    tag = make.tag("core")
    make.patch(f"/tags/{tag['hid']}", {"row_version": 1, "label": "Core"})
    item = make.item(name="x", asset_tag="AT-000123", serial_number="FCW0000X001")
    make.patch(
        f"/items/{item['hid']}",
        {"row_version": 1, "asset_tag": "AT-000124", "serial_number": "FCW0000X002"},
    )
    make.post("/choices", {"list": "catalog_type", "value": "load-balancer"})
    named = {change["field"] for event in make.audit(limit=1000) for change in event["changes"]}
    assert not {name for name in named if name.endswith("_key")}, named
    assert "list" in named
    assert "list_name" not in named


# --- null clears, or is refused, and nothing else -------------------------------------------


def test_null_clears_tags_and_is_refused_for_an_intent(make: Maker) -> None:
    make.tag("core")
    item = make.item(
        name="site2-sw-spare-01",
        lifecycle_state="Prod",
        disposition="Spare",
        expected_online=False,
        tags=["core"],
    )
    path = f"/items/{item['hid']}"
    refused = make.patch(path, {"row_version": 1, "expected_online": None}, 422)
    assert errors(refused) == {"expected_online": "true or false"}
    assert make.get(path)["expected_online"] is False
    cleared = make.patch(path, {"row_version": 1, "tags": None})
    assert (cleared["tags"], cleared["row_version"]) == ([], 2)


def test_text_with_a_nul_character_is_refused(make: Maker) -> None:
    assert make.post("/items", {"name": "a\x00b"}, 422)["status"] == 422
    assert make.post("/vendors", {"name": "a\x00b"}, 422)["status"] == 422


def test_vendor_renamed_to_its_own_alias_no_longer_lists_it(make: Maker) -> None:
    vendor = make.vendor("Cisco", aliases=["Cisco Systems", "CSCO"])
    renamed = make.patch(f"/vendors/{vendor['hid']}", {"row_version": 1, "name": "Cisco Systems"})
    assert (renamed["name"], renamed["aliases"]) == ("Cisco Systems", ["CSCO"])


# --- settings refuse what they cannot hold --------------------------------------------------


@pytest.mark.parametrize("value", ["NaN", "Infinity", 1e30, 0, 0.004, -5, "1e-9"])
def test_weight_per_resource_unit_is_a_real_number_above_zero(
    soft: TestClient, admin: dict, value: object
) -> None:
    body = {"row_version": 0, "value": value}
    answer = soft.put(f"{API}/settings/weight_per_resource_unit", json=body, headers=admin)
    assert answer.status_code == 422, (value, answer.text)


def test_a_setting_is_not_rounded_behind_the_callers_back(soft: TestClient, admin: dict) -> None:
    url = f"{API}/settings/stack_discount_pct"
    assert soft.put(url, json={"row_version": 0, "value": 33.333}, headers=admin).status_code == 422
    assert (
        soft.put(url, json={"row_version": 0, "value": 33.33}, headers=admin).json()["value"]
        == 33.33
    )


# --- the lifecycle rules' own gaps ------------------------------------------------------------


def test_item_first_entered_in_a_keeping_state_may_be_given_its_disposition(make: Maker) -> None:
    down = make.item(name="site2-sw-dist-09", lifecycle_state="Down", disposition="Production")
    assert (down["disposition"], down["expected_online"]) == ("Production", False)
    bare = make.item(name="site2-sw-dist-10", lifecycle_state="Down")
    assert bare["disposition"] is None
    given = make.patch(f"/items/{bare['hid']}", {"row_version": 1, "disposition": "Spare"})
    assert given["disposition"] == "Spare"
    # Once it has one, that is the one it keeps.
    changed = make.patch(
        f"/items/{bare['hid']}", {"row_version": 2, "disposition": "Production"}, 422
    )
    assert "disposition" in errors(changed)
    moved = make.move(
        make.item(name="site2-sw-dist-11"), "Pending-Removal", disposition="Production"
    )
    assert moved["disposition"] == "Production"


def test_no_rule_may_make_excess_online(client: TestClient, make: Maker, admin: dict) -> None:
    prod = next(rule for rule in make.get("/lifecycle-rules") if rule["state"] == "Prod")
    body = {
        "row_version": prod["row_version"],
        "dispositions": ["Production", "Spare", "Excess"],
        "may_be_online": ["Production", "Spare", "Excess"],
    }
    answer = client.patch(f"{API}/lifecycle-rules/{prod['hid']}", json=body, headers=admin)
    assert answer.status_code == 422
    assert errors(answer.json()) == {"may_be_online": "Excess is always offline"}
    null = {"row_version": prod["row_version"], "keeps_disposition": None}
    answer = client.patch(f"{API}/lifecycle-rules/{prod['hid']}", json=null, headers=admin)
    assert "keeps_disposition" in errors(answer.json())


# --- what the web UI needed and did not get --------------------------------------------------


def test_a_conflict_names_the_field_that_collides(make: Maker) -> None:
    cisco = make.vendor("Cisco", aliases=["CSCO"])
    entry = make.entry(cisco)
    make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X001", asset_tag="AT-000123")
    make.owner("Network Engineering")
    make.tag("core")
    twin = {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X001"}
    for path, body, field in (
        ("/items", twin, "serial_number"),
        ("/items", {"name": "x", "asset_tag": "AT-000123"}, "asset_tag"),
        ("/vendors", {"name": "cisco"}, "name"),
        ("/vendors", {"name": "Arista", "aliases": ["csco"]}, "aliases"),
        ("/catalog-entries", {"vendor_hid": cisco["hid"], "pid": "c9300-48p"}, "pid"),
        ("/owners", {"label": "network engineering"}, "label"),
        ("/tags", {"label": "CORE"}, "label"),
        ("/choices", {"list": "catalog_type", "value": "switch"}, "value"),
    ):
        problem = make.post(path, body, 409)
        assert list(errors(problem)) == [field], (path, problem)


def test_history_writes_an_amount_as_the_record_shows_it(make: Maker) -> None:
    entry = make.entry(
        make.vendor(), est_value="18000", support_weight="1.50", stack_discount_pct=30
    )
    assert (entry["est_value"], entry["support_weight"], entry["stack_discount_pct"]) == (
        "18000.00",
        "1.5",
        "30",
    )
    make.patch(
        f"/catalog-entries/{entry['hid']}",
        {"row_version": 1, "est_value": "18500", "support_weight": 2, "stack_discount_pct": "30.0"},
    )
    update, create = make.audit(record_type="catalog_entry")
    made = {change["field"]: change["new"] for change in create["changes"]}
    assert (made["est_value"], made["support_weight"], made["stack_discount_pct"]) == (
        "18000.00",
        "1.5",
        "30",
    )
    assert update["changes"] == [
        {"field": "est_value", "old": "18000.00", "new": "18500.00"},
        {"field": "support_weight", "old": "1.5", "new": "2"},
    ]


# --- found by the review before release 0.4.0 ------------------------------------------


def _slowly(monkeypatch, module, name: str) -> None:
    """Make one check take a while, so that two requests are surely inside it together."""
    real = getattr(module, name)

    def slow(*arguments, **named):
        found = real(*arguments, **named)
        time.sleep(0.3)
        return found

    monkeypatch.setattr(module, name, slow)


def test_two_requests_at_once_cannot_put_one_item_into_two_stacks(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    entry = make.entry(make.vendor())
    shared, *others = make.switches(entry, "site2-sw", 5)
    first = make.stack("site2-sw-stack1", others[:2])
    second = make.stack("site2-sw-stack2", others[2:])
    _slowly(monkeypatch, groups, "_check_joining")

    def join(stack: dict):
        body = {"members": [{"item_hid": shared["hid"]}]}
        return lambda caller: caller.post(
            f"{API}/device-groups/{stack['hid']}/members", json=body, headers=make.headers
        )

    assert _together(client, [join(first), join(second)]) == [201, 409]
    assert len(make.get(f"/items/{shared['hid']}")["groups"]) == 1


def test_two_requests_at_once_cannot_put_two_items_inside_each_other(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    one, other = make.item(name="chassis-1"), make.item(name="chassis-2")
    _slowly(monkeypatch, items, "ancestors")

    def put(item: dict, into: dict):
        body = {"row_version": item["row_version"], "parent_item_hid": into["hid"]}
        return lambda caller: caller.patch(
            f"{API}/items/{item['hid']}", json=body, headers=make.headers
        )

    assert _together(client, [put(one, other), put(other, one)]) == [200, 422]
    assert sorted(make.found(filter="is_major:eq:true")) in (["chassis-1"], ["chassis-2"])


def test_a_member_of_a_stack_is_not_given_a_parent_while_it_joins(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    entry = make.entry(make.vendor())
    joining, *others = make.switches(entry, "site2-sw", 3)
    stack = make.stack("site2-sw-stack1", others)
    chassis = make.item(name="chassis-1")
    _slowly(monkeypatch, groups, "_check_joining")
    _slowly(monkeypatch, items, "major_only_groups")

    def join(caller):
        body = {"members": [{"item_hid": joining["hid"]}]}
        return caller.post(
            f"{API}/device-groups/{stack['hid']}/members", json=body, headers=make.headers
        )

    def nest(caller):
        body = {"row_version": joining["row_version"], "parent_item_hid": chassis["hid"]}
        return caller.patch(f"{API}/items/{joining['hid']}", json=body, headers=make.headers)

    answers = _together(client, [join, nest])
    now = make.get(f"/items/{joining['hid']}")
    # Whichever came first stands, and the other was refused: never both.
    assert answers in ([200, 422], [201, 422])
    assert (now["is_major"], len(now["groups"])) in ((True, 1), (False, 0))


def test_a_retired_member_is_no_longer_a_member_of_its_stack(make: Maker) -> None:
    entry = make.entry(make.vendor(), support_weight="1")
    switches = make.switches(entry, "site2-sw", 3, lifecycle_state="Prod")
    stack = make.stack("site2-sw-stack1", switches)

    def retire(item: dict) -> dict:
        current = make.get(f"/items/{item['hid']}")
        return make.post(
            f"/items/{item['hid']}/retire", {"row_version": current["row_version"]}, 200
        )

    # The review found a retired master still shown as the master, and the others
    # still earning the discount. Retiring ends the membership that day.
    retired = retire(switches[0])
    assert (retired["record_status"], retired["groups"]) == ("retired", [])
    again = make.get(f"/device-groups/{stack['hid']}")
    assert (again["member_count"], again["master"], again["serial_number"]) == (2, None, None)
    past = make.members(stack, include_past="true")
    assert past[2]["left_on"] is not None
    totals = make.totals()
    assert (totals["component_count"], totals["managed_node_count"]) == (2, 1)
    assert totals["support_weight"] == "1"
    # With one left, it is one switch alone, and takes the full effort.
    retire(switches[1])
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 1
    assert make.totals()["support_weight"] == "1"
    retire(switches[2])
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 0


def test_a_bulk_edit_of_an_item_and_its_minor_items_copies_nothing_down(make: Maker) -> None:
    ours, theirs = make.owner("Network Engineering"), make.owner("Voice Services")
    chassis = make.item(name="chassis", owner_hid=ours["hid"], lifecycle_state="Prod")
    blade = make.item(name="blade", parent_item_hid=chassis["hid"])
    make.item(name="module", parent_item_hid=blade["hid"])
    make.item(name="zz-fan", parent_item_hid=chassis["hid"])

    # The rows are chosen by name, the blade before its chassis. They are worked the
    # chassis first, so each minor item is compared with what the chassis will hold.
    preview = make.post(
        "/items/bulk-update",
        {
            "filter": "owner.label:eq:Network Engineering",
            "set": {"owner": "Voice Services", "lifecycle_state": "Down"},
        },
    )
    assert [row["key"] for row in preview["rows"]] == ["blade", "chassis", "module", "zz-fan"]
    # Only the chassis is written to: what the others would be given, they have from it.
    assert [row["outcome"] for row in preview["rows"]] == [
        "unchanged",
        "update",
        "unchanged",
        "unchanged",
    ]
    make.post(f"/items/bulk-update/{preview['job']['hid']}/apply", {}, 200)

    for name in ("blade", "module", "zz-fan"):
        part = make.get("/items", filter=f"name:eq:{name}")["items"][0]
        assert (part["owner_hid"], part["lifecycle_state"], part["row_version"]) == (None, None, 1)
        assert part["effective"]["owner_hid"]["value"] == theirs["hid"]
        assert part["effective"]["lifecycle_state"] == {
            "value": "Down",
            "source": "parent_item",
            "source_hid": chassis["hid"],
        }
    # They still follow the chassis.
    make.move(make.get(f"/items/{chassis['hid']}"), "Prod")
    assert make.found(filter="effective.lifecycle_state:eq:Prod") == [
        "blade",
        "chassis",
        "module",
        "zz-fan",
    ]


def test_one_item_does_not_make_the_summary_fail_for_everybody(make: Maker) -> None:
    entry = make.entry(
        make.vendor(), est_value="9999999999999.99", support_weight="99999999.99", kind="software"
    )
    make.item(
        catalog_entry_hid=entry["hid"],
        name="licences",
        quantity=1_000_000_000,
        lifecycle_state="Prod",
    )
    make.item(
        catalog_entry_hid=entry["hid"], name="more", quantity=1_000_000_000, lifecycle_state="Prod"
    )

    summary = make.get("/reports/summary", by="kind")
    money = make.get("/reports/management", by="kind")

    # Exact, however large: nothing is rounded on the way.
    assert summary["totals"]["support_weight"] == "199999999980000000"
    assert money["totals"]["est_value"] == "19999999999999980000000.00"
    assert money["rows"][0]["est_value"] == "19999999999999980000000.00"


def test_support_weight_is_rounded_half_up(make: Maker) -> None:
    entry = make.entry(make.vendor(), support_weight="0.01", stack_discount_pct="50")
    switches = make.switches(entry, "site2-sw", 5, lifecycle_state="Prod")
    make.stack("site2-sw-stack1", switches)
    # Five times half a hundredth is 0.025: half up it is 0.03, and half to even 0.02.
    assert make.totals()["support_weight"] == "0.03"


def test_a_draft_stack_is_one_node_where_drafts_are_counted(make: Maker) -> None:
    entry = make.entry(make.vendor(), support_weight="1")
    switches = make.switches(entry, "site2-sw", 2, lifecycle_state="Prod", record_status="draft")
    make.group(
        "site2-sw-stack1",
        "stack",
        [(switches[0], "master"), (switches[1], "member")],
        record_status="draft",
    )
    assert make.totals()["items"] == 0
    drafts = make.totals(include_drafts="true")
    assert (drafts["component_count"], drafts["managed_node_count"], drafts["support_weight"]) == (
        2,
        1,
        "1",
    )


def test_the_duplicates_report_holds_at_its_largest_page(make: Maker, db: Session) -> None:
    holder = make.item(name="site2-rtr-wan-01")
    other = make.item(name="site2-rtr-wan-02")
    for number in range(1001):
        address = f"2001:db8::{number:x}"
        db.add_all(
            [
                Address(item_hid=holder["hid"], address=address, role="virtual"),
                Address(item_hid=other["hid"], address=address, role="virtual"),
            ]
        )
    db.commit()

    page = make.get("/reports/duplicates", limit=1000)

    assert (page["total"], len(page["items"])) == (1001, 1000)
    assert all(len(found["holders"]) == 2 for found in page["items"])


def test_the_list_of_groups_asks_the_database_no_more_for_more_members(make: Maker) -> None:
    owner = make.owner()
    entry = make.entry(make.vendor())
    statements: list[str] = []

    def note(*call) -> None:
        statements.append(call[2])

    def asked() -> int:
        statements.clear()
        make.get("/device-groups")
        return len(statements)

    # Every engine of this process is listened to: the application's is among them.
    event.listen(Engine, "before_cursor_execute", note)
    try:
        make.stack("stack-a", make.switches(entry, "a", 2), owner_hid=owner["hid"])
        few = asked()
        make.stack("stack-b", make.switches(entry, "b", 8), owner_hid=owner["hid"])
        make.stack("stack-c", make.switches(entry, "c", 8), owner_hid=owner["hid"])
        many = asked()
    finally:
        event.remove(Engine, "before_cursor_execute", note)
    assert 0 < many == few


def test_a_replacement_never_comes_round_to_where_it_began(make: Maker) -> None:
    first, second, third = (make.item(name=f"unit-{number}") for number in (1, 2, 3))

    def replace(old: dict, new: dict, expect: int = 201) -> dict:
        current = make.get(f"/items/{old['hid']}")
        body = {"row_version": current["row_version"], "reason": "rma", "new_item_hid": new["hid"]}
        return make.post(f"/items/{old['hid']}/replace", body, expect)

    replace(first, second)
    problem = replace(second, first, 422)
    assert "took its own" in problem["detail"]
    replace(second, third)
    problem = replace(third, first, 422)
    assert "took its own" in problem["detail"]


# --- found by the review before release 0.4.1 ------------------------------------------


def _send(make: Maker, entity: str, text: str) -> dict:
    """Preview a CSV file as the Inventory user."""
    response = make.client.post(
        f"{API}/imports/preview",
        params={"entity": entity},
        content=text,
        headers={**make.headers, "Content-Type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _told(row: dict) -> dict:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in row["changes"]}


def test_a_preview_tells_every_management_address_that_the_apply_changes(make: Maker) -> None:
    switch = make.item(hostname="site2-sw-01")
    make.address(switch, "192.0.2.21", is_primary=True)

    # A file with one address column, holding an address of the other family.
    preview = _send(make, "items", "hostname,ip\nsite2-sw-01,2001:db8::99\n")
    row = preview["rows"][0]
    assert (row["outcome"], _told(row)) == ("update", {"mgmt_ipv6": (None, "2001:db8::99")})
    make.post(f"/imports/{preview['job']['hid']}/apply", {}, 200)
    # Replacing it is told as well, and clearing `mgmt_address` tells of both it removes.
    row = _send(make, "items", "hostname,ip\nsite2-sw-01,2001:db8::77\n")["rows"][0]
    assert _told(row) == {"mgmt_ipv6": ("2001:db8::99", "2001:db8::77")}
    row = _send(make, "items", "hostname,mgmt_address\nsite2-sw-01,!clear\n")["rows"][0]
    assert _told(row) == {
        "mgmt_ipv4": ("192.0.2.21", None),
        "mgmt_ipv6": ("2001:db8::99", None),
    }


def test_an_export_of_two_networks_moves_neither_address_when_loaded_back(make: Maker) -> None:
    switch = make.item(hostname="site2-sw-01")
    red, blue = make.network("Red"), make.network("Blue")
    make.address(switch, "192.0.2.10", red, is_primary=True)
    six = make.address(switch, "2001:db8::10", blue, is_primary=True)

    columns = ["hostname", "mgmt_address", "mgmt_ipv4", "mgmt_ipv6", "mgmt_network"]
    exported = make.client.post(
        f"{API}/exports", json={"entity": "items", "columns": columns}, headers=make.headers
    ).text
    # One column cannot name two networks, so it names none.
    assert exported.splitlines()[1].endswith(",192.0.2.10,192.0.2.10,2001:db8::10,")

    preview = _send(make, "items", exported)
    assert preview["rows"][0]["outcome"] == "unchanged"
    make.post(f"/imports/{preview['job']['hid']}/apply", {}, 200)
    assert make.get(f"/addresses/{six['hid']}")["network"]["label"] == "Blue"
    assert make.audit(record_type="address", action="update") == []


@pytest.mark.parametrize(
    "moment",
    [
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-12:00",
        "1970-01-01T00:00:01Z",
        "2999-01-01T00:00:00Z",
    ],
)
def test_a_moment_that_cannot_be_kept_is_refused_and_never_a_500(
    make: Maker, soft: TestClient, moment: str
) -> None:
    item = make.item(name="site2-sw-01")
    stack = make.group("site2-sw-stack1", "stack", [(item, "member")])
    seen = {"row_version": 1, "observed_master_hid": item["hid"], "master_observed_at": moment}
    answers = [
        soft.patch(
            f"{API}/items/{item['hid']}",
            json={"row_version": 1, "observed_status": "online", "observed_at": moment},
            headers=make.headers,
        ),
        soft.patch(f"{API}/device-groups/{stack['hid']}", json=seen, headers=make.headers),
    ]
    assert [answer.status_code for answer in answers] == [422, 422], [a.text for a in answers]
    assert "observed_at" in errors(answers[0].json())
    # In a file it is a rejected row, and the rest of the file is read.
    preview = _send(
        make, "items", f"name,observed_status,observed_at\nsite2-sw-01,online,{moment}\n"
    )
    assert preview["rows"][0]["outcome"] == "rejected"


def test_a_moment_with_no_zone_is_utc_and_one_cleared_by_itself_is_refused(make: Maker) -> None:
    item = make.item(name="site2-sw-01")
    path = f"/items/{item['hid']}"
    seen = make.patch(
        path, {"row_version": 1, "observed_status": "online", "observed_at": "2026-11-02T15:00:00"}
    )
    assert seen["observed_at"] == "2026-11-02T15:00:00Z"

    body = {"row_version": seen["row_version"], "observed_at": None}
    problem = make.patch(path, body, 422)
    assert "clear observed_status" in errors(problem)["observed_at"]
    row = _send(make, "items", "name,observed_at\nsite2-sw-01,!clear\n")["rows"][0]
    assert row["outcome"] == "rejected"
    # Stated with the status and no moment, a file leaves the moment alone, and what
    # the preview tells is what the apply does.
    preview = _send(make, "items", "name,observed_status,observed_at\nsite2-sw-01,online,!clear\n")
    assert (preview["rows"][0]["outcome"], preview["rows"][0]["changes"]) == ("unchanged", [])
    assert make.post(f"/imports/{preview['job']['hid']}/apply", {}, 200)["status"] == "applied"
    assert make.get(path)["observed_at"] == "2026-11-02T15:00:00Z"


def test_looking_again_is_on_record_for_a_person_and_not_for_a_file(make: Maker) -> None:
    make.tag("spares")
    spare = make.item(name="spare-1", tags=["spares"], observed_status="present")
    first = make.get(f"/items/{spare['hid']}")["observed_at"]

    # The same file again changes nothing.
    row = _send(make, "items", "name,observed_status\nspare-1,present\n")["rows"][0]
    assert row["outcome"] == "unchanged"
    # A second walk round the store room, as a bulk edit, is a change, though none of
    # the fields it names has another value: the moment is now.
    preview = make.post(
        "/items/bulk-update", {"filter": "tags:has:spares", "set": {"observed_status": "present"}}
    )
    assert (preview["rows"][0]["outcome"], preview["rows"][0]["changes"]) == ("update", [])
    make.post(f"/items/bulk-update/{preview['job']['hid']}/apply", {}, 200)
    assert make.get(f"/items/{spare['hid']}")["observed_at"] > first


def test_an_item_that_has_left_the_teams_hands_joins_no_group(make: Maker, admin: dict) -> None:
    entry = make.entry(make.vendor())
    gone, staying, other = make.switches(entry, "site2-sw", 3, lifecycle_state="Prod")
    Maker(make.client, admin).move(gone, "Released", reason="disposed", force=True)
    stack = make.group("site2-sw-stack1", "stack", [(staying, "member")])

    problem = make.add(stack, [{"item_hid": gone["hid"]}], expect=422)
    assert "an item in Released is in no group" in errors(problem)["item_hid"]
    problem = make.group("another", "custom", [(gone, "member")], expect=422)
    assert "left the team's hands" in problem["detail"]
    # Nor does it take the place of a member.
    current = make.get(f"/items/{staying['hid']}")
    body = {"row_version": current["row_version"], "reason": "rma", "new_item_hid": gone["hid"]}
    assert make.post(f"/items/{staying['hid']}/replace", body, 422)["status"] == 422
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 1
    # A membership that has ended is still entered, for the record, as a file may.
    past = "group,item,joined_on,left_on\nsite2-sw-stack1,SITE2-SW-001,2024-01-01,2025-01-01\n"
    preview = _send(make, "device_group_members", past)
    assert preview["rows"][0]["outcome"] == "create"
    make.post(f"/imports/{preview['job']['hid']}/apply", {}, 200)
    assert len(make.members(stack, include_past="true")) == 2
    assert other["groups"] == []


def test_one_file_names_one_master_of_a_stack_and_loads_twice_the_same(make: Maker) -> None:
    entry = make.entry(make.vendor())
    make.switches(entry, "site2-sw", 3)
    make.group("site2-sw-stack1", "stack")
    text = (
        "group,item,role,observed_master\n"
        "site2-sw-stack1,SITE2-SW-001,master,true\n"
        "site2-sw-stack1,SITE2-SW-002,master,\n"
        "site2-sw-stack1,SITE2-SW-003,member,true\n"
    )

    preview = _send(make, "device_group_members", text)

    outcomes = [row["outcome"] for row in preview["rows"]]
    assert outcomes == ["create", "rejected", "rejected"]
    said = preview["rows"][1]["reasons"][0]["message"]
    assert "row 1 of the file names the intended master" in said
    assert preview["rows"][2]["reasons"][0]["field"] == "observed_master"
    good = text.replace("002,master,", "002,member,").replace("003,member,true", "003,member,")
    first = _send(make, "device_group_members", good)
    assert [row["outcome"] for row in first["rows"]] == ["create"] * 3
    make.post(f"/imports/{first['job']['hid']}/apply", {}, 200)
    again = _send(make, "device_group_members", good)
    assert [row["outcome"] for row in again["rows"]] == ["unchanged"] * 3


def test_the_controllers_of_an_endpoint_do_not_depend_on_what_else_is_listed(
    make: Maker,
) -> None:
    entry = make.entry(make.vendor())
    controllers = make.switches(entry, "wlc", 2)
    outer_point, inner_point = make.switches(entry, "ap", 2)
    outer = make.group("campus", "controller_domain", [(outer_point, "endpoint")])
    inner = make.group(
        "building", "controller_domain", [(inner_point, "endpoint")], parent_group_hid=outer["hid"]
    )
    make.group(
        "wlc-ha",
        "cluster",
        [(unit, "member") for unit in controllers],
        parent_group_hid=inner["hid"],
    )

    alone = make.get(f"/items/{outer_point['hid']}")["controllers"]
    listed = {
        row["hostname"]: row["controllers"]
        for row in make.get("/items", filter="hostname:prefix:ap-")["items"]
    }

    wanted = ["wlc-01", "wlc-02"]
    assert [one["name"] for one in alone] == wanted
    # On a page beside an endpoint of the inner domain, it lists the same.
    assert [one["name"] for one in listed["ap-01"]] == wanted
    assert [one["name"] for one in listed["ap-02"]] == wanted


def test_the_components_of_each_condition_are_those_the_headline_counts(make: Maker) -> None:
    vendor = make.vendor()
    switch = make.entry(vendor)
    licence = make.entry(vendor, "NETCONFIG-MANAGER", kind="software")
    make.item(catalog_entry_hid=switch["hid"], serial_number="A1", condition="good")
    for name in ("one", "two"):
        make.item(catalog_entry_hid=licence["hid"], name=name, condition="good")

    summary = make.get("/reports/summary", by="condition")

    totals = summary["totals"]
    assert totals["component_count"] == 1
    told = [(one["key"], one["items"], one["component_count"]) for one in totals["by_condition"]]
    assert told == [("good", 3, 1)]
    assert summary["rows"][0]["component_count"] == 1
    # By kind, each kind is told as it would count, were it in the headline.
    assert [(one["key"], one["component_count"]) for one in totals["by_kind"]] == [
        ("hardware", 1),
        ("software", 2),
    ]


def test_sorting_by_health_puts_the_worst_first(make: Maker) -> None:
    for name, condition in (("a", "good"), ("b", None), ("c", "failed"), ("d", "suspect")):
        make.item(name=name, **({"condition": condition} if condition else {}))
    assert make.found(sort="health") == ["c", "d", "b", "a"]
    assert make.found(sort="-health") == ["a", "b", "d", "c"]
