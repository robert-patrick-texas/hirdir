"""`hirdir whoami` and `hirdir profile`: a person shows and changes what is their own
from the command line (P-289, P-294, P-295), run against the application itself."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from hirdir.cli import client as cli_client
from hirdir.cli.main import app
from tests.api.inventory import API, Maker
from tests.conftest import sign_in

runner = CliRunner()
CODE = "kim-lee-code-01"
NEW_CODE = "kim-lee-code-02"
KIM = {
    "name": "Kim Lee",
    "email": "kim.lee@example.com",
    "phone": "+1 555 0100",
    "organization": "Example Networks",
}


@pytest.fixture
def hirdir(client: TestClient, monkeypatch, tmp_path: Path):
    """Run `hirdir` as whoever holds the headers, with its calls going to the test client."""
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.delenv("HIRDIR_TOKEN", raising=False)

    def run(headers: dict, *arguments: str, expect: int = 0, typed: str | None = None) -> Result:
        token = headers["Authorization"].removeprefix("Bearer ")
        result = runner.invoke(app, [*arguments, "--token", token], input=typed)
        assert result.exit_code == expect, result.output
        return result

    return run


def _person(
    client: TestClient, admin: dict, role: str | None = "viewer", operator: bool = True
) -> tuple[dict[str, str], dict[str, Any]]:
    body: dict[str, Any] = {"username": "klee", "access_code": CODE, "contact": KIM}
    if role:
        body["role"] = role
    if operator:
        body["operator"] = {"colour": "#1f6feb"}
    made = Maker(client, admin).post("/users", body)
    return sign_in(client, "klee", CODE), made


def _me(client: TestClient, headers: dict) -> dict[str, Any]:
    return client.get(f"{API}/auth/me", headers=headers).json()


def test_whoami_prints_the_contact_and_the_operators(
    client: TestClient, admin: dict, viewer: dict, hirdir
) -> None:
    kim, _ = _person(client, admin)
    said = hirdir(kim, "whoami").output.splitlines()
    assert said[0] == "klee  role: viewer  groups: -"
    assert said[1:] == [
        "name          Kim Lee",
        "email         kim.lee@example.com",
        "phone         +1 555 0100",
        "phone2        -",
        "organization  Example Networks",
        "operator      klee  #1f6feb",
    ]
    # An account with no contact is told so, and who gives it one.
    said = hirdir(viewer, "whoami").output.splitlines()
    assert said == [
        "vic  role: viewer  groups: -",
        "contact       none: an Admin gives an account its contact",
    ]
    whole = json.loads(hirdir(kim, "whoami", "--format", "json").output)
    assert whole == _me(client, kim)


def test_profile_show_prints_the_profile_as_a_table_and_as_json(
    client: TestClient, admin: dict, hirdir
) -> None:
    kim, made = _person(client, admin)
    night = Maker(client, admin).post(
        "/operators", {"label": "kl-night", "contact_hid": made["user"]["contact_hid"]}
    )
    assert hirdir(kim, "profile", "show").output.splitlines() == [
        "username      klee",
        "role          viewer",
        "name          Kim Lee",
        "email         kim.lee@example.com",
        "phone         +1 555 0100",
        "phone2        -",
        "organization  Example Networks",
        f"operator      kl-night  {night['colour'] or '-'}",
        "operator      klee  #1f6feb",
    ]
    assert json.loads(hirdir(kim, "profile", "show", "--format", "json").output) == _me(client, kim)


def test_profile_set_changes_the_contact_and_the_operator(
    client: TestClient, admin: dict, hirdir
) -> None:
    kim, made = _person(client, admin)
    said = hirdir(
        kim,
        "profile",
        "set",
        "--name",
        "Kim A. Lee",
        "--phone",
        "",
        "--phone2",
        "+1 555 0111",
        "--label",
        "KAL",
        "--colour",
        "#D29922",
    ).output
    assert "name          Kim A. Lee" in said
    assert "operator      KAL  #d29922" in said
    me = _me(client, kim)
    assert me["contact"] == {
        **me["contact"],
        "name": "Kim A. Lee",
        "email": "kim.lee@example.com",
        "phone": None,
        "phone2": "+1 555 0111",
        "organization": "Example Networks",
    }
    assert [(one["label"], one["colour"]) for one in me["operators"]] == [("KAL", "#d29922")]
    events = Maker(client, admin).audit(actor_hid=made["user"]["hid"], action="update")
    assert sorted(event["record_type"] for event in events) == ["contact", "operator"]
    assert {event["via"] for event in events} == {"cli"}


def test_profile_set_asks_which_operator_where_the_person_is_behind_several(
    client: TestClient, admin: dict, hirdir
) -> None:
    kim, made = _person(client, admin)
    night = Maker(client, admin).post(
        "/operators", {"label": "kl-night", "contact_hid": made["user"]["contact_hid"]}
    )
    before = _me(client, kim)
    unsaid = hirdir(kim, "profile", "set", "--name", "Kim A. Lee", "--label", "KAL", expect=2)
    assert "say --operator (kl-night, klee)" in unsaid.output
    wrong = hirdir(
        kim,
        "profile",
        "set",
        "--name",
        "Kim A. Lee",
        "--label",
        "KAL",
        "--operator",
        "other",
        expect=4,
    )
    assert "you are behind no operator other" in wrong.output
    # Which operator is meant is settled before anything is sent: nothing was changed.
    assert _me(client, kim) == before

    hirdir(kim, "profile", "set", "--label", "KAL", "--operator", "KL-Night")
    hirdir(kim, "profile", "set", "--colour", "", "--operator", made["operator"]["hid"])
    assert [(one["hid"], one["label"], one["colour"]) for one in _me(client, kim)["operators"]] == [
        (night["hid"], "KAL", night["colour"]),
        (made["operator"]["hid"], "klee", None),
    ]


def test_profile_set_says_that_the_contact_was_changed_where_the_operator_is_refused(
    client: TestClient, admin: dict, hirdir
) -> None:
    """The contact and an operator are two changes: the first is kept where the second
    is refused, and the command says so before the refusal, with its exit code."""
    kim, _ = _person(client, admin)
    Maker(client, admin).post("/operators", {"label": "TAKEN"})
    refused = hirdir(
        kim,
        "profile",
        "set",
        "--phone",
        "+1 555 0199",
        "--name",
        "Kim A. Lee",
        "--label",
        "taken",
        expect=5,
    )
    said = refused.output.splitlines()
    first = said.index("your contact is changed (name, phone); your operator klee is not:")
    assert said[first + 1] == "hirdir: there is already an operator TAKEN"
    # The profile is not printed as if all of it had been done.
    assert not [line for line in said if line.startswith("username")]
    me = _me(client, kim)
    assert (me["contact"]["name"], me["contact"]["phone"]) == ("Kim A. Lee", "+1 555 0199")
    assert me["operators"][0]["label"] == "klee"

    # A contact that the request left as it was is not said to be changed, and an
    # operator refused by itself is refused with nothing before it.
    same = hirdir(kim, "profile", "set", "--phone", "+1 555 0199", "--label", "taken", expect=5)
    alone = hirdir(kim, "profile", "set", "--label", "taken", expect=5)
    for result in (same, alone):
        assert "your contact is changed" not in result.output
        assert "there is already an operator TAKEN" in result.output


def test_profile_set_says_what_it_needs_and_what_the_server_refuses(
    client: TestClient, admin: dict, viewer: dict, hirdir
) -> None:
    kim, _ = _person(client, admin, operator=False)
    Maker(client, admin).contact("Sam Okafor", email="sam.okafor@example.com")
    assert "say what to change" in hirdir(kim, "profile", "set", expect=2).output
    lone = hirdir(kim, "profile", "set", "--operator", "klee", expect=2)
    assert "--label and --colour" in lone.output
    assert (
        "you are behind no operator"
        in hirdir(kim, "profile", "set", "--label", "KL", expect=4).output
    )
    none = hirdir(viewer, "profile", "set", "--name", "Vic Example", expect=5)
    assert "this account has no contact: an Admin gives an account its contact" in none.output
    taken = hirdir(kim, "profile", "set", "--email", "sam.okafor@example.com", expect=5)
    assert "Sam Okafor already has the email address" in taken.output
    blank = hirdir(kim, "profile", "set", "--name", "", expect=4)
    assert "name: must not be blank" in blank.output


def test_profile_access_code_asks_for_both_codes_and_keeps_the_new_session(
    client: TestClient, admin: dict, hirdir
) -> None:
    kim, _ = _person(client, admin)
    elsewhere = sign_in(client, "klee", CODE)

    wrong = hirdir(
        kim, "profile", "access-code", expect=4, typed=f"not-the-code\n{NEW_CODE}\n{NEW_CODE}\n"
    )
    assert "current_access_code: this is not the access code you have" in wrong.output
    short = hirdir(kim, "profile", "access-code", expect=4, typed=f"{CODE}\nshort\nshort\n")
    assert "access_code: at least 12 characters (access_code_min_length)" in short.output
    # Neither refusal kept a session, or ended one.
    assert not cli_client.settings_path().exists()
    assert client.get(f"{API}/auth/me", headers=elsewhere).status_code == 200

    done = hirdir(kim, "profile", "access-code", typed=f"{CODE}\n{NEW_CODE}\n{NEW_CODE}\n")
    assert "the access code of klee is changed; every other session has ended" in done.output
    # Neither code is shown as it is typed, nor afterwards.
    assert CODE not in done.output
    assert NEW_CODE not in done.output

    kept = cli_client.load_target()
    assert kept.token != kim["Authorization"].removeprefix("Bearer ")
    assert _me(client, {"Authorization": f"Bearer {kept.token}"})["username"] == "klee"
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    assert client.get(f"{API}/auth/me", headers=elsewhere).status_code == 401
    sign_in(client, "klee", NEW_CODE)
    # The token it was given has ended, and it says which one goes on.
    assert "has ended: use the one kept" in done.output


def test_profile_access_code_is_for_an_account_with_no_role_too(
    client: TestClient, admin: dict, hirdir
) -> None:
    nobody, _ = _person(client, admin, role=None)
    done = hirdir(nobody, "profile", "access-code", typed=f"{CODE}\n{NEW_CODE}\n{NEW_CODE}\n")
    assert "the access code of klee is changed" in done.output
    assert "needs the viewer role" not in done.output
    sign_in(client, "klee", NEW_CODE)


def test_a_new_code_typed_two_ways_is_asked_for_again(
    client: TestClient, admin: dict, hirdir
) -> None:
    kim, _ = _person(client, admin)
    typed = f"{CODE}\n{NEW_CODE}\nkim-lee-code-03\n{NEW_CODE}\n{NEW_CODE}\n"
    hirdir(kim, "profile", "access-code", typed=typed)
    sign_in(client, "klee", NEW_CODE)


def test_an_account_with_no_role_signs_in_from_the_command_line(
    client: TestClient, admin: dict, hirdir
) -> None:
    """The settings, which say the time zone, are closed to an account with no role: it
    is told when its session ends all the same, and the session is kept."""
    _person(client, admin, role=None)
    result = runner.invoke(app, ["sign-in", "--username", "klee"], input=f"{CODE}\n")
    assert result.exit_code == 0, result.output
    assert "signed in as klee (no role) until " in result.output
    kept = cli_client.load_target()
    assert _me(client, {"Authorization": f"Bearer {kept.token}"})["username"] == "klee"
