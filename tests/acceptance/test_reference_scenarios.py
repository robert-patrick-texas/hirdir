"""Scenarios S51 to S53 of docs/build-plan.md, against a real server process: a
photograph and a floor plan on a location, downloaded byte for byte and read by a
View-only user who cannot upload; an administration guide on a model, reached from every
item of it with no request leaving the server; and a file over the limit and one of a
kind that is not taken refused, then the files backed up and restored byte for byte on a
clean install."""

import shutil
import zlib
from pathlib import Path
from typing import Any

import httpx2
import pytest

from tests.acceptance.conftest import ADMIN, Server, configured, started
from tests.acceptance.test_geography_scenarios import Geography
from tests.acceptance.test_item_scenarios import IVY

MB = 1024 * 1024


def _png(seed: int) -> bytes:
    """A small picture of one colour, a real PNG of its own for each seed."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = (8).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    rows = b"".join(b"\x00" + bytes([seed % 256, 80, 160]) * 8 for _ in range(8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _pdf(text: str, padding: int = 0) -> bytes:
    """A small PDF that says text, with padding bytes of a comment to make it larger."""
    return b"%PDF-1.7\n% " + text.encode() + b"\n%" + b"x" * padding + b"\n%%EOF\n"


class Desk(Geography):
    """A signed-in person who uploads, lists and downloads references."""

    def upload(
        self, content: bytes, file_name: str, attach_to: list[str], expect: int = 201, **more: Any
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"file_name": file_name, "attach_to": attach_to, **more}
        params.setdefault("title", file_name.rsplit(".", 1)[0])
        response = self.client.post(
            "/reference-files",
            params=params,
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == expect, response.text
        return response.json()

    def download(self, reference: dict[str, Any]) -> httpx2.Response:
        response = self.client.get(f"/reference-files/{reference['hid']}/content")
        assert response.status_code == 200, response.text
        return response

    def listed(self, records: str, record: dict[str, Any]) -> list[dict[str, Any]]:
        return self.get(f"/{records}/{record['hid']}/references", limit=1000)["items"]


def _person(server: Server, name: str, code: str, role: str) -> Desk:
    admin = server.sign_in(*ADMIN)
    made = admin.post("/users", json={"username": name, "access_code": code, "role": role})
    assert made.status_code == 201, made.text
    return Desk(server.sign_in(name, code))


@pytest.fixture
def desk(server: Server) -> Desk:
    return _person(server, *IVY, "inventory")


def test_s51_a_photograph_and_a_floor_plan_on_a_location_come_back_byte_for_byte(
    server: Server, desk: Desk
) -> None:
    places = desk.layout()
    room = places["room"]
    photo_bytes, plan_bytes = _png(1), _pdf("Room 102, floor plan")
    photo = desk.upload(
        photo_bytes, "room-102.png", [room["hid"]], kind="photograph", title="Room 102 rack row"
    )
    plan = desk.upload(
        plan_bytes, "room-102-plan.pdf", [room["hid"]], kind="floor_plan", title="Room 102 plan"
    )

    listed = {entry["hid"]: entry for entry in desk.listed("locations", room)}
    assert listed[photo["hid"]]["title"] == "Room 102 rack row"
    assert listed[photo["hid"]]["kind"] == "photograph"
    assert listed[photo["hid"]]["source"] == "own"
    assert listed[photo["hid"]]["shown_in_page"] is True
    assert listed[plan["hid"]]["title"] == "Room 102 plan"
    assert listed[plan["hid"]]["kind"] == "floor_plan"
    assert listed[plan["hid"]]["shown_in_page"] is False

    for reference, content, media_type in (
        (photo, photo_bytes, "image/png"),
        (plan, plan_bytes, "application/pdf"),
    ):
        response = desk.download(reference)
        assert response.content == content
        assert response.headers["content-type"].startswith(media_type)
        assert response.headers["content-disposition"].startswith("attachment")
        assert "sandbox" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"

    # The building above the room lists neither; the room lists both as its own.
    assert desk.listed("locations", places["building"]) == []

    # A View-only user downloads both, and cannot upload, change or erase one.
    viewer = _person(server, "vic", "acceptance-viewer", "viewer")
    assert {entry["hid"] for entry in viewer.listed("locations", room)} == {
        photo["hid"],
        plan["hid"],
    }
    assert viewer.download(photo).content == photo_bytes
    assert viewer.download(plan).content == plan_bytes
    viewer.upload(_png(2), "other.png", [room["hid"]], expect=403, kind="photograph")
    refused = viewer.client.patch(
        f"/reference-files/{plan['hid']}", json={"title": "x", "row_version": plan["row_version"]}
    )
    assert refused.status_code == 403
    assert viewer.client.delete(f"/reference-files/{plan['hid']}").status_code == 403
    assert desk.download(plan).content == plan_bytes

    # Each upload and each download is in the audit trail.
    events = server.sign_in(*ADMIN).get("/audit-events", params={"limit": 1000}).json()["items"]
    actions = [
        (e["action"], e["record_hid"]) for e in events if e["record_type"] == "reference_file"
    ]
    assert ("create", photo["hid"]) in actions
    assert ("create", plan["hid"]) in actions
    assert actions.count(("download", plan["hid"])) == 3


def test_s52_an_administration_guide_on_a_model_is_reached_from_every_item_of_it(
    desk: Desk,
) -> None:
    entry = desk.entry("C9300-48P")
    other = desk.entry("C9300-24P")
    items = [
        desk.post("/items", {"catalog_entry_hid": entry["hid"], "serial_number": f"FCW0000X10{n}"})
        for n in (1, 2, 3)
    ]
    outsider = desk.post(
        "/items", {"catalog_entry_hid": other["hid"], "serial_number": "FCW0000X200"}
    )
    content = _pdf("Catalyst 9300 administration guide")
    guide = desk.upload(
        content,
        "c9300-admin.pdf",
        [entry["hid"]],
        kind="administration_guide",
        title="Catalyst 9300 administration guide",
    )
    assert guide["form"] == "file"
    assert guide["url"] is None

    for item in items:
        listed = desk.listed("items", item)
        assert [one["hid"] for one in listed] == [guide["hid"]]
        assert listed[0]["source"] == "catalog"
        assert listed[0]["source_hid"] == entry["hid"]
        # The way to it is a route of this server, and its content comes from here.
        response = desk.client.get(f"/reference-files/{listed[0]['hid']}/content")
        assert response.status_code == 200
        assert response.url.host == "127.0.0.1"
        assert response.content == content
    assert desk.listed("items", outsider) == []

    # Put on the second model too, it is one reference on two; a new edition is on both.
    desk.post(f"/reference-files/{guide['hid']}/attachments", {"records": [other["hid"]]}, 200)
    assert [one["hid"] for one in desk.listed("items", outsider)] == [guide["hid"]]
    edition = _pdf("Catalyst 9300 administration guide, second edition")
    replaced = desk.client.put(
        f"/reference-files/{guide['hid']}/content",
        params={"file_name": "c9300-admin-2.pdf", "row_version": guide["row_version"]},
        content=edition,
    )
    assert replaced.status_code == 200, replaced.text
    for item in (*items, outsider):
        assert desk.download(desk.listed("items", item)[0]).content == edition


def test_s53_too_large_and_not_allowed_are_refused_and_a_restore_brings_every_file_back(
    server: Server, desk: Desk, tmp_path: Path
) -> None:
    places = desk.layout()
    room = places["room"]

    # The limit is 100 MB; a file one byte over it is refused, and says so.
    over = desk.upload(
        _pdf("too large", padding=100 * MB), "huge.pdf", [room["hid"]], expect=413, kind="other"
    )
    assert "100 MB" in over["detail"]
    # A program is not a kind that is taken, and neither is a web page named as a picture.
    program = desk.upload(
        b"MZ\x90\x00" + b"\x00" * 64, "tool.exe", [room["hid"]], 422, kind="other"
    )
    assert "exe" in str(program)
    page = desk.upload(
        b"<html><script></script></html>", "plan.png", [room["hid"]], 422, kind="map"
    )
    assert "web page" in str(page)
    assert desk.listed("locations", room) == []

    kept = {
        "room-102.png": (_png(3), "photograph", room),
        "site-2-map.pdf": (_pdf("Site-2 map"), "map", places["site"]),
        "building-1.pdf": (_pdf("Building 1", padding=2 * MB), "floor_plan", places["building"]),
    }
    uploaded = {
        name: desk.upload(content, name, [record["hid"]], kind=kind)
        for name, (content, kind, record) in kept.items()
    }
    # The room lists its own, then the building's, then the site's.
    assert [one["source"] for one in desk.listed("locations", room)] == ["own", "location", "site"]

    backup = Path(server.admin("backup").strip())
    assert backup.is_file()

    # A clean install: the backup and the files beside it are copied there, and restored.
    clean = configured(tmp_path / "clean")
    backups = tmp_path / "clean" / "backups"
    backups.mkdir()
    shutil.copy2(backup, backups / backup.name)
    shutil.copytree(backup.parent / "files", backups / "files")
    clean.admin("restore", str(backups / backup.name))
    with started(tmp_path / "clean", first_admin=False) as restored:
        person = Desk(restored.sign_in(*IVY))
        for name, (content, _kind, _record) in kept.items():
            response = person.client.get(f"/reference-files/{uploaded[name]['hid']}/content")
            assert response.status_code == 200, response.text
            assert response.content == content
        assert [one["hid"] for one in person.listed("locations", room)] == [
            uploaded["room-102.png"]["hid"],
            uploaded["building-1.pdf"]["hid"],
            uploaded["site-2-map.pdf"]["hid"],
        ]
