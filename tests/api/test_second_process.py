"""The second process of the service, `hirdir admin work`, and the server beside it
(P-263, P-267).

The server applies nothing: here it is the application built with `work=False`, as
`hirdir admin serve` builds it, asked through its routes. The second process is
`background.working`, which `hirdir admin work` runs holding the lock of
`background.hold_lock`, and once the command itself, started as a process and stopped
with a signal.
"""

import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from hirdir import schedule
from hirdir.app import bind, create_app
from hirdir.cli import admin
from hirdir.cli.main import app as command
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import AuditEvent, CapacityRecord, ImportJob, Tag
from hirdir.domain import accounts, audit, tags
from hirdir.domain.audit import AuditContext
from hirdir.io import background, imports, kept
from tests.api.inventory import API, Maker
from tests.conftest import INVENTORY_CODE, sign_in

HEAD = "vendor,pid,serial_number,hostname"
STOPPED_BY_A_STOP = "the background work stopped while it was being applied"
runner = CliRunner()


def switches(count: int) -> str:
    """A file of new switches, one to a row, each with a serial number of its own."""
    rows = [
        f"Cisco,C9300-48P,FCW0000Z{number:03d},site3-sw-{number:03d}"
        for number in range(1, count + 1)
    ]
    return "\n".join([HEAD, *rows]) + "\n"


