"""The name a site gives the product, and whom to ask (P-168, P-169): the settings, what
they refuse, About, the name of an export, and the page served before signing in."""

import html
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from hirdir import app as app_module
from hirdir.domain import product, settings
from tests.api.inventory import API

HELP = {
    "help_organization": "Network Tools, Example Corp",
    "help_email": "tools@example.net",
    "help_phone": "+1 555 0100 ext. 12",
    "help_url": "https://help.example.net/network-tools",
}
PAGE = (
    '<!doctype html>\n<html lang="en">\n  <head>\n    <base href="/" />\n'
    "    <title>hirdir</title>\n  </head>\n  <body>\n"
    "    <noscript>hirdir needs JavaScript to run.</noscript>\n  </body>\n</html>\n"
)


def _put(client: TestClient, headers: dict, key: str, value: Any, expect: int = 200) -> Any:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=headers).json()}
    answer = client.put(
        f"{API}/settings/{key}",
        json={"row_version": now[key]["row_version"], "value": value},
        headers=headers,
    )
    assert answer.status_code == expect, answer.text
    return answer.json()


def _site(page: str) -> dict[str, Any]:
    """Return what the page carries for the web UI, read as a browser reads it."""
    found = re.search(r'<meta name="hirdir-site" content="([^"]*)" />', page)
    assert found, page
    return json.loads(html.unescape(found.group(1)))


def test_the_settings_start_at_hirdir_and_blank(client: TestClient, viewer: dict) -> None:
    by_key = {one["key"]: one for one in client.get(f"{API}/settings", headers=viewer).json()}
    assert by_key["product_name"]["value"] == "hirdir"
    for key in HELP:
        assert (by_key[key]["value"], by_key[key]["default"]) == (None, None), key
        assert by_key[key]["accepts"], key
        assert by_key[key]["meaning"], key
    assert by_key["help_on_sign_in"]["value"] is False
    about = client.get(f"{API}/about", headers=viewer).json()
    assert (about["name"], about["product_name"]) == ("hirdir", "hirdir")
    assert about["help"] == {"organization": None, "email": None, "phone": None, "url": None}


def test_an_admin_names_the_product_and_whom_to_ask_and_every_role_reads_it(
    client: TestClient, admin: dict, inventory: dict, viewer: dict
) -> None:
    assert _put(client, admin, "product_name", "  Example Inventory  ")["value"] == (
        "Example Inventory"
    )
    for key, value in HELP.items():
        assert _put(client, admin, key, value)["value"] == value
    # Only an Admin changes them.
    _put(client, inventory, "product_name", "other", expect=403)
    _put(client, viewer, "help_email", "x@example.net", expect=403)
    about = client.get(f"{API}/about", headers=viewer).json()
    assert (about["name"], about["product_name"]) == ("hirdir", "Example Inventory")
    assert about["help"] == {
        "organization": "Network Tools, Example Corp",
        "email": "tools@example.net",
        "phone": "+1 555 0100 ext. 12",
        "url": "https://help.example.net/network-tools",
    }
    # Each change is audited, as every setting is.
    events = client.get(
        f"{API}/audit-events", params={"record_type": "setting"}, headers=admin
    ).json()["items"]
    changed = {change["new"] for event in events for change in event["changes"]}
    assert {"Example Inventory", "tools@example.net"} <= changed
    # null makes one blank again, and the product hirdir again.
    assert _put(client, admin, "help_phone", None)["value"] is None
    assert _put(client, admin, "product_name", None)["value"] == "hirdir"
    assert client.get(f"{API}/about", headers=viewer).json()["help"]["phone"] is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("product_name", ""),
        ("product_name", "   "),
        ("product_name", "x" * 41),
        ("product_name", "<b>Assets</b>"),
        ("product_name", "Assets\u0007"),
        # A character that turns the text around, which could make a name read as another.
        ("product_name", "Assets\u202estessa"),
        ("product_name", "Assets\ue000"),
        ("product_name", 7),
        ("help_organization", "y" * 201),
        ("help_organization", "Tools <team>"),
        ("help_email", "tools"),
        ("help_email", "tools@example"),
        ("help_email", "@example.net"),
        ("help_email", "tools@@example.net"),
        ("help_email", "tools team@example.net"),
        ("help_email", "tools@example.net."),
        ("help_email", "<tools@example.net>"),
        # What would add a copy, a subject or a body to the message a link opens.
        ("help_email", "tools@example.net?bcc=other@example.org"),
        ("help_email", "tools@example.net&body=hi"),
        ("help_email", "javascript:alert(1)//@example.net"),
        ("help_email", "tools%40x@example.net"),
        ("help_email", "tools@example..net"),
        ("help_email", ".tools@example.net"),
        ("help_phone", "call the desk"),
        ("help_phone", "555 0100 <x>"),
        ("help_phone", "555_0100"),
        ("help_phone", "5" * 41),
        ("help_phone", "\u00b2"),
        ("help_url", "ftp://help.example.net/"),
        ("help_url", "help.example.net"),
        ("help_url", "https://help.example.net/a b"),
        ("help_url", "https://help.example.net/<x>"),
        ("help_on_sign_in", "true"),
        ("help_on_sign_in", 1),
    ],
)
def test_what_a_setting_cannot_take_is_refused_saying_what_it_takes(
    client: TestClient, admin: dict, key: str, value: Any
) -> None:
    refused = _put(client, admin, key, value, expect=422)
    assert refused["errors"][0]["field"] == "value", refused
    assert refused["errors"][0]["message"], refused


