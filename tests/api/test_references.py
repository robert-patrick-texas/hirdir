"""References (P-158 to P-162): files kept by hirdir and links to files kept elsewhere, on
catalog entries, places, circuits and items; what each record lists, with the records it
stands under; the kinds of file and their limits; erasing; and the store beside the
database."""

import zlib
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.io import store as stores
from tests.api.inventory import API, Maker
from tests.conftest import USERS, sign_in

MB = 1024 * 1024


def png(seed: int = 1) -> bytes:
    """A real PNG picture of eight by eight, of a colour of its own for each seed."""

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


def pdf(text: str = "a guide", padding: int = 0) -> bytes:
    return b"%PDF-1.7\n% " + text.encode() + b"\n%" + b"x" * padding + b"\n%%EOF\n"


class Desk(Maker):
    """A maker who also uploads, downloads and lists references."""

    def upload(
        self,
        content: bytes,
        file_name: str,
        to: list[dict[str, Any]] | dict[str, Any],
        expect: int = 201,
        headers: dict[str, str] | None = None,
        **more: Any,
    ) -> dict[str, Any]:
        records = to if isinstance(to, list) else [to]
        params: dict[str, Any] = {
            "file_name": file_name,
            "attach_to": [record["hid"] for record in records],
            "title": file_name.rsplit(".", 1)[0],
            "kind": "other",
            **more,
        }
        response = self.client.post(
            f"{API}/reference-files",
            params=params,
            content=content,
            headers={**self.headers, **(headers or {})},
        )
        assert response.status_code == expect, response.text
        return response.json()

    def link(self, to: list[dict[str, Any]], expect: int = 201, **more: Any) -> dict[str, Any]:
        body = {
            "title": "Elsewhere",
            "kind": "floor_plan",
            "url": "https://intranet.example.net/plans/b1.pdf",
            "attach_to": [record["hid"] for record in to],
            **more,
        }
        return self.post("/reference-files/links", body, expect)

    def content(self, reference: dict[str, Any], expect: int = 200) -> Any:
        response = self.client.get(
            f"{API}/reference-files/{reference['hid']}/content", headers=self.headers
        )
        assert response.status_code == expect, response.text
        return response

    def listed(self, records: str, record: dict[str, Any]) -> list[dict[str, Any]]:
        return self.get(f"/{records}/{record['hid']}/references", limit=1000)["items"]

    def erase(self, reference: dict[str, Any], expect: int = 204) -> None:
        self.delete(f"/reference-files/{reference['hid']}", expect)


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def places(desk: Desk) -> dict[str, dict[str, Any]]:
    americas = desk.region("Americas")
    central = desk.region("Central", americas)
    site = desk.site("Site-2", central)
    building = desk.location("Building 1", site, kind="building")
    floor = desk.location("Floor 2", site, building, kind="floor")
    rack = desk.location("Rack 4", site, floor, kind="rack")
    return {
        "americas": americas,
        "central": central,
        "site": site,
        "building": building,
        "floor": floor,
        "rack": rack,
    }


# --- uploading and downloading ---------------------------------------------------------


def test_a_file_comes_back_byte_for_byte_as_an_attachment_that_runs_nothing(
    desk: Desk, places: dict
) -> None:
    content = pdf("Floor 2", padding=3 * MB)
    plan = desk.upload(content, "floor-2.pdf", places["floor"], kind="floor_plan", title="Floor 2")
    assert plan["form"] == "file"
    assert plan["media_type"] == "application/pdf"
    assert plan["size_bytes"] == len(content)
    assert plan["shown_in_page"] is False
    assert plan["created_by_name"] == "ivy"
    assert plan["attachments"][0]["label"] == "Americas > Central > Site-2 > Building 1 > Floor 2"
    response = desk.content(plan)
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith('attachment; filename="floor-2.pdf"')
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "content-encoding" not in response.headers