@pytest.fixture(scope="module")
def built_alone(tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    """The application as the server of the service has it, with none of the background
    work in it: built once, and bound to the state of each test in turn."""
    settings = Config(state_dir=tmp_path_factory.mktemp("alone"), trusted_proxies=("testclient",))
    return create_app(settings, work=False)


@pytest.fixture
def server(config: Config, built_alone: FastAPI) -> Iterator[Maker]:
    """The server alone, asked by somebody with the Inventory role."""
    engine = make_engine(config.database_url)
    with make_sessions(engine)() as session:
        user, _ = accounts.create_user(
            session, audit.SYSTEM, username="ivy", access_code=INVENTORY_CODE
        )
        accounts.grant_role(session, audit.SYSTEM, role="inventory", user_hid=user.hid)
        session.commit()
    engine.dispose()
    built_alone.state.engine.dispose()
    bind(built_alone, config)
    with TestClient(built_alone) as client:
        yield Maker(client, sign_in(client, "ivy", INVENTORY_CODE))
    built_alone.state.engine.dispose()


@pytest.fixture
def installed(config: Config, monkeypatch) -> Config:
    """The state of a test as an installation that `hirdir admin` works on, with
    nothing listening where its server would."""
    quiet = Config(state_dir=config.state_dir, listen="127.0.0.1:1")
    monkeypatch.setattr(admin, "_load", lambda: quiet)
    return quiet


def asker(db: Any, request_id: str) -> AuditContext:
    """Return who asks for an apply where no route does: somebody with the Inventory
    role, whose role the worker looks at again as it takes the job up."""
    user, _ = accounts.create_user(db, audit.SYSTEM, username="imp", access_code="imp-code-01")
    accounts.grant_role(db, audit.SYSTEM, role="inventory", user_hid=user.hid)
    return AuditContext(actor_hid=user.hid, via="api", request_id=request_id)


def preview(make: Maker, entity: str, text: str) -> dict[str, Any]:
    response = make.client.post(
        f"{API}/imports/preview",
        params={"entity": entity},
        content=text,
        headers={**make.headers, "Content-Type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    return response.json()["job"]


def begin(make: Maker, job: dict[str, Any]) -> dict[str, Any]:
    """Ask for a job to be applied, and return the answer, which comes at once."""
    response = make.client.post(f"{API}/imports/{job['hid']}/apply", headers=make.headers)
    assert response.status_code == 202, response.text
    return response.json()


def ended(make: Maker, job: dict[str, Any], within: float = 30.0) -> dict[str, Any]:
    """Return a job once it is no longer waiting or being applied."""
    deadline = time.monotonic() + within
    while True:
        found = make.get(f"/imports/{job['hid']}")
        if found["status"] not in ("queued", "applying"):
            return found
        assert time.monotonic() < deadline, f"the job is still {found['status']}"
        time.sleep(0.02)


def anew(db: Any) -> None:
    """Have a session look at the database again, and not at what it read before."""
    db.rollback()
    db.expire_all()


def labels(make: Maker) -> list[str]:
    return sorted(tag["label"] for tag in make.get("/tags"))


def counted(config: Config, model: Any) -> int:
    engine = make_engine(config.database_url)
    with make_sessions(engine)() as db:
        found = db.scalar(select(func.count()).select_from(model)) or 0
    engine.dispose()
    return found


# --- the lock -------------------------------------------------------------------------


def test_one_process_of_the_background_work_holds_the_lock_and_a_second_is_refused(
    tmp_path: Path,
) -> None:
    lock = tmp_path / background.WORKER_LOCK
    assert not background.is_held(lock)
    first = background.hold_lock(tmp_path)
    assert background.is_held(lock)
    began = time.monotonic()
    with pytest.raises(background.AnotherWorks):
        background.hold_lock(tmp_path, within=0.3)
    # It asked for as long as it was given, and not once.
    assert time.monotonic() - began >= 0.3
    # Nothing is written for the lock: the file is there, and empty.
    assert lock.read_bytes() == b""
    first.close()
    assert not background.is_held(lock)
    background.hold_lock(tmp_path, within=0).close()


def test_the_servers_question_does_not_make_the_start_fail(tmp_path: Path) -> None:
    """The server learns whether the process runs by asking for its lock, shared, which
    holds the file for an instant. A process that starts in that instant asks again."""
    lock = tmp_path / background.WORKER_LOCK
    lock.touch()
    asking, let_go = threading.Event(), threading.Event()

    def question_that_lasts() -> None:
        with lock.open("rb") as asked:
            fcntl.flock(asked, fcntl.LOCK_SH | fcntl.LOCK_NB)
            asking.set()
            let_go.wait(10)

    asker = threading.Thread(target=question_that_lasts)
    asker.start()
    assert asking.wait(10)
    # Asked for once and no more, the lock is refused while the question lasts.
    with pytest.raises(background.AnotherWorks):
        background.hold_lock(tmp_path, within=0)
    threading.Timer(0.3, let_go.set).start()
    held = background.hold_lock(tmp_path)
    asker.join()
    assert background.is_held(lock)
    # A question while it is held learns that it runs, and takes nothing from it.
    state = SimpleNamespace(config=Config(state_dir=tmp_path))
    assert [background.worker_state(state) for _ in range(50)] == ["running"] * 50
    with pytest.raises(background.AnotherWorks):
        background.hold_lock(tmp_path, within=0)
    held.close()
    assert background.LOCK_WITHIN >= 1.0


def test_the_server_says_where_the_background_work_is_done_in_three_answers(
    config: Config, server: Maker, built_alone: FastAPI
) -> None:
    alone = built_alone.state
    # No file, and then a file that nobody holds.
    assert not (config.state_dir / background.WORKER_LOCK).exists()
    assert background.worker_state(alone) == "not_running"
    with closing(background.hold_lock(config.state_dir)):
        assert background.worker_state(alone) == "running"
    assert (config.state_dir / background.WORKER_LOCK).exists()
    assert background.worker_state(alone) == "not_running"
    # One process that does both says so, whoever holds the lock.
    both = create_app(config)
    with TestClient(both), closing(background.hold_lock(config.state_dir)):
        assert background.worker_state(both.state) == "in_process"
    both.state.engine.dispose()
    assert background.worker_state(both.state) == "not_running"


# --- the server alone, and the second process beside it -----------------------------


def test_the_server_alone_applies_nothing_and_the_second_process_applies_what_is_asked(
    config: Config, server: Maker, built_alone: FastAPI
) -> None:
    alone = built_alone.state
    assert not isinstance(getattr(alone, "worker", None), background.Worker)
    waiting = preview(server, "tags", "label\nlab\n")
    # The server takes the request whether anything is there to apply it or not, and
    # stores it as queued: nothing here takes it up.
    assert begin(server, waiting)["status"] == "queued"
    background.wake(alone)
    time.sleep(0.5)
    left = server.get(f"/imports/{waiting['hid']}")
    assert (left["status"], left["rows_done"], left["applied"]) == ("queued", 0, 0)
    assert labels(server) == []

    with closing(background.hold_lock(config.state_dir)), background.working(config):
        assert background.worker_state(alone) == "running"
        # What waited is applied when the process starts: it was never cut short, and
        # nobody has to ask again.
        found = ended(server, waiting)
        assert (found["status"], found["applied"], found["failure"]) == ("applied", 1, None)
        # And so is one asked for while the process runs.
        other = preview(server, "tags", "label\nspare\n")
        asked = time.monotonic()
        assert begin(server, other)["status"] == "queued"
        assert ended(server, other)["status"] == "applied"
        # Within a second of being asked for, and the time one row takes: nobody woke it.
        assert time.monotonic() - asked < background.LOOK_EVERY_ALONE + 5
    assert labels(server) == ["lab", "spare"]
    assert background.LOOK_EVERY_ALONE == 1.0
    assert background.worker_state(alone) == "not_running"


def test_a_stop_in_the_middle_of_an_apply_stops_after_the_batch_and_is_resumed(
    config: Config, server: Maker, monkeypatch
) -> None:
    server.entry(server.vendor())
    job = preview(server, "items", switches(120))
    original = imports._apply_batch
    stored, go_on = threading.Event(), threading.Event()

    def held_after_its_first_batch(db, run, which, hid, batch, typed):
        done = original(db, run, which, hid, batch, typed)
        if not stored.is_set():
            stored.set()
            assert go_on.wait(30)
        return done

    monkeypatch.setattr(imports, "_apply_batch", held_after_its_first_batch)
    with background.working(config) as worker:
        begin(server, job)
        assert stored.wait(30)
        # The stop is asked for while the first batch is being stored, as SIGTERM asks.
        worker.stop(within=0)
        go_on.set()
    stopped = server.get(f"/imports/{job['hid']}")
    assert (stopped["status"], stopped["rows_done"], stopped["applied"]) == ("stopped", 50, 50)
    assert stopped["failure"].startswith(STOPPED_BY_A_STOP)
    assert server.get("/items", limit=1)["total"] == 50

    # The process starts again: a stopped job is left for somebody to resume.
    with background.working(config):
        time.sleep(0.3)
        assert server.get(f"/imports/{job['hid']}")["status"] == "stopped"
        assert begin(server, job)["status"] == "queued"
        done = ended(server, job)
    assert (done["status"], done["rows_done"], done["applied"]) == ("applied", 120, 120)
    assert server.get("/items", limit=1)["total"] == 120


def test_what_is_done_by_the_clock_is_shared_between_the_two(config: Config) -> None:
    """The record of the week is written to the database, and is the second process's.
    The long reports are kept in the memory of the process that answers, and are the
    server's own, after the record, whose event would leave them stale."""
    assert [job.name for job in schedule.BACKGROUND_JOBS] == ["capacity record"]
    assert [job.name for job in schedule.SERVER_JOBS] == ["long reports"]
    assert set(schedule.BACKGROUND_JOBS) | set(schedule.SERVER_JOBS) == set(schedule.JOBS)
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    monday = datetime(2027, 3, 29, 12, 0, tzinfo=UTC)
    record = schedule.CAPACITY_RECORD.when(monday, zone)
    reports = schedule.LONG_REPORTS.when(monday, zone)
    assert (record.hour, record.minute) == (0, 1)
    assert (reports.hour, reports.minute) == (0, 5)
    assert record.date() == reports.date()

    # The second process, at its start: the record, and nothing kept in its memory.
    with background.working(config):
        assert counted(config, CapacityRecord) == 1
        engine = make_engine(config.database_url)
        with make_sessions(engine)() as db:
            assert kept.listing(db) == []
        engine.dispose()


def test_the_work_command_does_what_is_due_at_start_applies_and_stops_on_a_signal(
    config: Config, db, tmp_path: Path
) -> None:
    settings = tmp_path / "config.toml"
    settings.write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n', encoding="utf-8")
    env = {**os.environ, "HIRDIR_CONFIG": str(settings)}
    asked = asker(db, "apply-request-02")
    # A job that was being applied when the process stopped the last time: taken up, as
    # only a worker takes one, and left so. And one that was asked for since, and waits.
    cut_short = imports.preview(
        db, asked, None, data=b"label\nlab\n", format_="csv", entity_name="tags"
    )
    waited = imports.preview(
        db, asked, None, data=b"label\nwaited\n", format_="csv", entity_name="tags"
    )
    imports.begin_apply(db, asked, cut_short.hid, source="file")
    imports.begin_apply(db, asked, waited.hid, source="file")
    db.commit()
    assert imports._take(db, cut_short.hid) is not None

    said = tmp_path / "work.log"
    with said.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "hirdir.cli.main", "admin", "work"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
    try:
        deadline = time.monotonic() + 60
        while "is under way" not in said.read_text(encoding="utf-8"):
            assert process.poll() is None, said.read_text(encoding="utf-8")
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert background.is_held(config.state_dir / background.WORKER_LOCK)
        # What is due at start is done before it says so: the record of the week.
        anew(db)
        assert db.scalar(select(func.count()).select_from(CapacityRecord)) == 1
        found = db.get_one(ImportJob, cut_short.hid)
        assert found.status == "stopped"
        assert (found.failure or "").startswith(STOPPED_BY_A_STOP)
        # What waited queued while no process ran is applied by the one that starts.
        deadline = time.monotonic() + 30
        while db.get_one(ImportJob, waited.hid).status != "applied":
            assert time.monotonic() < deadline, db.get_one(ImportJob, waited.hid).status
            time.sleep(0.05)
            anew(db)

        # A second one on the same state directory stops with words, and the first goes on.
        second = subprocess.run(
            [sys.executable, "-m", "hirdir.cli.main", "admin", "work"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert second.returncode == 1
        assert (
            f"another process of the background work is running on {config.state_dir}: "
            "stop it first" in second.stderr
        )
        assert process.poll() is None

        # What is asked for while it runs, here as the server stores it, it finds itself:
        # the one to apply, and the one that waits queued behind it, in their order.
        job = imports.preview(
            db, asked, None, data=b"label\nspare\n", format_="csv", entity_name="tags"
        )
        behind = imports.preview(
            db, asked, None, data=b"label\nstaging\n", format_="csv", entity_name="tags"
        )
        first = imports.begin_apply(db, asked, job.hid, source="file")
        second_job = imports.begin_apply(db, asked, behind.hid, source="file")
        assert (first.status, second_job.status) == ("queued", "queued")
        db.commit()
        deadline = time.monotonic() + 30
        while True:
            anew(db)
            found = [db.get_one(ImportJob, one.hid).status for one in (job, behind)]
            if found == ["applied", "applied"]:
                break
            assert time.monotonic() < deadline, found
            time.sleep(0.05)
        assert sorted(db.scalars(select(Tag.label))) == ["spare", "staging", "waited"]

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=70) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    told = said.read_text(encoding="utf-8")
    assert f"hirdir: the background work of {config.state_dir} is under way" in told
    assert f"hirdir: the background work of {config.state_dir} is stopped" in told
    assert "Traceback" not in told
    assert not background.is_held(config.state_dir / background.WORKER_LOCK)


# --- hirdir admin serve ---------------------------------------------------------------


def served(installed: Config, monkeypatch, *options: str) -> dict[str, Any]:
    """Run `hirdir admin serve` up to where it would listen, start the application it
    built as uvicorn would, and return what was so while it ran."""
    seen: dict[str, Any] = {}

    def started_and_stopped(application: FastAPI, **how: Any) -> None:
        with TestClient(application):
            state = application.state
            seen["worker"] = background.worker_state(state)
            seen["server_lock"] = background.is_held(installed.state_dir / admin.SERVER_LOCK)
            seen["worker_lock"] = background.is_held(installed.state_dir / background.WORKER_LOCK)
            with state.sessions() as db:
                seen["kept"] = {entry.report for entry in kept.listing(db)}
                seen["records"] = db.scalar(select(func.count()).select_from(CapacityRecord))
                asked = asker(db, "apply-request-03")
                job = imports.preview(
                    db, asked, None, data=b"label\nlab\n", format_="csv", entity_name="tags"
                )
                hid = imports.begin_apply(db, asked, job.hid, source="file").hid
                db.commit()
                background.wake(state)
                # With the work in this process the job is waited for as long as a
                # loaded host may take; without, a moment shows that nothing takes it.
                deadline = time.monotonic() + (60 if "--work" in options else 1.5)
                while True:
                    anew(db)
                    seen["job"] = db.get_one(ImportJob, hid).status
                    if seen["job"] == "applied" or time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
        application.state.engine.dispose()

    monkeypatch.setattr(uvicorn, "run", started_and_stopped)
    result = runner.invoke(command, ["admin", "serve", *options])
    assert result.exit_code == 0, result.output
    return seen


def test_serve_does_none_of_the_background_work_and_keeps_what_is_the_servers_own(
    installed: Config, monkeypatch
) -> None:
    seen = served(installed, monkeypatch)
    # It holds its own lock and not the other, applies nothing and records nothing.
    assert (seen["server_lock"], seen["worker_lock"]) == (True, False)
    assert (seen["worker"], seen["job"], seen["records"]) == ("not_running", "queued", 0)
    # The long reports are kept in its own memory, so it works them out itself.
    assert seen["kept"] == {"coverage", "renewals", "renewal_alert", "capacity"}
    assert not background.is_held(installed.state_dir / admin.SERVER_LOCK)


def test_serve_with_work_does_both_in_one_process_and_holds_both_locks(
    installed: Config, monkeypatch
) -> None:
    seen = served(installed, monkeypatch, "--work")
    assert (seen["server_lock"], seen["worker_lock"]) == (True, True)
    assert (seen["worker"], seen["job"], seen["records"]) == ("in_process", "applied", 1)
    assert seen["kept"] == {"coverage", "renewals", "renewal_alert", "capacity"}
    assert not background.is_held(installed.state_dir / background.WORKER_LOCK)


def test_serve_with_work_is_refused_beside_a_process_of_the_background_work(
    installed: Config, monkeypatch
) -> None:
    monkeypatch.setattr(background, "LOCK_WITHIN", 0.2)
    monkeypatch.setattr(uvicorn, "run", lambda *given, **how: pytest.fail("it went on"))
    with closing(background.hold_lock(installed.state_dir)):
        result = runner.invoke(command, ["admin", "serve", "--work"])
        assert result.exit_code == 1
        assert "another process of the background work is running on" in result.output
        # And it let go of the server's lock, which it had taken first.
        assert not background.is_held(installed.state_dir / admin.SERVER_LOCK)
        refused = runner.invoke(command, ["admin", "work"])
        assert refused.exit_code == 1
        assert "another process of the background work is running on" in refused.output


# --- the commands that need the service stopped ---------------------------------------


@pytest.mark.parametrize(
    ("runs", "named", "not_named"),
    [
        ("worker", "the process of the background work (hirdir-worker.service)", "the server on"),
        ("server", "the server on 127.0.0.1:1 (hirdir.service)", "the process of"),
        (
            "both",
            "the server on 127.0.0.1:1 (hirdir.service) and the process of the background "
            "work (hirdir-worker.service)",
            "",
        ),
    ],
)
def test_the_commands_that_need_the_service_stopped_refuse_and_say_which_runs(
    installed: Config, db, runs: str, named: str, not_named: str
) -> None:
    tags.create_tag(db, asker(db, "tag-request-01"), {"label": "lab"})
    db.commit()
    made = runner.invoke(command, ["admin", "backup"])
    assert made.exit_code == 0, made.output
    backup = made.output.strip().splitlines()[-1]
    events = counted(installed, AuditEvent)
    held = []
    if runs in ("worker", "both"):
        held.append(background.hold_lock(installed.state_dir))
    if runs in ("server", "both"):
        held.append(admin._one_server(installed.state_dir))
    try:
        for arguments in (["reset", "--yes"], ["load-examples"], ["restore", backup]):
            result = runner.invoke(command, ["admin", *arguments])
            said = " ".join(result.output.split())
            assert result.exit_code == 1, said
            assert f"hirdir: the service is running, {named}: stop it first" in said
            assert "`sudo systemctl stop hirdir`, which stops the server and the process" in said
            assert not not_named or not_named not in said.split(": stop it first")[0]
    finally:
        for lock in held:
            lock.close()
    # Nothing was changed: the tag, the audit trail, and no copy kept by a restore.
    assert counted(installed, Tag) == 1
    assert counted(installed, AuditEvent) == events
    assert not Path(f"{installed.database_path}.before-restore").exists()
    # With both stopped, each goes on.
    assert runner.invoke(command, ["admin", "restore", backup]).exit_code == 0
    assert runner.invoke(command, ["admin", "reset", "--yes"]).exit_code == 0
    assert counted(installed, Tag) == 0
