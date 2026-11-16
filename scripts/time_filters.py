"""Time the item filters and the reports on the fixture that `make fixture` makes.

    uv run python scripts/time_filters.py                    fixture-data/, in this process
    uv run python scripts/time_filters.py PATH --runs 30     another fixture, more runs
    uv run python scripts/time_filters.py --only covered     the requests whose label has this
    uv run python scripts/time_filters.py --explain FILE     and write the SQL of each request,
                                                             what each statement took, and the
                                                             plan SQLite made for it
    uv run python scripts/time_filters.py --url http://127.0.0.1:8726
                                                             a server that is running already

`make time-filters` runs the first. Each request is asked several times after a
warm-up, and the median and the 95th percentile of the runs are printed, in
milliseconds (D-165: 15 runs after 2 warm-ups). A page is the first page the web grid
asks for: 100 records, with the total counted, as every page is. The requests are the
filters and sorts that 0.6.0 and 0.6.1 added to the item list, beside the list with no
filter as the baseline; the flag not to renew of 0.7.0 on the item list, and the
members to review and the overdue renewals on the contract list; and the reports of
0.7.0: the coverage report, the renewal worklist and the renewal alert, each worked out
anew and kept. And what 0.8.0 adds: a page of the circuit grid, with the fields the
grid asks for, under its filters; a circuit's record with its parts and contacts; the
list of circuit groups and a group's record and members; the report of what circuits
cost, by carrier, site, region and group, for the present fiscal year, whole and
narrowed to a region; the capacity report anew and kept, with none of the six weights of
the settings and with all six set, and a Try; the item grid and the summary with the
default and the minimum weight of an item set, against the same without; and the check
of what is kept, with the four long reports kept.

A request that is timed with settings set has them set by the fixture's Admin before
its warm-ups, through `PUT /settings/{key}` as a person sets them, and returned to
their defaults after its runs, so that every other request is timed with none.

An answer that is kept (D-184, P-157) is timed twice. "anew" drops every kept answer,
`hirdir.io.kept.drop()`, before each run, outside what is timed, so that each run works
it out from the records as the first request after a change does; "kept" asks the same
again unchanged, as every request after the first does until something changes. With
`--url` the kept answers are in the server's process and cannot be dropped from here, so
the requests anew are left out.

By default the application is built in this process, with `hirdir.app.create_app` on
the fixture's database, and asked through `fastapi.testclient.TestClient`: what is
timed is the application, from the request to the last byte of the answer, without a
network or a server process. With `--url` the same requests go to a server over HTTP,
such as `HIRDIR_CONFIG=fixture-data/config.toml uv run hirdir admin serve --dev`, and
`--explain` is not available, because the statements are then in the other process.

The host is shared, so the load is printed before and after: numbers taken on a busy
host are slower than the host can do. For the same reason the process is kept to 3 GiB
of memory, `--memory` to say another: a run takes a few hundred MB, and a
request that would take more fails in this process rather than the host running out.
A request that is not answered, refused or failed, is said so with what it was
answered and after how long, the others are timed all the same, and the run ends with
the status 1.
"""

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "fixture-data"
FACTS = "fixture.json"
API = "/api/v1"
# How many rows the web grid asks for at a time: BLOCK in web/src/components/grid/DataGrid.tsx.
PAGE = 100
TARGET_MS = 300
# The flag not to renew in force on the item list (0.7.0), and the view of one top
# region of the fixture that the reports are narrowed to.
NOT_RENEWED = "effective.do_not_renew"
REGION_FILTER = "location:within:Americas"
# How much of the parameters of a statement is written out with it.
SHOWN = 400
# The most memory the timing may take, in GiB. The host is shared: a request that would
# take more fails in this process, and is said not to be answered, before the host
# runs out. A run takes a few hundred MB.
MEMORY_GIB = 3.0
# The fields the circuit grid asks for: GRID_FIELDS in web/src/lib/circuits.ts. They
# name the carriers and the groups, so the parts of each circuit of a page are read.
CIRCUIT_FIELDS = (
    "name",
    "enterprise_circuit_id",
    "description",
    "notes",
    "circuit_type",
    "port_mbps",
    "down_mbps",
    "up_mbps",
    "speed",
    "a_location_hid",
    "a_note",
    "a_side",
    "z_location_hid",
    "z_note",
    "z_side",
    "cost_side",
    "cost_site_hid",
    "cost_site_path",
    "carrier_hid",
    "carrier",
    "carrier_circuit_number",
    "carriers",
    "billing_account",
    "billing_contract",
    "installed_on",
    "activated_on",
    "disconnected_on",
    "production",
    "support_weight",
    "owner_hid",
    "owner",
    "owner_exception",
    "owner_exception_reason",
    "monthly_cost",
    "annual_cost",
    "in_service",
    "groups",
    "effective.support_weight",
    "effective.down_mbps",
    "effective.up_mbps",
    "tags",
    "record_status",
    "created_at",
    "updated_at",
)
# The six weights of the settings (P-155), as a run with all six set sets them; the two
# of a major item; and what a Try tries beside two staff lines (P-156).
WEIGHTS = {
    "default_item_weight": "0.5",
    "minimum_item_weight": "0.1",
    "default_site_weight": "1",
    "minimum_site_weight": "0.5",
    "default_circuit_weight": "0.5",
    "minimum_circuit_weight": "0.25",
}
ITEM_WEIGHTS = {key: WEIGHTS[key] for key in ("default_item_weight", "minimum_item_weight")}
TRIED = {"default_item_weight": "0.5", "minimum_circuit_weight": "0.25"}
# The long reports that are kept, each for the view its page opens with (P-157).
LONG_REPORTS = ("/reports/coverage", "/reports/renewals", "/renewals/alert", "/reports/capacity")


