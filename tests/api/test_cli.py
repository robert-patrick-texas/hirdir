"""The client commands of the command line, run against the application itself.

The commands call the API with httpx2. Here those calls are handed to the test client,
so each command is run whole: its arguments, the requests it makes, what it prints and
the code it exits with.
"""

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from hirdir.io.entities import LOAD_ORDER
from tests.api.inventory import Maker

runner = CliRunner()


@pytest.fixture
def run(client: TestClient, inventory: dict[str, str], monkeypatch, tmp_path: Path):
    """Run `hirdir` as the Inventory user, with its calls going to the test client."""
    # The test client takes no timeout: the command's own is left out on the way.
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setattr(
        cli_client.httpx2,
        "stream",
        lambda method, url, timeout=None, **more: client.stream(method, url, **more),
    )
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
    run("export", "observations", expect=4)


def test_export_all_writes_the_zip_of_every_table(
    run, client: TestClient, inventory: dict, switches: list, tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "everything.zip"
    written = run("export", "--all", "--format", "json", "--output", str(target))
    assert f"wrote {target}" in written.stderr
    archive = zipfile.ZipFile(target)
    assert archive.namelist() == [f"{name.replace('_', '-')}.json" for name in LOAD_ORDER]
    alone = client.post(
        "/api/v1/exports",
        json={
            "entity": "items",
            "format": "json",
            "sort": ["depth", "name"],
            "own_values": True,
            "include_archived": True,
            "include_drafts": True,
        },
        headers=inventory,
    ).text
    assert archive.read("items.json").decode() == alone
    # With no --output, the name the server gives it, where the command is run.
    monkeypatch.chdir(tmp_path)
    named = run("export", "--all").stderr.removeprefix("wrote ").strip()
    assert named.startswith("hirdir-all-csv-")
    assert named.endswith(".zip")
    assert zipfile.ZipFile(tmp_path / named).namelist()[0] == "tags.csv"
    run("export", "--all", "items", expect=2)
    run("export", "--all", "--filter", "name:eq:x", expect=2)
    run("export", expect=2)


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


def test_an_apply_is_waited_for_or_left_to_the_server_and_a_stopped_one_resumed(
    run, make: Maker, switches: list, monkeypatch, tmp_path: Path
) -> None:
    from hirdir.io import imports

    file = tmp_path / "comments.csv"
    file.write_text("hostname,comments\nsite2-sw-1,first\nsite2-sw-2,second\n")
    # Left to the server, the command says where to look, and the job goes on.
    left = run("import", str(file), "--entity", "items", "--apply", "--no-wait")
    hid = make.get("/imports")["items"][0]["hid"]
    assert f"hirdir imports show {hid} --wait" in left.stderr
    waited = run("imports", "show", hid, "--wait")
    assert "applied: 0 created, 2 updated, 0 unchanged" in waited.stderr
    assert "status: applied" in run("imports", "show", hid).stdout

    # One that stops partway exits with 6 and says how to resume it.
    one = imports._apply_row

    def fails_at_the_second_row(run_, which, was, values):
        if was.row == 2:
            raise RuntimeError("something nobody foresaw")
        return one(run_, which, was, values)

    # Only the apply fails: the preview is made as ever.
    monkeypatch.setattr(imports, "_apply_row", fails_at_the_second_row)
    file.write_text("hostname,comments\nsite2-sw-1,third\nsite2-sw-2,fourth\n")
    stopped = run("import", str(file), "--entity", "items", "--apply", expect=6)
    hid = make.get("/imports")["items"][0]["hid"]
    assert f"`hirdir imports apply {hid}` resumes it" in stopped.stderr
    monkeypatch.setattr(imports, "_apply_row", one)
    resumed = run("imports", "apply", hid)
    assert "applied: 0 created, 2 updated" in resumed.stderr
    assert {item["comments"] for item in make.get("/items")["items"]} == {"third", "fourth", None}


def test_exit_codes_tell_access_from_a_conflict_from_no_server(
    run, client: TestClient, make: Maker, admin: dict, switches: list, monkeypatch, tmp_path: Path
) -> None:
    file = tmp_path / "items.csv"
    file.write_text("vendor,pid,serial_number,comments\nCisco,C9300-48P,FCW0000X001,noted\n")
    # A row changed between the preview and the apply is left out as stale, which is a
    # conflict: exit 5.
    request = cli_client.httpx2.request

    def changed_in_between(method: str, url: str, **more: Any):
        if url.endswith("/apply"):
            make.patch(f"/items/{switches[0]['hid']}", {"row_version": 1, "fqdn": "a.example.net"})
        return request(method, url, **more)

    monkeypatch.setattr(cli_client.httpx2, "request", changed_in_between)
    stale = run("import", str(file), "--entity", "items", "--apply", expect=5)
    assert "row 1  stale" in stale.stdout
    assert "changed since the preview" in stale.stdout
    assert "1 changed since the preview and were left out" in stale.stderr
    monkeypatch.setattr(cli_client.httpx2, "request", request)

    monkeypatch.setenv("HIRDIR_TOKEN", "not-a-token")
    assert run("items", "list", expect=3).stdout == ""
    run("items", "show", "site2-sw-1", expect=3)
    monkeypatch.delenv("HIRDIR_URL")
    assert "no server is set" in run("items", "list", expect=2).stderr


# --- structure: minor items, groups, addresses and reports ---------------------------


@pytest.fixture
def stack(make: Maker, switches: list) -> dict[str, Any]:
    """The three switches as one stack, with a power supply in the first and an address."""
    owner = make.get("/owners", filter="label:eq:Network Engineering")["items"][0]
    first = make.patch(
        f"/items/{switches[0]['hid']}", {"row_version": 1, "owner_hid": owner["hid"]}
    )
    make.item(name="PS-A", parent_item_hid=first["hid"], position="PS-A")
    made = make.stack("site2-sw-stack1", switches, hostname="site2-sw-stack1")
    make.address(made, "192.0.2.1", make.network("Red"), is_primary=True)
    make.address(switches[1], "192.0.2.254", role="virtual")
    make.address(switches[2], "192.0.2.254", role="virtual")
    return made


def test_an_item_is_shown_with_where_it_is_and_what_it_has_from_above(run, stack: dict) -> None:
    shown = run("items", "show", "PS-A").stdout
    assert f"{'in:':<21}site2-sw-1" in shown
    assert f"{'position:':<21}PS-A" in shown
    assert f"{'lifecycle_state:':<21}Prod (parent_item)" in shown
    assert f"{'expected_online:':<21}true (parent_item)" in shown
    assert f"{'owner:':<21}Network Engineering (parent_item)" in shown

    switch = run("items", "show", "site2-sw-1").stdout
    assert f"{'lifecycle_state:':<21}Prod\n" in switch
    assert f"{'owner:':<21}Network Engineering\n" in switch
    assert f"{'minor_items:':<21}1" in switch
    assert f"{'group:':<21}site2-sw-stack1 (stack, master, position 1)" in switch
    assert f"{'address:':<21}192.0.2.254 (virtual)" in run("items", "show", "site2-sw-2").stdout


def test_a_minor_item_is_moved_by_itself_and_returned_to_inheriting(run, stack: dict) -> None:
    moved = run("items", "transition", "PS-A", "Pending-Removal", "--reason", "rma").stdout
    assert moved == "PS-A: no state → Pending-Removal\n"
    back = run("items", "transition", "PS-A", "inherit", "--reason", "found").stdout
    assert back == "PS-A: Pending-Removal → Prod, as the item it is in\n"
    refused = run("items", "transition", "site2-sw-1", "inherit", expect=4)
    assert "leaves a state by moving to another" in refused.stderr


def test_a_minor_item_is_put_in_another_item_with_set(run, make: Maker, stack: dict) -> None:
    run("items", "set", "PS-A", "parent=FCW0000X002", "position=PS-B")
    part = make.get("/items", filter="name:eq:PS-A")["items"][0]
    assert (part["parent"]["serial_number"], part["position"]) == ("FCW0000X002", "PS-B")
    run("items", "set", "PS-A", "parent=")
    assert make.get(f"/items/{part['hid']}")["is_major"] is True


def test_a_group_is_shown_with_its_members_and_its_masters_serial_number(
    run, make: Maker, stack: dict
) -> None:
    shown = run("groups", "show", "SITE2-SW-STACK1").stdout
    assert f"{'type:':<21}stack" in shown
    assert f"{'serial_number:':<21}FCW0000X001" in shown
    assert f"{'address:':<21}192.0.2.1 under Red (management, primary)" in shown
    assert f"{'members:':<21}3" in shown
    table = [line.split() for line in shown.split("\n\n")[1].splitlines()]
    assert table[0] == ["POSITION", "ROLE", "NAME", "PID", "SERIAL_NUMBER", "JOINED_ON", "LEFT_ON"]
    assert [row[:5] for row in table[1:]] == [
        ["1", "master", "site2-sw-1", "C9300-48P", "FCW0000X001"],
        ["2", "member", "site2-sw-2", "C9300-48P", "FCW0000X002"],
        ["3", "member", "site2-sw-3", "C9300-48P", "FCW0000X003"],
    ]
    by_hid = json.loads(run("groups", "show", stack["hid"], "--format", "json").stdout)
    assert (by_hid["name"], len(by_hid["members"])) == ("site2-sw-stack1", 3)
    assert "there is no device group nobody" in run("groups", "show", "nobody", expect=4).stderr

    third = make.members(stack)[2]
    make.patch(
        f"/device-groups/{stack['hid']}/members/{third['hid']}",
        {"row_version": third["row_version"], "left_on": third["joined_on"]},
    )
    assert "site2-sw-3" not in run("groups", "show", "site2-sw-stack1").stdout
    assert "site2-sw-3" in run("groups", "show", "site2-sw-stack1", "--include-past").stdout


def test_groups_networks_and_addresses_are_listed_as_any_list_is(run, stack: dict) -> None:
    groups = run("groups", "list").stdout.splitlines()
    assert groups[0].split() == [
        "HID", "NAME", "TYPE", "HOSTNAME", "SERIAL_NUMBER", "MEMBERS", "HEALTH", "OWNER",
        "RECORD_STATUS",
    ]  # fmt: skip
    assert groups[1].split()[1:] == [
        "site2-sw-stack1", "stack", "site2-sw-stack1", "FCW0000X001", "3", "unknown", "active"
    ]  # fmt: skip
    assert run("networks", "list", "--format", "csv").stdout.splitlines()[1].endswith(",Red,vrf")
    rows = list(
        csv.DictReader(
            io.StringIO(
                run("addresses", "list", "--filter", "role:eq:virtual", "--format", "csv").stdout
            )
        )
    )
    assert [(row["address"], row["item"]) for row in rows] == [
        ("192.0.2.254", "FCW0000X002"),
        ("192.0.2.254", "FCW0000X003"),
    ]
    assert run("export", "device-group-members", "--format", "csv").stdout.count("\n") == 4


def test_the_summary_is_printed_whole_and_by_what_items_share(
    run, stack: dict, tmp_path: Path
) -> None:
    whole = run("report", "summary").stdout
    assert f"{'items:':<21}4" in whole
    assert f"{'component_count:':<21}3" in whole
    assert f"{'managed_node_count:':<21}1" in whole
    assert f"{'unknown:':<21}3" in whole
    assert "est_value" not in whole
    assert f"{'hardware:':<21}4 items, 3 in hand" in whole

    table = [
        line.split("  ") for line in run("report", "summary", "--by", "owner").stdout.splitlines()
    ]
    assert [cell.strip() for cell in table[0] if cell.strip()][:4] == [
        "OWNER", "ITEMS", "COMPONENT_COUNT", "MANAGED_NODE_COUNT"
    ]  # fmt: skip
    assert [row[0].strip() for row in table[1:]] == ["Network Engineering", "(none)", "(all)"]
    target = tmp_path / "summary.csv"
    run("report", "summary", "--by", "lifecycle_state", "--format", "csv", "--output", str(target))
    rows = list(csv.DictReader(target.open()))
    assert [(row["lifecycle_state"], row["items"]) for row in rows] == [
        ("Prod", "4"),
        ("(all)", "4"),
    ]
    filtered = json.loads(
        run("report", "summary", "--filter", "is_major:eq:false", "--format", "json").stdout
    )
    assert (filtered["totals"]["items"], filtered["totals"]["component_count"]) == (1, 0)
    run("report", "summary", "--by", "serial_number", expect=4)
    run("report", "summary", "--format", "xml", expect=2)


def test_the_duplicates_report_names_who_holds_an_address_twice(run, stack: dict) -> None:
    table = run("report", "duplicates").stdout.splitlines()
    assert table[0].split() == ["ADDRESS", "NETWORK", "HELD_BY", "ROLE"]
    assert [line.split() for line in table[1:]] == [
        ["192.0.2.254", "site2-sw-2", "virtual"],
        ["192.0.2.254", "site2-sw-3", "virtual"],
    ]
    found = json.loads(run("report", "duplicates", "--format", "json").stdout)
    assert (found[0]["address"], found[0]["count"]) == ("192.0.2.254", 2)


def test_the_management_report_prints_the_value_and_the_cost(run, stack: dict) -> None:
    # Asked for by nothing, it is by site: the items that are nowhere, and all of them.
    whole = run("report", "management").stdout.splitlines()
    assert whole[0].split() == [
        "SITE",
        "ITEMS",
        "COMPONENT_COUNT",
        "EST_VALUE",
        "ANNUAL_SUPPORT_COST",
    ]
    assert [line.split() for line in whole[1:]] == [
        ["(none)", "4", "3", "54000.00", "0.00"],
        ["(all)", "4", "3", "54000.00", "0.00"],
    ]
    assert "health" not in "".join(whole).lower()

    table = run("report", "management", "--by", "owner").stdout.splitlines()
    assert table[0].split() == [
        "OWNER",
        "ITEMS",
        "COMPONENT_COUNT",
        "EST_VALUE",
        "ANNUAL_SUPPORT_COST",
    ]
    assert [line.split("  ")[0] for line in table[1:]] == ["Network Engineering", "(none)", "(all)"]
    found = json.loads(run("report", "management", "--format", "json").stdout)
    assert found["totals"]["est_value"] == "54000.00"
    run("report", "management", "--by", "health", expect=4)


def test_an_item_and_a_group_are_shown_with_how_they_are_doing(
    run, make: Maker, stack: dict, switches: list
) -> None:
    run("items", "set", "site2-sw-1", "condition=good", "observed_status=online")
    shown = run("items", "show", "site2-sw-1").stdout
    assert f"{'condition:':<21}good" in shown
    assert f"{'observed_status:':<21}online, seen " in shown
    assert f"{'health:':<21}good: its condition is good; it is observed online" in shown

    current = make.get(f"/device-groups/{stack['hid']}")
    make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": current["row_version"], "observed_master_hid": switches[1]["hid"]},
    )
    group = run("groups", "show", "site2-sw-stack1").stdout
    assert f"{'serial_number:':<21}FCW0000X002 (of the master that is observed)" in group
    assert f"{'intended_master:':<21}site2-sw-1" in group
    assert f"{'observed_master:':<21}site2-sw-2, seen " in group
    assert "(not the one intended)" in group
    assert f"{'health:':<21}unknown: " in group
    # A stack answers to the serial number of any member.
    listed = run(
        "groups", "list", "--filter", "member.serial_number:eq:FCW0000X003", "--format", "csv"
    ).stdout.splitlines()
    assert len(listed) == 2
    assert "site2-sw-stack1" in listed[1]