def test_a_picture_is_shown_in_the_page_and_the_page_may_show_it(
    client: TestClient, desk: Desk, places: dict
) -> None:
    photo = desk.upload(png(), "rack-4.png", places["rack"], kind="photograph")
    assert photo["shown_in_page"] is True
    page = client.get("/")
    assert "img-src 'self' blob:" in page.headers["content-security-policy"]


def test_a_name_with_letters_of_any_alphabet_is_kept_and_sent_back_written_out(
    desk: Desk, places: dict
) -> None:
    plan = desk.upload(pdf(), "Étage 2 ½ plan.pdf", places["floor"])
    assert plan["file_name"] == "Étage 2 ½ plan.pdf"
    disposition = desk.content(plan).headers["content-disposition"]
    assert "filename*=UTF-8''%C3%89tage%202%20%C2%BD%20plan.pdf" in disposition


def test_a_directory_sent_with_a_name_is_left_out(desk: Desk, places: dict) -> None:
    plan = desk.upload(pdf(), "C:\\plans\\..\\floor-2.pdf", places["floor"])
    assert plan["file_name"] == "floor-2.pdf"


def test_the_same_content_twice_on_a_record_is_refused_and_on_another_record_is_kept_once(
    desk: Desk, places: dict, config: Config
) -> None:
    content = pdf("twice")
    first = desk.upload(content, "a.pdf", places["floor"])
    refused = desk.upload(content, "b.pdf", places["floor"], expect=409)
    assert first["hid"] in refused["errors"][0]["message"]
    other = desk.upload(content, "c.pdf", places["rack"])
    assert other["sha256"] == first["sha256"]
    assert list(stores.Store(config.files_dir).contents()) == [first["sha256"]]
    # Erasing one keeps the content the other holds.
    desk.erase(first)
    assert desk.content(other).content == content


def test_an_upload_takes_no_idempotency_key(desk: Desk, places: dict) -> None:
    refused = desk.upload(
        pdf(), "a.pdf", places["floor"], expect=422, headers={"Idempotency-Key": "upload-1"}
    )
    assert "Idempotency-Key" in str(refused)


def test_an_upload_names_records_that_take_references(desk: Desk) -> None:
    vendor = desk.vendor()
    refused = desk.upload(pdf(), "a.pdf", vendor, expect=422)
    assert refused["errors"][0]["field"] == "attach_to"
    assert desk.get("/reference-files")["total"] == 0


@pytest.mark.parametrize(
    ("content", "name", "says"),
    [
        (b"MZ\x90\x00" + b"\x00" * 60, "tool.exe", "never taken"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "plan.svg", "never taken"),
        (b"<html><script>alert(1)</script></html>", "plan.htm", "never taken"),
        (b"<!DOCTYPE html><html></html>", "plan.png", "a web page"),
        (b"\x7fELF\x02\x01\x01", "notes.txt", "a program"),
        (b"PK\x03\x04 not really", "guide.pdf", "not a PDF"),
        (pdf(), "photo.jpg", "not a JPEG picture"),
        (b"text\x00with a zero byte", "notes.txt", "not a text file"),
        (pdf(), "guide", "with no extension"),
        (pdf(), "guide.pdf2", "not taken"),
        (b"", "empty.pdf", "empty"),
    ],
)
def test_a_kind_that_is_not_taken_and_content_that_is_not_what_it_says_are_refused(
    desk: Desk, places: dict, content: bytes, name: str, says: str
) -> None:
    refused = desk.upload(content, name, places["floor"], expect=422)
    assert says in str(refused)
    assert desk.get("/reference-files")["total"] == 0


