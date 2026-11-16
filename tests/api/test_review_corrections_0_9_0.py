"""What the review of the server of 0.9.0 found: a new edition refused as stale that left
its content in the store, an upload with a service token that held the one writer while
its body arrived, a body sent in chunks over the limit answered 500, a kind made inactive
that a reference could not keep, a download cut short by an erasure, and a command that
printed refusals of its own while it looked for a record named by its HID."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.domain import accounts, audit
from hirdir.domain import references as refs
from hirdir.domain.errors import StaleVersion
from hirdir.io import store as stores
from tests.api import test_cli
from tests.api.inventory import API
from tests.api.test_references import MB, Desk, pdf
from tests.conftest import USERS, sign_in

run = test_cli.run


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def floor(desk: Desk) -> dict[str, Any]:
    site = desk.site("Site-2", desk.region("Americas"))
    return desk.location("Floor 2", site, kind="floor")


def test_a_new_edition_refused_as_stale_leaves_no_content_that_nothing_names(
    client: TestClient, desk: Desk, floor: dict
) -> None:
    plan = desk.upload(pdf("first"), "plan.pdf", floor)
    app = cast(Any, client.app)
    store: stores.Store = app.state.store
    with app.state.sessions() as second:
        # A second request read the reference at version 1 and holds it, and a change
        # is stored before its new edition is.
        held = refs.get(second, plan["hid"])
        assert held.row_version == 1
        desk.patch(f"/reference-files/{plan['hid']}", {"title": "Floor 2, east", "row_version": 1})
        edition = store.receive_bytes(pdf("second edition"), MB)
        with pytest.raises(StaleVersion):
            refs.replace_content(
                second, audit.SYSTEM, store, plan["hid"], edition, file_name="b.pdf", row_version=1
            )
        second.rollback()
        edition.discard()
        del held
    assert set(store.contents()) == {plan["sha256"]}


def _writer_let_in(config: Config) -> str:
    other = sqlite3.connect(str(config.database_path), timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")
        return "let in"
    except sqlite3.OperationalError as error:
        return f"held up: {error}"
    finally:
        other.close()


def test_an_upload_with_a_service_token_holds_no_writer_while_its_body_arrives(
    client: TestClient, admin: dict[str, str], floor: dict, config: Config
) -> None:
    created = client.post(
        f"{API}/users",
        headers=admin,
        json={"username": "svc-scanner", "is_service_account": True, "role": "inventory"},
    ).json()
    made = client.post(
        f"{API}/users/{created['user']['hid']}/service-tokens", headers=admin, json={"name": "x"}
    ).json()
    seen: list[str] = []

    def body() -> Iterator[bytes]:
        seen.append(_writer_let_in(config))
        yield pdf("scan")

    response = client.post(
        f"{API}/reference-files",
        params={
            "file_name": "scan.pdf",
            "attach_to": [floor["hid"]],
            "title": "S",
            "kind": "other",
        },
        content=body(),
        headers={"Authorization": f"Bearer {made['secret']}"},
    )
    assert response.status_code == 201, response.text
    assert seen == ["let in"]


@pytest.fixture
def small(config: Config) -> Iterator[TestClient]:
    limited = replace(config, max_file_megabytes=1, max_reference_megabytes=1)
    from hirdir.db.engine import make_engine, make_sessions

    engine = make_engine(limited.database_url)
    with make_sessions(engine)() as session:
        for name, code, role in USERS:
            user, _ = accounts.create_user(session, audit.SYSTEM, username=name, access_code=code)
            accounts.grant_role(session, audit.SYSTEM, role=role, user_hid=user.hid)
        session.commit()
    engine.dispose()
    app = create_app(limited)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.state.engine.dispose()


def test_an_upload_sent_in_chunks_over_the_limit_is_a_413(small: TestClient) -> None:
    desk = Desk(small, sign_in(small, "ivy", "inventory-code"))
    site = desk.site("Site-2", desk.region("Americas"))

    def body() -> Iterator[bytes]:
        yield pdf(padding=2 * MB)

    response = small.post(
        f"{API}/reference-files",
        params={
            "file_name": "big.pdf",
            "attach_to": [site["hid"]],
            "title": "Big",
            "kind": "other",
        },
        content=body(),
        headers=desk.headers,
    )
    assert response.status_code == 413, response.text


def test_an_upload_goes_on_a_hundred_records_at_most_and_more_go_by_attaching(
    desk: Desk,
) -> None:
    vendor = desk.vendor()
    entries = [desk.entry(vendor, f"C9300-{n:03d}") for n in range(101)]
    refused = desk.upload(pdf("guide"), "guide.pdf", entries, expect=422)
    assert "at most 100" in str(refused)
    guide = desk.upload(pdf("guide"), "guide.pdf", entries[:100])
    more = desk.post(
        f"/reference-files/{guide['hid']}/attachments", {"records": [entries[100]["hid"]]}, 200
    )
    assert more["attachment_count"] == 101


def test_a_reference_whose_kind_was_made_inactive_keeps_it_when_edited(
    desk: Desk, floor: dict
) -> None:
    sketch = desk.upload(pdf("sketch"), "sketch.pdf", floor, kind="sketch")
    choice = next(c for c in desk.get("/choices", list="reference_kind") if c["value"] == "sketch")
    desk.patch(f"/choices/{choice['hid']}", {"row_version": choice["row_version"], "active": False})
    changed = desk.patch(
        f"/reference-files/{sketch['hid']}",
        {"title": "Floor 2 sketch", "kind": "sketch", "row_version": 1},
    )
    assert (changed["title"], changed["kind"]) == ("Floor 2 sketch", "sketch")
    # A kind that is not offered is still refused where it is new.
    other = desk.upload(pdf("other"), "other.pdf", floor, kind="map")
    desk.patch(f"/reference-files/{other['hid']}", {"kind": "sketch", "row_version": 1}, 422)


def test_content_erased_between_its_check_and_its_answer_is_a_404(
    client: TestClient, desk: Desk, floor: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirdir.api import references as routes

    plan = desk.upload(pdf("plan"), "plan.pdf", floor)
    store: stores.Store = cast(Any, client.app).state.store
    checked = routes.refs.opened

    def then_erased(*arguments: Any) -> Any:
        found = checked(*arguments)
        store.path_of(plan["sha256"]).unlink()
        return found

    monkeypatch.setattr(routes.refs, "opened", then_erased)
    response = desk.content(plan, 404)
    assert "erased" in response.json()["detail"]


def test_a_record_named_by_its_hid_alone_is_found_without_a_word_of_refusal(
    run, desk: Desk, floor: dict
) -> None:
    entry = desk.entry(desk.vendor())
    switch = desk.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW0000X001", location_hid=floor["hid"]
    )
    desk.upload(pdf("guide"), "guide.pdf", entry, kind="administration_guide", title="Guide")
    said = run("references", "list", "--of", switch["hid"])
    assert "Guide" in said.output
    assert "there is no" not in said.output


@pytest.mark.parametrize(
    "content",
    [
        b'<?xml version="1.0"?>\n<!-- drawn by hand -->\n<svg xmlns="x"><script/></svg>',
        b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x">\n<svg/>',
        b'<?xml version="1.0"?><!DOCTYPE html PUBLIC "x" "y"><html><body/></html>',
        b"<!-- a comment first --><html><script>alert(1)</script></html>",
    ],
)
def test_a_page_that_begins_with_a_declaration_or_a_comment_is_refused_under_any_name(
    desk: Desk, floor: dict, content: bytes
) -> None:
    refused = desk.upload(content, "diagram.txt", floor, expect=422)
    assert "a web page" in str(refused)


def test_an_xml_file_that_is_no_page_is_taken_as_text(desk: Desk, floor: dict) -> None:
    config = b'<?xml version="1.0"?>\n<!-- show configuration -->\n<configuration><system/>'
    kept = desk.upload(config, "router.txt", floor)
    assert desk.content(kept).content == config
