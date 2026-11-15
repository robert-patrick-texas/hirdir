"""What the review of 0.7.0's server found, and what the owner answered of it: each
defect as a test that failed before its correction."""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Agreement, CatalogEntry, Contract, ContractCoverage
from hirdir.io import kept
from tests.api.inventory import API, errors
from tests.api.test_renewals import Renewer, day, listed, worklist

TODAY = date.today()


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Renewer:
    made = Renewer(client, inventory)
    made.entry_ = made.catalog()
    return made


def _renew(desk: Renewer, record: dict[str, Any], expect: int = 200, **body: Any) -> Any:
    path = "agreements" if "contracts" in record else "contracts"
    now = desk.get(f"/{path}/{record['hid']}")
    return desk.post(
        f"/{path}/{record['hid']}/renew", {"row_version": now["row_version"], **body}, expect
    )


def test_a_renewal_that_has_begun_waits_no_more_on_the_worklist(desk: Renewer, db: Session) -> None:
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(20))
    _renew(desk, contract, number="CON-2", starts_on=day(21), ends_on=day(60))
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(20))
    member = desk.contract("CON-M", agreement_hid=agreement["hid"])
    _renew(desk, agreement, starts_on=day(21), ends_on=day(60))
    assert worklist(desk)["totals"]["ending"] == 0
    # Both next terms began thirty days ago and end in thirty, with nothing written down.
    for model, hid in ((Contract, contract["hid"]), (Agreement, agreement["hid"])):
        held = db.get_one(model, hid)
        held.ends_on, held.next_starts_on = (
            date.fromisoformat(day(-31)),
            date.fromisoformat(day(-30)),
        )
        held.next_ends_on = date.fromisoformat(day(30))
    db.commit()
    # The day it began is a day the kept answers were not kept for.
    kept.drop()
    found = worklist(desk)
    assert listed(desk, "/contracts", found["sections"]["ending"]["filter"]) == {
        contract["hid"],
        member["hid"],
    }
    assert found["agreements"]["ending"]["count"] == 1
    assert desk.get("/contracts", filter="next_starts_on:empty:true")["total"] == 2


def test_the_end_a_renewal_gave_an_item_left_behind_goes_out_and_back_in_a_file(
    desk: Renewer, db: Session
) -> None:
    phone = desk.entry(desk.cisco, pid="CP-8845")
    flagged = desk.switch(phone, "PH-1")
    db.get_one(CatalogEntry, phone["hid"]).do_not_renew = True
    db.commit()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(20))
    desk.cover(contract, flagged)
    _renew(desk, contract, number="CON-2", starts_on=day(21), ends_on=day(385))
    exported = desk.client.post(
        f"{API}/exports",
        json={"entity": "contract_coverage", "format": "csv"},
        headers=desk.headers,
    )
    assert exported.status_code == 200, exported.text
    preview = desk.client.post(
        f"{API}/imports/preview",
        params={"entity": "contract_coverage", "mode": "upsert"},
        content=exported.text,
        headers={**desk.headers, "Content-Type": "text/csv"},
    ).json()
    assert [row["outcome"] for row in preview["rows"]] == ["unchanged"]
    # Loaded into an inventory that has lost the coverage, the end is kept too.
    held = db.scalar(select(ContractCoverage))
    assert held is not None
    gone = held.hid
    db.delete(held)
    db.commit()
    preview = desk.client.post(
        f"{API}/imports/preview",
        params={"entity": "contract_coverage", "mode": "upsert"},
        content=exported.text.replace(gone, ""),
        headers={**desk.headers, "Content-Type": "text/csv"},
    ).json()
    desk.apply(f"/imports/{preview['job']['hid']}/apply")
    assert desk.covered(flagged)[1] == day(20)


def test_two_members_are_not_given_one_new_number(desk: Renewer) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    first = desk.contract("CON-1", agreement_hid=agreement["hid"])
    second = desk.contract("CON-2", agreement_hid=agreement["hid"])
    refused = _renew(
        desk,
        agreement,
        422,
        starts_on=day(31),
        ends_on=day(395),
        members=[
            {"contract_hid": first["hid"], "renewal": "new_number", "number": "CON-X"},
            {"contract_hid": second["hid"], "renewal": "new_number", "number": "con-x"},
        ],
    )
    assert "members.1.number" in errors(refused)