@dataclass(frozen=True)
class Case:
    """One request to time. `anew` drops the kept answers before each run (D-184).

    `settings` are set by the Admin for its runs and returned to their defaults after;
    `admin` sends it as the Admin, for a route that asks for one; and `keeps` are the
    routes asked first, after the kept answers are dropped, so that they alone are kept.
    """

    label: str
    path: str
    params: dict[str, Any]
    anew: bool = False
    method: str = "GET"
    body: dict[str, Any] | None = None
    settings: dict[str, str] = field(default_factory=dict)
    admin: bool = False
    keeps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Picked:
    """The records some of the requests name: the contract that covers the most items,
    and the one that still counts the most items that are out of service; and of 0.8.0
    the carrier that bills the most circuits, the circuit with the most parts, the
    circuit group with the most circuits, and a staff line for a Try to change."""

    number: str
    counting_number: str
    counting_hid: str
    carrier_hid: str = ""
    circuit_hid: str = ""
    group_hid: str = ""
    staff_hid: str = ""


def cases(picked: Picked) -> list[Case]:
    """Return the requests to time."""

    def page(label: str, filter_: str = "", sort: str = "name", **more: Any) -> Case:
        params: dict[str, Any] = {"sort": sort, "limit": PAGE, "offset": 0, **more}
        if filter_:
            params["filter"] = filter_
        return Case(label, f"{API}/items", params)

    def contract_page(label: str, filter_: str = "") -> Case:
        params: dict[str, Any] = {"limit": PAGE, "offset": 0}
        if filter_:
            params["filter"] = filter_
        return Case(label, f"{API}/contracts", params)

    def report(label: str, route: str, anew: bool, **params: Any) -> Case:
        return Case(f"{label}, {'anew' if anew else 'kept'}", f"{API}{route}", params, anew)

    number = f"contract.number:eq:{picked.number}"
    # The contracts that still count an item out of service are listed as the coverage
    # report lists such items: whatever the status of the item.
    out = {"include_archived": "true"}
    counting = f"out_of_service_contract.number:eq:{picked.counting_number}"
    by_counting = "out_of_service_contract.number"
    return [
        page("no filter, by name"),
        page("is_major:eq:true, by name (the grid's first page)", "is_major:eq:true"),
        page("covered:eq:true, by name", "covered:eq:true"),
        page("covered:eq:true, by covered_until", "covered:eq:true", "covered_until"),
        page("covered:eq:false, by name", "covered:eq:false"),
        page("covered:eq:false, by covered_until", "covered:eq:false", "covered_until"),
        page("contract_count:gt:1, by name", "contract_count:gt:1"),
        page("contract_count:gt:1, by -contract_count", "contract_count:gt:1", "-contract_count"),
        page("no filter, by -contract_count", "", "-contract_count"),
        page("out_of_service_cover:eq:true, by name", "out_of_service_cover:eq:true", **out),
        page("out_of_service_contract.number:eq:<one>, by name", counting, **out),
        page(
            f"out_of_service_contract.number:eq:<one>, by {by_counting}",
            counting,
            by_counting,
            **out,
        ),
        page(f"no filter, by {by_counting}", "", by_counting),
        page(
            "out_of_service_contract.hid:eq:<one>, by name",
            f"out_of_service_contract.hid:eq:{picked.counting_hid}",
            **out,
        ),
        page("contract.number:eq:<one>, by name", number),
        page("contract.number:eq:<one>, by contract.number", number, "contract.number"),
        page("no filter, by contract.number", "", "contract.number"),
        page("contract.status:eq:renewal_pending, by name", "contract.status:eq:renewal_pending"),
        page("purchase_line_mismatch:eq:true, by name", "purchase_line_mismatch:eq:true"),
        # 0.7.0: the flag not to renew, its own or its model's, on the item list.
        page(f"{NOT_RENEWED}:eq:true, by name", f"{NOT_RENEWED}:eq:true"),
        page(
            f"covered:eq:false {NOT_RENEWED}:eq:true, by name",
            f"covered:eq:false {NOT_RENEWED}:eq:true",
        ),
        # 0.7.0: the contract list, by number as it is unless sorted, with the members
        # to review and the renewals that are overdue.
        contract_page("contracts, no filter"),
        contract_page("contracts, to_review:eq:true", "to_review:eq:true"),
        contract_page("contracts, renewal_overdue:eq:true", "renewal_overdue:eq:true"),
        # 0.7.0: the reports that are kept, each worked out anew and then kept.
        *(
            case
            for anew in (True, False)
            for case in (
                report("GET /reports/coverage", "/reports/coverage", anew),
                report(
                    f"GET /reports/coverage {REGION_FILTER}",
                    "/reports/coverage",
                    anew,
                    filter=REGION_FILTER,
                ),
                report(
                    "GET /reports/coverage section=uncovered",
                    "/reports/coverage",
                    anew,
                    section="uncovered",
                    limit=PAGE,
                ),
                report("GET /reports/renewals", "/reports/renewals", anew),
                report(
                    "GET /reports/renewals section=ending",
                    "/reports/renewals",
                    anew,
                    section="ending",
                    limit=PAGE,
                ),
                report("GET /renewals/alert", "/renewals/alert", anew),
            )
        ),
        *cases_of_0_8_0(picked),
    ]