def test_an_admin_chooses_the_kinds_of_file_but_never_a_program(
    client: TestClient, admin: dict[str, str], desk: Desk, places: dict
) -> None:
    setting = client.get(f"{API}/settings", headers=admin).json()
    types = next(one for one in setting if one["key"] == "reference_file_types")
    assert "pdf" in types["value"]
    assert "exe" not in types["value"]
    refused = next(one for one in setting if one["key"] == "refused_file_types")
    assert refused["fixed"] is True
    assert "svg" in refused["value"]

    def put(value: list[str], expect: int) -> None:
        current = client.get(f"{API}/settings", headers=admin).json()
        version = next(o for o in current if o["key"] == "reference_file_types")
        response = client.put(
            f"{API}/settings/reference_file_types",
            json={"value": value, "row_version": version["row_version"]},
            headers=admin,
        )
        assert response.status_code == expect, response.text

    put(["pdf", "exe"], 422)
    put(["pdf", ".PCAP"], 200)
    capture = desk.upload(b"\xd4\xc3\xb2\xa1 packets", "trace.pcap", places["rack"])
    assert capture["media_type"] == "application/octet-stream"
    desk.upload(png(), "rack.png", places["rack"], expect=422)
    # What is kept stays as it was.
    assert desk.content(capture).content.startswith(b"\xd4\xc3")