def test_the_geography_is_shown_as_a_tree_and_a_place_with_what_it_has_in_force(
    run, make: Maker, tmp_path: Path
) -> None:
    places = make.layout()
    make.region("East", places["americas"])
    room = "Americas > Central > Site-2 > Building 1 > Room 102"
    make.item(hostname="site2-sw-1", location_hid=places["room"]["hid"], lifecycle_state="Prod")
    make.item(hostname="site2-sw-2", lifecycle_state="Prod")
    dana = make.contact("Dana Whitfield", phone="+1 555 0100")
    make.assign(dana, "technical", region_hid=places["americas"]["hid"])
    make.assign(None, "shipping", stop_inheritance=True, site_hid=places["site"]["hid"])
    central = places["central"]
    make.patch(
        f"/regions/{central['hid']}",
        {"row_version": central["row_version"], "ship_address1": "1 Depot Road"},
    )

    tree = run("geography", "tree").stdout.splitlines()
    assert tree[0].split() == ["PLACE", "LEVEL", "ITEMS", "COMPONENT_COUNT"]
    assert [line.rstrip() for line in tree[1:]] == [
        "Americas          region    1      1",
        "  Central         region    1      1",
        "    Site-2        site      1      1",
        "      Building 1  location  1      1",
        "        Room 102  location  1      1",
        "  East            region    0      0",
        "(nowhere)                   1      1",
        "(all)                       2      2",
    ]
    short = run("geography", "tree", "--root", "Americas > Central", "--no-locations").stdout
    assert [line.split()[0] for line in short.splitlines()[1:]] == [
        "Central",
        "Site-2",
        "(nowhere)",
        "(all)",
    ]
    target = tmp_path / "tree.csv"
    run("geography", "tree", "--format", "csv", "--output", str(target))
    rows = list(csv.DictReader(target.open()))
    assert (rows[4]["place"], rows[4]["items"]) == (room, "1")
    assert json.loads(run("geography", "tree", "--format", "json").stdout)["totals"]["items"] == 2
    run("geography", "tree", "--root", "Atlantis", expect=4)

    shown = run("locations", "show", room).stdout
    assert f"{'path:':<21}{room}" in shown
    assert f"{'kind:':<21}room" in shown
    assert f"{'items:':<21}1" in shown
    assert (
        f"{'technical:':<21}Dana Whitfield dana.whitfield@example.net +1 555 0100 (from Americas)"
        in shown
    )
    assert f"{'shipping:':<21}nobody (from Americas > Central > Site-2)" in shown
    assert f"{'ship_address:':<21}1 Depot Road (from Americas > Central)" in shown
    by_hid = json.loads(run("sites", "show", places["site"]["hid"], "--format", "json").stdout)
    assert by_hid["effective"]["contacts"][1]["source"] == "region"
    assert (
        f"{'ship_address:':<21}1 Depot Road\n"
        in run("regions", "show", "Americas > Central").stdout
    )
    # A place of another level is said to be so, and nothing is shown.
    run("locations", "show", "Americas > Central", expect=4)

    listed = run("sites", "list").stdout.splitlines()
    assert listed[0].split() == ["HID", "PATH", "CODE", "CITY", "COUNTRY", "RECORD_STATUS"]
    assert "Americas > Central > Site-2" in listed[1]
    # A table shows a telephone number as it is, without the apostrophe of a CSV cell.
    listed = run("contacts", "list").stdout
    assert "Dana Whitfield" in listed
    assert " +1 555 0100" in listed
    assert "'+1" not in listed
    within = run("items", "list", "--filter", "location:within:Americas > Central").stdout
    assert [line.split()[1] for line in within.splitlines()[1:]] == ["site2-sw-1"]


