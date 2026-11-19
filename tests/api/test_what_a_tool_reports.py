"""What a tool reports (P-248): a row of a file read from an external system is found by
that system's own identifier, and what a file that is everything the system reports
does not name is marked `not_reported`."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.io import imports
from tests.api import test_cli
from tests.api.inventory import API, Maker, errors, wait_for_job
from tests.api.test_files import Files, changes, counts

SYSTEM = "Example vCenter"
HEAD = "external_id,name,description"
# The fixture that runs `hirdir` against the test client.
run = test_cli.run


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _system(make: Maker, name: str = SYSTEM) -> dict[str, Any]:
    return make.post("/external-systems", {"name": name, "kind": "other"})


def _vm(make: Maker, name: str) -> dict[str, Any]:
    return make.item(name=name)


def _register(
    make: Maker, system: dict[str, Any], item: dict[str, Any], external_id: str | None, **more: Any
) -> dict[str, Any]:
    body = {"system_hid": system["hid"], "item_hid": item["hid"], "external_id": external_id}
    return make.post("/registrations", {**body, **more})


def _registration(make: Maker, system: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    found = make.get(f"/items/{item['hid']}")["registrations"]
    shown = next(one for one in found if one["system"]["hid"] == system["hid"])
    return make.get(f"/registrations/{shown['hid']}")


def _csv(*rows: str) -> str:
    return "\n".join([HEAD, *rows]) + "\n"


# --- a row found by the tool's own identifier ---------------------------------------


def test_a_row_finds_the_item_its_system_knows_by_its_identifier_whatever_it_is_called(
    make: Maker, files: Files
) -> None:
    system = _system(make)
    app = _vm(make, "site2-vm-app01")
    registration = _register(make, system, app, "vm-101")

    preview = files.preview("items", _csv("vm-101,site2-vm-app01-renamed,"), system=SYSTEM)

    assert counts(preview["job"]) == (0, 1, 0, 0)
    assert (preview["job"]["system_hid"], preview["job"]["system"]["name"]) == (
        system["hid"],
        SYSTEM,
    )
    [row] = preview["rows"]
    assert row["record_hid"] == app["hid"]
    assert changes(row) == {"name": ("site2-vm-app01", "site2-vm-app01-renamed")}
    files.apply(preview)
    assert make.get(f"/items/{app['hid']}")["name"] == "site2-vm-app01-renamed"
    assert make.get("/items", limit=1)["total"] == 1
    confirmed = make.get(f"/registrations/{registration['hid']}")
    assert (confirmed["status"], confirmed["external_id"]) == ("registered", "vm-101")
    assert confirmed["confirmed_at"] is not None


def test_a_row_no_registration_answers_is_matched_as_any_row_and_registers_its_item(
    make: Maker, files: Files
) -> None:
    system = _system(make)
    web = _vm(make, "site2-vm-web01")
    text = _csv("vm-102,site2-vm-web01,", "vm-103,site2-ctr-dns1,a container")

    preview = files.preview("items", text, system=system["hid"])

    assert counts(preview["job"]) == (1, 1, 0, 0)
    first, second = preview["rows"]
    # A registration made says so, in the file's own words.
    assert (first["record_hid"], changes(first)) == (
        web["hid"],
        {"external_id": (None, "vm-102"), "registration": (None, "registered")},
    )
    assert changes(second)["external_id"] == (None, "vm-103")
    assert changes(second)["registration"] == (None, "registered")
    files.apply(preview)
    assert _registration(make, system, web)["external_id"] == "vm-102"
    made = make.get("/items", filter="name:eq:site2-ctr-dns1")["items"]
    [dns] = made
    assert _registration(make, system, dns)["external_id"] == "vm-103"

    # Loaded again, nothing changes but when the system last agreed.
    before = _registration(make, system, web)
    again = files.preview("items", text, system=SYSTEM)
    assert counts(again["job"]) == (0, 0, 2, 0)
    files.apply(again)
    after = _registration(make, system, web)
    assert after["row_version"] == before["row_version"] + 1
    assert after["confirmed_at"] >= before["confirmed_at"]
    assert make.get("/items", limit=1)["total"] == 2


def test_a_row_with_no_identifier_is_matched_as_any_row_and_registers_nothing(
    make: Maker, files: Files
) -> None:
    system = _system(make)
    web = _vm(make, "site2-vm-web01")

    files.load("items", _csv(",site2-vm-web01,a web server"), system=SYSTEM)

    assert make.get(f"/items/{web['hid']}")["description"] == "a web server"
    assert make.get(f"/items/{web['hid']}")["registrations"] == []
    assert system["hid"]


def test_an_identifier_two_items_have_and_an_item_known_otherwise_are_errors_on_the_row(
    make: Maker, files: Files
) -> None:
    system = _system(make)
    one, two, known = (_vm(make, f"site2-vm-app0{number}") for number in (1, 2, 3))
    _register(make, system, one, "vm-201")
    _register(make, system, two, "vm-201")
    _register(make, system, known, "vm-203")

    preview = files.preview(
        "items", _csv("vm-201,site2-vm-app01,", "vm-299,site2-vm-app03,"), system=SYSTEM
    )

    first, second = preview["rows"]
    assert first["outcome"] == second["outcome"] == "rejected"
    assert {reason["field"] for reason in first["reasons"]} == {"external_id"}
    assert "more than one item" in first["reasons"][0]["message"]
    assert {reason["field"] for reason in second["reasons"]} == {"external_id"}
    assert "vm-203" in second["reasons"][0]["message"]


def test_a_row_that_names_its_item_by_hid_is_held_to_the_identifier_as_any_row(
    make: Maker, files: Files
) -> None:
    system = _system(make)
    same, other, known = (_vm(make, f"site2-vm-app0{number}") for number in (1, 2, 3))
    _register(make, system, same, "vm-101")
    _register(make, system, other, "vm-103")
    _register(make, system, known, "vm-104")
    text = "\n".join(
        [
            "hid,external_id,description",
            f"{same['hid']},vm-101,the same item",
            # Another item's identifier, given to this one by its HID.
            f"{known['hid']},vm-103,",
            # An item the system knows under another identifier.
            f"{other['hid']},vm-199,",
        ]
    )

    preview = files.preview("items", text + "\n", system=SYSTEM)

    first, second, third = preview["rows"]
    assert first["outcome"] == "update"
    assert second["outcome"] == third["outcome"] == "rejected"
    assert {reason["field"] for reason in second["reasons"]} == {"external_id"}
    assert "site2-vm-app02" in second["reasons"][0]["message"]
    assert {reason["field"] for reason in third["reasons"]} == {"external_id"}
    assert "vm-103" in third["reasons"][0]["message"]
    files.apply(preview, skip_rejected="true")
    assert _registration(make, system, known)["external_id"] == "vm-104"
    assert _registration(make, system, other)["external_id"] == "vm-103"
    # The identifier stays one item's: a row that gives it finds that one.
    again = files.preview("items", _csv("vm-103,site2-vm-app02,"), system=SYSTEM)
    assert [row["outcome"] for row in again["rows"]] == ["unchanged"]


def test_what_a_file_read_from_a_system_needs(make: Maker, files: Files) -> None:
    _system(make)
    retired = _system(make, "Example Discovery")
    make.post(f"/external-systems/{retired['hid']}/retire", {"row_version": 1}, 200)

    no_system = files.preview("items", _csv("vm-1,site2-vm-app01,"), 422)
    assert "external_id" in errors(no_system)
    complete = files.preview("items", _csv(",site2-vm-app01,"), 422, complete="true")
    assert "complete" in errors(complete)
    # A report that came out empty would mark everything the system has: it is refused.
    empty = files.preview("items", _csv(), 422, system=SYSTEM, complete="true")
    assert errors(empty)["complete"] == (
        "a file that is everything a system reports names at least one thing"
    )
    assert "system" in errors(files.preview("items", _csv(",a,"), 422, system="Example Nothing"))
    assert "system" in errors(files.preview("items", _csv(",a,"), 422, system="Example Discovery"))
    assert "system" in errors(
        files.preview("vendors", "name\nExample Virtual\n", 422, system=SYSTEM)
    )
    # A file whose column is blank throughout, as an export loaded back, is no file of a
    # system's identifiers.
    blank = files.preview("items", _csv(",site2-vm-app01,"))
    assert (blank["job"]["system"], blank["job"]["complete"]) == (None, None)
    assert make.audit(record_type="registration") == []


# --- what a tool reports no more ----------------------------------------------------


def _reported(make: Maker) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """A system that knows five items: three registered, one pending, one retired."""
    system = _system(make)
    made = {name: _vm(make, f"site2-vm-{name}") for name in ("app", "web", "db", "old", "new")}
    for name, ident in (("app", "vm-1"), ("web", "vm-2"), ("db", "vm-3"), ("old", "vm-4")):
        _register(make, system, made[name], ident)
    _register(make, system, made["new"], "vm-5", status="pending")
    old = make.get(f"/items/{made['old']['hid']}")
    make.post(f"/items/{old['hid']}/retire", {"row_version": old["row_version"]}, 200)
    return system, made


def test_a_file_that_is_everything_its_system_reports_marks_what_it_does_not_name(
    make: Maker, files: Files
) -> None:
    system, made = _reported(make)
    group = make.group("site2-esx-cluster", "cluster", [])
    make.post("/registrations", {"system_hid": system["hid"], "group_hid": group["hid"]})
    text = _csv("vm-1,site2-vm-app,", "vm-2,site2-vm-web,")

    preview = files.preview("items", text, system=SYSTEM, complete="true")

    assert (preview["job"]["complete"], preview["job"]["not_reported"]) == (True, 1)
    assert preview["not_reported_first"] == [{"hid": made["db"]["hid"], "label": "site2-vm-db"}]
    job = files.apply(preview)
    assert (job["status"], job["not_reported"]) == ("applied", 1)
    marked = _registration(make, system, made["db"])
    assert marked["status"] == "not_reported"
    # The item is not changed otherwise; what is pending, retired or a group's stays.
    assert make.get(f"/items/{made['db']['hid']}")["record_status"] == "active"
    assert _registration(make, system, made["new"])["status"] == "pending"
    assert _registration(make, system, made["old"])["status"] == "registered"
    assert _registration(make, system, made["app"])["status"] == "registered"
    # By an event of its own, with the request of the apply.
    [event] = [
        one
        for one in make.audit(record_type="registration", record_hid=marked["hid"])
        if one["action"] == "update"
    ]
    # It names the import, and is the import's, as the events of its rows are.
    assert {entry["field"]: entry["new"] for entry in event["changes"]} == {
        "status": "not_reported",
        "import": job["hid"],
    }
    assert event["via"] == "import"
    [started] = make.audit(record_type="import_job", record_hid=job["hid"], action="apply_started")
    assert event["request_id"] == started["request_id"]
    [applied] = make.audit(record_type="import_job", record_hid=job["hid"], action="apply")
    assert {"field": "not_reported", "old": None, "new": 1} in applied["changes"]
    assert make.get(f"/imports/{job['hid']}")["not_reported"] == 1
    # Once applied, the preview names none.
    shown = make.get(f"/imports/{job['hid']}")
    assert shown["status"] == "applied"

    # The next file that names it makes it registered again.
    named_again = files.preview("items", _csv("vm-3,site2-vm-db,"), system=SYSTEM)
    assert counts(named_again["job"]) == (0, 1, 0, 0)
    assert changes(named_again["rows"][0]) == {"registration": ("not_reported", "registered")}
    files.apply(named_again)
    assert _registration(make, system, made["db"])["status"] == "registered"
    # And a person sets it as any status.
    marked = _registration(make, system, made["web"])
    make.patch(
        f"/registrations/{marked['hid']}",
        {"row_version": marked["row_version"], "status": "not_reported"},
    )
    again = _registration(make, system, made["web"])
    make.patch(
        f"/registrations/{again['hid']}", {"row_version": again["row_version"], "status": "removed"}
    )


def test_a_file_with_a_row_not_applied_marks_nothing(make: Maker, files: Files) -> None:
    system, made = _reported(make)
    other = _vm(make, "site2-vm-other")
    _register(make, system, other, "vm-9")
    # The second row names the item the system knows as vm-9 by another identifier.
    text = _csv("vm-1,site2-vm-app,", "vm-8,site2-vm-other,")

    preview = files.preview("items", text, system=SYSTEM, complete="true")

    assert (preview["job"]["rejected"], preview["job"]["not_reported"]) == (1, 0)
    # It says why it marks nothing, and not only that it does.
    assert preview["job"]["not_reported_held"] == "rejected"
    assert preview["not_reported_first"] == []
    job = files.apply(preview, skip_rejected="true")
    assert (job["status"], job["not_reported"], job["not_reported_held"]) == (
        "applied",
        0,
        "skipped",
    )
    assert _registration(make, system, made["db"])["status"] == "registered"


def test_a_file_with_a_row_left_out_as_stale_marks_nothing_and_says_so(
    run: Any, make: Maker, files: Files
) -> None:
    system, made = _reported(make)
    preview = files.preview(
        "items", _csv("vm-1,site2-vm-app,", "vm-2,site2-vm-web,"), system=SYSTEM, complete="true"
    )
    assert (preview["job"]["not_reported"], preview["job"]["not_reported_held"]) == (1, None)
    app = make.get(f"/items/{made['app']['hid']}")
    make.patch(f"/items/{app['hid']}", {"row_version": app["row_version"], "comments": "moved"})

    applied = run("imports", "apply", preview["job"]["hid"], expect=5)

    assert "nothing marked not reported: a row changed since the preview" in applied.output
    job = make.get(f"/imports/{preview['job']['hid']}")
    assert (job["stale"], job["not_reported"], job["not_reported_held"]) == (1, 0, "stale")
    assert _registration(make, system, made["db"])["status"] == "registered"


def test_an_import_that_stops_partway_and_is_resumed_marks_once_at_its_end(
    make: Maker, client: TestClient, files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    system, made = _reported(make)
    text = _csv(
        "vm-1,site2-vm-app,",
        "vm-2,site2-vm-web,",
        *(f"vm-1{number:02d},site2-vm-many{number:02d}," for number in range(60)),
    )
    preview = files.preview("items", text, system=SYSTEM, complete="true")
    assert preview["job"]["not_reported"] == 1
    one = imports._one
    failed: list[int] = []

    def fails_once_at_row_55(run: Any, which: Any, values: Any, result: Any) -> None:
        if result.row == 55 and not failed:
            failed.append(result.row)
            raise RuntimeError("something nobody foresaw")
        one(run, which, values, result)

    monkeypatch.setattr(imports, "_one", fails_once_at_row_55)
    begun = client.post(f"{API}/imports/{preview['job']['hid']}/apply", headers=files.headers)
    assert begun.status_code == 202, begun.text
    stopped = wait_for_job(client, files.headers, preview["job"]["hid"])
    assert stopped["status"] == "stopped"
    assert _registration(make, system, made["db"])["status"] == "registered"

    begun = client.post(f"{API}/imports/{preview['job']['hid']}/apply", headers=files.headers)
    assert begun.status_code == 202, begun.text
    ended = wait_for_job(client, files.headers, preview["job"]["hid"])

    assert (ended["status"], ended["not_reported"]) == ("applied", 1)
    marked = _registration(make, system, made["db"])
    assert marked["status"] == "not_reported"
    events = make.audit(record_type="registration", record_hid=marked["hid"], action="update")
    assert len(events) == 1
    # It names the job, whichever request resumed it.
    assert {"field": "import", "old": None, "new": ended["hid"]} in events[0]["changes"]
    assert events[0]["via"] == "import"


def test_an_item_retired_meanwhile_is_not_marked(make: Maker, files: Files) -> None:
    system, made = _reported(make)
    preview = files.preview("items", _csv("vm-1,site2-vm-app,"), system=SYSTEM, complete="true")
    assert preview["job"]["not_reported"] == 2
    db = make.get(f"/items/{made['db']['hid']}")
    make.post(f"/items/{db['hid']}/retire", {"row_version": db["row_version"]}, 200)

    job = files.apply(preview)

    assert job["not_reported"] == 1
    assert _registration(make, system, made["db"])["status"] == "registered"
    assert _registration(make, system, made["web"])["status"] == "not_reported"


def test_the_command_sends_the_system_and_says_what_the_file_marks(
    run: Any, make: Maker, tmp_path: Path
) -> None:
    system, made = _reported(make)
    report = tmp_path / "vms.csv"
    report.write_text(_csv("vm-1,site2-vm-app,", "vm-2,site2-vm-web,"))

    preview = run("import", str(report), "--entity", "items", "--system", SYSTEM, "--complete")
    assert f"it marks 1 as not reported by {SYSTEM}: site2-vm-db" in preview.stderr
    applied = run(
        "import", str(report), "--entity", "items", "--system", SYSTEM, "--complete", "--apply"
    )
    assert "1 marked not reported" in applied.stderr
    assert _registration(make, system, made["db"])["status"] == "not_reported"
    refused = run("import", str(report), "--entity", "items", "--complete", expect=4)
    assert "complete" in refused.output
    # A file with a row rejected says why it marks nothing.
    held = tmp_path / "held.csv"
    held.write_text(_csv("vm-1,site2-vm-app,", "vm-1,site2-vm-web,"))
    preview = run(
        "import", str(held), "--entity", "items", "--system", SYSTEM, "--complete", expect=4
    )
    assert f"it marks nothing as not reported by {SYSTEM}: a row is rejected" in preview.stderr
