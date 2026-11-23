"""The records of a file of items read back together, 50 rows at a time (P-324).

What a row changed is what its record reads as right after its own write. These files
have later rows that change what an earlier row's record reads as: the item it names as
its host or the item it was seen on renamed, another item made to answer to the text its
parent is written as, in one batch and across the edge of one. Each is previewed as
0.9.18 previewed it, each row read back after its own write, and as it is now, and the
two answer the same row for row; and the apply, which reads its batches back together,
does what the preview of 0.9.18 said, row for row, with no row stale.
"""

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import Item
from hirdir.domain import audit, catalog, groups, items
from hirdir.io import entities, examples, imports
from tests.api.inventory import API, Maker
from tests.api.test_files import Files
from tests.api.test_hosting import Lab

HEAD = "hid,vendor,pid,serial_number,asset_tag,name,parent,host,observed_host,comments"


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def rows_of(files: Files, preview: dict[str, Any]) -> list[dict[str, Any]]:
    """Every row of a preview, in the order of the file."""
    response = files.client.get(
        f"{API}/imports/{preview['job']['hid']}/rows", params={"limit": 1000}, headers=files.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def as_said(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """What a preview says of each row, without what a preview made and threw away."""
    return [
        (row["row"], row["outcome"], row["key"], row["changes"], row["notes"], row["reasons"])
        for row in rows
    ]


def preview_one_at_a_time(files: Files, text: str, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Preview as 0.9.18 did: each row read back after its own write."""
    with monkeypatch.context() as patch:
        patch.setattr(entities.Items, "reads_together", False)
        return files.preview("items", text)


def filler(number: int) -> str:
    """A row of a new switch that leans on nothing else in the file."""
    return f",Cisco,N7K-C7010,FILL{number:04d},,site2-fill-{number:02d},,,,"


def renaming_file(lab: Lab, first: int) -> str:
    """A file whose rows from `first` on change what the rows just before them read as."""
    sw = lab.make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number="SWP0001", name="site2-sw-01"
    )
    rows = [filler(number) for number in range(1, first)]
    rows += [
        # A context on the first server, seen on the second; then the first is given
        # another serial number, which is the text its host is written as, and the
        # second another name, which is not, and an asset tag, which is.
        ",Example Virtual,VDC,,,site2-vdc-a,,site2-esx-01,site2-esx-02,",
        f"{lab.esx['hid']},Example Virtual,SRV-2U,SRV0000X009,,site2-esx-01,,,,renamed",
        f"{lab.esx2['hid']},Example Virtual,SRV-2U,SRV0000X002,ESX-TAG-2,site2-esx-02b,,,,",
        # A minor item in the switch, whose parent is written as its serial number;
        # then a minor item of another chassis is made with that text as its asset tag,
        # which makes it no longer the switch's alone.
        ",Cisco,PWR-C1,PSU0001,,,site2-sw-01,,,",
        ",Cisco,PWR-C1,PSU0002,SWP0001,,site2-n7k-01,,,",
        # A second context on the second server, by its new name: the count of what
        # runs on it, which the read of its own row shows, changes.
        ",Example Virtual,VDC,,,site2-vdc-b,,site2-esx-02b,,",
    ]
    assert sw["serial_number"] == "SWP0001"
    return "\n".join([HEAD, *rows]) + "\n"


@pytest.mark.parametrize("first", [1, 46, 50], ids=["first-rows", "in-one-batch", "over-an-edge"])
def test_a_later_row_that_changes_what_an_earlier_one_reads_as_is_read_after_it(
    lab: Lab, files: Files, monkeypatch: pytest.MonkeyPatch, first: int
) -> None:
    lab.make.entry({"hid": lab.switch_model["vendor_hid"]}, "PWR-C1")
    text = renaming_file(lab, first)
    then = preview_one_at_a_time(files, text, monkeypatch)
    now = files.preview("items", text)
    said = rows_of(files, now)
    assert now["job"]["rejected"] == then["job"]["rejected"] == 0, said
    assert len(said) == first + 5
    assert as_said(said) == as_said(rows_of(files, then))
    by_row = {row["row"]: row for row in said}
    context = {entry["field"]: entry["new"] for entry in by_row[first]["changes"]}
    # As it read after its own row: its host and the item it was seen on each by the
    # serial number it had then, the one before it had another and the other an asset tag.
    assert (context["host"], context["observed_host"]) == ("SRV0000X001", "SRV0000X002")
    psu = {entry["field"]: entry["new"] for entry in by_row[first + 3]["changes"]}
    assert psu["parent"] == "SWP0001"
    # The apply, which reads its batches back together, does what 0.9.18 previewed.
    job = files.apply(then)
    assert (job["status"], job["applied"], job["stale"]) == ("applied", first + 5, 0)


def test_a_row_that_no_longer_does_what_was_previewed_is_left_out_before_the_rows_after_it(
    make: Maker, files: Files
) -> None:
    cisco = make.vendor("Cisco")
    make.entry(cisco, "M1")
    priced = make.entry(cisco, "M2", est_value="100.00")
    make.entry(cisco, "PWR")
    text = (
        "vendor,pid,serial_number,parent,est_value\n"
        "Cisco,M1,S-A,,\n"
        # The value its model has: it says nothing new, and the item inherits it.
        "Cisco,M2,S-B,,100.00\n"
        "Cisco,PWR,S-C,S-B,\n"
        "Cisco,M1,S-D,,\n"
    )
    preview = files.preview("items", text)
    assert preview["job"]["created"] == 4
    assert "est_value" not in {entry["field"] for entry in preview["rows"][1]["changes"]}
    # After the preview the model is valued otherwise: the row would now give its item a
    # value of its own, which is a change the preview did not say, and nothing else.
    make.patch(f"/catalog-entries/{priced['hid']}", {"row_version": 1, "est_value": "200.00"})
    job = files.apply(preview)
    assert (job["status"], job["applied"], job["stale"]) == ("applied", 2, 1)
    found = make.get(f"/imports/{job['hid']}/rows", limit=10)["items"]
    assert [row["applied_outcome"] for row in found] == ["create", "stale", "rejected", "create"]
    assert found[1]["applied_reasons"][0]["message"].startswith(
        "would no longer do what was previewed"
    )
    # The power supply was to go into the switch that the stale row did not make.
    assert found[2]["applied_reasons"][0]["field"] == "parent"
    assert {item["serial_number"] for item in make.get("/items")["items"]} == {"S-A", "S-D"}


def test_only_a_file_of_items_is_read_back_together_and_holds_what_it_cannot_change() -> None:
    together = {name for name, which in entities.ENTITIES.items() if which.reads_together}
    holding = {name for name, which in entities.ENTITIES.items() if which.holds}
    assert together == holding == {"items"}


def test_a_record_read_before_its_batch_is_read_again_where_an_earlier_row_changed_it(
    lab: Lab, files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    make = lab.make
    psu = make.entry({"hid": lab.switch_model["vendor_hid"]}, "PWR-C1")
    chassis = make.item(
        catalog_entry_hid=lab.switch_model["hid"], serial_number="SWP0002", asset_tag="AT-OLD"
    )
    module = make.item(
        catalog_entry_hid=psu["hid"], serial_number="PSU0003", parent_item_hid=chassis["hid"]
    )
    other = make.item(catalog_entry_hid=lab.switch_model["hid"], serial_number="SWP0003")
    # An export loaded back after the chassis was given a new asset tag in it: the row of
    # the module says its parent as the chassis is called by then, which is no change.
    text = (
        "hid,asset_tag,parent,comments\n"
        f"{chassis['hid']},AT-NEW,,\n"
        f"{other['hid']},,,untouched by the rest\n"
        f"{module['hid']},,AT-NEW,checked\n"
    )
    then = preview_one_at_a_time(files, text, monkeypatch)
    now = files.preview("items", text)
    said = rows_of(files, now)
    assert as_said(said) == as_said(rows_of(files, then))
    assert [row["outcome"] for row in said] == ["update", "update", "update"]
    assert {entry["field"] for entry in said[2]["changes"]} == {"comments"}
    job = files.apply(then)
    assert (job["status"], job["applied"], job["stale"]) == ("applied", 3, 0)


def test_what_a_batch_holds_is_looked_up_again_for_the_next_batch(
    make: Maker, files: Files, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = make.layout()["room"]
    make.entry(make.vendor("Cisco"), "C9300-48P")
    path = "Americas > Central > Site-2 > Building 1 > Room 102"
    text = "vendor,pid,serial_number,location\n" + "".join(
        f"Cisco,C9300-48P,HLD{number:04d},{path}\n" for number in range(1, 61)
    )
    preview = files.preview("items", text)
    assert preview["job"]["created"] == 60
    applied = imports._apply_batch
    renamed: list[str] = []

    def somebody_renames_the_room_between_two_batches(db, run, which, hid, batch, typed):
        done = applied(db, run, which, hid, batch, typed)
        if not renamed:
            body = {"row_version": room["row_version"], "name": "Room 202"}
            renamed.append(make.patch(f"/locations/{room['hid']}", body)["name"])
        return done

    monkeypatch.setattr(imports, "_apply_batch", somebody_renames_the_room_between_two_batches)
    job = files.apply(preview)
    assert renamed == ["Room 202"]
    # The second batch finds the room by its path again, and it is no longer there.
    assert (job["status"], job["applied"], job["stale"]) == ("applied", 50, 0)
    found = make.get(f"/imports/{job['hid']}/rows", limit=100)["items"]
    assert {row["applied_outcome"] for row in found[50:]} == {"rejected"}
    assert {row["applied_reasons"][0]["field"] for row in found[50:]} == {"location"}


@pytest.fixture(scope="module")
def with_examples(tmp_path_factory: pytest.TempPathFactory, migrated: Path) -> Path:
    """A database with the examples loaded, and items run on hosts and in a stack."""
    folder = tmp_path_factory.mktemp("compared")
    made = Config(state_dir=folder)
    assert made.database_path is not None
    shutil.copyfile(migrated, made.database_path)
    engine = make_engine(made.database_url)
    with make_sessions(engine)() as db:
        examples.load(db, examples.folder())
        hosts = list(db.scalars(select(Item).where(Item.parent_item_hid.is_(None)).limit(2)))
        vendor = catalog.create_vendor(db, audit.SYSTEM, {"name": "Example Virtual"})
        model = catalog.create_entry(
            db, audit.SYSTEM, {"vendor_hid": vendor.hid, "pid": "VM", "kind": "virtual_machine"}
        )
        cluster = groups.create_group(db, audit.SYSTEM, {"type": "cluster", "name": "ex-hosts"})
        db.flush()
        groups.add_members(db, audit.SYSTEM, cluster.hid, [{"item_hid": hosts[1].hid}])
        on = (
            {"host_item_hid": hosts[0].hid, "observed_host_hid": hosts[1].hid},
            {"host_group_hid": cluster.hid},
        )
        for number, host in enumerate(on):
            items.create_item(
                db,
                audit.SYSTEM,
                {"catalog_entry_hid": model.hid, "name": f"ex-vm-{number}", **host},
            )
        db.commit()
    engine.dispose()
    return made.database_path


def test_an_item_read_as_a_row_compares_it_reads_as_it_always_did_in_what_a_row_sets(
    with_examples: Path,
) -> None:
    # A row's changes are made of the columns a row sets, read as they are stored: the
    # read for a file leaves out what is worked out in force and beside them, and reads
    # each of those columns as the whole read does, for every item of the examples.
    engine = make_engine(f"sqlite:///{with_examples}")
    which = entities.Items()
    try:
        with make_sessions(engine)() as db:
            found = list(db.scalars(select(Item).order_by(Item.hid)))
            whole = which.read(db, found)
            compared = which.read(db, found, compared=True)
    finally:
        engine.dispose()
    assert len(found) > 30
    names = [column.name for column in which.settable] + ["hid", "row_version", "updated_at"]
    assert any(row["parent"] for row in whole)
    assert any(row["host"] for row in whole)
    assert any(row["observed_host"] for row in whole)
    assert any(row["host_group"] for row in whole)
    for one, other in zip(whole, compared, strict=True):
        assert {name: one[name] for name in names} == {name: other[name] for name in names}
    assert "covered" not in compared[0]
    assert "owner_source" not in compared[0]
