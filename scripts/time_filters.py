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
anew and kept, and the capacity balance with the demand of each region.

An answer that is kept (D-184) is timed twice. "anew" drops every kept answer,
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
host are slower than the host can do.
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


@dataclass(frozen=True)
class Case:
    """One request to time. `anew` drops the kept answers before each run (D-184)."""

    label: str
    path: str
    params: dict[str, Any]
    anew: bool = False


@dataclass(frozen=True)
class Picked:
    """The records some of the requests name: the contract that covers the most items,
    and the one that still counts the most items that are out of service."""

    number: str
    counting_number: str
    counting_hid: str


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
        Case(
            "GET /reports/capacity, with the demand of each region", f"{API}/reports/capacity", {}
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

    @property
    def median(self) -> float:
        return statistics.median(self.runs)

    @property
    def p95(self) -> float:
        return percentile(self.runs, 0.95)


# The counts of the renewal alert that lead to a list of the worklist.
ALERTED = ("lapsed", "renewal_pending", "ending")


def total_of(case: Case, answer: dict[str, Any]) -> Any:
    """Return what an answer counted: a page's total, or a section's; the totals of a
    report; the counts of the alert; or the demand and supply of the capacity balance."""
    if "section" in case.params or ("total" in answer and "totals" not in answer):
        return answer["total"]
    if "totals" in answer:
        return answer["totals"]
    if "show" in answer:
        return {
            **{name: answer[name]["count"] for name in ALERTED},
            "overdue": answer["overdue"],
            "agreements": answer["agreements"],
        }
    view = answer["active"]
    return {
        "demand": view["demand"],
        "supply": view["supply"],
        "regions": len(view["demand_by_region"]),
    }


def ask(client: httpx2.Client, case: Case) -> dict[str, Any]:
    response = client.get(case.path, params=case.params)
    if response.status_code != 200:
        raise SystemExit(f"{case.label}: {response.status_code} {response.text[:500]}")
    return response.json()


def drop_kept() -> None:
    """Drop every answer that the application in this process keeps (D-184)."""
    from hirdir.io import kept

    kept.drop()


def time_case(client: httpx2.Client, case: Case, runs: int, warm_up: int) -> Timed:
    """Ask for one request warm_up times, then time it runs times. One to be worked out
    anew has the kept answers dropped before each run, outside what is timed."""
    timed = Timed(case)
    for _ in range(warm_up):
        if case.anew:
            drop_kept()
        timed.total = total_of(case, ask(client, case))
    for _ in range(runs):
        if case.anew:
            drop_kept()
        started = time.perf_counter()
        answer = ask(client, case)
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


def explain(engine: Engine, client: httpx2.Client, chosen: Sequence[Case], out: Path) -> None:
    """Write, for each request, every statement it sent, what it took and its plan."""
    with out.open("w", encoding="utf-8") as handle:
        for case in chosen:
            if case.anew:
                drop_kept()
            with recorded(engine) as sent:
                started = time.perf_counter()
                ask(client, case)
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
    the 95th percentile under twice that."""
    return one.median > TARGET_MS or one.p95 > 2 * TARGET_MS


def table(results: Sequence[Timed]) -> str:
    """Return the results as a table, in the order asked, each with the load average of
    the host over the minute its runs ended in."""
    width = max(len(one.case.label) for one in results)
    lines = [f"{'request':<{width}}  {'median':>7}  {'p95':>7}  {'load':>5}  total"]
    for one in results:
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
    number, covered = largest_contract(client)
    say(f"contract.number is {number}, the contract that covers the most items: {covered:,}")
    counting_number, counting_hid, counted = most_counting(client)
    say(
        f"out_of_service_contract is {counting_number}, which still counts the most items "
        f"that are out of service: {counted:,}"
    )
    picked = Picked(number, counting_number, counting_hid)
    chosen = [case for case in cases(picked) if only is None or only in case.label]
    if not anew and any(case.anew for case in chosen):
        say("the requests anew are left out: the kept answers are in the server's process")
        chosen = [case for case in chosen if not case.anew]
    results = []
    for case in chosen:
        results.append(time_case(client, case, runs, warm_up))
        timed = results[-1]
        say(f"  {case.label}: {timed.median:.0f} / {timed.p95:.0f} ms, load {timed.load:.2f}")
    if explain_to is not None and engine is not None:
        explain(engine, client, chosen, explain_to)
        say(f"statements and plans written to {explain_to}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time the item filters and the reports.")
    parser.add_argument("folder", nargs="?", type=Path, default=FOLDER)
    parser.add_argument("--runs", type=int, default=15, help="timed runs of each request")
    parser.add_argument("--warm-up", type=int, default=2, help="untimed runs before them")
    parser.add_argument("--only", help="the requests whose label holds this text")
    parser.add_argument("--explain", type=Path, help="write the statements and plans here")
    parser.add_argument("--save", type=Path, help="write every run, as JSON, here")
    parser.add_argument("--url", help="time a server that is running, at this address")
    given = parser.parse_args(argv)
    facts_path = given.folder / FACTS
    if not facts_path.is_file():
        parser.error(f"{given.folder} holds no fixture: run `make fixture` first")
    if given.url and given.explain:
        parser.error("--explain times the application in this process, and not with --url")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    print(f"fixture of {facts['built_on']}: {facts['counts']['items']:,} items")
    print(f"before: {load()}")
    options = {
        "runs": given.runs,
        "warm_up": given.warm_up,
        "only": given.only,
        "explain_to": given.explain,
    }
    if given.url:
        with httpx2.Client(base_url=given.url, timeout=120) as client:
            results = run(client, facts, engine=None, anew=False, **options)
    else:
        from hirdir.app import create_app
        from hirdir.config import Config

        app = create_app(Config(state_dir=given.folder))
        with TestClient(app) as client:
            results = run(client, facts, engine=app.state.engine, **options)
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
            }
            for one in results
        ]
        given.save.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
