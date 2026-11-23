"""Time an import of new items, previewed and then applied in the background, on a copy
of the fixture that `make fixture` makes.

    uv run python scripts/time_import.py                  10,000 new items, fixture-data/
    uv run python scripts/time_import.py --rows 2000      a smaller file
    uv run python scripts/time_import.py PATH             another fixture

`make time-import` runs the first. The quality it is held to is in docs/requirements.md:
10,000 rows preview in under 30 s and apply in under 60 s.

The fixture is left as it is. Its database is copied, with SQLite's own backup, into a
folder of its own that is thrown away at the end, and an account with the Inventory
role is made in the copy alone. The application is built on the copy as `hirdir admin
serve` builds it, with `hirdir.app.create_app`, and served by uvicorn on a free port of
127.0.0.1 in a thread of this process: the worker that applies imports runs beside the
requests as it does in the service (D-185), and the requests are sent over HTTP, some
at once.

The file is of new items made from what the fixture holds: switches and access points
of its models, at its floors and rooms, under its owners, with serial numbers, asset
tags, host names and MAC addresses of their own (EXI..., AT-I..., imp-..., 02-5F-...).
It is previewed, and a file of more than a hundred rows is previewed in the background
(P-325): the request answers `202` at once, and the job is asked how far it has got
until it is previewed, the preview being timed from the request to the job previewed
(P-327). The preview is applied, and the job is asked how far it has got until it is
applied. While it is applied a person signs in every second, and each sign-in is
timed: a sign-in writes an audit event, so it waits for the one writer as any change
does. The same sign-in is timed first with nothing else going on.

What the apply spends its time on is told by wrapping, in this process only, the parts
of `hirdir.io.imports.work_job`: taking the job (`_take`), working out the order of the
rows (`_plan`), each batch (`_apply_waiting`, with each try of it, `_apply_batch`) and the
end (`_complete`). The time between two batches is the pause in which the one writer's
place is let go while somebody else changes something, `engine.wait_for_changes`, with
what little the loop does besides.
Nothing of the application is changed.

The host is shared, so the load average is printed beside every number.
"""

import argparse
import csv
import io
import json
import math
import os
import socket
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx2
import uvicorn
from fastapi import FastAPI
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "fixture-data"
FACTS = "fixture.json"
API = "/api/v1"
ROWS = 10_000
PREVIEW_TARGET_S = 30
APPLY_TARGET_S = 60
# The account that previews and applies the file, made in the copy and nowhere else.
USERNAME = "timing-import"
ACCESS_CODE = "timing-import-code"
DOMAIN = "example.net"
# How often a person signs in while the file is applied, and how often the job is asked
# how far it has got, in seconds; and how many sign-ins are timed with nothing going on.
SIGN_IN_EVERY = 1.0
ASK_EVERY = 0.25
IDLE_SIGN_INS = 15
WARM_UP = 2
# The longest any one step is waited for, in seconds.
LONGEST = 900
# The kinds of item the file holds, by catalog type, and how their host names begin.
USES = (("switch", "sw"), ("access-point", "ap"))
COLUMNS = (
    "vendor",
    "pid",
    "serial_number",
    "asset_tag",
    "hostname",
    "fqdn",
    "mac_address",
    "lifecycle_state",
    "owner",
    "location",
    "procured_on",
    "delivered_on",
    "in_service_on",
    "record_status",
)
# The parts of an apply that are timed, as `hirdir.io.imports` names them.
PARTS = ("_take", "_plan", "_apply_waiting", "_apply_batch", "_complete")


def load() -> float:
    """Return the load average of the host over the last minute."""
    return os.getloadavg()[0]