def cases_of_0_8_0(picked: Picked) -> list[Case]:
    """Return the requests that 0.8.0 adds: the circuits, their groups and what they
    cost, the capacity report with and without the weights of the settings and a Try,
    the item grid and the summary with and without the weights of an item, and the
    check of what is kept."""

    def circuits(label: str, filter_: str = "", sort: str = "name") -> Case:
        params: dict[str, Any] = {
            "sort": sort,
            "limit": PAGE,
            "offset": 0,
            "fields": list(CIRCUIT_FIELDS),
        }
        if filter_:
            params["filter"] = filter_
        return Case(f"circuits, {label}", f"{API}/circuits", params)

    def costs(by: str, filter_: str = "") -> Case:
        narrowed = f" {filter_}" if filter_ else ""
        params = {"by": by, **({"filter": filter_} if filter_ else {})}
        return Case(
            f"GET /reports/circuit-costs by={by}{narrowed}", f"{API}/reports/circuit-costs", params
        )

    def capacity(weighed: bool, anew: bool) -> Case:
        label = "GET /reports/capacity" + (", the six weights set" if weighed else "")
        return Case(
            f"{label}, {'anew' if anew else 'kept'}",
            f"{API}/reports/capacity",
            {},
            anew,
            settings=WEIGHTS if weighed else {},
        )

    def weighed(label: str, path: str, params: dict[str, Any], on: bool) -> Case:
        suffix = ", the item weights set" if on else ", no weight set"
        return Case(f"{label}{suffix}", f"{API}{path}", params, settings=ITEM_WEIGHTS if on else {})

    page = {"limit": PAGE, "offset": 0}
    tried = {
        **TRIED,
        "staff": {
            "add": [{"name": "Network engineer, tried", "quantity": "2", "units_each": "1"}],
            "change": [{"hid": picked.staff_hid, "quantity": "4"}],
        },
    }
    return [
        circuits("no filter, by name"),
        circuits(f"{REGION_FILTER}, by name", REGION_FILTER),
        circuits("billed_by:eq:<one>, by name", f"billed_by:eq:{picked.carrier_hid}"),
        circuits("effective.down_mbps:lt:200, by name", "effective.down_mbps:lt:200"),
        circuits("in_service:eq:true, by name", "in_service:eq:true"),
        circuits("monthly_cost:gt:2000, by name", "monthly_cost:gt:2000"),
        circuits("monthly_cost:gt:2000, by -monthly_cost", "monthly_cost:gt:2000", "-monthly_cost"),
        circuits("no filter, by -monthly_cost", "", "-monthly_cost"),
        Case(
            "GET /circuits/{hid}, the one with the most parts",
            f"{API}/circuits/{picked.circuit_hid}",
            {},
        ),
        Case("GET /circuit-groups", f"{API}/circuit-groups", page),
        Case(
            "GET /circuit-groups/{hid}, the largest", f"{API}/circuit-groups/{picked.group_hid}", {}
        ),
        Case(
            "GET /circuit-groups/{hid}/members, the largest",
            f"{API}/circuit-groups/{picked.group_hid}/members",
            page,
        ),
        *(
            costs(by, filter_)
            for by in ("carrier", "site", "region", "group")
            for filter_ in ("", REGION_FILTER)
        ),
        *(capacity(on, anew) for on in (False, True) for anew in (True, False)),
        Case(
            "POST /reports/capacity/try, a default, a minimum and two staff lines",
            f"{API}/reports/capacity/try",
            {},
            method="POST",
            body=tried,
        ),
        *(
            case
            for on in (False, True)
            for case in (
                weighed(
                    "is_major:eq:true, by name (the grid's first page)",
                    "/items",
                    {"filter": "is_major:eq:true", "sort": "name", **page},
                    on,
                ),
                weighed(
                    "no filter, by -effective.support_weight",
                    "/items",
                    {"sort": "-effective.support_weight", **page},
                    on,
                ),
                weighed("GET /reports/summary", "/reports/summary", {}, on),
                weighed("GET /reports/summary by=region", "/reports/summary", {"by": "region"}, on),
            )
        ),
        Case(
            "POST /kept-answers/check, the four long reports kept",
            f"{API}/kept-answers/check",
            {},
            method="POST",
            admin=True,
            keeps=LONG_REPORTS,
        ),
    ]