def test_a_waiting_number_is_withdrawn_when_the_member_is_given_an_end_of_its_own(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    _renew(
        desk,
        agreement,
        starts_on=day(31),
        ends_on=day(395),
        members=[{"contract_hid": member["hid"], "renewal": "new_number", "number": "CON-2"}],
    )
    desk.change(f"/contracts/{member['hid']}", starts_on=day(-100), ends_on=day(200))
    now = desk.get(f"/contracts/{member['hid']}")
    assert (now["next_term"], now["ends_on"]) == (None, day(200))
    db.expire_all()
    assert db.get_one(Contract, member["hid"]).next_with_agreement is False


def test_a_member_is_any_contract_whose_end_is_the_agreements(desk: Renewer, db: Session) -> None:
    phone = desk.entry(desk.cisco, pid="CP-8845")
    flagged = desk.switch(phone, "PH-1")
    db.get_one(CatalogEntry, phone["hid"]).do_not_renew = True
    db.commit()
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(-1))
    joined = desk.contract("CON-7", agreement_hid=agreement["hid"], starts_on=day(-100))
    desk.cover(joined, flagged)
    answer = _renew(
        desk,
        agreement,
        starts_on=day(0),
        ends_on=day(364),
        members=[{"contract_hid": joined["hid"], "renewal": "new_number", "number": "CON-7B"}],
    )
    assert [one["contract_hid"] for one in answer["members"]] == [joined["hid"]]
    assert answer["left_behind"] == 1
    assert desk.get(f"/contracts/{joined['hid']}")["number"] == "CON-7B"


def test_members_still_pending_or_expired_are_flagged_to_review_and_kept_as_they_said(
    desk: Renewer,
) -> None:
    agreement = desk.agreement(starts_on=day(-365), ends_on=day(-40))
    pending = desk.contract("CON-P", agreement_hid=agreement["hid"], status="renewal_pending")
    expired = desk.contract("CON-E", agreement_hid=agreement["hid"], status="expired")
    fine = desk.contract("CON-A", agreement_hid=agreement["hid"])
    answer = _renew(desk, agreement, starts_on=day(-39), ends_on=day(325))
    assert {one["number"] for one in answer["to_review"]} == {"CON-P", "CON-E"}
    # No status changed by itself.
    assert desk.get(f"/contracts/{pending['hid']}")["status"] == "renewal_pending"
    assert desk.get(f"/contracts/{expired['hid']}")["status"] == "expired"
    now = desk.get(f"/agreements/{agreement['hid']}")
    assert {one["number"] for one in now["members_to_review"]} == {"CON-P", "CON-E"}
    found = worklist(desk)
    assert found["totals"]["to_review"] == 2
    assert listed(desk, "/contracts", found["sections"]["to_review"]["filter"]) == {
        pending["hid"],
        expired["hid"],
    }
    desk.change(f"/contracts/{pending['hid']}", status="active")
    assert worklist(desk)["totals"]["to_review"] == 1
    assert fine["hid"] not in {one["hid"] for one in now["members_to_review"]}


def test_the_mark_not_to_renew_is_the_teams_note(desk: Renewer) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    desk.change(f"/contracts/{member['hid']}", ends_with_term=True)
    # It changes no date: the member still follows its agreement, and a renewal may still
    # occur, which keeps the mark and is to review.
    now = desk.get(f"/contracts/{member['hid']}")
    assert (now["starts_on"], now["ends_on"], now["ends_with_term"]) == (None, None, True)
    answer = _renew(desk, agreement, starts_on=day(31), ends_on=day(395))
    assert [one["number"] for one in answer["to_review"]] == ["CON-1"]
    assert desk.get(f"/contracts/{member['hid']}")["ends_with_term"] is True
    # It goes when the contract is taken out of its agreement.
    desk.change(f"/contracts/{member['hid']}", agreement_hid=None, starts_on=day(-300),
                ends_on=day(30))  # fmt: skip
    assert desk.get(f"/contracts/{member['hid']}")["ends_with_term"] is False