def test_a_file_name_begins_with_the_product_name_in_a_form_a_file_may_have() -> None:
    assert product.file_stem("hirdir") == "hirdir"
    assert product.file_stem("Example Inventory") == "Example-Inventory"
    assert product.file_stem("Ben & Ada's: Net/2") == "Ben-Ada-s-Net-2"
    assert product.file_stem("--.assets.--") == "assets"
    # Letters lose their accents; a script with none to lose is left out.
    assert product.file_stem("Réseau") == "Reseau"
    assert product.file_stem("Ünïcode") == "Unicode"
    assert product.file_stem("ÄÖÜ") == "AOU"
    assert product.file_stem("Сеть") == "hirdir"
    assert product.file_stem("/// ...") == "hirdir"


def test_an_export_is_named_by_the_product(client: TestClient, admin: dict) -> None:
    def named() -> str:
        answer = client.post(
            f"{API}/exports", json={"entity": "vendors", "format": "csv"}, headers=admin
        )
        assert answer.status_code == 200, answer.text
        found = re.search(r'filename="([^"]+)"', answer.headers["content-disposition"])
        assert found
        return found.group(1)

    assert re.fullmatch(r"hirdir-vendors-\d{8}T\d{6}[-+]\d{4}\.csv", named())
    _put(client, admin, "product_name", "ACME Inventory")
    assert re.fullmatch(r"ACME-Inventory-vendors-\d{8}T\d{6}[-+]\d{4}\.csv", named())