def percentile(samples: Sequence[float], share: float) -> float:
    """Return the sample at a share of the way up, by the nearest rank: the smallest
    sample that at least that share of the samples are no greater than."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = max(1, math.ceil(share * len(ordered)))
    return ordered[rank - 1]


@dataclass
class Timed:
    """What the runs of one request took, in milliseconds, and what it answered."""

    case: Case
    runs: list[float] = field(default_factory=list)
    total: Any = None
    # The load average of the host over the minute in which the runs ended.
    load: float = 0.0
    # Why it was not answered, after how long, where it was not.
    failed: str | None = None

    @property
    def median(self) -> float:
        return statistics.median(self.runs)

    @property
    def p95(self) -> float:
        return percentile(self.runs, 0.95)


# The counts of the renewal alert that lead to a list of the worklist.
ALERTED = ("lapsed", "renewal_pending", "ending")


def _balance(answer: dict[str, Any]) -> dict[str, Any]:
    """Return the demand, the supply and the parts of the support weight of a capacity
    balance, and how many counted at a default or were raised to a minimum."""
    view = answer["active"]
    return {
        "demand": view["demand"],
        "supply": view["supply"],
        "regions": len(view["demand_by_region"]),
        "weights": [view[name] for name in ("items_weight", "places_weight", "circuits_weight")],
        "defaulted": view["defaulted"],
        "raised": view["raised"],
    }


def total_of(case: Case, answer: dict[str, Any]) -> Any:
    """Return what an answer counted: a page's total, or a section's; the totals of a
    report; the counts of the alert; the demand and supply of the capacity balance, and
    of a Try beside it; the parts of a circuit; what a group of circuits costs; or how
    many kept answers a check checked and how many differed."""
    if "section" in case.params:
        return answer["total"]
    if "checked" in answer:
        return {"checked": answer["checked"], "differed": len(answer["differed"])}
    if "tried" in answer:
        return {"in_force": answer["in_force"]["active"]["demand"], **_balance(answer["tried"])}
    if "costs" in answer:
        parts = ("carriers", "costs", "devices", "groups", "contacts")
        return {name: len(answer[name] or []) for name in parts}
    if "in_service" in answer and "total" not in answer:
        return {name: answer[name] for name in ("circuits", "in_service", "monthly_cost")}
    if "fiscal_year" in answer:
        totals = answer["totals"]
        return {"rows": len(answer["rows"]), "circuits": totals["circuits"], "cost": totals["cost"]}
    if "by_kind" in answer.get("totals", {}):
        totals = answer["totals"]
        return {
            "rows": len(answer["rows"]),
            "items": totals["items"],
            "weight": totals["support_weight"],
        }
    if "total" in answer and "totals" not in answer:
        return answer["total"]
    if "totals" in answer:
        return answer["totals"]
    if "show" in answer:
        return {
            **{name: answer[name]["count"] for name in ALERTED},
            "overdue": answer["overdue"],
            "agreements": answer["agreements"],
        }
    return _balance(answer)


def ask(client: httpx2.Client, case: Case, admin: dict[str, str] | None = None) -> dict[str, Any]:
    """Send one request, as the Admin where it asks for one."""
    response = client.request(
        case.method,
        case.path,
        params=case.params,
        json=case.body,
        headers=admin if case.admin else None,
    )
    if response.status_code != 200:
        problem = (
            response.json() if response.headers.get("content-type", "").endswith("json") else {}
        )
        said = problem.get("title") if isinstance(problem, dict) else None
        raise Unanswered(f"{response.status_code} {said or response.text[:300]}")
    return response.json()


class Unanswered(Exception):
    """A request that was answered with anything but 200."""


def cap_memory(gib: float) -> None:
    """Keep this process to so much memory: a request that would take more fails here,
    with MemoryError, rather than the shared host running out of memory."""
    import resource

    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = int(gib * 2**30)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def drop_kept() -> None:
    """Drop every answer that the application in this process keeps (D-184)."""
    from hirdir.io import kept

    kept.drop()


def put_settings(
    client: httpx2.Client, admin: dict[str, str] | None, values: dict[str, str | None]
) -> None:
    """Give settings values as the Admin gives them, one audited change each; None
    returns one to its default."""
    if not values:
        return
    if admin is None:
        raise SystemExit("the settings are set by the Admin: run `make fixture` again")
    held = client.get(f"{API}/settings", headers=admin)
    versions = {one["key"]: one["row_version"] for one in held.json()}
    for key, value in values.items():
        response = client.put(
            f"{API}/settings/{key}",
            json={"value": value, "row_version": versions[key]},
            headers=admin,
        )
        if response.status_code != 200:
            raise SystemExit(f"setting {key}: {response.status_code} {response.text[:500]}")


@contextmanager
def settings_set(
    client: httpx2.Client, case: Case, admin: dict[str, str] | None
) -> Generator[None]:
    """Set the settings a request is timed with while the block runs, and return them to
    their defaults after."""
    put_settings(client, admin, dict(case.settings))
    try:
        yield
    finally:
        put_settings(client, admin, dict.fromkeys(case.settings))


def keep_first(client: httpx2.Client, case: Case, anew: bool) -> None:
    """Drop the kept answers, where they are in this process, and ask the routes a
    request keeps first, so that what is kept is theirs."""
    if not case.keeps:
        return
    if anew:
        drop_kept()
    for route in case.keeps:
        ask(client, Case(route, f"{API}{route}", {}))


def time_case(
    client: httpx2.Client,
    case: Case,
    runs: int,
    warm_up: int,
    admin: dict[str, str] | None = None,
    anew: bool = True,
) -> Timed:
    """Ask for one request warm_up times, then time it runs times. One to be worked out
    anew has the kept answers dropped before each run, outside what is timed; one with
    settings has them set before its warm-ups and returned after its runs."""
    timed = Timed(case)
    with settings_set(client, case, admin):
        keep_first(client, case, anew)
        for _ in range(warm_up):
            if case.anew:
                drop_kept()
            timed.total = total_of(case, ask(client, case, admin))
        for _ in range(runs):
            if case.anew:
                drop_kept()
            started = time.perf_counter()
            answer = ask(client, case, admin)
            timed.runs.append((time.perf_counter() - started) * 1000)
            timed.total = total_of(case, answer)
        timed.load = os.getloadavg()[0]
    return timed


# --- the statements a request sends ----------------------------------------------------


@dataclass
class Statement:
    sql: str
    parameters: Any
    ms: float = 0.0


@contextmanager
def recorded(engine: Engine) -> Generator[list[Statement]]:
    """Record every statement sent through the engine while the block runs, with how long
    it took."""
    sent: list[Statement] = []
    started: list[float] = []

    def before(_conn: Any, _cursor: Any, sql: str, parameters: Any, *_: Any) -> None:
        sent.append(Statement(sql, parameters))
        started.append(time.perf_counter())

    def after(*_: Any) -> None:
        sent[-1].ms = (time.perf_counter() - started[-1]) * 1000

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        yield sent
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


def plan_of(engine: Engine, statement: Statement) -> list[str]:
    """Return SQLite's plan for a statement, one line to a step, indented by its depth."""
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(f"EXPLAIN QUERY PLAN {statement.sql}", statement.parameters)
        rows = cursor.fetchall()
    finally:
        connection.close()
    depth: dict[int, int] = {0: -1}
    lines = []
    for node, parent, _, detail in rows:
        depth[node] = depth.get(parent, -1) + 1
        lines.append("  " * depth[node] + str(detail))
    return lines