def test_a_site_is_moved_and_an_item_is_put_somewhere_from_the_command_line(
    run, make: Maker
) -> None:
    places = make.layout()
    make.region("East", places["americas"])
    switch = make.item(hostname="site2-sw-1")
    outside = make.owner("Facilities", is_external=True, exception_reason="Runs the plant rooms")

    room = "Americas > Central > Site-2 > Building 1 > Room 102"
    run("items", "set", "site2-sw-1", f"location={room}")
    shown = run("items", "show", "site2-sw-1").stdout
    assert f"{'location:':<21}{room}" in shown

    moved = run("sites", "move", "Americas > Central > Site-2", "Americas > East").stdout
    assert moved.strip() == "Americas > Central > Site-2 is now Americas > East > Site-2"
    assert make.get(f"/items/{switch['hid']}")["effective"]["location_hid"]["label"] == (
        "Americas > East > Site-2 > Building 1 > Room 102"
    )
    assert run("regions", "move", "Americas > East", "top").stdout.strip() == (
        "Americas > East is now East"
    )
    run("regions", "move", "Americas", "East > Site-2", expect=4)
    run("sites", "move", "Nowhere", "East", expect=4)

    # A spare is planned for a site that is still a draft, and says so.
    plan = make.site("Site-3", make.get("/regions", filter="name:eq:East")["items"][0])
    make.patch(
        f"/sites/{plan['hid']}", {"row_version": plan["row_version"], "record_status": "draft"}
    )
    make.location("Suite 300", plan)
    make.item(hostname="spare-01")
    run("items", "set", "spare-01", "planned_location=East > Site-3 > Suite 300")
    assert (
        f"{'planned_location:':<21}East > Site-3 > Suite 300"
        in run("items", "show", "spare-01").stdout
    )
    # An item given to an owner outside the team is marked, with that owner's reason.
    run("items", "set", "site2-sw-1", f"owner={outside['label']}")
    assert (
        f"{'owner_exception:':<21}Runs the plant rooms" in run("items", "show", "site2-sw-1").stdout
    )


