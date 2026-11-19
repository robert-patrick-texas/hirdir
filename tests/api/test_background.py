"""Imports and bulk edits applied in the background, 50 rows to a batch (D-185).

These run the server's own worker, in its thread, as the server does: a test asks for an
apply and waits for the job as a person would. What happens between two batches is
seen by wrapping `imports._apply_batch`, which the worker calls for each.
"""

import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db.models import AuditEvent, ImportJob
from hirdir.domain.audit import AuditContext
from hirdir.io import entities, imports
from tests.api.inventory import API, Maker, wait_for_job
from tests.conftest import VIEWER_CODE

HEAD = "vendor,pid,serial_number,hostname"


def switches(count: int, first: int = 1) -> str:
    """A file of new switches, one to a row, each with a serial number of its own."""
    rows = [
        f"Cisco,C9300-48P,FCW0000Y{number:03d},site2-sw-{number:03d}"
        for number in range(first, first + count)
    ]
    return "\n".join([HEAD, *rows]) + "\n"


def preview(make: Maker, entity: str, text: str) -> dict[str, Any]:
    response = make.client.post(
        f"{API}/imports/preview",
        params={"entity": entity},
        content=text,
        headers={**make.headers, "Content-Type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    return response.json()["job"]


def begin(make: Maker, job: dict[str, Any], expect: int = 202) -> dict[str, Any]:
    """Ask for a job to be applied, and return the answer, which comes at once."""
    response = make.client.post(f"{API}/imports/{job['hid']}/apply", headers=make.headers)
    assert response.status_code == expect, response.text
    return response.json()


def rows(make: Maker, job: dict[str, Any], **params: Any) -> list[dict[str, Any]]:
    return make.get(f"/imports/{job['hid']}/rows", limit=1000, **params)["items"]


def job_events(make: Maker, job: dict[str, Any]) -> list[str]:
    """The actions of the audit events on a job, the first first."""
    events = make.audit(record_type="import_job", record_hid=job["hid"], limit=100)
    return [event["action"] for event in reversed(events)]


def free_to_write(config: Config) -> bool:
    """Say whether another connection could take the one writer's place without waiting."""
    path = config.database_path
    assert path is not None
    with closing(sqlite3.connect(path, timeout=0, isolation_level=None)) as other:
        try:
            other.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            return False
        other.execute("ROLLBACK")
        return True


@pytest.fixture
def catalog(make: Maker) -> dict[str, Any]:
    return make.entry(make.vendor())


@pytest.fixture
def watch(monkeypatch) -> Callable[[Callable[..., None] | None], list[tuple[str, int]]]:
    """Wrap each batch the worker applies. Return the batches, each as its job and size.

    `after`, when given, is called with the job's HID once each batch is stored.
    """

    def watching(after: Callable[..., None] | None = None) -> list[tuple[str, int]]:
        seen: list[tuple[str, int]] = []
        original = imports._apply_batch

        def wrapped(db, run, which, hid, batch, typed):
            seen.append((hid, len(batch)))
            done = original(db, run, which, hid, batch, typed)
            if after is not None:
                after(hid)
            return done

        monkeypatch.setattr(imports, "_apply_batch", wrapped)
        return seen

    return watching


def test_an_apply_answers_at_once_and_works_fifty_rows_to_a_transaction(
    make: Maker, client: TestClient, config: Config, catalog: dict, watch, monkeypatch
) -> None:
    job = preview(make, "items", switches(120))
    assert (job["row_count"], job["created"], job["rows_done"]) == (120, 120, 0)
    between: list[tuple[bool, int, int, str]] = []

    def somebody_else_gets_in(hid: str) -> None:
        # The batch is stored and the next not begun: nobody holds the writer's place,
        # and a person signs in at once beside the apply.
        free = free_to_write(config)
        signed = client.post(
            f"{API}/auth/sign-in", json={"username": "vic", "access_code": VIEWER_CODE}
        )
        now = make.get(f"/imports/{hid}")
        between.append((free, signed.status_code, now["rows_done"], now["status"]))

    batches = watch(somebody_else_gets_in)
    held: list[bool] = []
    one = imports._one

    def within_a_batch(run, which, values, result):
        if result.row == 25:
            # Halfway through the first batch, its rows are one transaction that holds
            # the writer's place.
            held.append(not free_to_write(config))
        return one(run, which, values, result)

    monkeypatch.setattr(imports, "_one", within_a_batch)

    # The request stores the job as queued and applies nothing: the worker takes it up.
    begun = begin(make, job)
    assert (begun["status"], begun["rows_done"]) == ("queued", 0)
    ended = wait_for_job(client, make.headers, job["hid"])
    assert (ended["status"], ended["rows_done"], ended["applied"], ended["stale"]) == (
        "applied",
        120,
        120,
        0,
    )
    assert [size for _, size in batches] == [50, 50, 20]
    assert held == [True]
    assert between == [
        (True, 200, 50, "applying"),
        (True, 200, 100, "applying"),
        (True, 200, 120, "applying"),
    ]
    assert make.get("/items", limit=1)["total"] == 120
    assert {row["applied_outcome"] for row in rows(make, job)} == {"create"}
    assert all(row["record_hid"] for row in rows(make, job))
    # One request ID for the apply, its batches and its events on the job alike.
    started = make.audit(record_type="import_job", action="apply_started")[0]
    # The event of the request says the status that the request stored.
    assert {"field": "status", "old": "previewed", "new": "queued"} in started["changes"]
    made = make.audit(record_type="item", action="create", limit=1000)
    assert len(made) == 120
    assert {event["request_id"] for event in made} == {started["request_id"]}
    assert {event["via"] for event in made} == {"import"}
    assert job_events(make, job) == ["preview", "apply_started", "apply"]
    end = make.audit(record_type="import_job", action="apply")[0]
    assert {entry["field"]: entry["new"] for entry in end["changes"]} == {
        "status": "applied",
        "created": 120,
        "updated": 0,
        "unchanged": 0,
        "stale": 0,
        "rejected": 0,
    }
    assert end["request_id"] == started["request_id"]


def test_a_stale_row_is_left_out_the_rest_apply_and_what_rests_on_it_is_refused(
    make: Maker, client: TestClient, catalog: dict
) -> None:
    one = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", name="one")
    make.item(catalog_entry_hid=catalog["hid"], serial_number="S2", name="two")
    text = (
        "vendor,pid,serial_number,name,parent,comments\n"
        "Cisco,C9300-48P,S1,,,first\n"
        "Juniper,EX4400-48P,J1,,,\n"
        ",,,PS-A,J1,\n"
        "Cisco,C9300-48P,S2,,,second\n"
    )
    job = preview(make, "items", text)
    assert (job["created"], job["updated"], job["rejected"]) == (2, 2, 0)
    # After the preview, somebody changes the first row's item, and makes the vendor
    # that the second row would have made: it would no longer do what was previewed.
    make.patch(f"/items/{one['hid']}", {"row_version": 1, "name": "uno"})
    make.vendor("Juniper")

    begin(make, job)
    ended = wait_for_job(client, make.headers, job["hid"])
    assert (ended["status"], ended["rows_done"], ended["applied"], ended["stale"]) == (
        "applied",
        4,
        1,
        2,
    )
    found = rows(make, job)
    assert [row["applied_outcome"] for row in found] == ["stale", "stale", "rejected", "update"]
    assert found[0]["applied_reasons"][0]["message"].startswith("changed since the preview")
    assert found[1]["applied_reasons"][0]["message"].startswith(
        "would no longer do what was previewed"
    )
    # The power supply was to go into the switch that the stale row did not make.
    assert found[2]["applied_reasons"][0]["field"] == "parent"
    by_serial = {item["serial_number"]: item for item in make.get("/items")["items"]}
    assert set(by_serial) == {"S1", "S2"}
    assert (by_serial["S1"]["name"], by_serial["S1"]["comments"]) == ("uno", None)
    assert by_serial["S2"]["comments"] == "second"
    assert [row["row"] for row in rows(make, job, applied_outcome="stale")] == [1, 2]
    assert [row["row"] for row in rows(make, job, applied_outcome="rejected")] == [3]
    assert make.get(f"/imports/{job['hid']}/rows", applied_outcome="nonsense", expect=422)


def test_a_stop_partway_keeps_what_was_stored_and_a_resume_applies_nothing_twice(
    make: Maker, client: TestClient, admin: dict[str, str], catalog: dict, monkeypatch
) -> None:
    job = preview(make, "items", switches(120))
    one = imports._one
    failed: list[int] = []

    def fails_once_at_row_75(run, which, values, result):
        if result.row == 75 and not failed:
            failed.append(result.row)
            raise RuntimeError("something nobody foresaw")
        return one(run, which, values, result)

    monkeypatch.setattr(imports, "_one", fails_once_at_row_75)
    begin(make, job)
    stopped = wait_for_job(client, make.headers, job["hid"])
    # The first batch is kept, the second, in which it failed, is undone.
    assert (stopped["status"], stopped["rows_done"], stopped["applied"]) == ("stopped", 50, 50)
    assert "RuntimeError" in stopped["failure"]
    assert make.get("/items", limit=1)["total"] == 50
    outcomes = [row["applied_outcome"] for row in rows(make, job)]
    assert outcomes == ["create"] * 50 + [None] * 70
    assert job_events(make, job) == ["preview", "apply_started", "apply_stopped"]
    stop = make.audit(record_type="import_job", action="apply_stopped")[0]
    assert (stop["actor_name"], stop["via"]) == (None, "system")

    # Anybody with the Inventory role resumes it, from the first row it had not applied.
    resumed = Maker(client, admin)
    assert begin(resumed, job)["status"] == "queued"
    ended = wait_for_job(client, make.headers, job["hid"])
    assert (ended["status"], ended["rows_done"], ended["applied"]) == ("applied", 120, 120)
    assert (ended["applied_by_name"], ended["failure"]) == ("ada", None)
    assert make.get("/items", limit=1)["total"] == 120
    made = make.audit(record_type="item", action="create", limit=1000)
    assert len(made) == 120
    assert len({event["record_hid"] for event in made}) == 120
    assert job_events(make, job) == [
        "preview",
        "apply_started",
        "apply_stopped",
        "apply_resumed",
        "apply",
    ]
    # The rows applied after the resume are under its request ID.
    again = make.audit(record_type="import_job", action="apply_resumed")[0]
    assert sum(event["request_id"] == again["request_id"] for event in made) == 70
    # An applied job is not resumed.
    assert "applied already" in begin(make, job, expect=409)["detail"]


def test_a_job_found_applying_when_the_worker_starts_was_cut_short_and_a_queued_one_waits(
    config: Config, db
) -> None:
    asked = AuditContext(actor_hid=None, via="api", request_id="apply-request-01")
    job = imports.preview(db, asked, None, data=b"label\nlab\n", format_="csv", entity_name="tags")
    waiting = imports.preview(
        db, asked, None, data=b"label\nspare\n", format_="csv", entity_name="tags"
    )
    begun = imports.begin_apply(db, asked, job.hid, source="file")
    behind = imports.begin_apply(db, asked, waiting.hid, source="file")
    db.commit()
    # Asking stores a job as queued, whether another is ahead of it or none.
    assert (begun.status, behind.status) == ("queued", "queued")
    # A worker took the first up, which is what makes it applying, and stopped there.
    taken = imports._take(db, job.hid)
    assert taken is not None
    assert taken.status == "applying"
    # The background work starts again, here as the worker of a server that does both.
    with TestClient(create_app(config)):
        db.expire_all()
        found = db.get_one(ImportJob, job.hid)
        assert found.status == "stopped"
        assert found.failure == imports.CUT_SHORT
        assert found.failure.startswith("the background work stopped while it was being applied")
        # The one that nobody had taken up was not cut short, and is not said to be.
        assert db.get_one(ImportJob, waiting.hid).failure != imports.CUT_SHORT
    stopped = db.query(AuditEvent).filter_by(record_hid=job.hid, action="apply_stopped").one()
    assert (stopped.actor_hid, stopped.via, stopped.request_id) == (
        None,
        "system",
        "apply-request-01",
    )
    # A worker that starts now finds nothing applying, and stops nothing.
    assert imports.recover(db) == []


def test_one_job_is_applied_at_a_time_and_the_next_waits_queued(
    make: Maker, client: TestClient, catalog: dict, watch, monkeypatch
) -> None:
    first = preview(make, "items", switches(60))
    second = preview(make, "tags", "label\nlab\n")
    batches = watch()
    original = imports._apply_batch
    working, release = threading.Event(), threading.Event()

    def held_in_its_first_batch(db, run, which, hid, batch, typed):
        if hid == first["hid"] and not working.is_set():
            working.set()
            assert release.wait(30)
        return original(db, run, which, hid, batch, typed)

    monkeypatch.setattr(imports, "_apply_batch", held_in_its_first_batch)
    assert begin(make, first)["status"] == "queued"
    assert working.wait(30)
    assert make.get(f"/imports/{first['hid']}")["status"] == "applying"
    assert begin(make, second)["status"] == "queued"
    assert make.get(f"/imports/{second['hid']}")["status"] == "queued"
    # Asked again while it waits, it is not taken twice.
    assert "being applied already" in begin(make, second, expect=409)["detail"]
    release.set()
    assert wait_for_job(client, make.headers, first["hid"])["status"] == "applied"
    assert wait_for_job(client, make.headers, second["hid"])["status"] == "applied"
    assert batches == [(first["hid"], 50), (first["hid"], 10), (second["hid"], 1)]


def test_the_members_of_one_group_are_kept_in_one_batch(
    make: Maker, client: TestClient, catalog: dict, watch
) -> None:
    assert make.apply(f"/imports/{preview(make, 'items', switches(100))['hid']}/apply")
    for name in ("lab-a", "lab-b", "lab-c"):
        make.group(name, "custom")
    # The rows of lab-a and lab-b take turns through the first sixty rows, and lab-c has
    # the forty after them.
    members = ["group,item"] + [
        f"{'lab-a' if number % 2 else 'lab-b'},FCW0000Y{number:03d}" for number in range(1, 61)
    ]
    members += [f"lab-c,FCW0000Y{number:03d}" for number in range(61, 101)]
    job = preview(make, "device_group_members", "\n".join(members) + "\n")
    assert job["created"] == 100
    batches = watch()
    begin(make, job)
    assert wait_for_job(client, make.headers, job["hid"])["applied"] == 100
    assert [size for _, size in batches] == [60, 40]


def test_rows_that_cannot_stand_together_are_refused_and_their_batch_worked_again(
    make: Maker, client: TestClient, catalog: dict, monkeypatch
) -> None:
    assert make.apply(f"/imports/{preview(make, 'items', switches(3))['hid']}/apply")
    make.group("lab-a", "custom")
    text = "group,item\n" + "".join(f"lab-a,FCW0000Y{number:03d}\n" for number in (1, 2, 3))
    job = preview(make, "device_group_members", text)
    asked: list[int] = []

    def the_second_cannot_stand(self, run):
        asked.append(len(asked))
        if len(asked) == 1:
            return {2: [{"field": "item", "message": "does not stand with the others"}]}
        return {}

    monkeypatch.setattr(entities.DeviceGroupMembers, "finish", the_second_cannot_stand)
    begin(make, job)
    ended = wait_for_job(client, make.headers, job["hid"])
    assert (ended["applied"], ended["rows_done"]) == (2, 3)
    found = rows(make, job)
    assert [row["applied_outcome"] for row in found] == ["create", "rejected", "create"]
    assert found[1]["applied_reasons"] == [
        {"field": "item", "message": "does not stand with the others"}
    ]
    group = make.get("/device-groups", filter="name:eq:lab-a")["items"][0]
    assert make.get(f"/device-groups/{group['hid']}/members")["total"] == 2
    # What the first try did was undone whole: no event is left of the row it refused.
    assert len(make.audit(record_type="device_group_member", action="create")) == 2


def test_an_apply_stops_when_who_asked_for_it_no_longer_holds_the_inventory_role(
    make: Maker, client: TestClient, admin: dict[str, str], catalog: dict, monkeypatch
) -> None:
    first = preview(make, "tags", "label\nfirst\n")
    second = preview(make, "tags", "label\nsecond\n")
    original = imports._apply_batch
    working, release = threading.Event(), threading.Event()

    def held(db, run, which, hid, batch, typed):
        if hid == first["hid"]:
            working.set()
            assert release.wait(30)
        return original(db, run, which, hid, batch, typed)

    monkeypatch.setattr(imports, "_apply_batch", held)
    boss = Maker(client, admin)
    begin(boss, first)
    assert working.wait(30)
    assert begin(make, second)["status"] == "queued"
    # While it waits, the person who asked is no longer given the Inventory role.
    mine = next(grant for grant in boss.get("/role-grants") if grant["target_name"] == "ivy")
    response = client.delete(f"{API}/role-grants/{mine['hid']}", headers=admin)
    assert response.status_code == 204, response.text
    release.set()
    stopped = wait_for_job(client, admin, second["hid"])
    assert stopped["status"] == "stopped"
    assert "no longer holds the Inventory role" in stopped["failure"]
    assert "second" not in [tag["label"] for tag in boss.get("/tags")]
    # Somebody who holds it resumes it.
    begin(boss, second)
    assert wait_for_job(client, admin, second["hid"])["status"] == "applied"


def test_a_bulk_edit_is_applied_in_the_background_like_a_file(
    make: Maker, client: TestClient, catalog: dict
) -> None:
    assert make.apply(f"/imports/{preview(make, 'items', switches(3))['hid']}/apply")
    edit = make.post(
        "/items/bulk-update", {"filter": "hostname:prefix:site2-sw-", "set": {"comments": "x"}}
    )
    response = client.post(
        f"{API}/items/bulk-update/{edit['job']['hid']}/apply", headers=make.headers
    )
    assert (response.status_code, response.json()["status"]) == (202, "queued")
    ended = wait_for_job(client, make.headers, edit["job"]["hid"])
    assert (ended["status"], ended["applied"]) == ("applied", 3)
    assert {item["comments"] for item in make.get("/items")["items"]} == {"x"}
    events = make.audit(record_type="item", action="update")
    assert {event["via"] for event in events} == {"api"}


def test_reading_a_job_is_open_to_a_viewer_and_applying_it_is_not(
    make: Maker, client: TestClient, viewer: dict[str, str]
) -> None:
    job = preview(make, "tags", "label\nlab\n")
    seen = client.get(f"{API}/imports/{job['hid']}", headers=viewer)
    assert (seen.status_code, seen.json()["rows_done"]) == (200, 0)
    refused = client.post(f"{API}/imports/{job['hid']}/apply", headers=viewer)
    assert refused.status_code == 403
    assert make.get(f"/imports/{job['hid']}")["status"] == "previewed"


def test_a_resumed_job_knows_the_records_its_earlier_batches_made_for_a_reference(
    make: Maker, client: TestClient, monkeypatch
) -> None:
    # Row 1 names a successor that no row has described yet, which the file makes for
    # the reference; row 60, in the second batch, describes it.
    lines = ["vendor,pid,successor_vendor,successor_pid,model_name"]
    lines.append("Cisco,M-001,Cisco,M-999,first")
    lines += [f"Cisco,M-{number:03d},,,model {number}" for number in range(2, 60)]
    lines.append("Cisco,M-999,,,the successor")
    job = preview(make, "catalog_entries", "\n".join(lines) + "\n")
    previewed = {row["row"]: row["outcome"] for row in rows(make, job)}
    one = imports._one
    failed: list[int] = []

    def fails_once_at_row_55(run, which, values, result):
        if result.row == 55 and not failed:
            failed.append(result.row)
            raise RuntimeError("something nobody foresaw")
        return one(run, which, values, result)

    monkeypatch.setattr(imports, "_one", fails_once_at_row_55)
    begin(make, job)
    assert wait_for_job(client, make.headers, job["hid"])["status"] == "stopped"
    begin(make, job)
    ended = wait_for_job(client, make.headers, job["hid"])
    assert (ended["status"], ended["stale"]) == ("applied", 0)
    applied = {row["row"]: row["applied_outcome"] for row in rows(make, job)}
    assert applied[60] == previewed[60]