def test_a_member_let_go_keeps_its_dates_when_loaded_into_an_empty_inventory(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    closing = desk.contract("CON-SITE", agreement_hid=agreement["hid"])
    _renew(
        desk,
        agreement,
        starts_on=day(31),
        ends_on=day(395),
        members=[{"contract_hid": closing["hid"], "renewal": "ends"}],
    )
    exported = desk.client.post(
        f"{API}/exports", json={"entity": "contracts", "format": "csv"}, headers=desk.headers
    )
    db.get_one(Contract, closing["hid"]).number = "CON-GONE"
    db.get_one(Contract, closing["hid"]).number_key = "con-gone"
    db.commit()
    csv = exported.text.replace(closing["hid"], "")
    preview = desk.client.post(
        f"{API}/imports/preview",
        params={"entity": "contracts", "mode": "upsert"},
        content=csv,
        headers={**desk.headers, "Content-Type": "text/csv"},
    ).json()
    desk.apply(f"/imports/{preview['job']['hid']}/apply")
    made = desk.get("/contracts", filter="number:eq:CON-SITE")["items"]
    assert [(one["starts_on"], one["ends_on"], one["ends_with_term"]) for one in made] == [
        (day(-300), day(30), True)
    ]


def test_the_lapsed_count_of_the_coverage_report_follows_its_filter(desk: Renewer) -> None:
    one = desk.switch(desk.entry_, "FCW-1", name="sw-one")
    two = desk.switch(desk.entry_, "FCW-2", name="sw-two")
    for number, item in (("CON-1", one), ("CON-2", two)):
        contract = desk.contract(number, starts_on=day(-400), ends_on=day(-30))
        desk.cover(contract, item)
    assert desk.get("/reports/coverage")["lapsed_contracts"]["count"] == 2
    narrowed = desk.get("/reports/coverage", filter="name:eq:sw-one")["lapsed_contracts"]
    assert narrowed["count"] == 1
    assert desk.get("/reports/coverage", filter="name:eq:nothing")["lapsed_contracts"]["count"] == 0


def test_a_sign_in_leaves_the_kept_answers_good(
    desk: Renewer, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk.contract("CON-LAP", starts_on=day(-400), ends_on=day(-10))
    kept.drop()
    worked: list[int] = []
    from hirdir.io import planning

    real = planning.renewals
    monkeypatch.setattr(planning, "renewals", lambda *a, **k: worked.append(1) or real(*a, **k))
    desk.get("/renewals/alert")
    response = client.post(
        f"{API}/auth/sign-in", json={"username": "nobody", "access_code": "wrong"}
    )
    assert response.status_code == 401
    desk.get("/renewals/alert")
    assert worked == [1]


def test_the_worklist_takes_include_archived(desk: Renewer) -> None:
    contract = desk.contract("CON-LAP", starts_on=day(-400), ends_on=day(-10))
    now = desk.get(f"/contracts/{contract['hid']}")
    desk.post(f"/contracts/{contract['hid']}/retire", {"row_version": now["row_version"]}, 200)
    assert worklist(desk, include_archived=True)["sections"]["lapsed"]["include_archived"] is True


def test_a_contacts_namings_on_contracts_count_among_its_uses(desk: Renewer) -> None:
    contact = desk.post("/contacts", {"name": "Jordan Reyes", "email": "jr@example.com"})
    contract = desk.contract("CON-1", starts_on=day(-10), ends_on=day(300))
    desk.post(
        f"/contracts/{contract['hid']}/contacts",
        {"contact_hid": contact["hid"], "role": "account_manager"},
    )
    assert desk.get(f"/contacts/{contact['hid']}")["uses"] == 1


def test_capacity_lines_sort_and_filter_by_what_they_apply_to(desk: Renewer) -> None:
    staff = desk.post(
        "/capacity-lines",
        {"side": "supply", "category": "staff", "name": "Network engineer", "quantity": "3",
         "units_each": "1"},
    )  # fmt: skip
    desk.post(
        "/capacity-lines",
        {"side": "supply", "category": "tools", "name": "AI assistant", "effect": "multiply",
         "factor": "1.2", "applies_to": [staff["hid"]]},
    )  # fmt: skip
    found = desk.get("/capacity-lines", filter="applies_to:eq:Network engineer")["items"]
    assert [one["name"] for one in found] == ["AI assistant"]
    assert desk.get("/capacity-lines", sort="applies_to")["total"] == 2


# --- the second review ------------------------------------------------------------------


def test_a_new_number_moves_no_status_and_the_operator_confirms_the_member(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-365), ends_on=day(-40))
    told = desk.contract("CON-T", agreement_hid=agreement["hid"], status="renewal_pending")
    renumbered = desk.contract("CON-N", agreement_hid=agreement["hid"], status="renewal_pending")
    answer = _renew(
        desk,
        agreement,
        starts_on=day(-39),
        ends_on=day(325),
        members=[
            {"contract_hid": told["hid"], "status": "active"},
            {"contract_hid": renumbered["hid"], "renewal": "new_number", "number": "CON-N2"},
        ],
    )
    assert desk.get(f"/contracts/{told['hid']}")["status"] == "active"
    now = desk.get(f"/contracts/{renumbered['hid']}")
    assert (now["number"], now["status"]) == ("CON-N2", "renewal_pending")
    assert [one["number"] for one in answer["to_review"]] == ["CON-N2"]


def test_a_waiting_number_keeps_the_members_status_when_it_begins(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"], status="renewal_pending")
    _renew(
        desk,
        agreement,
        starts_on=day(31),
        ends_on=day(395),
        members=[{"contract_hid": member["hid"], "renewal": "new_number", "number": "CON-2"}],
    )
    held = db.get_one(Agreement, agreement["hid"])
    held.ends_on, held.next_starts_on = date.fromisoformat(day(-2)), date.fromisoformat(day(-1))
    db.commit()
    now = desk.get(f"/contracts/{member['hid']}")
    assert (now["number"], now["status"]) == ("CON-2", "renewal_pending")


def test_a_marked_contract_is_on_the_list_of_what_is_let_go_alone(desk: Renewer) -> None:
    marked = desk.contract(
        "CON-M", starts_on=day(-400), ends_on=day(-70), status="renewal_pending",
        ends_with_term=True,
    )  # fmt: skip
    found = worklist(desk)
    assert (found["totals"]["renewal_pending"], found["totals"]["overdue"]) == (0, 0)
    assert listed(desk, "/contracts", found["sections"]["ends_with_term"]["filter"]) == {
        marked["hid"]
    }
    alert = desk.get("/renewals/alert")
    assert (alert["show"], alert["renewal_pending"]["count"]) == (False, 0)


def test_a_hand_added_coverage_keeps_the_contracts_end_only_while_a_renewal_waits(
    desk: Renewer, db: Session
) -> None:
    phone = desk.entry(desk.cisco, pid="CP-8845")
    flagged = desk.switch(phone, "PH-1")
    db.get_one(CatalogEntry, phone["hid"]).do_not_renew = True
    db.commit()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(20))
    desk.cover(contract, flagged, ends_on=day(20))
    desk.change(f"/contracts/{contract['hid']}", ends_on=day(200))
    assert desk.covered(flagged)[1] == day(200)


def test_a_line_corrected_keeps_the_pid_it_had_and_a_reload_keeps_the_correction(
    desk: Renewer,
) -> None:
    right = desk.entry(desk.cisco, pid="SFP-10G-LR")
    desk.entry(desk.cisco, pid="SFP-10G-SR")
    files = "request,line,vendor,pid,quantity\nRITM0012345,1,Cisco,SFP-10G-SR,4\n"
    desk.post("/purchase-requests", {"reference": "RITM0012345"})

    def load() -> dict[str, Any]:
        preview = desk.client.post(
            f"{API}/imports/preview",
            params={"entity": "purchase_lines", "mode": "upsert"},
            content=files,
            headers={**desk.headers, "Content-Type": "text/csv"},
        ).json()
        return preview

    first = load()
    desk.apply(f"/imports/{first['job']['hid']}/apply")
    (line,) = desk.get("/purchase-lines")["items"]
    assert line["part_number"] is None
    corrected = desk.patch(
        f"/purchase-lines/{line['hid']}",
        {"row_version": line["row_version"], "catalog_entry_hid": right["hid"]},
    )
    assert corrected["part_number"] == "SFP-10G-SR"
    again = load()
    assert [row["outcome"] for row in again["rows"]] == ["unchanged"]
