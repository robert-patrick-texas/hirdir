"""A preview of more than a hundred rows is worked in the background, as an apply is
(P-325).

These run the server's own worker, in its thread, as `hirdir admin serve --work` does:
the request stores the job as `previewing` and answers `202`, and the worker previews
it on a copy of the database. Where a test needs the worker to wait, it holds
`imports._worked`, which a preview in the background calls once it has taken the job.
"""

import json
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from hirdir.auth.roles import Role
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import ImportJob, ImportRow
from hirdir.domain import audit
from hirdir.io import imports, kept
from tests.api import test_cli
from tests.api.inventory import API, Maker, previewed, wait_for_job

HEAD = "vendor,pid,serial_number,hostname,owner,in_service_on"
# The fixture that runs `hirdir` against the test client.
run = test_cli.run
# What a row of a preview says, beside the job it is of.
SAID = ("row", "outcome", "record_hid", "key", "changes", "reasons")


def switches(count: int, first: int = 1, prefix: str = "FCW0000P") -> list[str]:
    """Rows of new switches, each with a serial number and a host name of its own."""
    return [
        f"Cisco,C9300-48P,{prefix}{number:03d},site2-sw-{number:03d},Network Engineering,"
        for number in range(first, first + count)
    ]


def csv(rows: list[str], head: str = HEAD) -> str:
    return "\n".join([head, *rows]) + "\n"


def send(make: Maker, text: str, **params: Any) -> Any:
    """Send a file of items to be previewed, and return the answer as it comes."""
    return make.client.post(
        f"{API}/imports/preview",
        params={"entity": "items", **params},
        content=text,
        headers={**make.headers, "Content-Type": "text/csv"},
    )