def explain(
    engine: Engine,
    client: httpx2.Client,
    chosen: Sequence[Case],
    out: Path,
    admin: dict[str, str] | None = None,
) -> None:
    """Write, for each request, every statement it sent, what it took and its plan."""
    with out.open("w", encoding="utf-8") as handle:
        for case in chosen:
            with settings_set(client, case, admin), recorded(engine) as sent:
                keep_first(client, case, anew=True)
                if case.anew:
                    drop_kept()
                sent.clear()
                started = time.perf_counter()
                ask(client, case, admin)
                whole = (time.perf_counter() - started) * 1000
            in_sql = sum(one.ms for one in sent)
            handle.write(f"=== {case.label}\n{case.path} {json.dumps(case.params)}\n")
            handle.write(f"{whole:.0f} ms in all, {in_sql:.0f} ms in {len(sent)} statements\n\n")
            for number, one in enumerate(sorted(sent, key=lambda one: -one.ms), start=1):
                handle.write(f"--- {number}: {one.ms:.1f} ms\n{one.sql}\n")
                shown = repr(one.parameters)
                cut = f"... ({len(shown):,} characters)" if len(shown) > SHOWN else ""
                handle.write(f"parameters: {shown[:SHOWN]}{cut}\n")
                if one.sql.lstrip().upper().startswith(("SELECT", "WITH")):
                    handle.write("plan:\n")
                    handle.writelines(f"  {line}\n" for line in plan_of(engine, one))
                handle.write("\n")