def test_who_looks_after_an_item_is_shown_counted_and_handed_over(
    run, make: Maker, switches: list
) -> None:
    lee = make.contact("Lee Marchetti")
    make.contact("Robin Achterberg")
    make.post("/operators", {"label": "LM", "description": "Core", "contact_hid": lee["hid"]})
    make.post("/operators", {"label": "Op2"})
    make.stack(
        "site2-sw-stack1", switches[:2], operator_hid=make.get("/operators")["items"][0]["hid"]
    )

    listed = run("operators", "list").stdout.splitlines()
    assert listed[0].split() == [
        "HID",
        "LABEL",
        "DESCRIPTION",
        "CONTACT",
        "SCOPE",
        "IS_OPEN",
        "RECORD_STATUS",
    ]
    assert [line.split()[1] for line in listed[1:]] == ["LM", "Op2"]
    shown = run("items", "show", "site2-sw-1").stdout
    assert f"{'operator:':<21}LM (Lee Marchetti), from the device group site2-sw-stack1" in shown
    run("items", "set", "site2-sw-3", "operator=op2")
    assert (
        f"{'operator:':<21}Op2 (open: nobody is behind it)\n"
        in run("items", "show", "site2-sw-3").stdout
    )
    assert (
        f"{'operator:':<21}LM (Lee Marchetti)\n" in run("groups", "show", "site2-sw-stack1").stdout
    )
    table = run("report", "summary", "--by", "operator").stdout.splitlines()
    assert [line.split("  ")[0] for line in table[1:]] == ["LM", "Op2", "(all)"]

    board = run("report", "summary", "--by", "lifecycle_state", "--operators").stdout
    assert board.splitlines()[0].split()[-1] == "OPERATORS"
    assert board.splitlines()[1].rstrip().endswith("LM 0, Op2 0")

    # The label is handed over, left open and released, each in one command.
    handed = run("operators", "assign", "LM", "robin.achterberg@example.net").stdout
    assert handed.strip() == "LM is Robin Achterberg, external; it is on 1 records of its own"
    assert "LM (Robin Achterberg)" in run("items", "show", "site2-sw-2").stdout
    assert "nobody: it is open" in run("operators", "assign", "lm", "--open").stdout
    open_ones = run("items", "list", "--filter", "operator.is_open:eq:true").stdout
    assert len(open_ones.splitlines()) == 4
    run("operators", "assign", "LM", expect=2)
    run("operators", "assign", "LM", "nobody@example.net", expect=4)
    assert run("operators", "release", "Op2").stdout.strip() == (
        "Op2 is released; it was on 1 records of its own"
    )
    nobody = run("items", "list", "--filter", "effective.operator_hid:empty:true").stdout
    assert [line.split()[1] for line in nobody.splitlines()[1:]] == ["site2-sw-3"]
    run("operators", "release", "ZZ", expect=4)


