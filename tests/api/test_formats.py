"""The input formats through the API: their settings, a contact by every way in, whom to
ask, and a file's preview, which says the file's value beside what a format writes
(P-293, P-322)."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import Contact, User
from hirdir.domain import audit, settings
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, counts

PLUS_ONE = "+1 (###) ###-####"
CODE = "kim-lee-code-01"


def _put(client: TestClient, headers: dict, key: str, value: Any, expect: int = 200) -> Any:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=headers).json()}
    answer = client.put(
        f"{API}/settings/{key}",
        json={"row_version": now[key]["row_version"], "value": value},
        headers=headers,
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


def _contact(make: Maker, hid: str) -> dict[str, Any]:
    return make.get(f"/contacts/{hid}")


def _said(row: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """What each change of a row saves, and the file's value where a format wrote another."""
    return {entry["field"]: (entry["new"], entry["as_in_file"]) for entry in row["changes"]}


def test_the_three_settings_start_as_the_owner_chose(client: TestClient, viewer: dict) -> None:
    by_key = {one["key"]: one for one in client.get(f"{API}/settings", headers=viewer).json()}
    phone = by_key["phone_formats"]
    assert (phone["value"], phone["default"], phone["is_default"]) == ([], [], True)
    assert phone["options"] == ["###-###-####", PLUS_ONE]
    assert "# for each digit" in phone["accepts"]
    for key in ("email_lower_case", "title_case_names"):
        assert (by_key[key]["value"], by_key[key]["default"]) == (True, True), key
        assert by_key[key]["accepts"] == "true or false", key
    assert "web page" in by_key["title_case_names"]["meaning"]


def test_an_admin_alone_sets_the_formats_and_each_change_is_audited(
    client: TestClient, admin: dict, inventory: dict
) -> None:
    _put(client, inventory, "phone_formats", [PLUS_ONE], 403)
    _put(client, inventory, "email_lower_case", False, 403)
    kept = _put(client, admin, "phone_formats", [f" {PLUS_ONE} ", "###-####", PLUS_ONE])
    assert (kept["value"], kept["is_default"]) == ([PLUS_ONE, "###-####"], False)
    refused = _put(client, admin, "phone_formats", [PLUS_ONE, "### x ####"], 422)
    assert refused["errors"][0]["field"] == "value"
    assert refused["errors"][0]["message"].endswith("### x #### holds x, which a pattern does not")
    _put(client, admin, "phone_formats", "###-####", 422)
    _put(client, admin, "title_case_names", "no", 422)
    assert _put(client, admin, "title_case_names", False)["value"] is False
    events = client.get(
        f"{API}/audit-events", params={"record_type": "setting"}, headers=admin
    ).json()["items"]
    assert {"field": "value", "old": None, "new": [PLUS_ONE, "###-####"]} in [
        change for event in events for change in event["changes"]
    ]
    # Back to none: no number is formatted again.
    assert _put(client, admin, "phone_formats", None)["value"] == []


