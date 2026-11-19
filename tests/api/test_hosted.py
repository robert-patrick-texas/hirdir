"""What runs on a record, listed, counted and shown on the command line (P-246)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from tests.api.inventory import API, Maker
from tests.api.test_hosting import Lab

runner = CliRunner()


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


def test_what_runs_on_an_item_is_listed_with_what_runs_on_that(lab: Lab) -> None:
    make = lab.make
    beta = lab.vm("site2-vm-beta", host_item_hid=lab.esx["hid"])
    alpha = lab.vm("site2-vm-alpha", host_item_hid=lab.esx["hid"])
    ctr = lab.ctr(host_item_hid=beta["hid"])
    elsewhere = lab.vm("site2-vm-other", host_group_hid=lab.cluster["hid"])

    listed = make.get(f"/items/{lab.esx['hid']}/hosted")
    assert listed["total"] == 3
    assert [(one["depth"], one["host_hid"], one["item"]["name"]) for one in listed["items"]] == [
        (1, lab.esx["hid"], "site2-vm-alpha"),
        (1, lab.esx["hid"], "site2-vm-beta"),
        (2, beta["hid"], "site2-ctr-dns1"),
    ]
    # Each is answered as an item of a list is.
    assert listed["items"][2]["item"]["effective"]["location_hid"]["source"] == "none"
    assert lab.get(lab.esx)["hosted_count"] == 2
    assert lab.get(beta)["hosted_count"] == 1

    on_cluster = make.get(f"/device-groups/{lab.cluster['hid']}/hosted")
    assert [one["item"]["hid"] for one in on_cluster["items"]] == [elsewhere["hid"]]
    assert make.get(f"/device-groups/{lab.cluster['hid']}")["hosted_count"] == 1

    # A retired one is listed only where asked, and is not counted.
    retired = make.post(f"/items/{alpha['hid']}/retire", {"row_version": alpha["row_version"]}, 200)
    assert [one["item"]["hid"] for one in make.get(f"/items/{lab.esx['hid']}/hosted")["items"]] == [
        beta["hid"],
        ctr["hid"],
    ]
    everything = make.get(f"/items/{lab.esx['hid']}/hosted", include_retired="true")
    assert retired["hid"] in [one["item"]["hid"] for one in everything["items"]]
    assert lab.get(lab.esx)["hosted_count"] == 1


def test_every_role_reads_what_runs_on_a_record(lab: Lab, client: TestClient, viewer) -> None:
    lab.vm(host_item_hid=lab.esx["hid"])
    for path in (f"/items/{lab.esx['hid']}/hosted", f"/device-groups/{lab.cluster['hid']}/hosted"):
        assert client.get(API + path, headers=viewer).status_code == 200
    assert client.get(f"{API}/items/{lab.esx['hid']}/hosted").status_code == 401
    missing = "01900000-0000-7000-8000-000000000000"
    assert client.get(f"{API}/items/{missing}/hosted", headers=viewer).status_code == 404


def test_the_command_line_says_what_an_item_runs_on_and_lists_what_runs_on_it(
    lab: Lab, client: TestClient, inventory: dict[str, str], monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.setenv("HIRDIR_TOKEN", inventory["Authorization"].removeprefix("Bearer "))
    vm = lab.vm(host_item_hid=lab.esx["hid"], observed_host_hid=lab.esx2["hid"])
    lab.ctr(host_item_hid=vm["hid"])
    lab.vdc(host_item_hid=lab.n7k["hid"])
    lab.vm("site2-vm-lost")

    shown = runner.invoke(app, ["items", "show", "site2-vm-app01"])
    assert shown.exit_code == 0, shown.output
    assert "runs_on:             site2-esx-01 (item)" in shown.stdout
    assert "seen_on:             site2-esx-02, " in shown.stdout
    assert "not what it runs on" in shown.stdout
    assert "runs_on_it:          1" in shown.stdout
    context = runner.invoke(app, ["items", "show", "site2-n7k-01-vdc2"]).stdout
    assert "serial_number:       JAF0000X001 (host)" in context
    lost = runner.invoke(app, ["items", "show", "site2-vm-lost"]).stdout
    assert "to_review:           it runs on a host, and names none" in lost

    listed = runner.invoke(app, ["items", "hosted", "site2-esx-01"])
    assert listed.exit_code == 0, listed.output
    rows = listed.stdout.splitlines()
    assert rows[0].split()[:3] == ["NAME", "KIND", "STATE"]
    assert rows[1].split()[:2] == ["site2-vm-app01", "virtual_machine"]
    assert rows[2].startswith("  site2-ctr-dns1")
    assert "container" in rows[2]
    nothing = runner.invoke(app, ["items", "hosted", "site2-esx-02"]).stdout
    assert nothing.strip() == "nothing runs on site2-esx-02"