@pytest.fixture
def small(config: Config) -> Iterator[TestClient]:
    """An application whose limits are 1 MB for an import and 2 MB for a reference file."""
    limited = replace(config, max_file_megabytes=1, max_reference_megabytes=2)
    from hirdir.db.engine import make_engine, make_sessions
    from hirdir.domain import accounts, audit

    engine = make_engine(limited.database_url)
    with make_sessions(engine)() as session:
        for name, code, role in USERS:
            user, _ = accounts.create_user(session, audit.SYSTEM, username=name, access_code=code)
            accounts.grant_role(session, audit.SYSTEM, role=role, user_hid=user.hid)
        session.commit()
    engine.dispose()
    app = create_app(limited)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def test_a_reference_file_may_be_larger_than_an_import_and_no_larger_than_its_own_limit(
    small: TestClient,
) -> None:
    desk = Desk(small, sign_in(small, "ivy", "inventory-code"))
    site = desk.site("Site-2", desk.region("Americas"))
    kept = desk.upload(pdf(padding=int(1.5 * MB)), "big.pdf", site)
    assert kept["size_bytes"] > MB
    over = desk.upload(pdf(padding=2 * MB), "huge.pdf", site, expect=413)
    assert "2 MB" in over["detail"]
    # Any other body is held to the limit of an import.
    body = b"name,serial_number\n" + b"x," * (MB // 2) + b"\n"
    response = small.post(
        f"{API}/imports/preview",
        params={"entity": "items"},
        content=body,
        headers={**desk.headers, "Content-Type": "text/csv"},
    )
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    # Nothing of the refused upload is left in the store.
    files = cast(Any, small.app).state.config.files_dir
    assert list((files / stores.INCOMING).iterdir()) == []


# --- links ---------------------------------------------------------------------------


def test_a_link_has_an_address_and_no_content(desk: Desk, places: dict) -> None:
    link = desk.link([places["building"]], title="Building 1 plans")
    assert link["form"] == "link"
    assert link["url"] == "https://intranet.example.net/plans/b1.pdf"
    assert link["file_name"] is None
    assert link["sha256"] is None
    assert "no content" in str(desk.content(link, 422).json())
    changed = desk.patch(
        f"/reference-files/{link['hid']}",
        {"url": "https://intranet.example.net/plans/b1-2027.pdf", "row_version": 1},
    )
    assert changed["url"].endswith("b1-2027.pdf")
    assert changed["row_version"] == 2
    desk.link([places["building"]], 422, url="file:///etc/passwd")
    desk.link([places["building"]], 422, url="https://intranet.example.net/a plan.pdf")


def test_a_file_has_no_address_and_is_changed_by_a_new_edition(desk: Desk, places: dict) -> None:
    plan = desk.upload(pdf(), "plan.pdf", places["floor"])
    desk.patch(
        f"/reference-files/{plan['hid']}", {"url": "https://example.net/x", "row_version": 1}, 422
    )
    changed = desk.patch(
        f"/reference-files/{plan['hid']}",
        {"title": "Floor 2, east", "kind": "floor_plan", "row_version": 1},
    )
    assert (changed["title"], changed["kind"], changed["row_version"]) == (
        "Floor 2, east",
        "floor_plan",
        2,
    )
    desk.patch(f"/reference-files/{plan['hid']}", {"title": "again", "row_version": 1}, 409)
    desk.patch(f"/reference-files/{plan['hid']}", {"kind": "no-such-kind", "row_version": 2}, 422)
    desk.patch(f"/reference-files/{plan['hid']}", {"title": "<b>", "row_version": 2}, 422)


# --- what a record lists -------------------------------------------------------------


def test_a_place_lists_its_own_then_those_of_each_place_above_nearest_first(
    desk: Desk, places: dict
) -> None:
    rack, floor, site, americas = (places[k] for k in ("rack", "floor", "site", "americas"))
    photo = desk.upload(png(1), "rack.png", rack, kind="photograph", title="B")
    other = desk.upload(png(2), "rack-back.png", rack, kind="photograph", title="A")
    plan = desk.upload(pdf("floor"), "floor.pdf", floor, kind="floor_plan")
    site_map = desk.upload(pdf("site"), "site.pdf", site, kind="map")
    region_map = desk.link([americas], kind="map", title="Americas")
    listed = desk.listed("locations", rack)
    assert [(one["hid"], one["source"]) for one in listed] == [
        (other["hid"], "own"),
        (photo["hid"], "own"),
        (plan["hid"], "location"),
        (site_map["hid"], "site"),
        (region_map["hid"], "region"),
    ]
    assert listed[2]["source_label"] == "Americas > Central > Site-2 > Building 1 > Floor 2"
    assert listed[2]["source_hid"] == floor["hid"]
    # A place above lists none of those below; nothing is copied down.
    assert [one["hid"] for one in desk.listed("sites", site)] == [
        site_map["hid"],
        region_map["hid"],
    ]
    assert [one["hid"] for one in desk.listed("regions", places["central"])] == [region_map["hid"]]
    # One on two levels is listed once, at the nearer.
    desk.post(f"/reference-files/{site_map['hid']}/attachments", {"records": [floor["hid"]]}, 200)
    sources = {one["hid"]: one["source"] for one in desk.listed("locations", rack)}
    assert sources[site_map["hid"]] == "location"
    # Paged.
    page = desk.get(f"/locations/{rack['hid']}/references", limit=2, offset=1)
    assert page["total"] == 5
    assert [one["hid"] for one in page["items"]] == [
        photo["hid"],
        plan["hid"],
    ]


def test_an_item_lists_its_own_then_its_models_then_those_of_where_it_is(
    desk: Desk, places: dict
) -> None:
    entry = desk.entry(desk.vendor())
    switch = desk.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW0000X001",
        location_hid=places["rack"]["hid"],
    )
    module = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW0000X002", parent_item_hid=switch["hid"]
    )
    labels = desk.upload(png(), "labels.png", switch, kind="photograph")
    guide = desk.upload(pdf("guide"), "guide.pdf", entry, kind="administration_guide")
    plan = desk.upload(pdf("floor"), "floor.pdf", places["floor"], kind="floor_plan")
    assert [(one["hid"], one["source"]) for one in desk.listed("items", switch)] == [
        (labels["hid"], "own"),
        (guide["hid"], "catalog"),
        (plan["hid"], "location"),
    ]
    # A minor item is where the item it is in is, and lists that place's.
    assert [(one["hid"], one["source"]) for one in desk.listed("items", module)] == [
        (guide["hid"], "catalog"),
        (plan["hid"], "location"),
    ]
    assert [one["hid"] for one in desk.listed("catalog-entries", entry)] == [guide["hid"]]


def test_a_circuit_lists_its_own(desk: Desk, places: dict) -> None:
    circuit = desk.post(
        "/circuits",
        {"name": "Site-2 internet", "a_location_hid": places["rack"]["hid"], "z_note": "carrier"},
    )
    authorization = desk.upload(pdf("LOA"), "loa.pdf", circuit, kind="letter_of_authorization")
    assert [one["hid"] for one in desk.listed("circuits", circuit)] == [authorization["hid"]]
    desk.get("/circuits/0193a1f4-0000-7000-8000-000000000000/references", expect=404)