@pytest.fixture
def ui(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The client, with a built page to serve: the page is read when it is asked for."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(PAGE)
    monkeypatch.setattr(app_module, "STATIC", static)
    return client


def test_the_page_is_named_by_the_product_before_signing_in(ui: TestClient) -> None:
    page = ui.get("/").text
    assert "<title>hirdir</title>" in page
    assert _site(page) == {"product_name": "hirdir", "help": None}


def test_the_page_escapes_the_name_it_writes(ui: TestClient, admin: dict) -> None:
    headers = admin
    tricky = """Ben & Ada's "Net" '/>"""
    # A name with < or > is refused; what else it holds is escaped where it is written.
    _put(ui, headers, "product_name", tricky.replace(">", ""))
    page = ui.get("/sites/1").text
    named = html.escape(tricky.replace(">", ""), quote=True)
    assert f"<title>{named}</title>" in page
    assert f"<noscript>{named} needs JavaScript to run.</noscript>" in page
    assert _site(page)["product_name"] == tricky.replace(">", "")
    assert page.count("<meta ") == 1
    assert "set-cookie" not in ui.get("/").headers


def test_whom_to_ask_is_in_the_page_only_where_an_admin_says(ui: TestClient, admin: dict) -> None:
    headers = admin
    for key, value in HELP.items():
        _put(ui, headers, key, value)
    # Set, but not to be shown before signing in: nothing of it is in the page.
    page = ui.get("/").text
    assert _site(page)["help"] is None
    for value in HELP.values():
        assert html.escape(value, quote=True) not in page
    _put(ui, headers, "help_on_sign_in", True)
    assert _site(ui.get("/").text)["help"] == {
        "organization": "Network Tools, Example Corp",
        "email": "tools@example.net",
        "phone": "+1 555 0100 ext. 12",
        "url": "https://help.example.net/network-tools",
    }
    # Shown on the sign-in page, but with none of them set, the page carries none.
    for key in HELP:
        _put(ui, headers, key, None)
    assert _site(ui.get("/").text)["help"] is None
    # An answer of the API is no page, and carries no such thing.
    assert "hirdir-site" not in ui.get(f"{API}/health/live").text


def test_names_some_scripts_need_are_taken(client: TestClient, admin: dict) -> None:
    # The joiners that Persian and emoji need, and a soft hyphen.
    for name in ("\u0641\u200c\u0627", "Ops \U0001f468\u200d\U0001f4bb", "Net\u00adwork"):
        assert _put(client, admin, "product_name", name)["value"] == name


def test_a_value_equal_to_the_default_is_kept_as_no_value(client: TestClient, admin: dict) -> None:
    named = _put(client, admin, "product_name", "  hirdir ")
    assert (named["value"], named["is_default"], named["row_version"]) == ("hirdir", True, 0)
    # Off, as it starts, is no change at all; on and off again is two, and at its default.
    assert _put(client, admin, "help_on_sign_in", False)["row_version"] == 0
    assert _put(client, admin, "help_on_sign_in", True)["value"] is True
    off = _put(client, admin, "help_on_sign_in", False)
    assert (off["value"], off["is_default"], off["row_version"]) == (False, True, 2)
    events = client.get(
        f"{API}/audit-events", params={"record_type": "setting"}, headers=admin
    ).json()["items"]
    flag = [c for e in events for c in e["changes"] if c["new"] is True or c["old"] is True]
    assert len(flag) == 2


def test_the_built_page_holds_what_the_server_names(ui: TestClient) -> None:
    # The server replaces these very strings of the page the web UI builds from.
    built = (Path(__file__).parents[2] / "web" / "index.html").read_text(encoding="utf-8")
    for held in (app_module.BASE_TAG, app_module.TITLE_TAG, app_module.NO_SCRIPT, "</head>"):
        assert built.count(held) == 1, held


def test_the_page_is_named_by_any_path_it_is_asked_for_by(ui: TestClient, admin: dict) -> None:
    _put(ui, admin, "product_name", "Réseau Example")
    for path in ("/", "/items", "/index.html", "/admin/settings"):
        page = ui.get(path).text
        assert "<title>Réseau Example</title>" in page, path
        assert _site(page)["product_name"] == "Réseau Example", path


def test_one_of_whom_to_ask_is_enough_for_the_sign_in_page(ui: TestClient, admin: dict) -> None:
    _put(ui, admin, "help_on_sign_in", True)
    assert _site(ui.get("/").text)["help"] is None
    _put(ui, admin, "help_phone", "+1 555 0100")
    assert _site(ui.get("/").text)["help"] == {
        "organization": None,
        "email": None,
        "phone": "+1 555 0100",
        "url": None,
    }


def test_the_page_is_served_when_the_settings_cannot_be_read(
    ui: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unread(*_: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(settings, "values", unread)
    page = ui.get("/")
    assert page.status_code == 200
    assert "<title>hirdir</title>" in page.text
    assert _site(page.text) == {"product_name": "hirdir", "help": None}