def percentile(samples: Sequence[float], share: float) -> float:
    """Return the sample at a share of the way up, by the nearest rank."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


# --- the copy of the fixture, and the file ----------------------------------------------


def copy_fixture(source: Path, target: Path) -> None:
    """Copy the fixture's database into target, with SQLite's own backup."""
    with (
        closing(sqlite3.connect(source / "hirdir.db")) as given,
        closing(sqlite3.connect(target / "hirdir.db")) as copy,
    ):
        given.backup(copy)


@dataclass(frozen=True)
class Known:
    """What the file refers to: models by use, as vendor and PID; the HIDs of floors and
    rooms; and the labels of owners."""

    models: dict[str, list[tuple[str, str]]]
    locations: list[str]
    owners: list[str]


def prepare(target: Path) -> Known:
    """Bring the copy to the schema of this code, as `hirdir admin migrate` does, make the
    account that applies the file in it, and read what the file is to refer to. A fixture
    made by an earlier release is so timed as this one, and is itself left as it is."""
    from hirdir.config import Config
    from hirdir.db import migrate
    from hirdir.db.engine import make_engine, make_sessions
    from hirdir.db.models import CatalogEntry, Location, Owner, Vendor
    from hirdir.domain import accounts, audit

    migrate.upgrade(Config(state_dir=target).database_url)
    engine = make_engine(Config(state_dir=target).database_url)
    try:
        with make_sessions(engine)() as db:
            user, _ = accounts.create_user(
                db, audit.SYSTEM, username=USERNAME, access_code=ACCESS_CODE
            )
            accounts.grant_role(db, audit.SYSTEM, role="inventory", user_hid=user.hid)
            db.commit()
            models = {
                use: [
                    (vendor, pid)
                    for vendor, pid in db.execute(
                        select(Vendor.name, CatalogEntry.pid)
                        .join(Vendor, Vendor.hid == CatalogEntry.vendor_hid)
                        .where(CatalogEntry.type == use, CatalogEntry.record_status == "active")
                        .order_by(CatalogEntry.pid_key)
                    )
                ]
                for use, _ in USES
            }
            locations = list(
                db.scalars(
                    select(Location.hid)
                    .where(Location.kind.in_(("floor", "room")), Location.record_status == "active")
                    .order_by(Location.hid)
                )
            )
            owners = list(
                db.scalars(
                    select(Owner.label)
                    .where(Owner.record_status == "active")
                    .order_by(Owner.label_key)
                )
            )
    finally:
        engine.dispose()
    return Known(models, locations, owners)


def make_file(known: Known, rows: int, today: date) -> bytes:
    """Return a CSV file of new items, half switches and half access points, all in
    service, spread over the models, places and owners the fixture has."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for number in range(1, rows + 1):
        use, short = USES[number % len(USES)]
        vendor, pid = known.models[use][number % len(known.models[use])]
        hostname = f"imp-{short}-{number:05d}"
        writer.writerow(
            [
                vendor,
                pid,
                f"EXI{number:07d}",
                f"AT-I{number:06d}",
                hostname,
                f"{hostname}.{DOMAIN}",
                f"025f{number:08x}" if use == "access-point" else "",
                "Prod",
                known.owners[number % len(known.owners)],
                known.locations[number % len(known.locations)],
                (today - timedelta(days=30)).isoformat(),
                (today - timedelta(days=20)).isoformat(),
                (today - timedelta(days=10)).isoformat(),
                "active",
            ]
        )
    return out.getvalue().encode()


# --- the parts of an apply, and the server -------------------------------------------------


@dataclass
class Spans:
    """When each call of a part of an apply began and ended, by `time.perf_counter`."""

    took: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _timed(self, name: str, inner: Callable[..., Any]) -> Callable[..., Any]:
        def timed(*args: Any, **kwargs: Any) -> Any:
            began = time.perf_counter()
            try:
                return inner(*args, **kwargs)
            finally:
                ended = time.perf_counter()
                with self.lock:
                    self.took.setdefault(name, []).append((began, ended))

        return timed

    @contextmanager
    def wrapped(self, module: Any, names: Sequence[str]) -> Generator[None]:
        """Time every call of some functions of a module while the block lasts, and put
        them back as they were after it."""
        held = {name: getattr(module, name) for name in names}
        try:
            for name, inner in held.items():
                setattr(module, name, self._timed(name, inner))
            yield
        finally:
            for name, inner in held.items():
                setattr(module, name, inner)

    def of(self, name: str, after: float) -> list[tuple[float, float]]:
        """Return the calls of one part that began after a moment, in order."""
        with self.lock:
            return sorted(span for span in self.took.get(name, []) if span[0] >= after)