# --- the run -------------------------------------------------------------------------------


def load() -> str:
    one, five, fifteen = os.getloadavg()
    return f"load average {one:.2f} {five:.2f} {fifteen:.2f} on {os.cpu_count()} cores"


def sign_in(client: httpx2.Client, facts: dict[str, Any]) -> None:
    response = client.post(
        f"{API}/auth/sign-in",
        json={"username": facts["username"], "access_code": facts["access_code"]},
    )
    if response.status_code != 200:
        raise SystemExit(f"cannot sign in to the fixture: {response.status_code} {response.text}")
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"


def sign_in_admin(client: httpx2.Client, facts: dict[str, Any]) -> dict[str, str] | None:
    """Sign in as the fixture's Admin and return the header that sends a request as it,
    or None for a fixture made before 0.8.0, which has none."""
    if "admin_username" not in facts:
        return None
    response = client.post(
        f"{API}/auth/sign-in",
        json={"username": facts["admin_username"], "access_code": facts["admin_access_code"]},
    )
    if response.status_code != 200:
        raise SystemExit(f"cannot sign in as the Admin: {response.status_code} {response.text}")
    return {"Authorization": f"Bearer {response.json()['token']}"}


def picked_of_0_8_0(client: httpx2.Client) -> tuple[dict[str, str], list[str]]:
    """Return the records the requests of 0.8.0 name, and what to say of each: the
    carrier that bills the most circuits, the circuit with the most parts of the first
    thousand, the circuit group with the most circuits, and the first staff line."""
    costs = client.get(f"{API}/reports/circuit-costs", params={"by": "carrier"}).json()
    carrier = max(costs["rows"], key=lambda row: (row["circuits"], row["key"] or ""))
    listed = client.get(
        f"{API}/circuits",
        params={"limit": 1000, "fields": ["name", "carriers", "costs", "devices", "groups"]},
    ).json()["items"]
    parts = ("carriers", "costs", "devices", "groups")
    circuit = max(
        listed, key=lambda one: (sum(len(one[name] or []) for name in parts), one["name"])
    )
    group = client.get(f"{API}/circuit-groups", params={"sort": "-circuits", "limit": 1}).json()
    staff = client.get(
        f"{API}/capacity-lines", params={"filter": "category:eq:staff", "sort": "name", "limit": 1}
    ).json()
    biggest = group["items"][0]
    said = [
        f"billed_by is {carrier['label']}, which bills the most circuits: {carrier['circuits']:,}",
        f"the circuit with the most parts is {circuit['name']}",
        f"the largest circuit group is {biggest['name']}: {biggest['circuits']:,} circuits",
        f"the staff line a Try changes is {staff['items'][0]['name']}",
    ]
    return {
        "carrier_hid": carrier["key"],
        "circuit_hid": circuit["hid"],
        "group_hid": biggest["hid"],
        "staff_hid": staff["items"][0]["hid"],
    }, said