# --- many records, editions, taking off and erasing ----------------------------------


def test_a_guide_on_several_models_and_a_new_edition_on_all_of_them(
    desk: Desk, config: Config
) -> None:
    vendor = desk.vendor()
    entries = [desk.entry(vendor, pid) for pid in ("C9300-24P", "C9300-48P", "C9300-24UX")]
    guide = desk.upload(pdf("first"), "guide.pdf", entries[:2], kind="administration_guide")
    assert guide["attachment_count"] == 2
    again = desk.post(
        f"/reference-files/{guide['hid']}/attachments",
        {"records": [entries[1]["hid"], entries[2]["hid"]]},
        200,
    )
    assert again["attachment_count"] == 3
    first = guide["sha256"]
    edition = pdf("second edition")
    response = desk.client.put(
        f"{API}/reference-files/{guide['hid']}/content",
        params={"file_name": "guide-2.pdf", "row_version": again["row_version"]},
        content=edition,
        headers=desk.headers,
    )
    assert response.status_code == 200, response.text
    replaced = response.json()
    assert (replaced["hid"], replaced["file_name"], replaced["attachment_count"]) == (
        guide["hid"],
        "guide-2.pdf",
        3,
    )
    for entry in entries:
        assert desk.content(desk.listed("catalog-entries", entry)[0]).content == edition
    # The first edition is erased.
    assert not stores.Store(config.files_dir).has(first)
    # A stale version is refused, and a link has no edition.
    stale = desk.client.put(
        f"{API}/reference-files/{guide['hid']}/content",
        params={"file_name": "guide-3.pdf", "row_version": again["row_version"]},
        content=pdf("third"),
        headers=desk.headers,
    )
    assert stale.status_code == 409


def test_taken_off_the_last_record_a_reference_is_erased_with_its_content(
    client: TestClient, admin: dict[str, str], desk: Desk, places: dict, config: Config
) -> None:
    plan = desk.upload(pdf("plan"), "plan.pdf", [places["floor"], places["rack"]])
    floor_link, rack_link = plan["attachments"]
    response = client.delete(
        f"{API}/reference-files/{plan['hid']}/attachments/{floor_link['hid']}", headers=desk.headers
    )
    assert response.json() == {"erased": False}
    assert desk.listed("locations", places["floor"]) == []
    response = client.delete(
        f"{API}/reference-files/{plan['hid']}/attachments/{rack_link['hid']}", headers=desk.headers
    )
    assert response.json() == {"erased": True}
    desk.get(f"/reference-files/{plan['hid']}", expect=404)
    assert not stores.Store(config.files_dir).has(plan["sha256"])
    events = client.get(
        f"{API}/audit-events", params={"record_hid": plan["hid"]}, headers=admin
    ).json()["items"]
    assert [event["action"] for event in events] == ["erase", "detach", "create"]
    erased = {change["field"]: change["old"] for change in events[0]["changes"]}
    assert erased["file_name"] == "plan.pdf"
    assert erased["sha256"] == plan["sha256"]
    assert erased["size_bytes"] == plan["size_bytes"]
    assert [one["record_hid"] for one in erased["records"]] == [places["rack"]["hid"]]


def test_erasing_takes_a_reference_from_every_record_at_once(
    desk: Desk, places: dict, config: Config
) -> None:
    plan = desk.upload(pdf("plan"), "plan.pdf", [places["floor"], places["rack"], places["site"]])
    desk.erase(plan)
    for records, record in (("locations", places["floor"]), ("sites", places["site"])):
        assert desk.listed(records, record) == []
    assert list(stores.Store(config.files_dir).contents()) == []
    desk.erase(plan, 404)


