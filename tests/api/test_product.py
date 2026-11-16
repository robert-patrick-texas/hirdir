"""The name a site gives the product, and whom to ask (P-168, P-169): the settings, what
they refuse, About, the name of an export, and the page served before signing in."""

import html
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir import app as app_module
from hirdir.domain import product
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
    assert _put(client, admin, "product_name", "  inv  ")["value"] == "inv"
    for key, value in HELP.items():
        assert _put(client, admin, key, value)["value"] == value
    # Only an Admin changes them.
    _put(client, inventory, "product_name", "other", expect=403)
    _put(client, viewer, "help_email", "x@example.net", expect=403)
    about = client.get(f"{API}/about", headers=viewer).json()
    assert (about["name"], about["product_name"]) == ("hirdir", "inv")
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
    assert {"inv", "tools@example.net"} <= changed
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
        ("product_name", "<b>inv</b>"),
        ("product_name", "inv\u0007"),
        ("product_name", "in​v"),
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
        ("help_phone", "call the desk"),
        ("help_phone", "555 0100 <x>"),
        ("help_phone", "555_0100"),
        ("help_phone", "5" * 41),
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
    assert product.file_stem("inv") == "inv"
    assert product.file_stem("ACME Inventory") == "ACME-Inventory"
    assert product.file_stem("Tom & Jerry's: Inv/2") == "Tom-Jerry-s-Inv-2"
    assert product.file_stem("--.inv.--") == "inv"
    assert product.file_stem("Ünïcode") == "n-code"
    assert product.file_stem("ÄÖÜ") == "hirdir"
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
    tricky = """Tom & Jerry's "Inv" '/>"""
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