def largest_contract(client: httpx2.Client) -> tuple[str, int]:
    """Return the number of the contract that covers the most items today, and how many."""
    response = client.get(f"{API}/contracts", params={"sort": "-covered_items", "limit": 1})
    found = response.json()["items"][0]
    return found["number"], found["covered_items"]


def most_counting(client: httpx2.Client) -> tuple[str, str, int]:
    """Return the number and the HID of the contract under which the most items that are
    out of service are still counted, of the first thousand such items, and how many."""
    response = client.get(
        f"{API}/items",
        params={
            "filter": "out_of_service_cover:eq:true",
            "include_archived": "true",
            "limit": 1000,
        },
    )
    tally: Counter[tuple[str, str]] = Counter()
    for item in response.json()["items"]:
        for coverage in item["coverage"]:
            if coverage["in_force"] or coverage["left_service"]:
                tally[coverage["contract"]["number"], coverage["contract_hid"]] += 1
    if not tally:
        raise SystemExit("no item of the fixture is out of service and still counted")
    (number, hid), count = tally.most_common(1)[0]
    return number, hid, count


def over_target(one: Timed) -> bool:
    """Say whether a request misses the target of D-165: the median under TARGET_MS and
    the 95th percentile under twice that. One that was not answered misses it."""
    return one.failed is not None or one.median > TARGET_MS or one.p95 > 2 * TARGET_MS


def table(results: Sequence[Timed]) -> str:
    """Return the results as a table, in the order asked, each with the load average of
    the host over the minute its runs ended in."""
    width = max(len(one.case.label) for one in results)
    lines = [f"{'request':<{width}}  {'median':>7}  {'p95':>7}  {'load':>5}  total"]
    for one in results:
        if one.failed is not None:
            lines.append(f"{one.case.label:<{width}}  not answered: {one.failed}")
            continue
        over = "  over" if over_target(one) else ""
        total = json.dumps(one.total) if isinstance(one.total, dict) else f"{one.total:,}"
        lines.append(
            f"{one.case.label:<{width}}  {one.median:>5.0f}ms  {one.p95:>5.0f}ms  "
            f"{one.load:>5.2f}  {total}{over}"
        )
    return "\n".join(lines)