# --- the commands of 0.6.0 ------------------------------------------------------------


@pytest.fixture
def covered(make: Maker, switches: list) -> dict[str, Any]:
    """An agreement with a contract in it, a contract by itself, and one switch covered."""
    cisco = make.get("/vendors", filter="name:eq:Cisco")["items"][0]
    agreement = make.post(
        "/agreements",
        {
            "name": "Cisco Enterprise Agreement",
            "vendor_hid": cisco["hid"],
            "starts_on": "2025-01-01",
            "ends_on": "2099-12-31",
            "account_manager": "Jordan Reyes, +1 555 0142",
        },
    )
    inside = make.post("/contracts", {"number": "CON-1", "agreement_hid": agreement["hid"]})
    alone = make.post(
        "/contracts",
        {
            "number": "CON-2",
            "vendor_hid": cisco["hid"],
            "starts_on": "2026-01-01",
            "ends_on": "2098-12-31",
            "purchase_reference": "RITM0001",
        },
    )
    make.post(f"/contracts/{inside['hid']}/coverage", {"items": [{"item_hid": switches[0]["hid"]}]})
    return {"agreement": agreement, "inside": inside, "alone": alone, "vendor": cisco}


def test_contracts_are_shown_covered_rolled_in_and_renewed(
    run, make: Maker, switches: list, covered: dict
) -> None:
    listed = run("agreements", "list", "--format", "csv").stdout.splitlines()
    assert listed[0].startswith("hid,name,number,vendor,reseller,starts_on,ends_on")
    table = run("contracts", "list").stdout.splitlines()
    assert [line.split()[1] for line in table[1:]] == ["CON-1", "CON-2"]
    shown = run("contracts", "show", "CON-1").stdout
    assert "agreement:           Cisco Enterprise Agreement" in shown
    # What it has from its agreement says so.
    assert "ends_on:             2099-12-31 (agreement)" in shown
    assert "account_manager:     Jordan Reyes, +1 555 0142 (agreement)" in shown
    assert "items covered:       1" in shown
    assert "site2-sw-1" in shown
    as_json = json.loads(run("contracts", "show", "CON-1", "--format", "json").stdout)
    assert [one["item"]["serial_number"] for one in as_json["coverage"]] == ["FCW0000X001"]
    run("contracts", "show", "CON-9", expect=4)

    # Covering is previewed, and done with --apply.
    preview = run("contracts", "cover", "CON-2", "--filter", "hostname:prefix:site2-sw-")
    assert "3 items would be covered by CON-2, 2026-01-01 to 2098-12-31" in preview.stdout
    assert "nothing was changed" in preview.stderr
    assert make.get(f"/contracts/{covered['alone']['hid']}")["covered_items"] == 0
    done = run("contracts", "cover", "CON-2", "FCW0000X002", "site2-sw-3", "--apply")
    assert "2 items are covered by CON-2" in done.stdout
    run("contracts", "cover", "CON-2", "FCW0000X002", "--apply", expect=5)
    run("contracts", "cover", "CON-2", expect=2)
    run("contracts", "cover", "CON-2", "--filter", "hostname:eq:nothing", expect=4)

    # Rolled into the agreement by one change, and its own dates cleared.
    rolled = run("contracts", "set", "CON-2", "agreement=Cisco Enterprise Agreement", "ends_on=")
    assert "CON-2 in Cisco Enterprise Agreement: 2026-01-01 to 2099-12-31, 2 items in scope" in (
        rolled.stdout
    )
    run("contracts", "set", "CON-2", "colour=red", expect=2)
    run("contracts", "set", "CON-2", "agreement=No such agreement", expect=4)
    out = run("contracts", "set", "CON-2", "agreement=").stdout
    assert out.startswith("CON-2: ")

    # A renewal whose period has begun is in force at once.
    renewed = run(
        "contracts", "renew", "CON-2", "--number", "CON-2-R1", "--from", "2026-06-01",
        "--to", "2097-12-31", "--purchase-reference", "RITM0002",
    )  # fmt: skip
    assert "CON-2 is now CON-2-R1, 2026-06-01 to 2097-12-31; 2 items follow" in renewed.stdout
    shown = run("contracts", "show", "CON-2-R1").stdout
    assert "earlier term:        CON-2, 2026-01-01 to further notice, RITM0001" in shown
    run("contracts", "renew", "CON-2-R1", expect=4)
    # One that is still to begin is kept as the next term, and may be withdrawn.
    ahead = run(
        "contracts", "renew", "CON-2-R1", "--number", "CON-2-R2", "--from", "2098-01-01",
        "--to", "2098-12-31",
    )  # fmt: skip
    assert "CON-2-R1 renews as CON-2-R2 on 2098-01-01, to 2098-12-31; until then" in ahead.stdout
    shown = run("contracts", "show", "CON-2-R2").stdout
    assert "number:              CON-2-R1" in shown
    assert "next term:           CON-2-R2, 2098-01-01 to 2098-12-31" in shown
    withdrawn = run("contracts", "renew", "CON-2-R1", "--withdraw").stdout
    assert "the term that was to begin is withdrawn" in withdrawn
    run("contracts", "renew", "CON-2-R1", "--withdraw", expect=4)
    of_agreement = run(
        "agreements", "renew", "Cisco Enterprise Agreement", "--from", "2100-01-01",
        "--to", "2100-12-31",
    )  # fmt: skip
    assert "Cisco Enterprise Agreement renews on 2100-01-01, to 2100-12-31" in of_agreement.stdout
    shown = run("agreements", "show", "Cisco Enterprise Agreement").stdout
    assert "next term:           2100-01-01 to 2100-12-31" in shown
    assert "contracts:           " in shown
    assert "earlier term:" not in shown

    by_contract = run("report", "summary", "--by", "contract", "--format", "csv").stdout
    rows = list(csv.reader(io.StringIO(by_contract)))
    assert [row[0] for row in rows] == ["contract", "CON-1 (Cisco)", "CON-2-R1 (Cisco)", "(all)"]
    # A renewal that is in force at once supersedes one that was waiting, and says so.
    run(
        "contracts", "renew", "CON-2-R1", "--number", "CON-2-R2", "--from", "2098-01-01",
        "--to", "2098-12-31",
    )  # fmt: skip
    at_once = run(
        "contracts", "renew", "CON-2-R1", "--number", "CON-2-R3", "--from", "2026-07-01",
        "--to", "2097-06-30",
    )  # fmt: skip
    assert "CON-2-R1 is now CON-2-R3, 2026-07-01 to 2097-06-30" in at_once.stdout
    assert "the term that was to begin is superseded by it" in at_once.stderr


