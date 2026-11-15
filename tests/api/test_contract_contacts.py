"""The contacts of an agreement and of a contract (P-119, P-132): contact records named
in a role, account manager or support contact, and what a contract has in force from
its agreement."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.api.test_contracts import Desk
from tests.api.test_files import Files, counts


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    desk = Desk(client, inventory)
    desk.catalog()
    return desk


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _name(desk: Maker, path: str, contact: dict[str, Any], role: str, expect: int = 201, **more):
    return desk.post(
        f"{path}/contacts", {"contact_hid": contact["hid"], "role": role, **more}, expect
    )


def _in_force(record: dict[str, Any], role: str) -> tuple[list[str], str, str | None]:
    found = record["effective"][role]
    return [one["contact"]["name"] for one in found["value"]], found["source"], found["source_hid"]


def test_an_agreement_and_a_contract_name_contacts_each_once_in_a_role(desk: Desk) -> None:
    agreement = desk.agreement()
    path = f"/agreements/{agreement['hid']}"
    jordan = desk.contact("Jordan Reyes", organization="Cisco", phone="+1 555 0142")
    casey = desk.contact("Casey Lund", organization="Cisco")
    first = _name(desk, path, jordan, "account_manager")
    second = _name(desk, path, casey, "account_manager")
    # Left out, the priority is one more than the highest of the record and the role.
    assert (first["priority"], second["priority"]) == (1, 2)
    assert (first["agreement_hid"], first["contract_hid"]) == (agreement["hid"], None)
    assert first["contact"] == {
        "hid": jordan["hid"],
        "name": "Jordan Reyes",
        "organization": "Cisco",
        "email": "jordan.reyes@example.net",
        "phone": "+1 555 0142",
        "record_status": "active",
    }
    assert _name(desk, path, jordan, "support_contact")["priority"] == 1
    # Named once for one record and one role.
    assert "contact_hid" in errors(_name(desk, path, jordan, "account_manager", expect=409))
    assert "role" in errors(_name(desk, path, jordan, "sales", expect=422))
    assert "priority" in [
        one["field"].split(".")[-1]
        for one in _name(desk, path, casey, "support_contact", priority=0, expect=422)["errors"]
    ]
    nobody = {"contact_hid": "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22", "role": "account_manager"}
    assert "contact_hid" in errors(desk.post(f"{path}/contacts", nobody, 422))

    listed = desk.get(f"{path}/contacts")
    assert [(one["role"], one["contact"]["name"]) for one in listed["items"]] == [
        ("account_manager", "Jordan Reyes"),
        ("account_manager", "Casey Lund"),
        ("support_contact", "Jordan Reyes"),
    ]
    shown = desk.get(path)
    assert [one["hid"] for one in shown["contacts"]] == [one["hid"] for one in listed["items"]]
    assert _in_force(shown, "account_managers") == (
        ["Jordan Reyes", "Casey Lund"],
        "own",
        agreement["hid"],
    )

    # The order is changed by the priority, and a naming may take another contact.
    moved = desk.patch(
        f"{path}/contacts/{second['hid']}", {"row_version": second["row_version"], "priority": 1}
    )
    assert moved["row_version"] == second["row_version"] + 1
    names = [one["contact"]["name"] for one in desk.get(f"{path}/contacts")["items"]]
    assert names[:2] == ["Casey Lund", "Jordan Reyes"]
    stale = {"row_version": second["row_version"], "priority": 3}
    desk.patch(f"{path}/contacts/{second['hid']}", stale, 409)
    clash = {"row_version": moved["row_version"], "contact_hid": jordan["hid"]}
    assert "contact_hid" in errors(desk.patch(f"{path}/contacts/{second['hid']}", clash, 409))

    # A naming is reached through its own record only, and removed outright.
    contract = desk.contract("CON-2026-0001")
    elsewhere = f"/contracts/{contract['hid']}/contacts/{first['hid']}"
    desk.patch(elsewhere, {"row_version": 1, "priority": 5}, 404)
    desk.delete(elsewhere, 404)
    desk.delete(f"{path}/contacts/{first['hid']}")
    desk.delete(f"{path}/contacts/{first['hid']}", 404)
    assert desk.get(f"{path}/contacts")["total"] == 2
    desk.get("/agreements/0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22/contacts", 404)


def test_a_contract_has_its_agreements_contacts_in_each_role_until_it_names_its_own(
    desk: Desk,
) -> None:
    agreement = desk.agreement(account_manager="Account team, +1 555 0100")
    inside = desk.contract("CON-2026-0001", agreement_hid=agreement["hid"])
    named = desk.contract("CON-2026-0002", agreement_hid=agreement["hid"])
    alone = desk.contract("CON-2026-0003")
    jordan = desk.contact("Jordan Reyes", phone="+1 555 0142")
    casey = desk.contact("Casey Lund")
    desk_line = desk.contact("Support Desk", email="support@example.com")
    _name(desk, f"/agreements/{agreement['hid']}", jordan, "account_manager")
    _name(desk, f"/agreements/{agreement['hid']}", desk_line, "support_contact")
    _name(desk, f"/contracts/{named['hid']}", casey, "account_manager")

    first = desk.get(f"/contracts/{inside['hid']}")
    assert first["contacts"] == []
    assert _in_force(first, "account_managers") == (["Jordan Reyes"], "agreement", agreement["hid"])
    assert _in_force(first, "support_contacts") == (["Support Desk"], "agreement", agreement["hid"])
    # One that names anybody in a role has its own, all of them, in place of the
    # agreement's; the other role is still the agreement's.
    second = desk.get(f"/contracts/{named['hid']}")
    assert _in_force(second, "account_managers") == (["Casey Lund"], "own", named["hid"])
    assert _in_force(second, "support_contacts") == (
        ["Support Desk"],
        "agreement",
        agreement["hid"],
    )
    # A contract in no agreement has its own or none.
    assert _in_force(desk.get(f"/contracts/{alone['hid']}"), "account_managers") == (
        [],
        "none",
        None,
    )
    # The free text is beside them, and inherited by itself as before.
    assert first["effective"]["account_manager"]["value"] == "Account team, +1 555 0100"
    assert first["effective"]["account_manager"]["source"] == "agreement"

    # Nothing is copied: a change of the contact record shows wherever it is in force.
    desk.change(f"/contacts/{jordan['hid']}", phone="+1 555 0199")
    shown = desk.get(f"/contracts/{inside['hid']}")["effective"]["account_managers"]["value"]
    assert shown[0]["contact"]["phone"] == "+1 555 0199"
    assert desk.get(f"/contracts/{inside['hid']}")["row_version"] == inside["row_version"]
    # The list of contracts answers them as the record does.
    listed = desk.get("/contracts", filter=f"agreement_hid:eq:{agreement['hid']}")["items"]
    assert [_in_force(one, "account_managers")[1] for one in listed] == ["agreement", "own"]

    # Out of the agreement, a contract has nothing of it; back in, it has it again.
    desk.change(f"/contracts/{inside['hid']}", agreement_hid=None)
    assert _in_force(desk.get(f"/contracts/{inside['hid']}"), "account_managers")[1] == "none"
    # Once a contract's own are removed, it has its agreement's again.
    own = desk.get(f"/contracts/{named['hid']}/contacts")["items"][0]
    desk.delete(f"/contracts/{named['hid']}/contacts/{own['hid']}")
    again = desk.get(f"/contracts/{named['hid']}")
    assert _in_force(again, "account_managers") == (["Jordan Reyes"], "agreement", agreement["hid"])


def test_a_retired_contact_stays_where_it_is_named_and_is_named_nowhere_new(desk: Desk) -> None:
    contract = desk.contract("CON-2026-0001")
    path = f"/contracts/{contract['hid']}"
    jordan = desk.contact("Jordan Reyes")
    casey = desk.contact("Casey Lund")
    link = _name(desk, path, jordan, "support_contact")
    desk.post(f"/contacts/{jordan['hid']}/retire", {"row_version": jordan["row_version"]}, 200)
    marked = desk.get(path)["contacts"][0]["contact"]
    assert (marked["name"], marked["record_status"]) == ("Jordan Reyes", "retired")
    assert "contact_hid" in errors(_name(desk, path, jordan, "account_manager", expect=422))
    # It may still be put in another order where it stands.
    desk.patch(f"{path}/contacts/{link['hid']}", {"row_version": 1, "priority": 2})
    swap = {"row_version": 2, "contact_hid": jordan["hid"], "priority": 3}
    assert desk.patch(f"{path}/contacts/{link['hid']}", swap)["priority"] == 3
    # A retired contract takes no new contact; what it names stays.
    desk.post(f"{path}/retire", {"row_version": contract["row_version"]}, 200)
    assert "contract_hid" in errors(_name(desk, path, casey, "account_manager", expect=422))
    assert len(desk.get(path)["contacts"]) == 1


def test_naming_a_contact_is_role_checked_and_audited(
    desk: Desk, client: TestClient, viewer: dict[str, str]
) -> None:
    agreement = desk.agreement()
    path = f"{API}/agreements/{agreement['hid']}/contacts"
    jordan = desk.contact("Jordan Reyes")
    body = {"contact_hid": jordan["hid"], "role": "account_manager"}
    assert client.post(path, json=body, headers=viewer).status_code == 403
    link = _name(desk, f"/agreements/{agreement['hid']}", jordan, "account_manager")
    assert client.get(path, headers=viewer).status_code == 200
    one = f"{path}/{link['hid']}"
    assert (
        client.patch(one, json={"row_version": 1, "priority": 2}, headers=viewer).status_code == 403
    )
    assert client.delete(one, headers=viewer).status_code == 403
    desk.patch(
        f"/agreements/{agreement['hid']}/contacts/{link['hid']}", {"row_version": 1, "priority": 2}
    )
    desk.delete(f"/agreements/{agreement['hid']}/contacts/{link['hid']}")

    removed, changed, made = desk.audit(record_type="contract_contact", record_hid=link["hid"])
    assert [made["action"], changed["action"], removed["action"]] == ["create", "update", "delete"]
    assert changed["changes"] == [{"field": "priority", "old": 1, "new": 2}]
    # The removal holds what it was.
    assert {one["field"]: one["old"] for one in removed["changes"]} == {
        "agreement_hid": agreement["hid"],
        "role": "account_manager",
        "contact_hid": jordan["hid"],
        "priority": 2,
    }


def test_the_contacts_of_contracts_travel_in_files(desk: Desk, files: Files) -> None:
    juniper = desk.vendor("Juniper")
    agreement = desk.agreement()
    desk.contract("CON-2026-0001", agreement_hid=agreement["hid"])
    desk.contract("SHARED-1")
    desk.contract("SHARED-1", vendor_hid=juniper["hid"])
    desk.contact("Jordan Reyes")
    desk.contact("Casey Lund")
    loaded = files.load(
        "contract_contacts",
        "agreement,contract,vendor,role,contact,priority\n"
        "Cisco Enterprise Agreement,,,account_manager,jordan.reyes@example.net,\n"
        ",CON-2026-0001,,support_contact,Casey Lund,\n"
        ",SHARED-1,Juniper,account_manager,casey.lund@example.net,4\n",
    )
    assert loaded["created"] == 3
    shared = desk.get("/contracts", filter=f"vendor_hid:eq:{juniper['hid']}")["items"][0]
    assert [(one["role"], one["priority"]) for one in shared["contacts"]] == [
        ("account_manager", 4)
    ]
    inside = desk.get("/contracts", filter="number:eq:CON-2026-0001")["items"][0]
    assert _in_force(inside, "account_managers")[:2] == (["Jordan Reyes"], "agreement")
    assert _in_force(inside, "support_contacts")[:2] == (["Casey Lund"], "own")

    # Loaded again, every row finds its naming by its record, its role and its contact.
    exported = files.export("contract_contacts", own_values=True)
    again = files.preview("contract_contacts", exported)
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 3, again["rows"]
    moved = files.load(
        "contract_contacts",
        "agreement,role,contact,priority\n"
        "Cisco Enterprise Agreement,account_manager,Jordan Reyes,7\n",
    )
    assert counts(moved) == (0, 1, 0, 0)
    # An import does not remove one: what the file leaves out stays as it is.
    assert len(desk.get(f"/contracts/{inside['hid']}")["contacts"]) == 1
    assert len(shared["contacts"]) == 1
    # A row names one record, and a number two vendors use takes the vendor.
    rows = files.preview(
        "contract_contacts",
        "agreement,contract,role,contact\n"
        "Cisco Enterprise Agreement,CON-2026-0001,account_manager,Casey Lund\n"
        ",SHARED-1,account_manager,Casey Lund\n"
        ",CON-2026-0001,account_manager,nobody@example.net\n",
    )["rows"]
    assert [row["outcome"] for row in rows] == ["rejected"] * 3
    assert [row["reasons"][0]["field"] for row in rows] == ["agreement", "contract", "contact"]
