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
    request = cli_client.httpx2.request

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
    run("report", "summary", "--by", "contract", expect=4)
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

    # An item given to an owner outside the team is marked, with that owner's reason.
    run("items", "set", "site2-sw-1", f"owner={outside['label']}")
    assert (
        f"{'owner_exception:':<21}Runs the plant rooms" in run("items", "show", "site2-sw-1").stdout
    )
