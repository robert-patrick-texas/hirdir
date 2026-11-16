"""The reference commands of the command line (P-162), run against the application itself."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api import test_cli
from tests.api.test_references import Desk, pdf, png

# The fixture that runs `hirdir` against the test client.
run = test_cli.run
ROOM = "Americas > Central > Site-2 > Building 1 > Room 102"


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def laid_out(desk: Desk, tmp_path: Path) -> dict[str, Any]:
    central = desk.region("Central", desk.region("Americas"))
    site = desk.site("Site-2", central)
    building = desk.location("Building 1", site, kind="building")
    room = desk.location("Room 102", site, building, kind="room")
    cisco = desk.vendor("Cisco")
    small, large = desk.entry(cisco, "C9300-24P"), desk.entry(cisco, "C9300-48P")
    switch = desk.item(
        catalog_entry_hid=large["hid"], serial_number="FCW0000X001", location_hid=room["hid"]
    )
    files = tmp_path / "files"
    files.mkdir()
    for name, content in (
        ("rack-1.png", png(1)),
        ("rack-2.png", png(2)),
        ("plan.pdf", pdf("plan")),
        ("guide.pdf", pdf("guide")),
        ("guide-2.pdf", pdf("guide, second edition")),
        ("tool.exe", b"MZ\x90\x00" + b"\x00" * 60),
    ):
        (files / name).write_bytes(content)
    return {
        "room": room,
        "building": building,
        "switch": switch,
        "small": small,
        "large": large,
        "files": files,
    }


def test_files_are_added_listed_downloaded_and_one_refused_leaves_the_others(
    run, desk: Desk, laid_out: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = laid_out["files"]
    said = run(
        "references",
        "add",
        str(files / "rack-1.png"),
        str(files / "tool.exe"),
        str(files / "rack-2.png"),
        "--to",
        f"location:{ROOM}",
        "--kind",
        "photograph",
        expect=4,
    )
    assert "rack-1.png:" in said.output
    assert "rack-2.png:" in said.output
    assert "tool.exe: refused" in said.output
    run(
        "references",
        "add",
        str(files / "plan.pdf"),
        "--to",
        "location:Americas > Central > Site-2 > Building 1",
        "--kind",
        "floor_plan",
        "--title",
        "Building 1 plan",
    )
    listed = run("references", "list", "--of", f"location:{ROOM}").output
    assert "rack-1" in listed
    assert "rack-2" in listed
    assert "Building 1 plan" in listed
    assert "location: Americas > Central > Site-2 >" in listed
    plan = desk.listed("locations", laid_out["building"])[0]
    monkeypatch.chdir(tmp_path)
    run("references", "get", plan["hid"], "--output", "copy.pdf")
    assert (tmp_path / "copy.pdf").read_bytes() == pdf("plan")
    run("references", "get", plan["hid"], "--output", "copy.pdf", expect=2)
    shown = run("references", "show", plan["hid"]).output
    assert "on:              location: Americas > Central > Site-2 > Building 1" in shown


def test_a_guide_on_two_models_gets_a_new_edition_and_is_taken_off_and_erased(
    run, desk: Desk, laid_out: dict
) -> None:
    files = laid_out["files"]
    run(
        "references",
        "add",
        str(files / "guide.pdf"),
        "--to",
        "model:Cisco C9300-24P",
        "--to",
        "model:C9300-48P",
        "--kind",
        "administration_guide",
    )
    guide = desk.listed("catalog-entries", laid_out["small"])[0]
    assert guide["attachment_count"] == 2
    # The item of the larger model reaches it, from its model.
    on_item = run("references", "list", "--of", "item:FCW0000X001").output
    assert "guide" in on_item
    assert "catalog: Cisco C9300-48P" in on_item
    said = run("references", "replace", guide["hid"], str(files / "guide-2.pdf")).output
    assert "now guide-2.pdf" in said
    assert "on 2 records" in said
    assert desk.content(guide).content == pdf("guide, second edition")
    run("references", "set", guide["hid"], "title=Catalyst 9300 guide")
    assert desk.get(f"/reference-files/{guide['hid']}")["title"] == "Catalyst 9300 guide"
    run("references", "detach", guide["hid"], "--from", "model:Cisco C9300-24P")
    assert desk.listed("catalog-entries", laid_out["small"]) == []
    assert (
        "erased"
        in run("references", "detach", guide["hid"], "--from", "model:C9300-48P", "--yes").output
    )
    desk.get(f"/reference-files/{guide['hid']}", expect=404)


def test_a_link_is_made_attached_and_removed(run, desk: Desk, laid_out: dict) -> None:
    run(
        "references",
        "link",
        "https://intranet.example.net/site-2/b1.pdf",
        "--to",
        f"location:{ROOM}",
        "--kind",
        "floor_plan",
        "--title",
        "Building 1, as built",
    )
    link = desk.listed("locations", laid_out["room"])[0]
    run("references", "attach", link["hid"], "--to", "item:FCW0000X001")
    assert desk.get(f"/reference-files/{link['hid']}")["attachment_count"] == 2
    run("references", "get", link["hid"], expect=4)
    run("references", "remove", link["hid"], "--yes")
    assert desk.listed("locations", laid_out["room"]) == []
    run("references", "list", "--of", "vendor:Cisco", expect=2)
    run("references", "list", "--of", "nothing", expect=2)