def run(
    client: httpx2.Client,
    facts: dict[str, Any],
    *,
    runs: int,
    warm_up: int,
    only: str | None,
    engine: Engine | None,
    explain_to: Path | None,
    anew: bool = True,
    say: Callable[[str], None] = print,
) -> list[Timed]:
    """Time the requests. `anew` is false where the kept answers cannot be dropped, in
    a server of another process, and the requests anew are then left out."""
    sign_in(client, facts)
    admin = sign_in_admin(client, facts)
    if admin is None:
        raise SystemExit("the fixture was made before 0.8.0: run `make fixture` again")
    number, covered = largest_contract(client)
    say(f"contract.number is {number}, the contract that covers the most items: {covered:,}")
    counting_number, counting_hid, counted = most_counting(client)
    say(
        f"out_of_service_contract is {counting_number}, which still counts the most items "
        f"that are out of service: {counted:,}"
    )
    named, said = picked_of_0_8_0(client)
    for line in said:
        say(line)
    picked = Picked(number, counting_number, counting_hid, **named)
    chosen = [case for case in cases(picked) if only is None or only in case.label]
    if not anew and any(case.anew for case in chosen):
        say("the requests anew are left out: the kept answers are in the server's process")
        chosen = [case for case in chosen if not case.anew]
    results = []
    for case in chosen:
        started = time.perf_counter()
        try:
            timed = time_case(client, case, runs, warm_up, admin, anew)
        except (Unanswered, MemoryError) as error:
            took = time.perf_counter() - started
            why = str(error) or type(error).__name__
            timed = Timed(case, load=os.getloadavg()[0], failed=f"{why}, after {took:.1f} s")
        results.append(timed)
        if timed.failed is not None:
            say(f"  {case.label}: not answered: {timed.failed}")
            continue
        say(f"  {case.label}: {timed.median:.0f} / {timed.p95:.0f} ms, load {timed.load:.2f}")
    if explain_to is not None and engine is not None:
        explain(engine, client, chosen, explain_to, admin)
        say(f"statements and plans written to {explain_to}")
    return results


def said(line: str) -> None:
    """Print a line at once, so that what was timed is there if the run is stopped."""
    print(line, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time the item filters and the reports.")
    parser.add_argument("folder", nargs="?", type=Path, default=FOLDER)
    parser.add_argument("--runs", type=int, default=15, help="timed runs of each request")
    parser.add_argument("--warm-up", type=int, default=2, help="untimed runs before them")
    parser.add_argument("--only", help="the requests whose label holds this text")
    parser.add_argument("--explain", type=Path, help="write the statements and plans here")
    parser.add_argument("--save", type=Path, help="write every run, as JSON, here")
    parser.add_argument("--url", help="time a server that is running, at this address")
    parser.add_argument(
        "--memory",
        type=float,
        default=MEMORY_GIB,
        help=f"the most memory this process may take, in GiB, {MEMORY_GIB} unless said",
    )
    given = parser.parse_args(argv)
    facts_path = given.folder / FACTS
    if not facts_path.is_file():
        parser.error(f"{given.folder} holds no fixture: run `make fixture` first")
    if given.url and given.explain:
        parser.error("--explain times the application in this process, and not with --url")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    cap_memory(given.memory)
    print(f"fixture of {facts['built_on']}: {facts['counts']['items']:,} items", flush=True)
    print(f"before: {load()}", flush=True)
    options = {
        "runs": given.runs,
        "warm_up": given.warm_up,
        "only": given.only,
        "explain_to": given.explain,
    }
    if given.url:
        with httpx2.Client(base_url=given.url, timeout=120) as client:
            results = run(client, facts, engine=None, anew=False, say=said, **options)
    else:
        from hirdir.app import create_app
        from hirdir.config import Config

        app = create_app(Config(state_dir=given.folder))
        with TestClient(app) as client:
            results = run(client, facts, engine=app.state.engine, say=said, **options)
        app.state.engine.dispose()
    print(f"after: {load()}")
    print()
    print(table(results))
    if given.save:
        saved = [
            {
                "label": one.case.label,
                "params": one.case.params,
                "anew": one.case.anew,
                "runs": one.runs,
                "load": one.load,
                "total": one.total,
                "failed": one.failed,
            }
            for one in results
        ]
        given.save.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    return 1 if any(one.failed is not None for one in results) else 0


if __name__ == "__main__":
    sys.exit(main())