class Served:
    """An application served by uvicorn on a free port of 127.0.0.1, in a thread."""

    def __init__(self, app: FastAPI) -> None:
        with closing(socket.socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            server_header=False,
            proxy_headers=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        began = time.monotonic()
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() - began > LONGEST:
                raise SystemExit("the server did not start")
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.server.should_exit = True
        self.thread.join(LONGEST)


# --- signing in -------------------------------------------------------------------------


def sign_in(client: httpx2.Client, username: str, access_code: str) -> tuple[float, str]:
    """Sign in. Return how long it took, in milliseconds, and the token."""
    began = time.perf_counter()
    response = client.post(
        f"{API}/auth/sign-in", json={"username": username, "access_code": access_code}
    )
    took = (time.perf_counter() - began) * 1000
    if response.status_code != 200:
        raise SystemExit(f"cannot sign in as {username}: {response.status_code} {response.text}")
    return took, response.json()["token"]


class Signer(threading.Thread):
    """A person who signs in every so often until told to stop, each sign-in timed."""

    def __init__(self, base: str, username: str, access_code: str, every: float) -> None:
        super().__init__(name="signer", daemon=True)
        self.base, self.username, self.access_code, self.every = base, username, access_code, every
        self.done = threading.Event()
        # When each sign-in began, by `time.perf_counter`, and how long it took, in ms.
        self.samples: list[tuple[float, float]] = []

    def run(self) -> None:
        with httpx2.Client(base_url=self.base, timeout=LONGEST) as client:
            while not self.done.is_set():
                began = time.perf_counter()
                took, _ = sign_in(client, self.username, self.access_code)
                self.samples.append((began, took))
                self.done.wait(max(0.0, self.every - took / 1000))


# --- the run -------------------------------------------------------------------------------


@dataclass
class Measured:
    """What one run measured, in seconds unless said."""

    rows: int
    file_bytes: int
    preview_s: float
    preview_answered_s: float
    preview_load: float
    previewed: dict[str, Any]
    apply_s: float
    apply_load: float
    job: dict[str, Any]
    taken_after_s: float
    plan_s: float
    batches: list[float]
    tries: int
    pauses: list[float]
    complete_s: float
    idle_sign_ins_ms: list[float]
    sign_ins_ms: list[float]
    sign_ins_load: float


def ask_job(client: httpx2.Client, hid: str) -> dict[str, Any]:
    response = client.get(f"{API}/imports/{hid}")
    if response.status_code != 200:
        raise SystemExit(f"cannot read the import {hid}: {response.status_code} {response.text}")
    return response.json()


def run(base: str, data: bytes, rows: int, facts: dict[str, Any], spans: Spans) -> Measured:
    """Preview the file and apply it, with a person signing in beside the apply."""
    with httpx2.Client(base_url=base, timeout=LONGEST) as client:
        _, token = sign_in(client, USERNAME, ACCESS_CODE)
        client.headers["Authorization"] = f"Bearer {token}"
        idle = []
        with httpx2.Client(base_url=base, timeout=LONGEST) as other:
            for number in range(WARM_UP + IDLE_SIGN_INS):
                took, _ = sign_in(other, facts["username"], facts["access_code"])
                if number >= WARM_UP:
                    idle.append(took)
        print(f"sign-in with nothing going on: median {statistics.median(idle):.0f} ms")
        began = time.perf_counter()
        response = client.post(
            f"{API}/imports/preview",
            params={"entity": "items", "mode": "create", "file_name": "new-items.csv"},
            content=data,
            headers={"Content-Type": "text/csv"},
        )
        answered_s = time.perf_counter() - began
        if response.status_code not in (201, 202):
            raise SystemExit(f"the preview was refused: {response.status_code} {response.text}")
        previewed = response.json()["job"]
        # More than a hundred rows are previewed in the background (P-325): followed
        # from the request to the job previewed.
        told = 0.0
        while previewed["status"] == "previewing":
            if time.perf_counter() - began > LONGEST:
                raise SystemExit(f"the preview took longer than {LONGEST} s")
            time.sleep(ASK_EVERY)
            previewed = ask_job(client, previewed["hid"])
            if time.perf_counter() - told >= 10:
                told = time.perf_counter()
                print(
                    f"  previewing: {previewed['rows_previewed']:,} of "
                    f"{previewed['row_count']:,} rows, load {load():.2f}"
                )
        preview_s = time.perf_counter() - began
        preview_load = load()
        if previewed["status"] != "previewed":
            raise SystemExit(f"the preview ended {previewed['status']}: {previewed['failure']}")
        print(
            f"preview answered {response.status_code} in {answered_s:.2f} s, "
            f"previewed {preview_s:.1f} s after the request"
        )
        print(
            f"preview: {preview_s:.1f} s, load {preview_load:.2f}; "
            f"{previewed['created']:,} to create, {previewed['rejected']:,} rejected"
        )
        if previewed["rejected"] or previewed["created"] != rows:
            raise SystemExit(f"the preview does not create every row: {json.dumps(previewed)}")
        hid = previewed["hid"]
        signer = Signer(base, facts["username"], facts["access_code"], SIGN_IN_EVERY)
        signer.start()
        began = time.perf_counter()
        response = client.post(f"{API}/imports/{hid}/apply")
        if response.status_code != 202:
            raise SystemExit(f"the apply was refused: {response.status_code} {response.text}")
        job = response.json()
        told = 0.0
        while job["status"] in ("queued", "applying"):
            if time.perf_counter() - began > LONGEST:
                raise SystemExit(f"the apply took longer than {LONGEST} s")
            time.sleep(ASK_EVERY)
            job = ask_job(client, hid)
            if time.perf_counter() - told >= 10:
                told = time.perf_counter()
                print(f"  {job['rows_done']:,} of {job['row_count']:,} rows, load {load():.2f}")
        seen_s = time.perf_counter() - began
        signer.done.set()
        signer.join(LONGEST)
    apply_load = load()
    if job["status"] != "applied":
        raise SystemExit(f"the apply ended {job['status']}: {job.get('failure')}")
    after = began
    taken = spans.of("_take", after)
    batches = spans.of("_apply_waiting", after)
    ended = spans.of("_complete", after)[-1][1]
    plan = spans.of("_plan", after)
    pauses = [later[0] - earlier[1] for earlier, later in pairwise(batches)]
    during = [took for at, took in signer.samples if batches[0][0] <= at <= batches[-1][1]]
    print(f"applied: {ended - began:.1f} s to the end of the job, {seen_s:.1f} s as asked")
    return Measured(
        rows=rows,
        file_bytes=len(data),
        preview_s=preview_s,
        preview_answered_s=answered_s,
        preview_load=preview_load,
        previewed=previewed,
        apply_s=ended - began,
        apply_load=apply_load,
        job=job,
        taken_after_s=taken[0][0] - began,
        plan_s=sum(end - start for start, end in plan),
        batches=[end - start for start, end in batches],
        tries=len(spans.of("_apply_batch", after)),
        pauses=pauses,
        complete_s=sum(end - start for start, end in spans.of("_complete", after)),
        idle_sign_ins_ms=idle,
        sign_ins_ms=during,
        sign_ins_load=apply_load,
    )


def report(found: Measured) -> str:
    """Return what was measured, against the quality of docs/requirements.md."""
    batches, pauses = found.batches, found.pauses
    in_batches = sum(batches)
    paused = sum(pauses)
    rest = found.apply_s - found.taken_after_s - found.plan_s - in_batches - paused
    rest -= found.complete_s
    idle = statistics.median(found.idle_sign_ins_ms)
    during = found.sign_ins_ms
    waited = [max(0.0, took - idle) for took in during]

    def verdict(seconds: float, target: int) -> str:
        return f"{'meets' if seconds < target else 'misses'} the {target} s of the quality"

    lines = [
        f"file: {found.rows:,} new items, {found.file_bytes / 1e6:.1f} MB of CSV",
        f"preview: {found.preview_s:.1f} s from the request to the job previewed, "
        f"{verdict(found.preview_s, PREVIEW_TARGET_S)}, load {found.preview_load:.2f}; "
        f"the request answered in {found.preview_answered_s:.2f} s",
        f"apply: {found.apply_s:.1f} s from the request to the job applied, "
        f"{verdict(found.apply_s, APPLY_TARGET_S)}, load {found.apply_load:.2f}; "
        f"{found.job['applied']:,} applied, {found.job['stale']:,} stale",
        f"  taken up by the worker after {found.taken_after_s * 1000:.0f} ms",
        f"  the order of the rows worked out: {found.plan_s:.1f} s",
        f"  {len(batches)} batches: {in_batches:.1f} s in all, median "
        f"{statistics.median(batches) * 1000:.0f} ms, 95th percentile "
        f"{percentile(batches, 0.95) * 1000:.0f} ms, longest {max(batches) * 1000:.0f} ms, "
        f"{found.tries - len(batches)} tried again",
        f"  {len(pauses)} pauses between them: {paused:.1f} s in all, the longest "
        f"{max(pauses, default=0) * 1000:.0f} ms",
        f"  the end of the job: {found.complete_s * 1000:.0f} ms; the rest: {rest:.1f} s",
        f"sign-in with nothing going on: median {idle:.0f} ms, 95th percentile "
        f"{percentile(found.idle_sign_ins_ms, 0.95):.0f} ms ({len(found.idle_sign_ins_ms)} "
        f"after {WARM_UP})",
    ]
    if during:
        lines.append(
            f"sign-in during the apply: {len(during)}, median {statistics.median(during):.0f} "
            f"ms, 95th percentile {percentile(during, 0.95):.0f} ms, longest {max(during):.0f} "
            f"ms; waited beyond the idle median: median {statistics.median(waited):.0f} ms, "
            f"95th percentile {percentile(waited, 0.95):.0f} ms, longest {max(waited):.0f} ms; "
            f"load {found.sign_ins_load:.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time an import of new items on the fixture.")
    parser.add_argument("folder", nargs="?", type=Path, default=FOLDER)
    parser.add_argument("--rows", type=int, default=ROWS, help="how many, 10,000 unless said")
    parser.add_argument("--save", type=Path, help="write what was measured, as JSON, here")
    given = parser.parse_args(argv)
    facts_path = given.folder / FACTS
    if not facts_path.is_file():
        parser.error(f"{given.folder} holds no fixture: run `make fixture` first")
    if given.rows < 1:
        parser.error("--rows is 1 at the least")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    print(f"fixture of {facts['built_on']}: {facts['counts']['items']:,} items")
    print(f"before: load average {load():.2f} on {os.cpu_count()} cores")
    from hirdir.app import create_app
    from hirdir.config import Config
    from hirdir.io import imports
    from hirdir.memory import settle

    with tempfile.TemporaryDirectory(prefix="hirdir-time-import-") as folder:
        target = Path(folder)
        began = time.perf_counter()
        copy_fixture(given.folder, target)
        known = prepare(target)
        data = make_file(known, given.rows, date.today())
        print(f"copied and prepared in {time.perf_counter() - began:.1f} s, in {target}")
        spans = Spans()
        app = create_app(Config(state_dir=target), scheduled=True)
        # As the server does once it is made (P-326).
        settle()
        with spans.wrapped(imports, PARTS), Served(app) as base:
            found = run(base, data, given.rows, facts, spans)
        app.state.engine.dispose()
    print(f"after: load average {load():.2f}")
    print()
    print(report(found))
    if given.save:
        given.save.write_text(json.dumps(found.__dict__, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