def test_purchases_are_shown_and_received_from_the_command_line(
    run, make: Maker, switches: list
) -> None:
    entry = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"][0]
    room = make.layout()["room"]
    make.post(
        "/purchase-requests",
        {
            "reference": "RITM0012345",
            "status": "ordered",
            "lines": [{"catalog_entry_hid": entry["hid"], "quantity": 3}],
        },
    )
    assert run("purchases", "list").stdout.splitlines()[1].split()[1] == "RITM0012345"
    shown = run("purchases", "show", "RITM0012345").stdout
    assert "still to come:       3 of 3" in shown
    assert shown.splitlines()[-1].split()[:6] == [
        "RITM0012345/1",
        "Cisco",
        "C9300-48P",
        "3",
        "0",
        "3",
    ]
    received = run(
        "purchases", "receive", "RITM0012345/1", "--serial", "FCW-101", "--serial", "FCW-102",
        "--location", room["path"], "--on", "2026-11-02",
    )  # fmt: skip
    assert "2 items received on RITM0012345/1; 1 of 3 are still to come" in received.stdout
    arrived = make.get("/items", filter="serial_number:prefix:FCW-10", sort="serial_number")
    assert [(item["lifecycle_state"], item["delivered_on"]) for item in arrived["items"]] == [
        ("Delivered", "2026-11-02")
    ] * 2
    assert arrived["items"][0]["location"]["path"] == room["path"]
    run("purchases", "receive", "RITM0012345/1", "--name", "a", "--asset-tag", "b", expect=4)
    run("purchases", "receive", "RITM0012345/1", expect=2)
    counted = run("purchases", "receive", "RITM0012345/1", "--count", "1")
    assert "1 items received on RITM0012345/1; 0 of 3 are still to come" in counted.stdout
    assert make.get("/items", filter="name:eq:RITM0012345/1-003")["total"] == 1
    assert "received" in run("purchases", "show", "RITM0012345").stdout
    run("purchases", "receive", "RITM0012345", "--serial", "x", expect=2)
    run("purchases", "receive", "RITM0099999/1", "--serial", "x", expect=4)
    run("purchases", "show", "RITM0099999", expect=4)


