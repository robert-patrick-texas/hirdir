"""The client commands of the command line, run against the application itself.

The commands call the API with httpx2. Here those calls are handed to the test client,
so each command is run whole: its arguments, the requests it makes, what it prints and
the code it exits with.
"""

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from tests.api.inventory import Maker

runner = CliRunner()


@pytest.fixture
def run(client: TestClient, inventory: dict[str, str], monkeypatch, tmp_path: Path):
    """Run `hirdir` as the Inventory user, with its calls going to the test client."""
    monkeypatch.setattr(cli_client.httpx2, "request", client.request)
    monkeypatch.setattr(cli_client.httpx2, "stream", client.stream)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.setenv("HIRDIR_TOKEN", inventory["Authorization"].removeprefix("Bearer "))

    def hirdir(*arguments: str, expect: int = 0) -> Result:
        result = runner.invoke(app, list(arguments))
        assert result.exit_code == expect, result.output
        return result

    return hirdir


@pytest.fixture
def switches(make: Maker) -> list[dict[str, Any]]:
    entry = make.entry(make.vendor(), est_value="18000.00", ldos="2034-04-30")
    make.owner("Network Engineering")
    make.owner("Voice Services")
    make.tag("refresh-2030")
    return [
        make.item(
            catalog_entry_hid=entry["hid"],
            serial_number=f"FCW0000X00{number}",
            hostname=f"site2-sw-{number}",
            lifecycle_state="Prod",
        )
        for number in range(1, 4)
    ]


def test_a_list_is_a_table_on_a_terminal_and_a_file_for_a_script(run, switches: list) -> None:
    table = run("items", "list", "--sort", "-hostname", "--limit", "2").stdout.splitlines()
    assert table[0].split() == [
        "HID", "NAME", "HOSTNAME", "VENDOR", "PID", "SERIAL_NUMBER", "LIFECYCLE_STATE", "OWNER",
    ]  # fmt: skip
    assert [line.split()[1] for line in table[1:]] == ["site2-sw-3", "site2-sw-2"]
    assert table[1].startswith(switches[2]["hid"])

    wanted = ("--filter", "hostname:prefix:site2-sw-", "--columns", "hostname,catalog.pid,ldos")
    as_csv = list(csv.reader(io.StringIO(run("items", "list", *wanted, "--format", "csv").stdout)))
    assert as_csv[0] == ["hid", "hostname", "pid", "ldos"]
    assert [row[1:] for row in as_csv[1:]] == [
        [f"site2-sw-{number}", "C9300-48P", "2034-04-30"] for number in (1, 2, 3)
    ]
    as_json = json.loads(run("items", "list", *wanted, "--format", "json").stdout)
    assert [list(record.values()) for record in as_json["records"]] == as_csv[1:]
    # The other records are listed the same way.
    assert "Cisco" in run("vendors", "list").stdout
    assert "C9300-48P" in run("catalog", "list").stdout
    assert "Voice Services" in run("owners", "list").stdout
    assert "refresh-2030" in run("tags", "list").stdout
    run("items", "list", "--format", "yaml", expect=2)
    run("items", "list", "--filter", "nonsense:eq:1", expect=4)


def test_export_writes_what_the_api_exports(
    run, client: TestClient, inventory: dict, switches: list, tmp_path: Path
) -> None:
    body = {"entity": "items", "filter": "hostname:prefix:site2-sw-", "own_values": True}
    from_api = client.post("/api/v1/exports", json=body, headers=inventory).text
    arguments = ("export", "items", "--filter", "hostname:prefix:site2-sw-", "--own-values")
    assert run(*arguments).stdout == from_api
    target = tmp_path / "items.csv"
    written = run(*arguments, "--output", str(target))
    assert target.read_text() == from_api
    assert written.stdout == ""
    assert "wrote" in written.stderr
    sources = run("export", "catalog-entries", "--include-sources", "--format", "json").stdout
    assert json.loads(sources)["records"][0]["stack_discount_pct_source"] == "setting"
    run("export", "contracts", expect=4)


def test_an_item_is_shown_by_whatever_it_is_known_by(run, make: Maker, switches: list) -> None:
    make.item(name="twin")
    make.item(hostname="TWIN")
    for known_by in (switches[0]["hid"], "fcw0000x001", "site2-sw-1"):
        shown = run("items", "show", known_by).stdout
        assert f"{'hid:':<21}{switches[0]['hid']}" in shown
        assert f"{'est_value:':<21}18000.00 (catalog)" in shown
    assert " E" in run("items", "show", "site2-sw-1").stdout.split("created_at:")[1].splitlines()[0]
    assert (
        json.loads(run("items", "show", "FCW0000X002", "--format", "json").stdout)["hostname"]
        == "site2-sw-2"
    )
    twins = run("items", "show", "twin", expect=4)
    assert "more than one item answers to twin" in twins.stderr
    assert twins.stdout == ""
    assert "there is no item nobody" in run("items", "show", "nobody", expect=4).stderr