def test_a_view_only_user_reads_and_downloads_and_changes_nothing(
    client: TestClient, viewer: dict[str, str], desk: Desk, places: dict
) -> None:
    plan = desk.upload(pdf("plan"), "plan.pdf", places["floor"])
    looker = Desk(client, viewer)
    assert looker.content(plan).content == pdf("plan")
    assert looker.get("/reference-files")["total"] == 1
    looker.upload(pdf("other"), "other.pdf", places["floor"], expect=403)
    looker.link([places["floor"]], 403)
    looker.patch(f"/reference-files/{plan['hid']}", {"title": "x", "row_version": 1}, 403)
    looker.post(
        f"/reference-files/{plan['hid']}/attachments", {"records": [places["rack"]["hid"]]}, 403
    )
    looker.delete(
        f"/reference-files/{plan['hid']}/attachments/{plan['attachments'][0]['hid']}", 403
    )
    looker.erase(plan, 403)
    response = client.put(
        f"{API}/reference-files/{plan['hid']}/content",
        params={"file_name": "x.pdf", "row_version": 1},
        content=pdf("x"),
        headers=viewer,
    )
    assert response.status_code == 403


def test_a_download_is_audited_and_leaves_the_kept_answers_good(
    client: TestClient, admin: dict[str, str], desk: Desk, places: dict
) -> None:
    from hirdir.io import kept

    plan = desk.upload(pdf("plan"), "plan.pdf", places["floor"])
    app = cast(Any, client.app)
    with app.state.sessions() as db:
        before = kept.stamp(db)
    desk.content(plan)
    with app.state.sessions() as db:
        assert kept.stamp(db) == before
    events = client.get(
        f"{API}/audit-events",
        params={"record_hid": plan["hid"], "action": "download"},
        headers=admin,
    ).json()["items"]
    assert len(events) == 1
    assert events[0]["actor_name"] == "ivy"


def test_content_missing_from_the_store_says_so(desk: Desk, places: dict, config: Config) -> None:
    plan = desk.upload(pdf("plan"), "plan.pdf", places["floor"])
    stores.Store(config.files_dir).path_of(plan["sha256"]).unlink()
    assert desk.get(f"/reference-files/{plan['hid']}")["content_missing"] is True
    assert "missing" in desk.content(plan, 404).json()["detail"]


def test_the_list_of_every_reference_is_sorted_and_narrowed(desk: Desk, places: dict) -> None:
    desk.upload(pdf("b", padding=3000), "b.pdf", places["floor"], title="Bravo", kind="floor_plan")
    desk.upload(png(), "a.png", [places["floor"], places["rack"]], title="alpha", kind="photograph")
    desk.link([places["site"]], title="Charlie", kind="map")
    titles = [one["title"] for one in desk.get("/reference-files")["items"]]
    assert titles == ["alpha", "Bravo", "Charlie"]
    by_size = desk.get("/reference-files", sort="-size_bytes")["items"]
    assert [one["title"] for one in by_size][:2] == ["Bravo", "alpha"]
    by_count = desk.get("/reference-files", sort="-attachment_count")["items"]
    assert by_count[0]["title"] == "alpha"
    assert [one["title"] for one in desk.get("/reference-files", form="link")["items"]] == [
        "Charlie"
    ]
    assert [one["title"] for one in desk.get("/reference-files", kind="photograph")["items"]] == [
        "alpha"
    ]
    assert [one["title"] for one in desk.get("/reference-files", title="RAV")["items"]] == ["Bravo"]
    desk.get("/reference-files", expect=422, sort="no_such_field")


# --- the store ------------------------------------------------------------------------


def test_the_store_sweeps_what_an_upload_left_and_content_nobody_names(
    db: Any, config: Config
) -> None:
    store = stores.Store(config.files_dir)
    left = store.receive(MB)
    left.write(b"cut short")
    named_by_none = store.receive_bytes(pdf("stray"), MB)
    sha256 = store.keep(named_by_none)
    young = store.receive_bytes(pdf("young"), MB)
    young_sha = store.keep(young)
    old = store.path_of(sha256)
    import os

    os.utime(old, (0, 0))
    parts, strays = store.sweep(db)
    assert (parts, strays) == (1, 1)
    assert not store.has(sha256)
    assert store.has(young_sha)
    left.discard()