def test_the_reports_that_look_ahead_are_printed(
    run, make: Maker, switches: list, covered: dict
) -> None:
    coverage = run("report", "coverage").stdout
    assert "in_service:          3" in coverage
    assert "uncovered:           2" in coverage
    assert "overlapping:         0" in coverage
    assert "lapsed contracts:    0" in coverage
    uncovered = run("report", "coverage", "--section", "uncovered", "--format", "csv").stdout
    rows = list(csv.reader(io.StringIO(uncovered)))
    assert rows[0] == ["name", "pid", "serial_number", "lifecycle_state", "site", "covered_until"]
    assert [row[2] for row in rows[1:]] == ["FCW0000X002", "FCW0000X003"]
    as_json = json.loads(run("report", "coverage", "--format", "json").stdout)
    assert as_json["totals"]["covered"] == 1
    run("report", "coverage", "--section", "nonsense", expect=4)

    end_of_life = run("report", "end-of-life", "--within-days", "36500").stdout.splitlines()
    assert end_of_life[0].split() == [
        "DATE", "PAST", "PAST_COMPONENTS", "APPROACHING", "APPROACHING_COMPONENTS",
    ]  # fmt: skip
    assert ["ldos", "0", "0", "3", "3"] in [line.split() for line in end_of_life]
    assert end_of_life[-1].split()[0] == "2034"
    listed = run(
        "report", "end-of-life", "--section", "approaching", "--within-days", "36500",
        "--format", "csv",
    ).stdout  # fmt: skip
    assert listed.splitlines()[1].endswith(",2034-04-30")

    assert "no item has been replaced" in run("report", "replacements").stderr
    make.post(
        f"/items/{switches[0]['hid']}/replace",
        {
            "row_version": make.get(f"/items/{switches[0]['hid']}")["row_version"],
            "new_item_hid": switches[1]["hid"],
            "reason": "rma",
            "reference": "RMA-1",
        },
    )
    replaced = run("report", "replacements").stdout
    assert replaced.splitlines()[1].split()[1:] == ["site2-sw-1", "site2-sw-2", "RMA", "RMA-1"]
    assert "1 replacement: RMA 1" in replaced
    # An item lists each of its replacements, the latest first (P-241).
    make.post(
        f"/items/{switches[1]['hid']}/replace",
        {
            "row_version": make.get(f"/items/{switches[1]['hid']}")["row_version"],
            "new_item_hid": switches[0]["hid"],
            "reason": "refresh",
        },
    )
    shown = [
        line.split(None, 1)
        for line in run("items", "show", switches[1]["hid"]).stdout.splitlines()
        if line.startswith("replac")
    ]
    assert [(name, said.split(" on ")[0]) for name, said in shown] == [
        ("replaced_by:", "site2-sw-1"),
        ("replaces:", "site2-sw-1"),
    ]

    make.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "staff",
            "name": "Engineer",
            "quantity": "3",
            "units_each": "1",
        },
    )
    assert run("capacity", "list").stdout.splitlines()[1].split()[1:4] == [
        "supply",
        "staff",
        "Engineer",
    ]
    capacity = run("report", "capacity", "--format", "csv").stdout
    rows = {row[0]: row[1:] for row in csv.reader(io.StringIO(capacity))}
    assert rows["measure"] == ["active", "with_drafts"]
    assert (rows["supply"], rows["supply: Staff"], rows["coverage_pct"]) == (
        ["3", "3"],
        ["3", "3"],
        ["", ""],
    )

    portfolio = run("vendors", "portfolio", "Cisco").stdout
    assert "items:               3" in portfolio
    assert "agreement:           Cisco Enterprise Agreement, 2025-01-01 to 2099-12-31" in portfolio
    hardware = next(line for line in portfolio.splitlines() if line.startswith("hardware"))
    assert hardware.split()[:3] == ["hardware", "3", "3"]
    as_file = run("vendors", "portfolio", "Cisco", "--format", "csv").stdout
    rows = list(csv.DictReader(io.StringIO(as_file)))
    assert [(row["serial_number"], row["covered"], row["contracts"]) for row in rows] == [
        ("FCW0000X001", "true", "CON-1"),
        ("FCW0000X002", "false", ""),
        ("FCW0000X003", "false", ""),
    ]
    run("vendors", "portfolio", "Nobody", expect=4)


def test_systems_and_registrations_are_listed(run, make: Maker, switches: list) -> None:
    watch = make.post("/external-systems", {"name": "NetWatch", "kind": "monitoring"})
    make.post(
        "/registrations",
        {"system_hid": watch["hid"], "item_hid": switches[0]["hid"], "external_id": "node-1"},
    )
    assert run("systems", "list").stdout.splitlines()[1].split()[1:3] == ["NetWatch", "monitoring"]
    listed = run(
        "registrations", "list", "--filter", "system.name:eq:NetWatch", "--format", "csv"
    ).stdout
    rows = list(csv.DictReader(io.StringIO(listed)))
    assert [(row["system"], row["item"], row["external_id"]) for row in rows] == [
        ("NetWatch", "FCW0000X001", "node-1")
    ]


# --- the settings of 0.7.0 ------------------------------------------------------------


def test_items_are_covered_in_pieces_as_large_as_the_setting_says(
    run, make: Maker, client: TestClient, admin: dict
) -> None:
    setting = {"row_version": 0, "value": 100}
    put = client.put("/api/v1/settings/max_items_per_request", json=setting, headers=admin)
    assert put.status_code == 200, put.text
    cisco = make.vendor()
    entry = make.entry(cisco)
    request = make.post(
        "/purchase-requests",
        {
            "reference": "RITM0012345",
            "lines": [
                {"catalog_entry_hid": entry["hid"], "quantity": 150},
                {"part_number": "HLT-100", "description": "Hook-and-loop tape", "quantity": 20},
            ],
        },
    )
    line = request["lines"][0]
    path = f"/purchase-lines/{line['hid']}/receive"
    first = make.post(path, {"row_version": line["row_version"], "quantity": 100})
    make.post(path, {"row_version": first["row_version"], "quantity": 50})
    make.post("/contracts", {"number": "CON-1", "vendor_hid": cisco["hid"]})
    # One request of 150 would be refused: the command sends two.
    done = run(
        "contracts", "cover", "CON-1", "--filter", "purchase_line_hid:empty:false", "--apply"
    )
    assert "150 items are covered by CON-1" in done.stdout
    # A line that is not tracked is shown with the part number procurement gave it.
    shown = run("purchases", "show", "RITM0012345").stdout
    assert "still to come:       0 of 150" in shown
    assert shown.splitlines()[-1].split() == [
        "RITM0012345/2",
        "(not",
        "tracked)",
        "HLT-100",
        "20",
        "0",
        "0",
    ]


