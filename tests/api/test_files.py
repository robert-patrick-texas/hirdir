"""Import with preview and apply, and export: the rules of files, through the API."""

import csv
import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

ITEM_HEAD = "vendor,pid,serial_number,asset_tag,name,lifecycle_state,owner,est_value,tags"


class Files:
    """Sends files and exports as one signed-in user."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers

    def preview(
        self, entity: str | None, text: str | dict, expect: int = 201, **params: Any
    ) -> dict[str, Any]:
        is_json = isinstance(text, dict)
        response = self.client.post(
            f"{API}/imports/preview",
            params={"entity": entity, **params} if entity else params,
            content=json.dumps(text) if is_json else text,
            headers={
                **self.headers,
                "Content-Type": "application/json" if is_json else "text/csv",
            },
        )
        assert response.status_code == expect, response.text
        return response.json()

    def apply(self, preview: dict[str, Any], expect: int = 200, **params: Any) -> dict[str, Any]:
        response = self.client.post(
            f"{API}/imports/{preview['job']['hid']}/apply", params=params, headers=self.headers
        )
        assert response.status_code == expect, response.text
        return response.json()

    def load(self, entity: str, text: str | dict, **params: Any) -> dict[str, Any]:
        preview = self.preview(entity, text, **params)
        assert preview["job"]["rejected"] == 0, preview["rows"]
        return self.apply(preview)

    def export(self, entity: str, **body: Any) -> str:
        response = self.client.post(
            f"{API}/exports", json={"entity": entity, **body}, headers=self.headers
        )
        assert response.status_code == 200, response.text
        return response.text

    def refused_export(self, entity: str, **body: Any) -> dict[str, Any]:
        response = self.client.post(
            f"{API}/exports", json={"entity": entity, **body}, headers=self.headers
        )
        assert response.status_code == 422, response.text
        return response.json()


def table(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def counts(job: dict[str, Any]) -> tuple[int, int, int, int]:
    return job["created"], job["updated"], job["unchanged"], job["rejected"]


def changes(row: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in row["changes"]}


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


@pytest.fixture
def catalog(make: Maker) -> dict[str, Any]:
    """A vendor with one model, an owner and a tag, for item files to refer to."""
    vendor = make.vendor("Cisco", aliases=["Cisco Systems"])
    entry = make.entry(vendor, "C9300-48P", est_value="18000.00", ldos="2034-04-30")
    make.owner("Network Engineering")
    make.tag("refresh-2030")
    return entry


# --- preview and apply ---------------------------------------------------------------


def test_preview_changes_nothing_and_apply_creates_what_it_showed(
    files: Files, make: Maker, catalog: dict
) -> None:
    text = (
        f"{ITEM_HEAD}\n"
        "Cisco,C9300-48P,FCW0000X001,AT-000123,site2-sw-access-01,Prod,Network Engineering,,"
        "refresh-2030\n"
        "cisco systems,c9300-48p,FCW0000X002,,site2-sw-access-02,,,19500,\n"
    )
    preview = files.preview("items", text, file_name="items.csv")
    job = preview["job"]
    assert counts(job) == (2, 0, 0, 0)
    assert (job["status"], job["source"], job["mode"]) == ("previewed", "file", "upsert")
    assert (job["file_name"], job["created_by_name"]) == ("items.csv", "ivy")
    first = preview["rows"][0]
    assert (first["row"], first["outcome"], first["record_hid"]) == (1, "create", None)
    assert changes(first)["owner"] == (None, "Network Engineering")
    assert changes(first)["disposition"] == (None, "Production")
    assert make.get("/items")["total"] == 0

    applied = files.apply(preview)
    assert applied["status"] == "applied"
    assert applied["applied_at"] is not None
    listed = {row["serial_number"]: row for row in make.get("/items")["items"]}
    one, two = listed["FCW0000X001"], listed["FCW0000X002"]
    assert (one["lifecycle_state"], one["expected_online"], one["tags"]) == (
        "Prod",
        True,
        ["refresh-2030"],
    )
    assert one["effective"]["est_value"]["source"] == "catalog"
    assert two["catalog"]["pid"] == "C9300-48P"  # found by an alias, whatever its case
    assert two["est_value"] == "19500.00"
    rows = make.get(f"/imports/{job['hid']}/rows")["items"]
    assert [row["record_hid"] for row in rows] == [one["hid"], two["hid"]]


def test_importing_the_same_file_again_changes_nothing(files: Files, catalog: dict) -> None:
    text = (
        f"{ITEM_HEAD}\nCisco,C9300-48P,FCW0000X001,,sw-1,Prod,Network Engineering,,refresh-2030\n"
    )
    files.load("items", text)
    again = files.preview("items", text)
    assert counts(again["job"]) == (0, 0, 1, 0)
    assert again["rows"][0]["changes"] == []
    assert files.apply(again)["status"] == "applied"


def test_blank_leaves_alone_and_clear_returns_a_field_to_inheriting(
    files: Files, make: Maker, catalog: dict
) -> None:
    item = make.item(
        catalog_entry_hid=catalog["hid"],
        serial_number="FCW0000X001",
        name="sw-1",
        comments="kept",
        est_value="20000.00",
    )
    text = (
        "vendor,pid,serial_number,name,comments,est_value\n"
        "Cisco,C9300-48P,FCW0000X001,sw-one,,!clear\n"
    )
    preview = files.preview("items", text)
    assert counts(preview["job"]) == (0, 1, 0, 0)
    assert changes(preview["rows"][0]) == {
        "name": ("sw-1", "sw-one"),
        "est_value": ("20000.00", None),
    }
    files.apply(preview)
    after = make.get(f"/items/{item['hid']}")
    assert (after["name"], after["comments"], after["est_value"]) == ("sw-one", "kept", None)
    assert after["effective"]["est_value"] == {
        "value": "18000.00",
        "source": "catalog",
        "source_hid": catalog["hid"],
    }


def test_unknown_vendor_and_pid_are_created_unreviewed(files: Files, make: Maker) -> None:
    preview = files.preview(
        "items",
        "vendor,pid,serial_number\nJuniper,EX4400-48P,JN0000X001\nJuniper,EX4400-48P,JN0000X002\n",
    )
    assert counts(preview["job"]) == (2, 0, 0, 0)
    assert preview["rows"][0]["notes"] == [
        "creates the vendor Juniper, to be reviewed",
        "creates the catalog entry Juniper EX4400-48P, to be reviewed",
    ]
    assert preview["rows"][1]["notes"] == []
    assert make.get("/vendors")["total"] == 0
    files.apply(preview)
    assert [v["review_status"] for v in make.get("/vendors")["items"]] == ["unreviewed"]
    entries = make.get("/catalog-entries", filter="review_status:eq:unreviewed")["items"]
    assert [entry["pid"] for entry in entries] == ["EX4400-48P"]


def test_a_rejected_row_leaves_nothing_behind_and_blocks_the_apply(
    files: Files, make: Maker, catalog: dict
) -> None:
    text = (
        "vendor,pid,serial_number,owner,quantity,warranty_end\n"
        "Acme,X-1,S1,Nobody,,\n"  # the owner is not known: no vendor Acme is left behind
        "Cisco,C9300-48P,S2,,many,2030-13-01\n"
        "Cisco,C9300-48P,S3,,,\n"
    )
    preview = files.preview("items", text)
    assert counts(preview["job"]) == (1, 0, 0, 2)
    first, second, third = preview["rows"]
    assert first["reasons"] == [{"field": "owner", "message": "there is no owner Nobody"}]
    assert {reason["field"] for reason in second["reasons"]} == {"quantity", "warranty_end"}
    assert third["outcome"] == "create"

    blocked = files.apply(preview, expect=422)
    assert "skip_rejected" in errors(blocked)
    assert make.get("/items")["total"] == 0
    rejected = make.get(f"/imports/{preview['job']['hid']}/rows", outcome="rejected")
    assert [row["row"] for row in rejected["items"]] == [1, 2]

    applied = files.apply(preview, skip_rejected=True)
    assert (applied["status"], applied["skip_rejected"]) == ("applied", True)
    assert [row["serial_number"] for row in make.get("/items")["items"]] == ["S3"]
    assert make.get("/vendors", filter="name:eq:Acme")["total"] == 0


def test_a_record_changed_after_the_preview_stops_the_whole_apply(
    files: Files, make: Maker, catalog: dict
) -> None:
    one = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", name="one")
    make.item(catalog_entry_hid=catalog["hid"], serial_number="S2", name="two")
    text = (
        "vendor,pid,serial_number,comments\nCisco,C9300-48P,S1,first\nCisco,C9300-48P,S2,second\n"
    )
    preview = files.preview("items", text)
    assert counts(preview["job"]) == (0, 2, 0, 0)
    make.patch(f"/items/{one['hid']}", {"row_version": one["row_version"], "name": "uno"})

    refused = files.apply(preview, expect=409)
    assert refused["title"] == "Preview out of date"
    assert list(errors(refused)) == ["rows.1"]
    assert "changed since the preview" in errors(refused)["rows.1"]
    assert [row["comments"] for row in make.get("/items")["items"]] == [None, None]
    job = make.get(f"/imports/{preview['job']['hid']}")
    assert (job["status"], job["applied_at"]) == ("failed", None)
    assert "preview again" in job["failure"]
    # A failed preview is not applied a second time either.
    assert files.apply(preview, expect=409)["title"] == "Conflict"
    assert counts(files.preview("items", text)["job"]) == (0, 2, 0, 0)


def test_a_row_that_was_unchanged_must_still_be_as_it_was_previewed(
    files: Files, make: Maker, catalog: dict
) -> None:
    item = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", name="one")
    preview = files.preview("items", "vendor,pid,serial_number,name\nCisco,C9300-48P,S1,one\n")
    assert counts(preview["job"]) == (0, 0, 1, 0)
    make.patch(f"/items/{item['hid']}", {"row_version": 1, "comments": "touched"})
    assert list(errors(files.apply(preview, expect=409))) == ["rows.1"]


def test_another_with_the_inventory_role_may_apply_a_preview_and_only_once(
    files: Files, client: TestClient, admin: dict[str, str], viewer: dict[str, str], catalog: dict
) -> None:
    text = "vendor,pid,serial_number\nCisco,C9300-48P,S1\n"
    preview = files.preview("items", text)
    Files(client, viewer).preview("items", text, expect=403)
    assert Files(client, viewer).apply(preview, expect=403)["title"] == "Not allowed"
    # One person prepared it. Another looks it over and applies it.
    applied = Files(client, admin).apply(preview)
    assert (applied["status"], applied["created_by_name"], applied["applied_by_name"]) == (
        "applied",
        "ivy",
        "ada",
    )
    assert "applied already" in files.apply(preview, expect=409)["detail"]
    event = client.get(f"{API}/audit-events?action=apply", headers=admin).json()["items"][0]
    assert event["actor_name"] == "ada"
    # Anybody who may read the inventory may read a preview and the list of them.
    listed = client.get(f"{API}/imports", headers=viewer).json()
    assert [job["hid"] for job in listed["items"]] == [preview["job"]["hid"]]


def test_create_mode_refuses_a_row_that_matches(files: Files, make: Maker, catalog: dict) -> None:
    make.item(catalog_entry_hid=catalog["hid"], serial_number="S1")
    preview = files.preview(
        "items", "vendor,pid,serial_number\nCisco,C9300-48P,S1\nCisco,C9300-48P,S2\n", mode="create"
    )
    assert [row["outcome"] for row in preview["rows"]] == ["rejected", "create"]
    assert "exists already" in preview["rows"][0]["reasons"][0]["message"]


def test_two_rows_that_name_one_record_reject_the_second(files: Files, catalog: dict) -> None:
    preview = files.preview(
        "items",
        "vendor,pid,serial_number,comments\nCisco,C9300-48P,S1,a\ncisco,C9300-48P,s1,b\n",
    )
    assert [row["outcome"] for row in preview["rows"]] == ["create", "rejected"]
    assert "row 1" in preview["rows"][1]["reasons"][0]["message"]


# --- matching ------------------------------------------------------------------------


def test_items_are_matched_by_hid_then_serial_then_asset_tag_then_name(
    files: Files, make: Maker, catalog: dict
) -> None:
    by_serial = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", asset_tag="AT-1")
    by_tag = make.item(asset_tag="AT-2", name="tagged")
    by_name = make.item(name="Fluke-1")
    make.item(hostname="twin")
    make.item(name="TWIN")
    text = (
        "hid,vendor,pid,serial_number,asset_tag,name,comments\n"
        f"{by_name['hid']},,,,,renamed,by hid\n"
        ",Cisco,C9300-48P,S1,AT-2,,serial wins and the tag then collides\n"
        ",,,,AT-2,tagged-again,by tag\n"
        ",,,,,twin,ambiguous\n"
        ",,,,,brand-new,new\n"
        "01900000-0000-7000-8000-000000000000,,,,,nobody,no such hid\n"
    )
    rows = files.preview("items", text)["rows"]
    assert [row["outcome"] for row in rows] == [
        "update",
        "rejected",
        "update",
        "rejected",
        "create",
        "rejected",
    ]
    assert rows[0]["record_hid"] == by_name["hid"]
    assert rows[1]["reasons"][0]["field"] == "asset_tag"
    assert rows[2]["record_hid"] == by_tag["hid"]
    assert changes(rows[2])["name"] == ("tagged", "tagged-again")
    assert "more than one" in rows[3]["reasons"][0]["message"]
    assert rows[5]["reasons"][0]["field"] == "hid"
    # The row that was refused still says which item it matched.
    assert rows[1]["record_hid"] == by_serial["hid"]


# --- what a file may and may not do --------------------------------------------------


def test_an_import_never_copies_an_inherited_value_down(
    files: Files, make: Maker, catalog: dict
) -> None:
    inheriting = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1")
    make.item(catalog_entry_hid=catalog["hid"], serial_number="S2", est_value="18000.00")
    exported = files.export("items", columns=["serial_number", "est_value", "ldos"])
    assert [row["est_value"] for row in table(exported)] == ["18000.00", "18000.00"]

    preview = files.preview("items", exported)
    assert counts(preview["job"]) == (0, 0, 2, 0)
    files.apply(preview)
    after = make.get(f"/items/{inheriting['hid']}")
    assert (after["est_value"], after["ldos"], after["row_version"]) == (None, None, 1)
    # A value that differs is an override, as anywhere else.
    edited = exported.replace("S1,18000.00", "S1,17000.00")
    assert changes(files.preview("items", edited)["rows"][0]) == {"est_value": (None, "17000.00")}


def test_a_different_state_is_a_transition_under_the_rules(
    files: Files, make: Maker, catalog: dict
) -> None:
    item = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", lifecycle_state="Prod")
    make.item(catalog_entry_hid=catalog["hid"], serial_number="S2", lifecycle_state="Delivered")
    text = (
        "vendor,pid,serial_number,lifecycle_state,expected_online,state_reason\n"
        "Cisco,C9300-48P,S1,Down,,maintenance\n"
        "Cisco,C9300-48P,S2,Prod,,\n"
    )
    preview = files.preview("items", text)
    moved, refused = preview["rows"]
    assert changes(moved) == {
        "lifecycle_state": ("Prod", "Down"),
        "expected_online": (True, False),
        "state_reason": (None, "maintenance"),
    }
    assert refused["reasons"][0]["field"] == "lifecycle_state"
    assert refused["key"] == "Cisco C9300-48P S2"
    assert refused["record_hid"] is not None
    files.apply(preview, skip_rejected=True)
    history = make.get(f"/items/{item['hid']}/history")["items"]
    assert (history[0]["action"], history[0]["via"]) == ("transition", "import")
    # A reason alone, with no move, is not a change an import makes.
    alone = files.preview(
        "items", "vendor,pid,serial_number,state_reason\nCisco,C9300-48P,S1,rma\n"
    )
    assert alone["rows"][0]["reasons"][0]["field"] == "state_reason"


def test_an_import_does_not_retire(files: Files, make: Maker) -> None:
    owner = make.owner("Voice Services")
    text = "label,record_status\nVoice Services,retired\nFacilities,retired\n"
    rows = files.preview("owners", text)["rows"]
    assert [row["outcome"] for row in rows] == ["rejected", "rejected"]
    assert rows[0]["reasons"][0]["field"] == "record_status"
    make.post(f"/owners/{owner['hid']}/retire", {"row_version": 1}, expect=200)
    rows = files.preview("owners", text)["rows"]
    assert rows[0]["outcome"] == "unchanged"
    back = files.preview("owners", "label,record_status\nVoice Services,active\n")
    assert changes(back["rows"][0]) == {"record_status": ("retired", "active")}


def test_every_record_an_import_changes_is_audited_under_one_request(
    files: Files, make: Maker, catalog: dict
) -> None:
    preview = files.preview(
        "items", "vendor,pid,serial_number\nCisco,C9300-48P,S1\nJuniper,EX4400-48P,J1\n"
    )
    files.apply(preview)
    applied = make.audit(action="apply")[0]
    assert (applied["record_type"], applied["record_hid"]) == ("import_job", preview["job"]["hid"])
    shared = make.audit(request_id=applied["request_id"])
    assert sorted((event["record_type"], event["via"]) for event in shared) == [
        ("catalog_entry", "import"),
        ("import_job", "api"),
        ("item", "import"),
        ("item", "import"),
        ("vendor", "import"),
    ]
    assert make.audit(action="preview")[0]["record_hid"] == preview["job"]["hid"]


# --- the other entities, and JSON ----------------------------------------------------


def test_tags_vendors_catalog_entries_and_owners_load_and_load_again(
    files: Files, make: Maker
) -> None:
    loads = {
        "tags": "label,colour,description\nrefresh-2030,#1F6FEB,Due in 2030\n",
        "vendors": "name,aliases,notes\nCisco,Cisco Systems;Cisco Systems Inc,\nJuniper,,\n",
        "catalog_entries": (
            "vendor,pid,kind,type,ldos,est_value,support_weight,stack_discount_pct,"
            "successor_vendor,successor_pid,tags\n"
            "Cisco,C9200L-48P-4G,,switch,2031-04-30,6500,1,,,C9300-48P,\n"
            "Cisco,C9300-48P,hardware,switch,2034-04-30,18000,1.5,30,,,refresh-2030\n"
        ),
        "owners": (
            "label,organization,is_external,exception_reason\n"
            "Network Engineering,Infrastructure,no,\n"
            "Facilities,Corporate Services,yes,Owns the building management network\n"
        ),
    }
    for entity, text in loads.items():
        assert files.load(entity, text)["rejected"] == 0
    old, new = make.get("/catalog-entries", sort="pid")["items"]
    assert old["successor_hid"] == new["hid"]
    # The successor was named before its own row: that row made it, and it is reviewed.
    assert (new["review_status"], new["stack_discount_pct"], new["tags"]) == (
        "reviewed",
        "30",
        ["refresh-2030"],
    )
    assert make.get("/vendors", filter="name:eq:Cisco")["items"][0]["aliases"] == [
        "Cisco Systems",
        "Cisco Systems Inc",
    ]
    assert make.get("/owners", filter="is_external:eq:true")["items"][0]["label"] == "Facilities"
    for entity, text in loads.items():
        job = files.preview(entity, text)["job"]
        assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0), entity


def test_a_vendor_found_by_an_alias_is_not_renamed(files: Files, make: Maker) -> None:
    make.vendor("Cisco", aliases=["Cisco Systems"])
    preview = files.preview("vendors", "name,notes\nCisco Systems,Renewal in March\n")
    assert changes(preview["rows"][0]) == {"notes": (None, "Renewal in March")}


def test_json_names_its_entity_and_null_clears(files: Files, make: Maker, catalog: dict) -> None:
    item = make.item(
        catalog_entry_hid=catalog["hid"], serial_number="S1", comments="c", est_value="1.00"
    )
    envelope = {
        "schema": "hirdir/1",
        "entity": "items",
        "mode": "upsert",
        "records": [
            {
                "vendor": "Cisco",
                "pid": "C9300-48P",
                "serial_number": "S1",
                "comments": "",
                "est_value": None,
                "quantity": 3,
                "tags": ["refresh-2030"],
                "expected_online": None,
            }
        ],
    }
    preview = files.preview(None, envelope)
    assert changes(preview["rows"][0]) == {
        "est_value": ("1.00", None),
        "quantity": (1, 3),
        "tags": ([], ["refresh-2030"]),
    }
    files.apply(preview)
    assert make.get(f"/items/{item['hid']}")["comments"] == "c"
    files.preview("owners", envelope, expect=422)
    files.preview(None, {**envelope, "schema": "other/9"}, expect=422)
    files.preview(None, {**envelope, "extra": 1}, expect=422)


# --- files that are refused whole ----------------------------------------------------


def test_an_unknown_column_rejects_the_file_and_a_read_only_one_is_passed_over(
    files: Files, make: Maker, catalog: dict
) -> None:
    refused = files.preview("items", "serial_number,location\nS1,Room 102\n", expect=422)
    assert "'location' is not a column of items" in errors(refused)["column"]
    assert make.get("/imports")["total"] == 0
    passed = files.preview(
        "items",
        "vendor,pid,serial_number,model_name,est_value_source,updated_at,row_version\n"
        "Cisco,C9300-48P,S1,Whatever,own,2020-01-01T00:00:00Z,99\n",
    )
    assert counts(passed["job"]) == (1, 0, 0, 0)
    assert set(changes(passed["rows"][0])) == {
        "vendor",
        "pid",
        "serial_number",
        "quantity",
        "record_status",
    }


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("", "no header row"),
        ("serial_number,serial_number\nS1,S2\n", "named twice"),
        ('serial_number\n"S1\n', "CSV"),
    ],
)
def test_a_file_that_cannot_be_read_is_refused(files: Files, text: str, said: str) -> None:
    refused = files.preview("items", text, expect=422)
    assert said in " ".join(errors(refused).values())


def test_the_file_needs_an_entity_a_known_format_and_a_size_within_the_limit(
    files: Files, client: TestClient, inventory: dict[str, str], monkeypatch
) -> None:
    assert "entity" in errors(files.preview(None, "name\nCisco\n", expect=422))
    unknown = client.post(
        f"{API}/imports/preview?entity=vendors",
        content=b"name\nCisco\n",
        headers={**inventory, "Content-Type": "application/octet-stream"},
    )
    assert unknown.status_code == 422
    by_name = client.post(
        f"{API}/imports/preview?entity=vendors&file_name=vendors.csv",
        content=b"\xef\xbb\xbfname\nCisco\n",  # a byte-order mark, as a spreadsheet writes
        headers={**inventory, "Content-Type": "application/octet-stream"},
    )
    assert by_name.status_code == 201
    assert by_name.json()["rows"][0]["outcome"] == "create"

    from hirdir.io import files as rules

    monkeypatch.setattr(rules, "MAX_ROWS", 2)
    too_long = files.preview("vendors", "name\nA\nB\nC\n", expect=413)
    assert "at most 2 rows" in too_long["detail"]


def test_a_formula_is_written_with_an_apostrophe_and_read_back_without(
    files: Files, make: Maker
) -> None:
    make.item(name="=cmd|' /C calc'!A0", comments="-1+1", hostname="plain")
    exported = files.export("items", columns=["name", "comments", "hostname"])
    row = table(exported)[0]
    assert (row["name"], row["comments"], row["hostname"]) == (
        "'=cmd|' /C calc'!A0",
        "'-1+1",
        "plain",
    )
    assert counts(files.preview("items", exported)["job"]) == (0, 0, 1, 0)


# --- export --------------------------------------------------------------------------


def test_export_takes_the_filter_the_sort_and_the_columns_of_a_list(
    files: Files, make: Maker, catalog: dict
) -> None:
    for number, state in enumerate(("Prod", "Test", "Prod"), start=1):
        make.item(
            catalog_entry_hid=catalog["hid"],
            serial_number=f"S{number}",
            hostname=f"site2-sw-{number}",
            lifecycle_state=state,
        )
    text = files.export(
        "items",
        filter="lifecycle_state:eq:Prod",
        sort=["-hostname"],
        columns=["hostname", "catalog.pid", "effective.ldos", "est_value"],
        include_sources=True,
    )
    lines = text.splitlines()
    assert lines[0] == "hid,hostname,pid,ldos,ldos_source,est_value,est_value_source"
    rows = table(text)
    assert [row["hostname"] for row in rows] == ["site2-sw-3", "site2-sw-1"]
    assert rows[0]["ldos"] == "2034-04-30"
    assert rows[0]["ldos_source"] == "catalog"
    assert all(len(row["hid"]) == 36 for row in rows)

    own = table(files.export("items", own_values=True))[0]
    assert (own["ldos"], own["est_value"], own["expected_online"]) == ("", "", "true")
    chosen = files.export("items", hids=[rows[1]["hid"]], columns=["hostname"])
    assert [row["hostname"] for row in table(chosen)] == ["site2-sw-1"]


def test_json_export_is_an_envelope_that_imports_as_it_is(
    files: Files, make: Maker, catalog: dict
) -> None:
    make.item(
        catalog_entry_hid=catalog["hid"],
        serial_number="S1",
        lifecycle_state="Prod",
        tags=["refresh-2030"],
        quantity=2,
    )
    envelope = json.loads(files.export("items", format="json", own_values=True))
    assert (envelope["schema"], envelope["entity"], envelope["mode"]) == (
        "hirdir/1",
        "items",
        "upsert",
    )
    record = envelope["records"][0]
    assert (record["quantity"], record["expected_online"], record["tags"], record["est_value"]) == (
        2,
        True,
        ["refresh-2030"],
        None,
    )
    assert counts(files.preview(None, envelope)["job"]) == (0, 0, 1, 0)
    assert json.loads(files.export("tags", format="json"))["records"][0]["label"] == "refresh-2030"


def test_export_is_for_every_role_and_refuses_what_a_list_refuses(
    files: Files, client: TestClient, viewer: dict[str, str], make: Maker
) -> None:
    make.item(name="one")
    seen = client.post(f"{API}/exports", json={"entity": "items"}, headers=viewer)
    assert seen.status_code == 200
    assert seen.headers["content-type"].startswith("text/csv")
    assert seen.headers["content-disposition"].startswith('attachment; filename="hirdir-items-')
    assert "set-cookie" not in seen.headers
    assert client.post(f"{API}/exports", json={"entity": "items"}).status_code == 401
    assert "columns" in errors(files.refused_export("items", columns=["nonsense"]))
    assert "filter" in errors(files.refused_export("items", filter="name:regex:("))
    assert "filter" in errors(files.refused_export("items", filter="nonsense:eq:1"))
    files.refused_export("contracts")


def test_export_leaves_out_what_a_list_leaves_out(files: Files, make: Maker) -> None:
    make.item(name="active")
    make.item(name="draft", record_status="draft")
    gone = make.item(name="gone")
    make.post(f"/items/{gone['hid']}/retire", {"row_version": 1}, expect=200)
    names = lambda **more: [row["name"] for row in table(files.export("items", **more))]  # noqa: E731
    assert names() == ["active"]
    assert names(include_drafts=True, include_archived=True) == ["active", "draft", "gone"]
    # Named by its HID, a record is exported whatever its status: it was selected.
    assert names(hids=[gone["hid"]]) == ["gone"]
    assert names(hids=[gone["hid"]], filter="name:eq:active") == []


# --- a large preview holds nobody up -------------------------------------------------


def test_a_large_preview_is_tried_on_a_copy_and_holds_no_other_change_up(
    files: Files, make: Maker, catalog: dict, config, monkeypatch
) -> None:
    from hirdir.db.engine import make_engine, make_sessions
    from hirdir.domain import audit, owners
    from hirdir.io import imports

    work = imports._work
    saved_meanwhile: list[str] = []

    def work_while_another_saves(trying, *arguments, **more):
        results = work(trying, *arguments, **more)
        # The rows are worked and not yet undone. Somebody else saves a change now.
        with make_sessions(make_engine(config.database_url))() as another:
            another.connection().exec_driver_sql("PRAGMA busy_timeout=200")
            label = f"Voice Services {len(saved_meanwhile) + 1}"
            owner = owners.create_owner(another, audit.SYSTEM, {"label": label})
            another.commit()
            saved_meanwhile.append(owner.hid)
        return results

    monkeypatch.setattr(imports, "_work", work_while_another_saves)
    monkeypatch.setattr(imports, "IN_PLACE_UP_TO", 1)
    text = (
        "vendor,pid,serial_number,owner\n"
        "Cisco,C9300-48P,S1,Network Engineering\n"
        "Juniper,EX4400-48P,J1,\n"
        "Cisco,C9300-48P,S2,Nobody\n"
    )
    preview = files.preview("items", text)
    assert len(saved_meanwhile) == 1
    assert counts(preview["job"]) == (2, 0, 0, 1)
    assert preview["rows"][1]["notes"][0] == "creates the vendor Juniper, to be reviewed"
    assert make.get("/items")["total"] == 0
    assert make.get("/vendors")["total"] == 1
    monkeypatch.setattr(imports, "_work", work)
    assert files.apply(preview, skip_rejected=True)["status"] == "applied"
    assert make.get("/items")["total"] == 2
    # Tried in place, the same preview is the same, and it does hold the other up.
    monkeypatch.setattr(imports, "_work", work_while_another_saves)
    monkeypatch.setattr(imports, "IN_PLACE_UP_TO", 100)
    busy = files.preview("items", text.replace("S1", "S8"), expect=503)
    assert busy["title"] == "Busy"
    assert len(saved_meanwhile) == 1


def test_a_change_that_waits_too_long_behind_another_is_told_to_try_again(
    make: Maker, inventory: dict[str, str], config, monkeypatch
) -> None:
    from sqlalchemy import text

    from hirdir.app import create_app
    from hirdir.db import engine as engine_module

    holder = engine_module.make_engine(config.database_url)
    # An application that waits a tenth of a second for its turn, and not five.
    monkeypatch.setitem(engine_module.SQLITE_PRAGMAS, "busy_timeout", 100)
    with TestClient(create_app(config)) as impatient, holder.connect() as writing:
        writing.execute(text("BEGIN IMMEDIATE"))
        waited = impatient.post(f"{API}/owners", json={"label": "Late"}, headers=inventory)
        writing.execute(text("ROLLBACK"))
        assert waited.status_code == 503
        assert waited.headers["retry-after"] == "5"
        assert waited.json()["title"] == "Busy"
        assert make.get("/owners")["total"] == 0
        again = impatient.post(f"{API}/owners", json={"label": "Late"}, headers=inventory)
        assert again.status_code == 201


# --- found by review -----------------------------------------------------------------


def test_an_apply_that_fails_after_its_work_leaves_nothing_behind(
    files: Files,
    make: Maker,
    client: TestClient,
    inventory: dict[str, str],
    catalog: dict,
    monkeypatch,
) -> None:
    from hirdir.io import imports

    preview = files.preview("items", "vendor,pid,serial_number\nCisco,C9300-48P,S1\n")
    record = imports.audit.record

    def fails_at_the_end(db, context, action, *more, **named):
        if action == "apply":
            raise RuntimeError("the server stopped here")
        return record(db, context, action, *more, **named)

    monkeypatch.setattr(imports.audit, "record", fails_at_the_end)
    with TestClient(client.app, raise_server_exceptions=False) as failing:
        path = f"{API}/imports/{preview['job']['hid']}/apply"
        assert failing.post(path, headers=inventory).status_code == 500
    monkeypatch.setattr(imports.audit, "record", record)
    assert make.get("/items")["total"] == 0
    assert make.audit(record_type="item") == []
    assert make.get(f"/imports/{preview['job']['hid']}")["status"] == "previewed"
    assert files.apply(preview)["status"] == "applied"
    assert make.get("/items")["total"] == 1


def test_a_catalog_entrys_inherited_discount_is_never_copied_down(
    files: Files, make: Maker
) -> None:
    vendor = make.vendor()
    inheriting = make.entry(vendor, "C9300-48P")
    make.entry(vendor, "EX4400-48P", stack_discount_pct="30")
    exported = files.export("catalog_entries", columns=["vendor", "pid", "stack_discount_pct"])
    assert [row["stack_discount_pct"] for row in table(exported)] == ["50", "30"]
    assert counts(files.preview("catalog_entries", exported)["job"]) == (0, 0, 2, 0)
    as_json = json.loads(files.export("catalog_entries", format="json"))
    assert counts(files.preview(None, as_json)["job"]) == (0, 0, 2, 0)
    new = files.preview("catalog_entries", "vendor,pid,stack_discount_pct\nCisco,NEW-1,50\n")
    assert "stack_discount_pct" not in changes(new["rows"][0])
    edited = files.preview("catalog_entries", exported.replace("C9300-48P,50", "C9300-48P,40"))
    assert changes(edited["rows"][0]) == {"stack_discount_pct": (None, "40")}
    assert make.get(f"/catalog-entries/{inheriting['hid']}")["stack_discount_pct"] is None


def test_a_row_that_changes_the_model_does_not_keep_the_old_models_values(
    files: Files, make: Maker, catalog: dict
) -> None:
    vendor = make.get("/vendors")["items"][0]
    make.entry(vendor, "C9200L-48P-4G", est_value="6500.00", ldos="2031-10-31")
    item = make.item(catalog_entry_hid=catalog["hid"], serial_number="S1", name="one")
    exported = files.export("items", columns=["name", "pid", "vendor", "est_value", "ldos"])
    moved = exported.replace("C9300-48P", "C9200L-48P-4G")
    preview = files.preview("items", moved)
    assert changes(preview["rows"][0]) == {"pid": ("C9300-48P", "C9200L-48P-4G")}
    files.apply(preview)
    after = make.get(f"/items/{item['hid']}")
    assert (after["est_value"], after["ldos"]) == (None, None)
    assert after["effective"]["est_value"]["value"] == "6500.00"


def test_a_later_row_may_name_an_earlier_new_row_of_the_same_file(
    files: Files, make: Maker
) -> None:
    make.vendor()
    text = "vendor,pid,successor_pid\nCisco,NEW-A,\nCisco,NEW-B,NEW-A\nNewco,N-1,\nNewco,N-2,N-1\n"
    preview = files.preview("catalog_entries", text)
    assert [row["outcome"] for row in preview["rows"]] == ["create"] * 4
    assert preview["rows"][3]["notes"] == []
    files.apply(preview)
    assert make.get("/catalog-entries", filter="review_status:eq:unreviewed")["total"] == 0


def test_an_apply_never_makes_a_record_the_preview_did_not_show(
    files: Files, make: Maker, catalog: dict
) -> None:
    preview = files.preview("items", "vendor,pid,serial_number\nCisco,C9300-48P,S1\n")
    assert preview["rows"][0]["notes"] == []
    make.patch(f"/catalog-entries/{catalog['hid']}", {"row_version": 1, "pid": "C9300-48P-A"})
    refused = files.apply(preview, expect=409)
    assert list(errors(refused)) == ["rows.1"]
    assert make.get("/catalog-entries")["total"] == 1
    assert make.get("/items")["total"] == 0


def test_a_draft_known_only_by_its_name_is_not_made_twice(files: Files, make: Maker) -> None:
    text = "name,record_status\nsite3-planned-sw-01,draft\n"
    files.load("items", text)
    assert counts(files.preview("items", text)["job"]) == (0, 0, 1, 0)
    twice = files.preview("items", "name,record_status\nsite3-sw-02,draft\nSITE3-SW-02,draft\n")
    assert [row["outcome"] for row in twice["rows"]] == ["create", "rejected"]


def test_text_no_database_can_hold_is_a_rejected_row_and_never_a_500(
    files: Files, client: TestClient, inventory: dict[str, str], make: Maker
) -> None:
    envelope = '{"schema": "hirdir/1", "entity": "tags", "records": [{"label": "bad\\ud800"}]}'
    sent = client.post(
        f"{API}/imports/preview",
        content=envelope,
        headers={**inventory, "Content-Type": "application/json"},
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["rows"][0]["reasons"][0]["field"] == "label"
    nested = client.post(
        f"{API}/imports/preview",
        content="[" * 200_000,
        headers={**inventory, "Content-Type": "application/json"},
    )
    assert nested.status_code == 422
    make.item(name="one")
    in_bulk = client.post(
        f"{API}/items/bulk-update",
        content='{"all_rows": true, "set": {"comments": "bad\\ud800"}}',
        headers={**inventory, "Content-Type": "application/json"},
    )
    assert in_bulk.status_code == 422


def test_an_apostrophe_of_the_values_own_survives_export_and_import(
    files: Files, make: Maker
) -> None:
    item = make.item(name="one", comments="'=kept", description="'-5 below")
    exported = files.export("items", columns=["name", "comments", "description"])
    row = table(exported)[0]
    assert (row["comments"], row["description"]) == ("''=kept", "''-5 below")
    assert counts(files.preview("items", exported)["job"]) == (0, 0, 1, 0)
    assert make.get(f"/items/{item['hid']}")["comments"] == "'=kept"
    refused = make.post("/vendors", {"name": "Example", "aliases": ["Example; Software"]}, 422)
    assert "aliases" in errors(refused)


def test_a_site_may_raise_or_lower_the_largest_file_in_its_configuration(
    config, inventory: dict[str, str], tmp_path
) -> None:
    from dataclasses import replace

    from hirdir import config as config_module
    from hirdir.app import create_app

    assert config.max_file_megabytes == 20
    path = tmp_path / "site.toml"
    path.write_text("[files]\nmax_megabytes = 50\n")
    assert config_module.load(path).max_file_bytes == 50 * 1024 * 1024
    with TestClient(create_app(replace(config, max_file_megabytes=1))) as small:
        headers = {**inventory, "Content-Type": "text/csv"}
        body = b"label,description\n" + b"x" * (1024 * 1024)
        refused = small.post(f"{API}/imports/preview?entity=tags", content=body, headers=headers)
        assert refused.status_code == 413
        assert "at most 1 MB" in refused.json()["detail"]
        fits = small.post(
            f"{API}/imports/preview?entity=tags", content=b"label\nlab\n", headers=headers
        )
        assert fits.status_code == 201
