"""Several items or device groups retired at once, and an Admin's deletion of those that
were a mistake (P-227, P-228, P-236)."""

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.domain import contracts as contract_rules
from hirdir.domain import errors as domain_errors
from hirdir.domain import items as item_rules
from hirdir.domain import removal
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files
from tests.api.test_hardening import _together

NOBODY = "01900000-0000-7000-8000-000000000000"


def _switches(make: Maker, count: int, prefix: str = "site9-sw-wrong") -> list[dict[str, Any]]:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    entry = entries[0] if entries else make.entry(vendor)
    return make.switches(entry, prefix, count)


def _retire(
    client: TestClient, headers: dict[str, str], path: str, hids: list[str], expect: int = 200
) -> dict[str, Any]:
    response = client.post(f"{API}{path}/retire", json={"hids": hids}, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


# --- several retired at once (P-228) --------------------------------------------------


def test_the_items_ticked_are_retired_by_one_request_each_as_its_page_retires_it(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    one, two, three = _switches(make, 3)
    stack = make.stack("site9-sw-stack-wrong", [one, two])
    make.post(f"/items/{three['hid']}/retire", {"row_version": three["row_version"]}, 200)

    named = [one["hid"], two["hid"], three["hid"], NOBODY, one["hid"]]
    done = _retire(client, inventory, "/items", named)

    assert done == {
        "dry_run": False,
        "retired": [
            {"hid": one["hid"], "label": "site9-sw-wrong-01"},
            {"hid": two["hid"], "label": "site9-sw-wrong-02"},
        ],
        # Retired before: counted, and not refused.
        "already": [{"hid": three["hid"], "label": "site9-sw-wrong-03"}],
        "refused": [],
        "missing": [NOBODY],
        # Nothing runs on a switch here (P-247).
        "hosted": [],
    }
    for item in (one, two):
        assert make.get(f"/items/{item['hid']}")["record_status"] == "retired"
        events = make.audit(record_hid=item["hid"], action="retire")
        assert len(events) == 1
        assert events[0]["request_id"]
    # As on its page: a retired item is in no stack any more, and the list leaves it out.
    assert make.members(stack) == []
    assert one["hid"] not in [row["hid"] for row in make.get("/items")["items"]]
    shown = make.get("/items", include_archived="true")["items"]
    assert one["hid"] in [row["hid"] for row in shown]
    # Brought back as before.
    back = make.get(f"/items/{one['hid']}")
    make.patch(
        f"/items/{one['hid']}", {"row_version": back["row_version"], "record_status": "active"}
    )


def test_device_groups_are_retired_several_at_once_and_their_memberships_end(
    client: TestClient, make: Maker, inventory: dict[str, str]
) -> None:
    one, two = _switches(make, 2)
    first = make.stack("site9-stack-a", [one])
    second = make.stack("site9-stack-b", [two])

    done = _retire(client, inventory, "/device-groups", [first["hid"], second["hid"]])

    assert [entry["label"] for entry in done["retired"]] == ["site9-stack-a", "site9-stack-b"]
    assert make.members(first) == []
    assert make.members(second) == []
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"
    events = make.audit(record_type="device_group", action="retire")
    assert {event["record_hid"] for event in events} == {first["hid"], second["hid"]}


def test_retiring_several_is_for_the_inventory_role_and_takes_at_most_a_thousand(
    client: TestClient, make: Maker, viewer: dict[str, str], inventory: dict[str, str]
) -> None:
    (one,) = _switches(make, 1)

    assert _retire(client, viewer, "/items", [one["hid"]], 403)
    assert _retire(client, viewer, "/device-groups", [one["hid"]], 403)
    too_many = [NOBODY] * 1001
    assert "hids" in errors(_retire(client, inventory, "/items", too_many, 422))
    assert "hids" in errors(_retire(client, inventory, "/items", [], 422))
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"


def test_one_that_is_refused_leaves_the_others_as_they_went(
    client: TestClient,
    make: Maker,
    inventory: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No rule refuses to retire an item today, so the refusal is planted here: it is
    # what `refused` would hold, and that one refused undoes only its own part.
    one, two = _switches(make, 2)
    retire = item_rules.retire_item

    def refusing(db: Any, context: Any, hid: str, row_version: int) -> Any:
        retire(db, context, hid, row_version)
        if hid == one["hid"]:
            # Refused after it had written: what it wrote is undone.
            raise domain_errors.Invalid("not now", {"record_status": "a rule says no"})
        return None

    monkeypatch.setattr(item_rules, "retire_item", refusing)
    done = _retire(client, inventory, "/items", [one["hid"], two["hid"]])

    assert done["refused"] == [
        {
            "hid": one["hid"],
            "label": "site9-sw-wrong-01",
            "detail": "not now; record_status: a rule says no",
            "depends_on": [],
        }
    ]
    assert [entry["hid"] for entry in done["retired"]] == [two["hid"]]
    assert make.get(f"/items/{one['hid']}")["record_status"] == "active"
    assert make.audit(record_hid=one["hid"], action="retire") == []


# --- an Admin deletes what was a mistake (P-227, P-236) -------------------------------


def _delete(
    client: TestClient,
    headers: dict[str, str],
    path: str,
    hids: list[str],
    expect: int = 200,
    **body: Any,
) -> dict[str, Any]:
    body.setdefault("reason", "a wrong file of 2026-11-18")
    response = client.post(f"{API}{path}/delete", json={"hids": hids, **body}, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


def _changes(event: dict[str, Any]) -> dict[str, Any]:
    return {entry["field"]: (entry["old"], entry["new"]) for entry in event["changes"]}


def test_an_admin_deletes_items_a_wrong_file_made_with_what_belongs_to_them_alone(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    tag = make.tag("wrong-file")
    one, two = _switches(make, 2)
    tagged = make.patch(
        f"/items/{one['hid']}", {"row_version": one["row_version"], "tags": ["wrong-file"]}
    )
    address = make.address(one, "192.0.2.10", is_primary=True)
    stack = make.stack("site9-stack-wrong", [one, two])
    make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "observed_master_hid": one["hid"]},
    )
    watch = make.post("/external-systems", {"name": "NetWatch", "kind": "monitoring"})
    known = make.post(
        "/registrations",
        {"system_hid": watch["hid"], "item_hid": one["hid"], "external_id": "node-1"},
    )
    hids = [one["hid"], two["hid"]]

    # Asked first: the same answer, and nothing changed.
    tried = _delete(client, admin, "/items", hids, dry_run=True, reason=None)
    assert tried == {
        "dry_run": True,
        "deleted": [
            {"hid": one["hid"], "label": "site9-sw-wrong-01"},
            {"hid": two["hid"], "label": "site9-sw-wrong-02"},
        ],
        "refused": [],
        "missing": [],
    }
    assert make.get(f"/items/{one['hid']}")["hid"] == one["hid"]
    assert make.audit(action="delete") == []
    # A deletion says why.
    assert "reason" in errors(_delete(client, admin, "/items", hids, 422, reason="  "))

    done = _delete(client, admin, "/items", hids)

    assert done == {**tried, "dry_run": False}
    gone = make.get(f"/items/{one['hid']}", 404)
    assert gone["deleted"]["actor_name"] == "ada"
    assert gone["deleted"]["reason"] == "a wrong file of 2026-11-18"
    assert f"the item {one['hid']} was deleted on " in gone["detail"]
    # The reason is in `deleted` alone: it may be long, and is not said twice.
    assert gone["detail"].endswith(" by ada")
    assert "a wrong file" not in gone["detail"]
    # Its event holds every field as it was, what went with it, and the reason.
    (event,) = make.audit(record_hid=one["hid"], action="delete")
    said = _changes(event)
    assert said["serial_number"] == ("SITE9-SW-WRONG-001", None)
    assert said["row_version"] == (tagged["row_version"], None)
    assert said["tags"] == (["wrong-file"], None)
    assert said["reason"] == (None, "a wrong file of 2026-11-18")
    assert [one["hid"] for one in said["addresses"][0]] == [address["hid"]]
    assert {member["group_hid"] for member in said["memberships"][0]} == {stack["hid"]}
    assert said["memberships"][0][0]["role"] == "master"
    assert [one["external_id"] for one in said["registrations"][0]] == ["node-1"]
    # The events it had before stay, found by its HID.
    assert {event["action"] for event in make.audit(record_hid=one["hid"])} >= {
        "create",
        "update",
        "delete",
    }
    # Each part has an event of its own, and is gone.
    (removed,) = make.audit(record_hid=address["hid"], action="delete")
    assert _changes(removed)["deleted_with"] == (None, one["hid"])
    assert make.audit(record_hid=known["hid"], action="delete")
    make.get(f"/addresses/{address['hid']}", 404)
    make.get(f"/registrations/{known['hid']}", 404)
    # The stack stays, with no members and no master seen, and says why.
    left = make.get(f"/device-groups/{stack['hid']}")
    assert left["observed_master_hid"] is None
    assert make.members(stack, include_past="true") == []
    cleared = make.audit(record_hid=stack["hid"], action="update")[0]
    assert _changes(cleared)["deleted_with"] == (None, one["hid"])
    # The tag is used by nothing now.
    make.delete(f"/tags/{tag['hid']}")
    # A HID that was deleted is not there for any other request.
    assert _retire(client, admin, "/items", [one["hid"]])["missing"] == [one["hid"]]
    assert _delete(client, admin, "/items", [one["hid"]])["missing"] == [one["hid"]]
    response = client.patch(
        f"{API}/items/{two['hid']}", json={"row_version": 1, "name": "x"}, headers=admin
    )
    assert response.status_code == 404
    assert response.json()["deleted"]["actor_name"] == "ada"


def test_deleting_is_for_an_admin_alone(
    client: TestClient,
    make: Maker,
    viewer: dict[str, str],
    inventory: dict[str, str],
) -> None:
    (one,) = _switches(make, 1)
    group = make.stack("site9-stack-alone", [one])

    for headers in (viewer, inventory):
        _delete(client, headers, "/items", [one["hid"]], 403)
        _delete(client, headers, "/device-groups", [group["hid"]], 403)
    assert make.get(f"/items/{one['hid']}")["hid"] == one["hid"]
    assert make.audit(action="delete") == []
    # A record that was never there answers as before.
    assert "deleted" not in make.get(f"/items/{NOBODY}", 404)


def test_an_item_that_another_record_depends_on_is_refused_naming_what(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    entry = make.entry(make.vendor("Cisco"))
    made = [
        make.item(catalog_entry_hid=entry["hid"], serial_number=f"FCW0000D{number:03d}")
        for number in range(1, 9)
    ]
    covered, bought, holder, old, new, wired, filed, free = made
    contract = make.post(
        "/contracts",
        {
            "number": "CON-2026-0001",
            "vendor_hid": entry["vendor"]["hid"],
            "starts_on": "2026-01-01",
        },
    )
    make.post(f"/contracts/{contract['hid']}/coverage", {"items": [{"item_hid": covered["hid"]}]})
    request = make.post(
        "/purchase-requests",
        {"reference": "RITM0012345", "lines": [{"catalog_entry_hid": entry["hid"], "quantity": 2}]},
    )
    line = request["lines"][0]
    make.patch(
        f"/items/{bought['hid']}",
        {"row_version": bought["row_version"], "purchase_line_hid": line["hid"]},
    )
    supply = make.item(name="PS-A", parent_item_hid=holder["hid"])
    replacement = make.post(
        f"/items/{old['hid']}/replace",
        {"row_version": old["row_version"], "reason": "rma", "new_item_hid": new["hid"]},
    )
    places = make.layout()
    circuit = make.post(
        "/circuits",
        {"name": "Site-2 internet", "a_location_hid": places["room"]["hid"], "z_note": "carrier"},
    )
    make.post(
        f"/circuits/{circuit['hid']}/devices",
        {"devices": [{"item_hid": wired["hid"], "side": "a"}]},
    )
    reference = make.post(
        "/reference-files/links",
        {
            "title": "Rack photograph",
            "kind": "other",
            "url": "https://intranet.example.net/racks/r1.jpg",
            "attach_to": [filed["hid"]],
        },
    )

    done = _delete(client, admin, "/items", [one["hid"] for one in made])

    depends = {one["hid"]: one["depends_on"] for one in done["refused"]}
    assert depends == {
        covered["hid"]: [
            {"record_type": "contract", "hid": contract["hid"], "label": "CON-2026-0001"}
        ],
        bought["hid"]: [
            {"record_type": "purchase_line", "hid": line["hid"], "label": "RITM0012345/1"}
        ],
        holder["hid"]: [{"record_type": "item", "hid": supply["hid"], "label": "PS-A"}],
        old["hid"]: [
            {
                "record_type": "item_replacement",
                "hid": replacement["hid"],
                "label": "FCW0000D004 replaced by FCW0000D005",
            }
        ],
        new["hid"]: [
            {
                "record_type": "item_replacement",
                "hid": replacement["hid"],
                "label": "FCW0000D004 replaced by FCW0000D005",
            }
        ],
        wired["hid"]: [
            {"record_type": "circuit", "hid": circuit["hid"], "label": "Site-2 internet"}
        ],
        filed["hid"]: [
            {"record_type": "reference_file", "hid": reference["hid"], "label": "Rack photograph"}
        ],
    }
    # Each is judged by itself: the one nothing depends on is gone.
    assert done["deleted"] == [{"hid": free["hid"], "label": "FCW0000D008"}]
    make.get(f"/items/{free['hid']}", 404)
    for item in made[:-1]:
        assert make.get(f"/items/{item['hid']}")["hid"] == item["hid"]
    # Ended coverage refuses it too: the contract has covered it.
    now = make.get(f"/contracts/{contract['hid']}/coverage")["items"][0]
    make.patch(
        f"/contracts/{contract['hid']}/coverage/{now['hid']}",
        {"row_version": now["row_version"], "ends_on": "2026-02-01"},
    )
    again = _delete(client, admin, "/items", [covered["hid"]], dry_run=True)
    assert again["refused"][0]["depends_on"][0]["record_type"] == "contract"


def test_a_switch_named_with_the_power_supplies_in_it_goes_with_them(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    entry = make.entry(make.vendor("Cisco"))
    switch, other = (
        make.item(catalog_entry_hid=entry["hid"], serial_number=serial)
        for serial in ("FCW0000P001", "FCW0000P002")
    )
    first = make.item(name="PS-A", parent_item_hid=switch["hid"])
    fan = make.item(name="FAN-1", parent_item_hid=first["hid"])
    kept = make.item(name="PS-B", parent_item_hid=other["hid"])
    contract = make.post(
        "/contracts", {"number": "CON-2026-0002", "vendor_hid": entry["vendor"]["hid"]}
    )
    make.post(f"/contracts/{contract['hid']}/coverage", {"items": [{"item_hid": kept["hid"]}]})

    # Named after what it is in, the minor items still go first.
    hids = [switch["hid"], other["hid"], first["hid"], kept["hid"], fan["hid"]]
    done = _delete(client, admin, "/items", hids)

    assert {one["hid"] for one in done["deleted"]} == {switch["hid"], first["hid"], fan["hid"]}
    # The supply that stays keeps the switch it is in: the switch names it.
    refused = {one["hid"]: one["depends_on"] for one in done["refused"]}
    assert refused == {
        other["hid"]: [{"record_type": "item", "hid": kept["hid"], "label": "PS-B"}],
        kept["hid"]: [
            {"record_type": "contract", "hid": contract["hid"], "label": "CON-2026-0002"}
        ],
    }
    for item in (switch, first, fan):
        make.get(f"/items/{item['hid']}", 404)


def test_an_admin_deletes_device_groups_whose_members_stay(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    make.tag("wrong-file")
    one, two, three = _switches(make, 3)
    stack = make.stack("site9-stack-wrong", [one, two], tags=["wrong-file"])
    address = make.address(stack, "192.0.2.20", is_primary=True)
    outer = make.group("site9-domain", "custom")
    inner = make.group("site9-inner", "custom", parent_group_hid=outer["hid"])
    lone = make.group("site9-lone", "custom", parent_group_hid=outer["hid"])
    wired = make.group("site9-wired", "cluster", [(three, "member")])
    places = make.layout()
    circuit = make.post(
        "/circuits",
        {"name": "Site-2 ring", "a_location_hid": places["room"]["hid"], "z_note": "carrier"},
    )
    make.post(
        f"/circuits/{circuit['hid']}/devices",
        {"devices": [{"group_hid": wired["hid"], "side": "a"}]},
    )

    done = _delete(
        client, admin, "/device-groups", [stack["hid"], outer["hid"], inner["hid"], wired["hid"]]
    )

    assert {one["label"] for one in done["deleted"]} == {"site9-stack-wrong", "site9-inner"}
    refused = {one["hid"]: one["depends_on"] for one in done["refused"]}
    assert refused == {
        outer["hid"]: [{"record_type": "device_group", "hid": lone["hid"], "label": "site9-lone"}],
        wired["hid"]: [{"record_type": "circuit", "hid": circuit["hid"], "label": "Site-2 ring"}],
    }
    gone = make.get(f"/device-groups/{stack['hid']}", 404)
    assert gone["deleted"]["actor_name"] == "ada"
    assert "the device group" in gone["detail"]
    make.get(f"/addresses/{address['hid']}", 404)
    # Its members stay, in no group.
    for item in (one, two):
        found = make.get(f"/items/{item['hid']}")
        assert found["record_status"] == "active"
        assert found["groups"] == []
    (event,) = make.audit(record_hid=stack["hid"], action="delete")
    said = _changes(event)
    assert said["name"] == ("site9-stack-wrong", None)
    assert said["tags"] == (["wrong-file"], None)
    assert {member["item_hid"] for member in said["memberships"][0]} == {one["hid"], two["hid"]}
    assert len(make.audit(record_type="device_group_member", action="delete")) == 2


def test_a_deletion_leaves_what_a_report_kept_unused(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    (one, two) = _switches(make, 2)
    for item in (one, two):
        make.move(make.get(f"/items/{item['hid']}"), "Prod")
    before = make.get("/reports/coverage")
    # Asked again, it is the kept answer.
    assert make.get("/reports/coverage") == before

    _delete(client, admin, "/items", [one["hid"]])

    after = make.get("/reports/coverage")
    assert after["totals"] != before["totals"]


def test_a_file_that_names_a_deleted_hid_is_told_it_was_deleted(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    (one,) = _switches(make, 1)
    group = make.group("site9-gone", "custom")
    _delete(client, admin, "/items", [one["hid"]])
    _delete(client, admin, "/device-groups", [group["hid"]])
    files = Files(client, make.headers)
    for entity, hid, what in (
        ("items", one["hid"], "item"),
        ("device_groups", group["hid"], "device group"),
    ):
        (row,) = files.preview(entity, f"hid,name\n{hid},again\n")["rows"]
        assert row["outcome"] == "rejected"
        said = errors({"errors": row["reasons"]})["hid"]
        assert said.startswith(f"the {what} {hid} was deleted on "), said
        assert said.endswith(" by ada"), said
    # One that never was is told so, as before.
    (row,) = files.preview("items", f"hid,name\n{NOBODY},again\n")["rows"]
    assert errors({"errors": row["reasons"]})["hid"] == f"there is no record {NOBODY}"


def test_every_route_of_a_deleted_record_that_reads_it_says_it_was_deleted(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    (one,) = _switches(make, 1)
    group = make.group("site9-gone", "custom")
    _delete(client, admin, "/items", [one["hid"]])
    _delete(client, admin, "/device-groups", [group["hid"]])
    item, held = f"{API}/items/{one['hid']}", f"{API}/device-groups/{group['hid']}"
    version = {"row_version": 1}
    for method, path, body in (
        ("GET", item, None),
        ("PATCH", item, {**version, "name": "x"}),
        ("POST", f"{item}/retire", version),
        ("POST", f"{item}/transition", {**version, "to": "Prod"}),
        ("POST", f"{item}/replace", {**version, "reason": "rma", "new_item": {}}),
        ("GET", f"{item}/children", None),
        ("GET", f"{item}/history", None),
        ("GET", f"{item}/resolution", None),
        ("GET", f"{item}/references", None),
        ("GET", held, None),
        ("PATCH", held, {**version, "name": "x"}),
        ("POST", f"{held}/retire", version),
        ("GET", f"{held}/resolution", None),
        ("GET", f"{held}/members", None),
        ("POST", f"{held}/members", {"members": [{"item_hid": NOBODY, "role": "member"}]}),
    ):
        response = client.request(method, path, json=body, headers=admin)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["deleted"]["actor_name"] == "ada", (method, path)


# --- a deletion and another change at the same moment ---------------------------------


def _held(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> threading.Event:
    """Make a function of a module, once called, let the other request go and wait a
    moment before it returns: what its request does next comes after the other asked."""
    looked = threading.Event()
    real = getattr(module, name)

    def held(*args: Any, **kwargs: Any) -> Any:
        found = real(*args, **kwargs)
        looked.set()
        threading.Event().wait(0.5)
        return found

    monkeypatch.setattr(module, name, held)
    return looked


def test_a_coverage_asked_for_while_the_item_is_deleted_finds_it_gone(
    client: TestClient,
    make: Maker,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (one,) = _switches(make, 1)
    cisco = make.get("/vendors", filter="name:eq:Cisco")["items"][0]
    contract = make.post("/contracts", {"number": "CON-2026-0003", "vendor_hid": cisco["hid"]})
    looked = _held(monkeypatch, removal, "_item_ties")

    def deleting(caller: TestClient) -> Any:
        body = {"hids": [one["hid"]], "reason": "a wrong file"}
        return caller.post(f"{API}/items/delete", json=body, headers=admin)

    def covering(caller: TestClient) -> Any:
        looked.wait(5)
        body = {"items": [{"item_hid": one["hid"]}]}
        return caller.post(
            f"{API}/contracts/{contract['hid']}/coverage", json=body, headers=make.headers
        )

    # The deletion took its turn before it looked, so the coverage waits, and then finds
    # no item: no coverage is left naming one that is not there.
    assert _together(client, [deleting, covering]) == [200, 422]
    make.get(f"/items/{one['hid']}", 404)
    assert make.get(f"/contracts/{contract['hid']}/coverage")["items"] == []


def test_a_deletion_asked_for_while_the_item_is_covered_sees_it_and_is_refused(
    client: TestClient,
    make: Maker,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (one,) = _switches(make, 1)
    cisco = make.get("/vendors", filter="name:eq:Cisco")["items"][0]
    contract = make.post("/contracts", {"number": "CON-2026-0004", "vendor_hid": cisco["hid"]})
    looked = _held(monkeypatch, contract_rules, "get_contract")
    answers: list[dict[str, Any]] = []

    def covering(caller: TestClient) -> Any:
        body = {"items": [{"item_hid": one["hid"]}]}
        return caller.post(
            f"{API}/contracts/{contract['hid']}/coverage", json=body, headers=make.headers
        )

    def deleting(caller: TestClient) -> Any:
        looked.wait(5)
        body = {"hids": [one["hid"]], "reason": "a wrong file"}
        response = caller.post(f"{API}/items/delete", json=body, headers=admin)
        answers.append(response.json())
        return response

    assert _together(client, [covering, deleting]) == [200, 201]
    assert answers[0]["deleted"] == []
    assert answers[0]["refused"][0]["depends_on"][0]["label"] == "CON-2026-0004"
    assert make.get(f"/items/{one['hid']}")["hid"] == one["hid"]


def test_an_item_that_joins_a_group_while_it_is_deleted_is_found_gone(
    client: TestClient,
    make: Maker,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (one,) = _switches(make, 1)
    group = make.group("site9-cluster", "cluster")
    looked = _held(monkeypatch, removal, "_item_ties")

    def deleting(caller: TestClient) -> Any:
        body = {"hids": [one["hid"]], "reason": "a wrong file"}
        return caller.post(f"{API}/items/delete", json=body, headers=admin)

    def joining(caller: TestClient) -> Any:
        looked.wait(5)
        body = {"members": [{"item_hid": one["hid"], "role": "member"}]}
        return caller.post(
            f"{API}/device-groups/{group['hid']}/members", json=body, headers=make.headers
        )

    assert _together(client, [deleting, joining]) == [200, 422]
    assert make.members(group, include_past="true") == []