# --- capacity over time, and links (0.7.0) ---------------------------------------------


def test_the_balance_is_recorded_and_listed_and_the_report_says_where_the_work_is(
    run, make: Maker
) -> None:
    engineer = make.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "staff",
            "name": "Engineer",
            "quantity": "3",
            "units_each": "1",
        },
    )
    make.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "services",
            "name": "AI assistant",
            "effect": "multiply",
            "factor": "1.5",
            "applies_to": [engineer["hid"]],
        },
    )
    region = make.region("Americas")
    room = make.location("Room 1", make.site("Site-2", region))
    entry = make.entry(make.vendor(), support_weight="300")
    make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW0000X001",
        lifecycle_state="Prod",
        location_hid=room["hid"],
    )
    report = run("report", "capacity", "--format", "csv").stdout
    rows = {row[0]: row[1:] for row in csv.reader(io.StringIO(report))}
    assert rows["supply"] == ["4.5", "4.5"]
    assert rows["multiplies: AI assistant (1.5 on Engineer)"] == ["1.5", "1.5"]
    assert (rows["demand: Americas"], rows["share: Americas"]) == (["1", "1"], ["100", "100"])
    assert (rows["demand: nowhere"], rows["share: nowhere"]) == (["0", "0"], ["0", "0"])

    recorded = run("capacity", "record", "--note", "by hand").stdout
    assert "recorded the week of" in recorded
    assert "active:      demand 1, supply 4.5, balance 3.5" in recorded
    listed = run("capacity", "records", "--format", "csv").stdout
    [row] = list(csv.DictReader(io.StringIO(listed)))
    assert (row["active.supply"], row["active.coverage_pct"], row["adjusted"], row["note"]) == (
        "4.5",
        "450",
        "false",
        "by hand",
    )
    assert run("capacity", "records").stdout.lower().splitlines()[0].split()[:3] == [
        "week_of",
        "active.demand",
        "active.supply",
    ]


def test_show_prints_the_links_of_a_place_and_of_the_model_of_an_item(run, make: Maker) -> None:
    sheet = {"url": "https://www.example.com/c9300/datasheet.pdf", "text": "Data sheet"}
    plain = {"url": "https://intranet.example.net/site-2/room-102"}
    region = make.region("Americas")
    room = make.location("Room 102", make.site("Site-2", region), links=[sheet, plain])
    shown = run("locations", "show", room["hid"]).stdout
    assert f"link:                Data sheet <{sheet['url']}>" in shown
    assert f"link:                {plain['url']}\n" in shown
    entry = make.entry(make.vendor(), links=[sheet])
    make.item(catalog_entry_hid=entry["hid"], serial_number="FCW0000X009")
    item = run("items", "show", "FCW0000X009").stdout
    assert f"link:                Data sheet <{sheet['url']}>" in item


# --- the commands of 0.7.0: the contacts of agreements and contracts -------------------


def test_the_contacts_of_a_contract_are_named_shown_with_their_source_and_removed(
    run, make: Maker, covered: dict
) -> None:
    make.contact("Jordan Reyes", phone="+1 555 0142")
    make.contact("Casey Lund")
    agreement = "Cisco Enterprise Agreement"
    named = run(
        "agreements", "add-contact", agreement, "jordan.reyes@example.net", "--role",
        "account_manager",
    )  # fmt: skip
    assert f"{agreement} names Jordan Reyes as account_manager, number 1 of the list" in (
        named.stdout
    )
    reached = "Jordan Reyes jordan.reyes@example.net +1 555 0142"
    assert f"account_managers:    {reached}" in run("agreements", "show", agreement).stdout
    # A contract that names nobody of its own has its agreement's, and says so.
    assert f"account_managers:    {reached} (agreement)" in run("contracts", "show", "CON-1").stdout

    run("contracts", "add-contact", "CON-1", "Casey Lund", "--role", "account_manager")
    shown = run("contracts", "show", "CON-1").stdout
    assert "account_managers:    Casey Lund casey.lund@example.net\n" in shown
    # Its own, in place of the agreement's; the free text is beside it as before.
    assert reached not in shown
    as_json = json.loads(run("contracts", "show", "CON-1", "--format", "json").stdout)
    assert as_json["effective"]["account_managers"]["source"] == "own"
    run("contracts", "add-contact", "CON-1", "Casey Lund", "--role", "account_manager", expect=5)
    run("contracts", "add-contact", "CON-1", "Casey Lund", "--role", "sales", expect=4)
    run("contracts", "add-contact", "CON-1", "nobody@example.net", "--role", "account_manager",
        expect=4)  # fmt: skip

    removed = run(
        "contracts", "remove-contact", "CON-1", "casey.lund@example.net", "--role",
        "account_manager",
    )  # fmt: skip
    assert "CON-1 no longer names Casey Lund as account_manager" in removed.stdout
    run("contracts", "remove-contact", "CON-1", "Casey Lund", "--role", "account_manager", expect=4)
    assert f"{reached} (agreement)" in run("contracts", "show", "CON-1").stdout
