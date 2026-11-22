"""The records an import made, and the commands that retire and delete several (P-227,
P-228, P-234)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hirdir.io import examples
from tests.api import test_cli
from tests.api.inventory import API, Maker, wait_for_job
from tests.api.test_files import Files

# The fixture that runs `hirdir` against the test client.
run = test_cli.run

WRONG = """vendor,pid,serial_number,hostname
Cisco,C9300-48P,FCW0000W001,site9-sw-01
Cisco,C9300-48P,FCW0000W002,site9-sw-02
Cisco,C9300-24P,FCW0000W003,site9-sw-03
"""


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _made(make: Maker, job: dict[str, Any], **params: Any) -> dict[str, Any]:
    return make.get(f"/imports/{job['hid']}/created", **params)


def test_a_past_import_lists_the_records_it_made_with_what_each_is_now(
    client: TestClient, make: Maker, files: Files, admin: dict[str, str], viewer: dict[str, str]
) -> None:
    make.vendor("Cisco")
    job = files.load("items", WRONG)
    made = _made(make, job)
    hids = [one["record_hid"] for one in made["items"]]

    assert made["total"] == 3
    assert [
        (one["row"], one["record_type"], one["label"], one["state"]) for one in made["items"]
    ] == [
        (1, "item", "site9-sw-01", "active"),
        (2, "item", "site9-sw-02", "active"),
        (3, "item", "site9-sw-03", "active"),
    ]
    # Cisco was there; the two models were made because the rows named them.
    assert [(one["record_type"], one["label"], one["state"]) for one in made["also"]] == [
        ("catalog_entry", "Cisco C9300-24P", "active"),
        ("catalog_entry", "Cisco C9300-48P", "active"),
    ]
    # What each is now: one retired, one deleted, by what it was known by then.
    client.post(f"{API}/items/retire", json={"hids": [hids[0]]}, headers=make.headers)
    client.post(
        f"{API}/items/delete", json={"hids": [hids[1]], "reason": "a wrong file"}, headers=admin
    )
    again = Maker(client, viewer).get(f"/imports/{job['hid']}/created", limit=2, offset=1)
    assert (again["total"], again["limit"], again["offset"]) == (3, 2, 1)
    assert [(one["label"], one["state"]) for one in again["items"]] == [
        ("site9-sw-02", "deleted"),
        ("site9-sw-03", "active"),
    ]
    assert len(again["also"]) == 2
    assert [one["state"] for one in _made(make, job)["items"]] == ["retired", "deleted", "active"]


def test_two_applies_under_one_request_id_each_list_only_what_they_made(
    client: TestClient, make: Maker, files: Files
) -> None:
    # A caller may send one X-Request-Id on two applies: each lists its own.
    shared = {**make.headers, "X-Request-Id": "the-same-request-1"}
    jobs = []
    for text in (
        "vendor,pid,serial_number\nJuniper,EX4300-48T,JN0000A001\n",
        "vendor,pid,serial_number\nArista,7050SX3-48YC8,JPE0000B001\n",
    ):
        preview = files.preview("items", text)
        response = client.post(f"{API}/imports/{preview['job']['hid']}/apply", headers=shared)
        assert response.status_code == 202, response.text
        jobs.append(wait_for_job(client, make.headers, preview["job"]["hid"]))
    first, second = (
        [(one["record_type"], one["label"]) for one in _made(make, job)["also"]] for job in jobs
    )
    assert first == [("vendor", "Juniper"), ("catalog_entry", "Juniper EX4300-48T")]
    assert second == [("vendor", "Arista"), ("catalog_entry", "Arista 7050SX3-48YC8")]


def test_the_examples_list_only_what_each_file_made(
    client: TestClient, make: Maker, db: Session
) -> None:
    # `hirdir admin load-examples` is run with the service stopped (P-166): with the
    # application's worker running beside it, the worker may take a job the load has just
    # queued, which no account asked for, and stop it for want of a role.
    app = client.app
    assert isinstance(app, FastAPI)
    worker = app.state.worker
    worker.stop()
    try:
        examples.load(db, examples.folder())
        db.commit()
    finally:
        worker.start()
    jobs = {job["file_name"]: job for job in make.get("/imports", limit=100)["items"]}
    # The tags made nothing for a row; the catalog entries made their vendors' records
    # only where a model named one that the vendors' file had not.
    assert _made(make, jobs["tags.csv"])["also"] == []
    every = [one["record_hid"] for job in jobs.values() for one in _made(make, job)["also"]]
    assert len(every) == len(set(every))
    # Each file is a request of its own.
    requests = {
        event["request_id"]
        for event in make.audit(record_type="import_job", action="apply", limit=100)
    }
    assert len(requests) == len(jobs)


def test_a_bulk_edit_lists_the_model_it_made_and_no_item(
    client: TestClient, make: Maker, files: Files
) -> None:
    make.vendor("Cisco")
    job = files.load("items", WRONG)
    hids = [one["record_hid"] for one in _made(make, job)["items"]]
    preview = make.post("/items/bulk-update", {"hids": hids, "set": {"pid": "C9300-24UX"}})
    edited = make.apply(f"/items/bulk-update/{preview['job']['hid']}/apply")
    made = _made(make, edited)
    assert (made["total"], made["items"]) == (0, [])
    assert [(one["record_type"], one["label"]) for one in made["also"]] == [
        ("catalog_entry", "Cisco C9300-24UX")
    ]


def test_an_import_of_places_lists_them_by_path_and_a_preview_made_nothing(
    make: Maker, files: Files
) -> None:
    job = files.load("regions", "name,parent\nAmericas,\nCentral,Americas\n")
    made = _made(make, job)
    assert [one["label"] for one in made["items"]] == ["Americas", "Americas > Central"]
    assert {one["record_type"] for one in made["items"]} == {"region"}
    preview = files.preview("regions", "name\nEMEA\n")
    assert _made(make, preview["job"]) == {
        "total": 0,
        "limit": 100,
        "offset": 0,
        "items": [],
        "also": [],
    }
    make.get("/imports/01900000-0000-7000-8000-000000000000/created", 404)


def test_the_commands_retire_and_delete_several_and_list_what_an_import_made(
    run,
    make: Maker,
    files: Files,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    make.vendor("Cisco")
    job = files.load("items", WRONG)

    listed = run("imports", "created", job["hid"]).stdout.splitlines()
    assert listed[0].split() == ["ROW", "KIND", "NAME", "STATE", "HID"]
    assert [line.split()[:4] for line in listed[1:4]] == [
        ["1", "item", "site9-sw-01", "active"],
        ["2", "item", "site9-sw-02", "active"],
        ["3", "item", "site9-sw-03", "active"],
    ]
    assert "made because a row named them:" in listed
    whole = json.loads(run("imports", "created", job["hid"], "--format", "json").stdout)
    hids = [one["record_hid"] for one in whole["items"]]

    # By what each is known by, or its HID; one named twice counts once.
    retired = run("items", "retire", "site9-sw-01", hids[0], hids[1])
    assert retired.stdout.splitlines() == [
        f"retired: site9-sw-01  {hids[0]}",
        f"retired: site9-sw-02  {hids[1]}",
    ]
    again = run("items", "retire", hids[0], "--format", "json", expect=0)
    assert [one["hid"] for one in json.loads(again.stdout)["already"]] == [hids[0]]

    # Deleting is for an Admin: the Inventory role is refused.
    refused = run("items", "delete", hids[2], "--reason", "a wrong file", "--yes", expect=3)
    assert "admin role" in refused.output
    monkeypatch.setenv("HIRDIR_TOKEN", admin["Authorization"].removeprefix("Bearer "))
    assert "--reason" in run("items", "delete", hids[2], expect=2).output
    tried = run("items", "delete", hids[2], "--dry-run")
    assert tried.stdout.splitlines() == [f"would be deleted: site9-sw-03  {hids[2]}"]
    make.get(f"/items/{hids[2]}")
    # Asked, and answered no: nothing is done.
    declined = run("items", "delete", hids[2], "--reason", "a wrong file", expect=1)
    assert "Delete 1 items?" in declined.output
    make.get(f"/items/{hids[2]}")
    done = run("items", "delete", hids[0], hids[2], "--reason", "a wrong file", "--yes")
    assert f"deleted: site9-sw-01  {hids[0]}" in done.stdout
    make.get(f"/items/{hids[2]}", 404)
    # One that is not there is said so, and the command exits 4.
    missing = run("items", "delete", hids[2], "--reason", "a wrong file", "--yes", expect=4)
    assert f"not found: {hids[2]}" in missing.stdout
    # Asked for, a deleted item says when, by whom and why: the reason once.
    shown = run("items", "show", hids[2], expect=4).output
    assert f"the item {hids[2]} was deleted on " in shown
    assert shown.count("a wrong file") == 1
    assert shown.rstrip().endswith("by ada: a wrong file")

    stack = make.stack("site9-stack-wrong", [make.item(hostname="site9-sw-09")])
    run("groups", "retire", "site9-stack-wrong")
    assert make.get(f"/device-groups/{stack['hid']}")["record_status"] == "retired"
    run("groups", "delete", "site9-stack-wrong", "--reason", "a wrong file", "--yes")
    make.get(f"/device-groups/{stack['hid']}", 404)


def test_a_command_takes_a_thousand_records_at_most_and_does_not_split_them(
    run, make: Maker, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = make.item(hostname="site9-sw-kept")
    many = [f"01900000-0000-7000-8000-{number:012d}" for number in range(1000)]
    for command in (("items", "retire"), ("groups", "retire")):
        refused = run(*command, kept["hid"], *many, expect=2)
        assert "at most 1,000 are retired by one command, and 1,001 were given" in (refused.output)
    monkeypatch.setenv("HIRDIR_TOKEN", admin["Authorization"].removeprefix("Bearer "))
    refused = run("items", "delete", kept["hid"], *many, "--reason", "x", "--yes", expect=2)
    assert "at most 1,000 are deleted by one command, and 1,001 were given" in refused.output
    assert make.get(f"/items/{kept['hid']}")["record_status"] == "active"
    # A thousand, one named twice among them, are one request.
    done = json.loads(
        run(
            "items", "retire", kept["hid"], *many[:999], kept["hid"], "--format", "json", expect=4
        ).stdout
    )
    assert ([one["hid"] for one in done["retired"]], len(done["missing"])) == ([kept["hid"]], 999)