def test_a_contact_is_saved_in_the_formats_by_the_api_the_profile_and_new_user(
    client: TestClient, admin: dict, make: Maker
) -> None:
    _put(client, admin, "phone_formats", [PLUS_ONE])
    made = make.post(
        "/contacts",
        {
            "name": "john smith",
            "email": "John.Smith@Example.COM",
            "phone": "5550100123",
            "phone2": "1 555 010 0124",
        },
    )
    # The name is kept as given: Title Case is the web page's alone.
    assert (made["name"], made["email"], made["phone"], made["phone2"]) == (
        "john smith",
        "john.smith@example.com",
        "+1 (555) 010-0123",
        "+1 (555) 010-0124",
    )
    # A number with a letter in it, and one no pattern fits, are kept as typed.
    changed = make.patch(
        f"/contacts/{made['hid']}",
        {"row_version": made["row_version"], "phone": "555 0100 x12", "phone2": "+1 555 0100"},
    )
    assert (changed["phone"], changed["phone2"]) == ("555 0100 x12", "+1 555 0100")
    # The form of an address is held after the format, and its key is what it was.
    assert "email" in errors(make.post("/contacts", {"name": "X", "email": "Not An Address"}, 422))
    assert "email" in errors(
        make.post("/contacts", {"name": "X", "email": "JOHN.SMITH@example.com"}, 409)
    )

    person = client.post(
        f"{API}/users",
        json={
            "username": "klee",
            "access_code": CODE,
            "role": "viewer",
            "contact": {"name": "Kim Lee", "email": "Kim.Lee@Example.NET", "phone": "555.010.0125"},
        },
        headers=admin,
    )
    assert person.status_code == 201, person.text
    contact = _contact(make, person.json()["user"]["contact_hid"])
    assert (contact["email"], contact["phone"]) == ("kim.lee@example.net", "+1 (555) 010-0125")

    signed = client.post(f"{API}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    kim = {"Authorization": f"Bearer {signed.json()['token']}"}
    own = client.patch(
        f"{API}/auth/me/contact",
        json={
            "row_version": contact["row_version"],
            "email": "KIM.A.LEE@Example.NET",
            "phone2": "(555) 010-0126",
        },
        headers=kim,
    )
    assert own.status_code == 200, own.text
    contact = _contact(make, contact["hid"])
    assert (contact["email"], contact["phone2"]) == ("kim.a.lee@example.net", "+1 (555) 010-0126")


def test_with_no_pattern_and_no_lower_case_a_value_is_kept_as_typed(
    client: TestClient, admin: dict, make: Maker
) -> None:
    plain = make.post(
        "/contacts", {"name": "Sam Roe", "email": "Sam.Roe@Example.ORG", "phone": "5550100123"}
    )
    # No number is formatted until an Admin chooses a pattern; an address is lowered.
    assert (plain["email"], plain["phone"]) == ("sam.roe@example.org", "5550100123")
    _put(client, admin, "email_lower_case", False)
    kept = make.post("/contacts", {"name": "Rex Example", "email": "Rex.Example@Example.ORG"})
    assert kept["email"] == "Rex.Example@Example.ORG"


def test_nothing_held_is_written_again_when_a_setting_changes(
    client: TestClient, admin: dict, make: Maker
) -> None:
    _put(client, admin, "email_lower_case", False)
    held = make.post(
        "/contacts", {"name": "Kim Lee", "email": "Kim.Lee@Example.NET", "phone": "555 010 0125"}
    )
    _put(client, admin, "email_lower_case", True)
    _put(client, admin, "phone_formats", [PLUS_ONE])
    read = _contact(make, held["hid"])
    assert (read["email"], read["phone"], read["row_version"]) == (
        "Kim.Lee@Example.NET",
        "555 010 0125",
        held["row_version"],
    )
    # A change of another field leaves them as they are held.
    renamed = make.patch(
        f"/contacts/{held['hid']}", {"row_version": read["row_version"], "organization": "NOC"}
    )
    assert (renamed["email"], renamed["phone"]) == ("Kim.Lee@Example.NET", "555 010 0125")
    # A change that gives them is saved in the formats, as every change is.
    tidied = make.patch(
        f"/contacts/{held['hid']}",
        {
            "row_version": renamed["row_version"],
            "email": renamed["email"],
            "phone": renamed["phone"],
        },
    )
    assert (tidied["email"], tidied["phone"]) == ("kim.lee@example.net", "+1 (555) 010-0125")


def test_whom_to_ask_is_written_in_the_formats_when_an_admin_sets_it(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    _put(client, admin, "phone_formats", ["###/###-####"])
    # The / a pattern may write is one that help_phone takes.
    assert _put(client, admin, "help_phone", " 555 010 0123 ")["value"] == "555/010-0123"
    assert _put(client, admin, "help_phone", "555 0100 ext. 12")["value"] == "555 0100 ext. 12"
    assert _put(client, admin, "help_email", "Tools@Example.NET")["value"] == "tools@example.net"
    # Its own rule stands beside the format: a domain with a dot, as About makes a link.
    _put(client, admin, "help_email", "Tools@Localhost", 422)
    help_ = client.get(f"{API}/about", headers=viewer).json()["help"]
    assert (help_["email"], help_["phone"]) == ("tools@example.net", "555 0100 ext. 12")
    _put(client, admin, "email_lower_case", False)
    assert _put(client, admin, "help_email", "Tools@Example.NET")["value"] == "Tools@Example.NET"
    # With no pattern, a number is kept as it is typed.
    _put(client, admin, "phone_formats", [])
    assert _put(client, admin, "help_phone", "5550100123")["value"] == "5550100123"


CSV = (
    "name,email,phone,phone2\n"
    "Ada Example,Ada.Example@Example.COM,1 555 010 0124,555 0100 x12\n"
    "Sam Roe,sam.roe@example.net,555 010 0126,\n"
)


def test_a_preview_says_the_files_value_beside_what_a_format_writes(
    client: TestClient, admin: dict, inventory: dict, make: Maker
) -> None:
    files = Files(client, inventory)
    _put(client, admin, "phone_formats", [PLUS_ONE])
    sam = make.post(
        "/contacts", {"name": "Sam Roe", "email": "sam.roe@example.net", "phone": "5550100126"}
    )
    assert sam["phone"] == "+1 (555) 010-0126"

    preview = files.preview("contacts", CSV)
    assert counts(preview["job"]) == (1, 0, 1, 0)
    made, same = preview["rows"]
    assert _said(made) == {
        "name": ("Ada Example", None),
        "email": ("ada.example@example.com", "Ada.Example@Example.COM"),
        "phone": ("+1 (555) 010-0124", "1 555 010 0124"),
        "phone2": ("555 0100 x12", None),
        "record_status": ("active", None),
    }
    # A row that differs from what is held only by what a format writes the same is no
    # change.
    assert (same["outcome"], same["changes"]) == ("unchanged", [])

    job = files.apply(preview)
    assert counts(job) == (1, 0, 1, 0)
    ada = make.get("/contacts", filter="name:eq:Ada Example")["items"][0]
    assert (ada["email"], ada["phone"], ada["phone2"]) == (
        "ada.example@example.com",
        "+1 (555) 010-0124",
        "555 0100 x12",
    )
    assert counts(files.preview("contacts", CSV)["job"]) == (0, 0, 2, 0)


def test_a_preview_applied_after_the_formats_changed_is_stale(
    client: TestClient, admin: dict, inventory: dict
) -> None:
    files = Files(client, inventory)
    _put(client, admin, "phone_formats", [PLUS_ONE])
    preview = files.preview("contacts", "name,phone\nAda Example,5550100124\n")
    assert _said(preview["rows"][0])["phone"] == ("+1 (555) 010-0124", "5550100124")
    _put(client, admin, "phone_formats", ["###-###-####"])
    job = files.apply(preview)
    assert (job["applied"], job["stale"]) == (0, 1)
    rows = client.get(f"{API}/imports/{job['hid']}/rows", headers=inventory).json()["items"]
    assert rows[0]["applied_outcome"] == "stale"


def test_the_first_admin_is_made_in_the_formats(tmp_path: Path, monkeypatch) -> None:
    """`hirdir admin create-user` calls the rules of a contact directly, and they apply
    the formats there."""
    path = tmp_path / "config.toml"
    path.write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=tmp_path, listen="127.0.0.1:1")
    migrate.upgrade(config.database_url)
    sessions = make_sessions(make_engine(config.database_url))
    with sessions() as db:
        context = audit.AuditContext(actor_hid=None, via="api", request_id="r-formats")
        settings.set_setting(db, context, "phone_formats", 0, ["###-###-####"])
        db.commit()
    made = CliRunner().invoke(
        app,
        [
            "admin",
            "create-user",
            "--role",
            "admin",
            "--name",
            "ada example",
            "--email",
            "Ada@Example.ORG",
            "--phone",
            "(555) 010-0127",
            "--phone2",
            "555 0100 x12",
            "ada",
        ],
    )
    assert made.exit_code == 0, made.output
    with sessions() as db:
        hid = db.scalar(select(User.contact_hid).where(User.username == "ada"))
        contact = db.get(Contact, hid)
        assert contact is not None
        assert (contact.name, contact.email, contact.phone, contact.phone2) == (
            "ada example",
            "ada@example.org",
            "555-010-0127",
            "555 0100 x12",
        )
