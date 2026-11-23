"""A contact may have the name of another, and is saved with a warning (P-315).

The record of a contact answers `same_name`, how many other contacts that are not
retired have its name, compared as a file matches a contact by its name; it is read when
the contact is read, a page of them in one statement, and nothing is refused or written
for it. `hirdir profile set --name` says so after the change.
"""

import json
import shlex
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from typer.testing import CliRunner

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from hirdir.cli.profile import same_name_line
from tests.api.inventory import API, Maker
from tests.conftest import sign_in

CODE = "kim-lee-code-01"
runner = CliRunner()


def _contact(make: Maker, name: str, email: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if email is not None:
        body["email"] = email
    return make.post("/contacts", body)


def _same(make: Maker, contact: dict[str, Any]) -> int:
    return make.get(f"/contacts/{contact['hid']}")["same_name"]


def test_a_name_another_contact_has_is_saved_and_counted_by_each(make: Maker) -> None:
    kim = _contact(make, "Kim Lee", "kim.lee@example.com")
    assert kim["same_name"] == 0
    # A second of the name is made as before, by its case and its spaces too, and the
    # answer of the change counts the other.
    other = _contact(make, "  kim LEE ", "k.lee@example.net")
    assert (other["name"], other["same_name"]) == ("kim LEE", 1)
    assert _same(make, kim) == 1
    third = _contact(make, "Kim Lee")
    assert [_same(make, one) for one in (kim, other, third)] == [2, 2, 2]
    # A name changed away is counted by none, and one changed to it by each.
    moved = make.patch(
        f"/contacts/{third['hid']}", {"row_version": third["row_version"], "name": "Sam Roe"}
    )
    assert moved["same_name"] == 0
    assert _same(make, kim) == 1
    back = make.patch(
        f"/contacts/{third['hid']}", {"row_version": moved["row_version"], "name": "KIM LEE"}
    )
    assert back["same_name"] == 2


def test_a_retired_contact_and_a_draft_are_counted_as_a_file_finds_them(make: Maker) -> None:
    """The lead's reading at the review of P-315: a file that names a contact by its name
    alone finds every contact of that name, the retired and the drafts among them, so
    each of them is counted."""
    kim = _contact(make, "Kim Lee", "kim.lee@example.com")
    gone = _contact(make, "Kim Lee", "k.lee@example.net")
    assert _same(make, kim) == 1
    make.post(f"/contacts/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)
    assert _same(make, kim) == 1
    assert _same(make, gone) == 1
    draft = make.post("/contacts", {"name": "KIM LEE", "record_status": "draft"})
    assert [_same(make, one) for one in (kim, gone, draft)] == [2, 2, 2]


def test_nothing_is_written_for_a_name_another_has(make: Maker) -> None:
    kim = _contact(make, "Kim Lee", "kim.lee@example.com")
    before = make.audit(limit=200)
    made = _contact(make, "Kim Lee", "k.lee@example.net")
    after = make.audit(limit=200)
    # One event, the creation of the new contact, with nothing of the other in it; and
    # the other is not changed.
    assert len(after) == len(before) + 1
    assert (after[0]["action"], after[0]["record_hid"]) == ("create", made["hid"])
    assert {one["field"] for one in after[0]["changes"]} == {"name", "email", "record_status"}
    assert make.get(f"/contacts/{kim['hid']}")["row_version"] == kim["row_version"]


def test_a_list_reads_the_names_of_a_page_in_one_statement(client: TestClient, make: Maker) -> None:
    for number in range(9):
        _contact(make, f"Example Person {number % 3}", f"person.{number}@example.net")
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    def read(limit: int) -> tuple[int, list[int]]:
        statements.clear()
        page = make.get("/contacts", limit=limit)
        # The page itself is read by joining the records it matched to the contacts
        # (P-326): that statement is the page's, and not the names'.
        joined = [
            one
            for one in statements
            if one.count("FROM contacts")
            and "JOIN contacts" in one
            and "AS chosen JOIN contacts" not in one
        ]
        return len(joined), [one["same_name"] for one in page["items"]]

    engine = cast(FastAPI, client.app).state.engine
    event.listen(engine, "before_cursor_execute", note)
    try:
        few, counted = read(3)
        many, all_counted = read(9)
    finally:
        event.remove(engine, "before_cursor_execute", note)
    assert few == many == 1
    assert counted == [2, 2, 2]
    assert all_counted == [2] * 9


def test_the_profile_answers_it_and_saves_a_name_another_has(
    client: TestClient, admin: dict
) -> None:
    make = Maker(client, admin)
    _contact(make, "Sam Roe", "sam.roe@example.net")
    make.post(
        "/users",
        {
            "username": "klee",
            "access_code": CODE,
            "role": "viewer",
            "contact": {"name": "Kim Lee", "email": "kim.lee@example.com"},
        },
    )
    kim = sign_in(client, "klee", CODE)
    me = client.get(f"{API}/auth/me", headers=kim).json()
    assert me["contact"]["same_name"] == 0
    saved = client.patch(
        f"{API}/auth/me/contact",
        json={"row_version": me["contact"]["row_version"], "name": "sam roe"},
        headers=kim,
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["contact"]["name"], saved.json()["contact"]["same_name"]) == (
        "sam roe",
        1,
    )


@pytest.fixture
def hirdir(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Run `hirdir` as whoever holds the headers, with its calls going to the test client."""
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.delenv("HIRDIR_TOKEN", raising=False)

    def run(headers: dict, *arguments: str) -> Any:
        token = headers["Authorization"].removeprefix("Bearer ")
        result = runner.invoke(app, [*arguments, "--token", token])
        assert result.exit_code == 0, result.output
        return result

    return run


def test_profile_set_says_that_another_contact_is_named_so(
    client: TestClient, admin: dict, hirdir
) -> None:
    make = Maker(client, admin)
    _contact(make, "Sam Roe", "sam.roe@example.net")
    make.post(
        "/users",
        {
            "username": "klee",
            "access_code": CODE,
            "role": "viewer",
            "contact": {"name": "Kim Lee", "email": "kim.lee@example.com"},
        },
    )
    kim = sign_in(client, "klee", CODE)
    # A change of another field, or to a name nobody else has, says nothing of it.
    assert hirdir(kim, "profile", "set", "--phone", "+1 555 0100").stderr == ""
    assert hirdir(kim, "profile", "set", "--name", "Kim A. Lee").stderr == ""
    said = hirdir(kim, "profile", "set", "--name", "Sam Roe")
    assert said.stderr.splitlines() == [
        "another contact is named Sam Roe: a file tells you apart by your email or your HID; "
        "hirdir contacts list --filter 'name:eq:Sam Roe' --include-archived "
        "--include-drafts lists them"
    ]
    assert "name          Sam Roe" in said.stdout.splitlines()
    _contact(make, "SAM ROE")
    said = hirdir(kim, "profile", "set", "--name", "Sam Roe")
    assert said.stderr.startswith("2 other contacts are named Sam Roe: ")


def test_the_cli_line_names_a_filter_that_lists_them_whatever_the_name(make: Maker) -> None:
    """Review 9: a name the short form would read as more than one condition is written
    as a tree, as the web writes it, and lists the contacts of that name."""
    odd = "Ex tags:has:y"
    _contact(make, odd, "one@example.net")
    _contact(make, odd, "two@example.net")
    line = same_name_line({"name": odd, "same_name": 1})
    assert line is not None
    written = shlex.split(line.split("hirdir contacts list --filter ", 1)[1])[0]
    assert json.loads(written) == {"field": "name", "op": "eq", "value": odd}
    assert make.get("/contacts", filter=written)["total"] == 2
    plain = same_name_line({"name": "Sam Roe", "same_name": 1})
    assert plain is not None
    assert "--filter 'name:eq:Sam Roe'" in plain
