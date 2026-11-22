"""Scenario S65 of docs/build-plan.md, against a real server process: the input formats
of a telephone number and an email address, by the API, a file loaded by the command
line, and the examples exported and loaded back (P-293, P-322)."""

import io
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import httpx2

from tests.acceptance.conftest import ADMIN, HIRDIR, Server
from tests.acceptance.test_file_scenarios import LOAD_ORDER, Desk, example

PLUS_ONE = "+1 (###) ###-####"
FILE = (
    "name,email,phone\n"
    "Ada Example,ada.example@example.org,1 555 010 0124\n"
    "Sam Roe,sam.roe@example.org,555 0100 x12\n"
)


def _put(admin: httpx2.Client, key: str, value: Any) -> dict[str, Any]:
    held = {one["key"]: one for one in admin.get("/settings").json()}[key]
    answer = admin.put(
        f"/settings/{key}", json={"row_version": held["row_version"], "value": value}
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def _hirdir(server: Server, admin: httpx2.Client, *arguments: str) -> str:
    """Run a client command of `hirdir` as the Admin."""
    token = admin.headers["Authorization"].removeprefix("Bearer ")
    env = {**server.env, "HIRDIR_URL": server.url.removesuffix("/api/v1"), "HIRDIR_TOKEN": token}
    result = subprocess.run(  # noqa: S603 - our own command with fixed arguments
        [*HIRDIR, *arguments], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr.strip() or result.stdout.strip()
    return result.stdout


def _said(row: dict[str, Any]) -> dict[str, tuple[Any, Any, Any]]:
    return {
        entry["field"]: (entry["old"], entry["new"], entry["as_in_file"])
        for entry in row["changes"]
    }


def test_s65_the_formats_write_what_comes_in_and_tidy_what_is_held_only_by_a_file(
    server: Server, tmp_path: Path
) -> None:
    admin = server.sign_in(*ADMIN)
    desk = Desk(admin)
    desk.load_examples()
    # A contact held from before: its address and its number as they were typed then.
    _put(admin, "email_lower_case", False)
    rex = desk.post(
        "/contacts",
        {"name": "Rex Example", "email": "Rex.Example@Example.NET", "phone": "555 010 0125"},
        expect=201,
    )
    _put(admin, "email_lower_case", True)
    assert _put(admin, "phone_formats", [PLUS_ONE])["value"] == [PLUS_ONE]
    # Nothing held is written again when a setting changes.
    held = desk.get(f"/contacts/{rex['hid']}")
    assert (held["email"], held["phone"], held["row_version"]) == (
        "Rex.Example@Example.NET",
        "555 010 0125",
        rex["row_version"],
    )

    # By the API: the number in the pattern, the address in lower case.
    john = desk.post(
        "/contacts",
        {"name": "John Smith", "phone": "5550100123", "email": "John.Smith@Example.COM"},
        expect=201,
    )
    assert (john["phone"], john["email"]) == ("+1 (555) 010-0123", "john.smith@example.com")

    # By a file: the preview shows the number as it will be saved beside the file's,
    # and keeps the extension as typed.
    loaded = tmp_path / "contacts.csv"
    loaded.write_text(FILE)
    preview = desk.preview("contacts", FILE)
    ada, sam = preview["rows"]
    assert _said(ada)["phone"] == (None, "+1 (555) 010-0124", "1 555 010 0124")
    assert _said(sam)["phone"] == (None, "555 0100 x12", None)
    shown = _hirdir(server, admin, "import", str(loaded), "--entity", "contacts")
    assert "    phone: blank → +1 (555) 010-0124 (in the file: 1 555 010 0124)\n" in shown
    assert "    phone: blank → 555 0100 x12\n" in shown
    _hirdir(server, admin, "import", str(loaded), "--entity", "contacts", "--apply")
    by_name = {
        contact["name"]: contact["phone"]
        for contact in desk.get("/contacts", filter="name:in:Ada Example,Sam Roe")["items"]
    }
    assert (by_name["Ada Example"], by_name["Sam Roe"]) == ("+1 (555) 010-0124", "555 0100 x12")

    # The examples exported and loaded back: their numbers fit no pattern and nothing of
    # them changes; what is held from before is tidied by the file alone, its preview
    # showing each change before it is applied.
    taken = admin.post("/exports/all", json={"format": "csv"})
    assert taken.status_code == 200, taken.text
    archive = zipfile.ZipFile(io.BytesIO(taken.content))
    contacts_file = ""
    for entity in LOAD_ORDER:
        text = archive.read(example(entity, "csv").name).decode()
        job = desk.preview(entity, text)["job"]
        if entity == "contacts":
            contacts_file = text
            assert (job["created"], job["updated"], job["rejected"]) == (0, 1, 0), entity
        else:
            assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0), entity
    tidy = desk.preview("contacts", contacts_file)
    changed = [row for row in tidy["rows"] if row["outcome"] == "update"]
    assert [row["record_hid"] for row in changed] == [rex["hid"]]
    assert _said(changed[0]) == {
        "email": ("Rex.Example@Example.NET", "rex.example@example.net", "Rex.Example@Example.NET"),
        "phone": ("555 010 0125", "+1 (555) 010-0125", "555 010 0125"),
    }
    assert desk.get(f"/contacts/{rex['hid']}")["phone"] == "555 010 0125"
    assert desk.apply(tidy)["updated"] == 1
    after = desk.get(f"/contacts/{rex['hid']}")
    assert (after["email"], after["phone"]) == ("rex.example@example.net", "+1 (555) 010-0125")
    again = admin.post(
        "/exports", json={"entity": "contacts", "format": "csv", "include_archived": True}
    )
    assert again.status_code == 200, again.text
    job = desk.preview("contacts", again.text)["job"]
    assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0)
