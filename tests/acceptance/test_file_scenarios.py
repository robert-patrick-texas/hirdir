"""Scenarios S12 to S17 of docs/build-plan.md, against a real server process.

The browser's part of S15 and S16, changing a row and copying rows on the page, is run
by `make e2e`. Here the same steps are taken through the API and the command line.
"""

import csv
import importlib.util
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx2
import pytest

from tests.acceptance.conftest import ADMIN, HIRDIR, Server

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
LOAD_ORDER = ("tags", "vendors", "catalog_entries", "owners", "items")
ROUTES = {
    "tags": "/tags",
    "vendors": "/vendors",
    "catalog_entries": "/catalog-entries",
    "owners": "/owners",
    "items": "/items",
}
IVY = ("ivy", "acceptance-inventory")
IAN = ("ian", "acceptance-second")


def example(entity: str, format_: str) -> Path:
    return EXAMPLES / f"{entity.replace('_', '-')}.{format_}"


def seed_counts() -> dict[str, int]:
    """Count the records of the seed that `examples/` is exported from."""
    spec = importlib.util.spec_from_file_location(
        "seed_examples", ROOT / "scripts/seed_examples.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.counts()


class Desk:
    """A signed-in person who imports, exports and bulk-edits."""

    def __init__(self, client: httpx2.Client) -> None:
        self.client = client

    def get(self, path: str, **params: Any) -> Any:
        response = self.client.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, body: Any = None, expect: int = 200, **params: Any) -> Any:
        response = self.client.post(path, json=body, params=params)
        assert response.status_code == expect, response.text
        return response.json()

    def preview(self, entity: str, text: str, format_: str = "csv") -> dict[str, Any]:
        response = self.client.post(
            "/imports/preview",
            params={"entity": entity},
            content=text,
            headers={"Content-Type": "application/json" if format_ == "json" else "text/csv"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def apply(self, preview: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        return self.post(f"/imports/{preview['job']['hid']}/apply", expect=expect)

    def total(self, entity: str) -> int:
        if entity == "tags":
            return len(self.get("/tags"))
        return self.get(ROUTES[entity], include_archived=True, include_drafts=True, limit=1)[
            "total"
        ]

    def load_examples(self, format_: str = "csv") -> dict[str, dict[str, Any]]:
        jobs = {}
        for entity in LOAD_ORDER:
            preview = self.preview(entity, example(entity, format_).read_text(), format_)
            assert preview["job"]["rejected"] == 0, preview["rows"]
            jobs[entity] = self.apply(preview)
        return jobs


def _person(server: Server, who: tuple[str, str]) -> Desk:
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": who[0], "access_code": who[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Desk(server.sign_in(*who))


@pytest.fixture
def desk(server: Server) -> Desk:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    return _person(server, IVY)


def test_s12_the_examples_load_into_an_empty_database_in_load_order(desk: Desk) -> None:
    jobs = desk.load_examples()
    seed = seed_counts()
    for entity in LOAD_ORDER:
        job = jobs[entity]
        assert job["status"] == "applied", entity
        assert (job["created"], job["updated"], job["unchanged"], job["rejected"]) == (
            seed[entity],
            0,
            0,
            0,
        ), entity
        assert desk.total(entity) == seed[entity], entity
    # Nothing had to be made up for a reference: the catalog came from its own file.
    assert desk.get("/catalog-entries", filter="review_status:eq:unreviewed")["total"] == 0
    assert desk.get("/vendors", filter="review_status:eq:unreviewed")["total"] == 0


def test_s13_importing_the_same_files_again_changes_nothing(desk: Desk) -> None:
    desk.load_examples()
    events = desk.get("/audit-events", limit=1)["total"]
    for format_ in ("csv", "json"):
        for entity in LOAD_ORDER:
            preview = desk.preview(entity, example(entity, format_).read_text(), format_)
            job = preview["job"]
            assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0), entity
            assert job["unchanged"] == job["row_count"] > 0, entity
            assert all(row["changes"] == [] for row in preview["rows"]), entity
            assert desk.apply(preview)["status"] == "applied"
    # The only events since are the previews and the applies themselves.
    since = desk.get("/audit-events", limit=1)["total"] - events
    assert since == 2 * 2 * len(LOAD_ORDER)
    assert desk.get("/audit-events", record_type="item", action="update")["total"] == 0


def test_s14_a_blank_leaves_a_clear_inherits_and_an_unknown_model_is_created_unreviewed(
    desk: Desk,
) -> None:
    desk.load_examples()
    firewall = desk.get("/items", filter="hostname:eq:site2-fw-edge-01")["items"][0]
    assert firewall["est_value"] == "36500.00"
    assert firewall["comments"] is None
    desk.client.patch(
        f"/items/{firewall['hid']}",
        json={"row_version": firewall["row_version"], "comments": "kept as it is"},
    )
    text = (
        "vendor,pid,serial_number,comments,est_value\n"
        "Palo Alto Networks,PA-3410,PA0000X001,,!clear\n"
        "Arista,DCS-7050SX3-48YC8,JPE0000X001,,\n"
    )
    preview = desk.preview("items", text)
    known, unknown = preview["rows"]
    assert known["outcome"] == "update"
    assert known["changes"] == [{"field": "est_value", "old": "36500.00", "new": None}]
    assert unknown["outcome"] == "create"
    assert len(unknown["notes"]) == 2
    assert desk.apply(preview)["status"] == "applied"

    after = desk.get(f"/items/{firewall['hid']}")
    assert after["comments"] == "kept as it is"
    assert after["est_value"] is None
    assert after["effective"]["est_value"]["value"] == "31000.00"
    assert after["effective"]["est_value"]["source"] == "catalog"
    entry = desk.get("/catalog-entries", filter="pid:eq:DCS-7050SX3-48YC8")["items"][0]
    assert (entry["review_status"], entry["vendor"]["name"]) == ("unreviewed", "Arista")
    assert desk.get("/vendors", filter="name:eq:Arista")["items"][0]["review_status"] == (
        "unreviewed"
    )


def test_s15_a_row_changed_after_the_preview_stops_the_apply(desk: Desk) -> None:
    desk.load_examples()
    text = (
        "hostname,asset_tag,comments\n"
        "site2-sw-core-01,AT-000121,Uplinks moved to the new core\n"
        "site2-sw-core-02,AT-000122,Uplinks moved to the new core\n"
    )
    preview = desk.preview("items", text)
    assert preview["job"]["updated"] == 2
    # Somebody changes one of its rows on the item's page.
    core = desk.get("/items", filter="hostname:eq:site2-sw-core-02")["items"][0]
    changed = desk.client.patch(
        f"/items/{core['hid']}", json={"row_version": core["row_version"], "fqdn": None}
    )
    assert changed.status_code == 200, changed.text

    refused = desk.apply(preview, expect=409)
    assert refused["title"] == "Preview out of date"
    assert "preview again" in refused["detail"]
    assert [entry["field"] for entry in refused["errors"]] == ["rows.2"]
    assert desk.get("/items", filter="comments:prefix:Uplinks")["total"] == 0
    assert desk.get(f"/imports/{preview['job']['hid']}")["status"] == "failed"
    # A new preview is what goes through.
    assert desk.apply(desk.preview("items", text))["status"] == "applied"
    assert desk.get("/items", filter="comments:prefix:Uplinks")["total"] == 2


def _cli(server: Server, token: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    root = server.url.removesuffix("/api/v1")
    return subprocess.run(  # noqa: S603 - our own command with fixed arguments
        [*HIRDIR, *arguments, "--url", root, "--token", token],
        capture_output=True,
        text=True,
        check=False,
        env={**server.env, "XDG_CONFIG_HOME": str(Path(server.env["HIRDIR_CONFIG"]).parent)},
    )


def test_s16_the_api_and_the_command_line_export_the_same_rows_and_columns(
    server: Server, desk: Desk
) -> None:
    desk.load_examples()
    wanted = "lifecycle_state:eq:Prod catalog.type:eq:switch"
    columns = ["hostname", "pid", "serial_number", "lifecycle_state", "ldos"]
    body = {"entity": "items", "filter": wanted, "sort": ["hostname"], "columns": columns}

    as_csv = desk.client.post("/exports", json=body)
    assert as_csv.status_code == 200, as_csv.text
    rows = list(csv.reader(io.StringIO(as_csv.text)))
    assert rows[0] == ["hid", *columns]
    listed = desk.get("/items", filter=wanted, sort="hostname")["items"]
    assert [row[0] for row in rows[1:]] == [item["hid"] for item in listed]
    assert len(rows) - 1 == 11

    as_json = desk.client.post("/exports", json={**body, "format": "json"}).json()
    assert [list(record) for record in as_json["records"]] == [rows[0]] * 11
    assert [
        ["" if value is None else value for value in record.values()]
        for record in as_json["records"]
    ] == rows[1:]

    # The rows the page would select are exported by their HIDs, and are the same rows.
    selected = [row[0] for row in rows[1:4]]
    by_hid = desk.client.post("/exports", json={**body, "hids": selected})
    assert list(csv.reader(io.StringIO(by_hid.text))) == [rows[0], *rows[1:4]]

    token = desk.client.headers["authorization"].removeprefix("Bearer ")
    arguments = ("export", "items", "--filter", wanted, "--sort", "hostname")
    arguments += ("--columns", ",".join(columns))
    from_cli = _cli(server, token, *arguments, "--format", "csv")
    assert from_cli.returncode == 0, from_cli.stderr
    assert from_cli.stdout == as_csv.text
    json_from_cli = _cli(server, token, *arguments, "--format", "json")
    assert json.loads(json_from_cli.stdout) == as_json
    listed_by_cli = _cli(
        server,
        token,
        "items",
        "list",
        "--filter",
        wanted,
        "--sort",
        "hostname",
        "--format",
        "csv",
        "--columns",
        ",".join(columns),
    )
    assert listed_by_cli.returncode == 0, listed_by_cli.stderr
    assert listed_by_cli.stdout == as_csv.text


def test_s17_the_second_of_two_overlapping_bulk_edits_is_shown_the_conflict(
    server: Server, desk: Desk
) -> None:
    desk.load_examples()
    other = _person(server, IAN)
    mine = desk.post(
        "/items/bulk-update",
        {"filter": "hostname:prefix:site2-sw-access-0", "set": {"owner": "Voice Services"}},
        expect=201,
    )
    theirs = other.post(
        "/items/bulk-update",
        {
            "filter": "catalog.pid:eq:C9300-48P lifecycle_state:eq:Prod",
            "set": {"comments": "Checked in the autumn audit"},
            "add_tags": ["refresh-2030"],
        },
        expect=201,
    )
    assert (mine["job"]["updated"], theirs["job"]["updated"]) == (8, 7)

    applied = desk.post(f"/items/bulk-update/{mine['job']['hid']}/apply")
    assert applied["status"] == "applied"
    refused = other.post(f"/items/bulk-update/{theirs['job']['hid']}/apply", expect=409)
    assert refused["title"] == "Preview out of date"
    assert len(refused["errors"]) == 7
    assert all("changed since the preview" in entry["message"] for entry in refused["errors"])

    switches = desk.get("/items", filter="hostname:prefix:site2-sw-access-0")["items"]
    assert {item["owner"]["label"] for item in switches} == {"Voice Services"}
    assert all(item["comments"] != "Checked in the autumn audit" for item in switches)
    assert desk.get("/items", filter="tags:has:refresh-2030 catalog.pid:eq:C9300-48P")["total"] == 0
    # Shown the conflict, the second person previews again and goes through.
    again = other.post(
        "/items/bulk-update",
        {
            "filter": "catalog.pid:eq:C9300-48P lifecycle_state:eq:Prod",
            "set": {"comments": "Checked in the autumn audit"},
        },
        expect=201,
    )
    assert other.post(f"/items/bulk-update/{again['job']['hid']}/apply")["status"] == "applied"
    kept = desk.get("/items", filter="comments:prefix:Checked")["items"]
    assert {item["owner"]["label"] for item in kept} == {"Voice Services"}