def test_one_item_is_set_at_once_and_many_only_with_apply(run, make: Maker, switches: list) -> None:
    one = run("items", "set", "site2-sw-1", "disposition=Spare", "expected_online=false",
              "hostname=site2-sw-spare", "--add-tag", "refresh-2030")  # fmt: skip
    assert "disposition: Production → Spare" in one.stdout
    after = make.get(f"/items/{switches[0]['hid']}")
    assert (after["disposition"], after["expected_online"], after["hostname"], after["tags"]) == (
        "Spare",
        False,
        "site2-sw-spare",
        ["refresh-2030"],
    )
    assert make.audit(record_type="item", action="update")[0]["via"] == "cli"

    many = ("items", "set", "--filter", "hostname:prefix:site2-sw-", "owner=Voice Services")
    preview = run(*many)
    assert "owner: blank → Voice Services" in preview.stdout
    assert "Nothing was changed" in preview.stderr
    assert make.get("/items", filter="owner.label:eq:Voice Services")["total"] == 0
    assert "applied: 0 created, 3 updated" in run(*many, "--apply").stderr
    assert make.get("/items", filter="owner.label:eq:Voice Services")["total"] == 3

    cleared = run("items", "set", "site2-sw-2", "owner=")
    assert "owner: Voice Services → blank" in cleared.stdout
    # What the rules refuse is said, and nothing is changed.
    refused = run("items", "set", "site2-sw-2", "expected_online=false", expect=4)
    assert "expected_online" in refused.stdout
    run("items", "set", "site2-sw-2", "nonsense=1", expect=4)
    run("items", "set", "site2-sw-2", "not-a-pair", expect=2)
    run("items", "set", "comments=nobody named", expect=2)
    run("items", "set", "--filter", "hostname:prefix:site2-sw-", "hostname=same", expect=4)


def test_a_transition_records_the_move_and_says_what_the_rules_refuse(
    run, make: Maker, switches: list
) -> None:
    moved = run("items", "transition", "site2-sw-1", "down", "--reason", "maintenance")
    assert moved.stdout.strip() == "site2-sw-1: Prod → Down"
    history = make.get(f"/items/{switches[0]['hid']}/history")["items"][0]
    assert (history["action"], history["via"]) == ("transition", "cli")
    refused = run("items", "transition", "site2-sw-1", "Archived", expect=4)
    assert "an Admin may force another move" in refused.stderr
    run("items", "transition", "site2-sw-1", "Archived", "--force", "--reason", "lost", expect=3)


def test_import_previews_then_applies_and_exits_4_on_rejected_rows(
    run, make: Maker, switches: list, tmp_path: Path
) -> None:
    good = tmp_path / "items.csv"
    good.write_text(
        "vendor,pid,serial_number,owner\n"
        "Cisco,C9300-48P,FCW0000X001,Network Engineering\n"
        "Cisco,C9300-48P,FCW0000X009,Network Engineering\n"
    )
    preview = run("import", str(good), "--entity", "items")
    assert "row 2  create  Cisco C9300-48P FCW0000X009" in preview.stdout
    assert "preview: 1 created, 1 updated, 0 unchanged, 0 rejected" in preview.stderr
    assert make.get("/items")["total"] == 3
    assert (
        "applied: 1 created, 1 updated"
        in run("import", str(good), "--entity", "items", "--apply").stderr
    )
    assert make.get("/items")["total"] == 4
    assert make.get("/imports")["items"][0]["file_name"] == "items.csv"

    bad = tmp_path / "more.csv"
    bad.write_text(
        "vendor,pid,serial_number,owner\n"
        "Cisco,C9300-48P,FCW0000X010,Nobody\n"
        "Cisco,C9300-48P,FCW0000X011,\n"
    )
    assert (
        "owner: there is no owner Nobody"
        in run("import", str(bad), "--entity", "items", expect=4).stdout
    )
    blocked = run("import", str(bad), "--entity", "items", "--apply", expect=4)
    assert "nothing was applied" in blocked.stderr
    assert make.get("/items")["total"] == 4
    skipped = run("import", str(bad), "--entity", "items", "--apply", "--skip-rejected")
    assert "1 rejected and left out" in skipped.stderr
    assert make.get("/items")["total"] == 5

    envelope = tmp_path / "tags.json"
    envelope.write_text(
        json.dumps({"schema": "hirdir/1", "entity": "tags", "records": [{"label": "lab"}]})
    )
    as_json = json.loads(run("import", str(envelope), "--format", "json").stdout)
    assert (as_json["job"]["entity"], as_json["rows"][0]["outcome"]) == ("tags", "create")
    run("import", str(tmp_path / "absent.csv"), "--entity", "items", expect=2)
    run("import", str(good), expect=4)


def test_exit_codes_tell_access_from_a_conflict_from_no_server(
    run, client: TestClient, make: Maker, admin: dict, switches: list, monkeypatch, tmp_path: Path
) -> None:
    file = tmp_path / "items.csv"
    file.write_text("vendor,pid,serial_number,comments\nCisco,C9300-48P,FCW0000X001,noted\n")
    # A row changed between the preview and the apply is a conflict: exit 5.
    request = client.request

    def changed_in_between(method: str, url: str, **more: Any):
        if url.endswith("/apply"):
            make.patch(f"/items/{switches[0]['hid']}", {"row_version": 1, "fqdn": "a.example.net"})
        return request(method, url, **more)

    monkeypatch.setattr(cli_client.httpx2, "request", changed_in_between)
    stale = run("import", str(file), "--entity", "items", "--apply", expect=5)
    assert "rows.1" in stale.stderr
    monkeypatch.setattr(cli_client.httpx2, "request", request)

    monkeypatch.setenv("HIRDIR_TOKEN", "not-a-token")
    assert run("items", "list", expect=3).stdout == ""
    run("items", "show", "site2-sw-1", expect=3)
    monkeypatch.delenv("HIRDIR_URL")
    assert "no server is set" in run("items", "list", expect=2).stderr