def said(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """What each row of a preview says, without the job it is of."""
    return [(*(row[name] for name in SAID), row["notes"]) for row in rows]


def stored(db: Any, hid: str) -> list[tuple[Any, ...]]:
    """Each row of a job as it is stored, all that the apply compares with, but its job."""
    db.rollback()
    return [
        tuple(found)
        for found in db.execute(
            select(
                ImportRow.row,
                ImportRow.outcome,
                ImportRow.record_hid,
                ImportRow.row_version,
                ImportRow.key,
                ImportRow.values,
                ImportRow.changes,
                ImportRow.reasons,
                ImportRow.notes,
            )
            .where(ImportRow.job_hid == hid)
            .order_by(ImportRow.row)
        )
    ]


def all_rows(make: Maker, hid: str) -> list[dict[str, Any]]:
    return make.get(f"/imports/{hid}/rows", limit=1000)["items"]


@pytest.fixture
def catalog(make: Maker) -> dict[str, Any]:
    """A vendor with one model and an owner, for the files to refer to."""
    entry = make.entry(make.vendor("Cisco"), "C9300-48P")
    make.owner("Network Engineering")
    return entry


@pytest.fixture
def hold(monkeypatch) -> Iterator[Callable[[], tuple[threading.Event, threading.Event]]]:
    """Hold the worker once it has taken a preview up, before it works a row. Return a
    maker of two events: `taken`, set once it has, and `go_on`, to let it go on."""
    events: list[threading.Event] = []

    def holding() -> tuple[threading.Event, threading.Event]:
        taken, go_on = threading.Event(), threading.Event()
        events.append(go_on)
        original = imports._worked

        def held(*arguments: Any, **more: Any) -> Any:
            taken.set()
            assert go_on.wait(30)
            return original(*arguments, **more)

        monkeypatch.setattr(imports, "_worked", held)
        return taken, go_on

    yield holding
    # A test that fails before it lets the worker go must not leave it waiting.
    for go_on in events:
        go_on.set()


# --- a hundred rows in the request, more in the background ---------------------------


def test_a_hundred_rows_are_previewed_in_the_request_and_more_in_the_background(
    make: Maker, client: TestClient, catalog: dict, hold, config, monkeypatch
) -> None:
    at_once = send(make, csv(switches(100)))
    assert at_once.status_code == 201, at_once.text
    whole = at_once.json()
    assert (whole["job"]["status"], whole["job"]["rows_previewed"]) == ("previewed", 100)
    assert (whole["job"]["created"], len(whole["rows"])) == (100, 100)

    taken, go_on = hold()
    later = send(make, csv(switches(101, first=201)))
    assert later.status_code == 202, later.text
    answer = later.json()
    job = answer["job"]
    assert (job["status"], job["row_count"], job["rows_previewed"]) == ("previewing", 101, 0)
    assert (job["created"], job["rejected"], answer["rows"]) == (0, 0, [])
    assert taken.wait(30)
    # While it is previewed, the job says how far it has got, and nothing else is had.
    assert make.get(f"/imports/{job['hid']}")["status"] == "previewing"
    listed = make.get("/imports")["items"][0]
    assert (listed["hid"], listed["status"], listed["rows_previewed"]) == (
        job["hid"],
        "previewing",
        0,
    )
    refused = make.get(f"/imports/{job['hid']}/rows", expect=409)
    assert refused["detail"] == (
        "this preview is still being worked out: its rows are listed once it is previewed"
    )
    applying = client.post(f"{API}/imports/{job['hid']}/apply", headers=make.headers)
    assert applying.status_code == 409, applying.text
    assert applying.json()["detail"] == (
        "this preview is still being worked out: it may be applied once it is previewed"
    )

    # How far it has got is stored as it goes, where anybody reads it.
    seen: list[int] = []
    work = imports._work

    def watched(*arguments: Any, progress: Any = None, **more: Any) -> Any:
        def told(done: int) -> None:
            progress(done)
            with make_sessions(make_engine(config.database_url))() as another:
                found = another.scalar(
                    select(ImportJob.rows_previewed).where(ImportJob.hid == job["hid"])
                )
                seen.append(found or 0)

        return work(*arguments, progress=told if progress else None, **more)

    with monkeypatch.context() as watching:
        watching.setattr(imports, "_work", watched)
        go_on.set()
        done = wait_for_job(client, make.headers, job["hid"])
    assert seen == [50, 100, 101]
    assert (done["status"], done["rows_previewed"], done["created"]) == ("previewed", 101, 101)
    assert len(all_rows(make, job["hid"])) == 101
    assert make.get("/items", limit=1)["total"] == 0
    # Applied as any preview is.
    assert make.apply(f"/imports/{job['hid']}/apply")["status"] == "applied"
    assert make.get("/items", limit=1)["total"] == 101
    events = make.audit(record_type="import_job", record_hid=job["hid"], limit=100)
    assert [event["action"] for event in reversed(events)] == [
        "preview",
        "previewed",
        "apply_started",
        "apply",
    ]
    sent, ended = events[-1], events[-2]
    # The end of the preview is under the request that sent it, as the person who did.
    assert (ended["request_id"], ended["actor_name"]) == (sent["request_id"], "ivy")
    assert {"field": "status", "old": "previewing", "new": "previewed"} in ended["changes"]
    assert {"field": "created", "old": None, "new": 101} in ended["changes"]


def test_a_preview_in_the_background_says_what_one_in_the_request_says(
    make: Maker, client: TestClient, catalog: dict, db
) -> None:
    """The same file, previewed in its request and in the background, on one inventory:
    the same counts, and each row the same, its changes, reasons and notes."""
    make.item(catalog_entry_hid=catalog["hid"], serial_number="FCW0000Q001", hostname="old-1")
    make.item(catalog_entry_hid=catalog["hid"], serial_number="FCW0000Q002", hostname="same-2")
    rows = [
        # A change, and nothing changed.
        "Cisco,C9300-48P,FCW0000Q001,new-1,Network Engineering,",
        "Cisco,C9300-48P,FCW0000Q002,same-2,,",
        # Refused by the rules, and a cell that cannot be read.
        "Cisco,C9300-48P,FCW0000Q003,site2-sw-q3,Nobody,",
        "Cisco,C9300-48P,FCW0000Q004,site2-sw-q4,,not a day",
        # A vendor and a model nobody has entered, made for the row.
        "Juniper,EX4400-48P,JN0000Q005,site2-sw-q5,,2026-01-15",
        # A row that names what an earlier row makes.
        "Cisco,C9300-48P,FCW0000Q001,new-1,Network Engineering,",
        *switches(120, prefix="FCW0000R"),
    ]
    text = csv(rows)
    me = make.get("/auth/me")
    context = audit.AuditContext(actor_hid=me["hid"], via="api", request_id="in-the-request")
    in_request = imports.preview(
        db, context, Role.INVENTORY, data=text.encode(), format_="csv", entity_name="items"
    )
    db.commit()
    assert in_request.status == "previewed"

    answer = send(make, text)
    assert answer.status_code == 202, answer.text
    background = previewed(client, make.headers, answer.json())["job"]

    first = make.get(f"/imports/{in_request.hid}")
    shown = ("row_count", "rows_previewed", "created", "updated", "unchanged", "rejected")
    assert [background[name] for name in shown] == [first[name] for name in shown]
    assert (background["created"], background["updated"], background["unchanged"]) == (121, 1, 1)
    assert background["rejected"] == 3
    found = all_rows(make, background["hid"])
    assert said(found) == said(all_rows(make, in_request.hid))
    assert stored(db, background["hid"]) == stored(db, in_request.hid)
    assert [row["outcome"] for row in found[:6]] == [
        "update",
        "unchanged",
        "rejected",
        "rejected",
        "create",
        "rejected",
    ]
    assert found[3]["reasons"][0]["field"] == "in_service_on"
    assert "creates the vendor Juniper, to be reviewed" in found[4]["notes"]
    # What it previewed is what is applied: nothing is stale.
    done = make.apply(f"/imports/{background['hid']}/apply", skip_rejected="true")
    assert (done["status"], done["applied"], done["stale"]) == ("applied", 123, 0)


def test_a_file_that_is_everything_its_system_reports_counts_the_same_in_the_background(
    make: Maker, client: TestClient, db
) -> None:
    system = make.post("/external-systems", {"name": "Example vCenter", "kind": "other"})
    gone = [make.item(name=f"site2-vm-gone{number}") for number in range(3)]
    for number, item in enumerate(gone):
        body = {"system_hid": system["hid"], "item_hid": item["hid"], "external_id": f"g{number}"}
        make.post("/registrations", body)
    head = "external_id,name"
    text = csv([f"vm-{number},site2-vm-{number:03d}" for number in range(120)], head)
    me = make.get("/auth/me")
    context = audit.AuditContext(actor_hid=me["hid"], via="api", request_id="in-the-request")
    in_request = imports.preview(
        db,
        context,
        Role.INVENTORY,
        data=text.encode(),
        format_="csv",
        entity_name="items",
        system=system["hid"],
        complete=True,
    )
    db.commit()
    answer = send(make, text, system=system["hid"], complete="true")
    assert answer.status_code == 202, answer.text
    background = previewed(client, make.headers, answer.json())
    first = make.get(f"/imports/{in_request.hid}")
    assert (background["job"]["not_reported"], background["job"]["complete"]) == (3, True)
    assert background["job"]["not_reported"] == first["not_reported"]
    assert background["job"]["not_reported_first"] == first["not_reported_first"]
    assert said(all_rows(make, background["job"]["hid"])) == said(all_rows(make, in_request.hid))
    assert stored(db, background["job"]["hid"]) == stored(db, in_request.hid)


def test_a_preview_in_the_background_leaves_the_kept_answers_good(
    make: Maker, client: TestClient, catalog: dict, db
) -> None:
    """Its end changes no record, as its start does not: the long reports kept for the
    newest change stay good (P-275)."""
    newest = kept._newest(db)
    db.rollback()
    previewed(client, make.headers, send(make, csv(switches(101))).json())
    assert kept._newest(db) == newest


# --- what ends a preview in the background ---------------------------------------------


def test_a_preview_fails_when_its_sender_no_longer_holds_the_inventory_role(
    make: Maker, client: TestClient, admin: dict[str, str], catalog: dict, monkeypatch
) -> None:
    taken, go_on = threading.Event(), threading.Event()
    take = imports._take_preview

    def held(db: Any, hid: str) -> Any:
        taken.set()
        assert go_on.wait(30)
        return take(db, hid)

    monkeypatch.setattr(imports, "_take_preview", held)
    answer = send(make, csv(switches(101)))
    assert answer.status_code == 202, answer.text
    job = answer.json()["job"]
    assert taken.wait(30)
    boss = Maker(client, admin)
    mine = next(grant for grant in boss.get("/role-grants") if grant["target_name"] == "ivy")
    response = client.delete(f"{API}/role-grants/{mine['hid']}", headers=admin)
    assert response.status_code == 204, response.text
    go_on.set()
    failed = wait_for_job(client, admin, job["hid"])
    assert failed["status"] == "failed"
    assert failed["failure"] == (
        "who asked for the preview no longer holds the Inventory role; anybody who does may "
        "send the file again"
    )
    # Nothing of it is listed, and it is not applied.
    assert boss.get(f"/imports/{job['hid']}/rows")["total"] == 0
    refused = client.post(f"{API}/imports/{job['hid']}/apply", headers=admin)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "this preview failed, and is not applied"
    events = boss.audit(record_type="import_job", record_hid=job["hid"], limit=100)
    assert [event["action"] for event in reversed(events)] == ["preview", "preview_failed"]
    assert (events[0]["actor_name"], events[0]["via"]) == (None, "system")
    assert events[0]["request_id"] == events[1]["request_id"]


def test_an_error_nobody_foresaw_fails_a_preview_with_its_request_id(
    make: Maker, client: TestClient, catalog: dict, monkeypatch, caplog
) -> None:
    one = imports._one

    def fails_at_row_60(run_, which, values, result):
        if result.row == 60:
            raise RuntimeError("something nobody foresaw")
        return one(run_, which, values, result)

    monkeypatch.setattr(imports, "_one", fails_at_row_60)
    answer = send(make, csv(switches(120)), file_name="switches.csv")
    assert answer.status_code == 202, answer.text
    job = answer.json()["job"]
    with caplog.at_level(logging.ERROR, logger="hirdir"):
        failed = wait_for_job(client, make.headers, job["hid"])
    assert failed["status"] == "failed"
    sent = make.audit(record_type="import_job", action="preview")[0]
    assert failed["failure"] == (
        f"an error nobody foresaw ended it (RuntimeError); the request ID is "
        f"{sent['request_id']}; send the file again"
    )
    assert any(
        record.exc_info and f"the preview of {job['hid']} failed" in record.getMessage()
        for record in caplog.records
    )
    assert make.get(f"/imports/{job['hid']}/rows")["total"] == 0
    response = client.post(f"{API}/imports/{job['hid']}/apply", headers=make.headers)
    assert response.status_code == 409, response.text
    assert make.get("/items", limit=1)["total"] == 0
    # The file is sent again, and previewed whole.
    monkeypatch.setattr(imports, "_one", one)
    again = previewed(client, make.headers, send(make, csv(switches(120))).json())
    assert again["job"]["created"] == 120


def test_a_stop_leaves_a_preview_to_be_worked_again_from_its_first_row(
    make: Maker, client: TestClient, catalog: dict, config, monkeypatch
) -> None:
    """Nothing of a preview is kept until it ends: one that a stop cut short, or that is
    found `previewing` when the worker starts, is worked again from its first row."""
    worker = cast(FastAPI, client.app).state.worker
    worker.stop()
    answer = send(make, csv(switches(120)))
    assert answer.status_code == 202, answer.text
    hid = answer.json()["job"]["hid"]
    stop = threading.Event()
    work = imports._work

    def stopped_after_the_first_rows(*arguments: Any, progress: Any = None, **more: Any) -> Any:
        def told(done: int) -> None:
            progress(done)
            stop.set()

        return work(*arguments, progress=told, **more)

    engine = make_engine(config.database_url)
    sessions = make_sessions(engine)
    with monkeypatch.context() as stopping, sessions() as db:
        stopping.setattr(imports, "_work", stopped_after_the_first_rows)
        assert imports.next_job(db) == hid
        assert imports.work(db, hid, stop) == "previewing"
    with sessions() as db:
        job = db.get_one(ImportJob, hid)
        assert (job.status, job.rows_previewed, job.created) == ("previewing", 0, 0)
        waiting = set(db.scalars(select(ImportRow.outcome).where(ImportRow.job_hid == hid)))
        assert waiting == {imports.WAITING}
        # A process that stopped without a word left it partway: it is said to have
        # worked none when the worker starts again.
        job.rows_previewed = 70
        db.commit()
        assert imports.recover(db) == []
        db.commit()
        assert db.get_one(ImportJob, hid).rows_previewed == 0
    engine.dispose()
    worker.start()
    done = wait_for_job(client, make.headers, hid)
    assert (done["status"], done["rows_previewed"], done["created"]) == ("previewed", 120, 120)
    events = make.audit(record_type="import_job", record_hid=hid, limit=100)
    assert [event["action"] for event in reversed(events)] == ["preview", "previewed"]


def test_previews_and_applies_are_worked_in_the_order_they_were_asked_for(
    make: Maker, client: TestClient, catalog: dict, db
) -> None:
    cast(FastAPI, client.app).state.worker.stop()
    me = make.get("/auth/me")
    context = audit.AuditContext(actor_hid=me["hid"], via="api", request_id="ordered")
    small = imports.preview(
        db, context, Role.INVENTORY, data=b"label\nlab\n", format_="csv", entity_name="tags"
    )
    db.commit()
    preview_first = imports.preview(
        db,
        context,
        Role.INVENTORY,
        data=csv(switches(101)).encode(),
        format_="csv",
        entity_name="items",
        in_background=True,
    )
    db.commit()
    imports.begin_apply(db, context, small.hid, source="file")
    db.commit()
    preview_last = imports.preview(
        db,
        replace(context, request_id="later"),
        Role.INVENTORY,
        data=csv(switches(101, first=301)).encode(),
        format_="csv",
        entity_name="items",
        in_background=True,
    )
    db.commit()
    assert preview_first.status == preview_last.status == "previewing"
    # The worker lets go of what its session held: the jobs are named by their HIDs.
    first, apply, last = preview_first.hid, small.hid, preview_last.hid
    worked = []
    for _ in range(3):
        hid = imports.next_job(db)
        db.rollback()
        assert hid is not None
        worked.append(hid)
        imports.work(db, hid)
    assert worked == [first, apply, last]
    assert imports.next_job(db) is None
    statuses = {hid: db.get_one(ImportJob, hid).status for hid in worked}
    assert statuses == {first: "previewed", apply: "applied", last: "previewed"}


def test_a_preview_waits_out_another_change_that_holds_the_writer_too_long(
    make: Maker, client: TestClient, catalog: dict, monkeypatch
) -> None:
    """Where another change holds the one writer's place longer than `busy_timeout`, how
    far a preview has got is said at its next rows, and what it worked out is stored a
    moment later: it does not fail for it."""
    import sqlite3

    from sqlalchemy.exc import OperationalError

    locked = OperationalError("UPDATE", {}, sqlite3.OperationalError("database is locked"))
    store, refused = imports._previewed, []

    def busy_once(*arguments: Any) -> None:
        if "store" not in refused:
            refused.append("store")
            raise locked
        store(*arguments)

    work = imports._work

    def refuse(*_: Any) -> None:
        raise locked

    def told_busy_once(*arguments: Any, progress: Any = None, **more: Any) -> Any:
        def told(done: int) -> None:
            if done == 50:
                # The write of how far it has got is refused, as a busy database does.
                with monkeypatch.context() as held:
                    held.setattr(imports, "update", refuse)
                    progress(done)
                refused.append("told")
            else:
                progress(done)

        return work(*arguments, progress=told, **more)

    monkeypatch.setattr(imports, "_previewed", busy_once)
    monkeypatch.setattr(imports, "_work", told_busy_once)
    answer = send(make, csv(switches(120)))
    assert answer.status_code == 202, answer.text
    done = wait_for_job(client, make.headers, answer.json()["job"]["hid"])
    assert (done["status"], done["created"], done["failure"]) == ("previewed", 120, None)
    assert refused == ["told", "store"]


# --- the bulk edit -------------------------------------------------------------------


def test_a_bulk_edit_of_more_than_a_hundred_items_is_previewed_in_the_background(
    make: Maker, client: TestClient, catalog: dict, hold
) -> None:
    loaded = previewed(client, make.headers, send(make, csv(switches(101))).json())
    assert make.apply(f"/imports/{loaded['job']['hid']}/apply")["status"] == "applied"
    hids = [item["hid"] for item in make.get("/items", limit=200)["items"]]

    # A hundred items are previewed in the request, as ever.
    hundred = make.post("/items/bulk-update", {"hids": hids[:100], "set": {"comments": "x"}})
    assert (hundred["job"]["status"], hundred["job"]["updated"]) == ("previewed", 100)
    # What cannot be changed is refused at once, with nothing stored.
    make.post("/items/bulk-update", {"all_rows": True, "set": {"nonsense": "1"}}, 422)
    assert make.get("/imports", source="bulk")["total"] == 1

    taken, go_on = hold()
    response = client.post(
        f"{API}/items/bulk-update",
        json={"all_rows": True, "set": {"comments": "x"}},
        headers=make.headers,
    )
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    assert (job["source"], job["status"], job["row_count"]) == ("bulk", "previewing", 101)
    assert taken.wait(30)
    make.get(f"/imports/{job['hid']}/rows", expect=409)
    refused = client.post(f"{API}/items/bulk-update/{job['hid']}/apply", headers=make.headers)
    assert refused.status_code == 409, refused.text
    go_on.set()
    done = wait_for_job(client, make.headers, job["hid"])
    assert (done["status"], done["updated"], done["rows_previewed"]) == ("previewed", 101, 101)
    first = all_rows(make, hundred["job"]["hid"])[0]
    same = all_rows(make, job["hid"])[0]
    assert (same["outcome"], same["changes"]) == (first["outcome"], first["changes"])
    applied = make.apply(f"/items/bulk-update/{job['hid']}/apply")
    assert (applied["status"], applied["applied"]) == ("applied", 101)
    assert {item["comments"] for item in make.get("/items", limit=200)["items"]} == {"x"}


# --- the command line ----------------------------------------------------------------


def test_import_and_set_wait_for_a_preview_in_the_background(
    run, make: Maker, catalog: dict, tmp_path
) -> None:
    file = tmp_path / "switches.csv"
    file.write_text(csv(switches(101)))
    waited = run("import", str(file), "--entity", "items")
    assert "previewing: " in waited.stderr
    assert "of 101 rows" in waited.stderr
    assert "preview: 101 created, 0 updated, 0 unchanged, 0 rejected" in waited.stderr
    assert "the first 100 of 101 rows are shown" in waited.stderr
    assert "row 100  create" in waited.stdout

    # Left to the server, the command says where to look, and the job goes on.
    left = run("import", str(file), "--entity", "items", "--no-wait")
    hid = make.get("/imports")["items"][0]["hid"]
    assert f"`hirdir imports show {hid} --wait` waits for it" in left.stderr
    shown = run("imports", "show", hid, "--wait")
    assert "preview: 101 created" in shown.stderr
    assert "rows_previewed: 101" in run("imports", "show", hid).stdout

    # With --apply the preview is waited for, and applied.
    applied = run("import", str(file), "--entity", "items", "--apply", "--no-wait")
    assert "previewing: " in applied.stderr
    hid = make.get("/imports")["items"][0]["hid"]
    assert f"hirdir imports show {hid} --wait" in applied.stderr
    assert "applied: 101 created" in run("imports", "show", hid, "--wait").stderr

    as_json = run("items", "set", "--all", "comments=x", "--format", "json")
    preview = json.loads(as_json.stdout)
    assert (preview["job"]["status"], preview["job"]["updated"]) == ("previewed", 101)
    assert len(preview["rows"]) == 100
    set_ = run("items", "set", "--all", "comments=x", "--apply")
    assert "applied: 0 created, 101 updated" in set_.stderr


def test_a_preview_that_failed_exits_6_with_why(
    run, make: Maker, catalog: dict, tmp_path, monkeypatch
) -> None:
    one = imports._one

    def fails(run_, which, values, result):
        raise RuntimeError("something nobody foresaw")

    monkeypatch.setattr(imports, "_one", fails)
    file = tmp_path / "switches.csv"
    file.write_text(csv(switches(101)))
    failed = run("import", str(file), "--entity", "items", "--apply", expect=6)
    assert "the preview failed: an error nobody foresaw ended it (RuntimeError)" in failed.stderr
    monkeypatch.setattr(imports, "_one", one)
    assert make.get("/items", limit=1)["total"] == 0
