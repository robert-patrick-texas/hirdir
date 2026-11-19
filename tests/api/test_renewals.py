"""Renewals in practice (0.7.0): the worklist, the alert after sign-in, an agreement
renewed with its members, a contract that ends with its term, the items a renewal
leaves behind, and a contract's history across joining and leaving an agreement."""

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import (
    Agreement,
    AuditEvent,
    CatalogEntry,
    Contract,
    Item,
    RenewalAlertView,
)
from hirdir.io import kept
from hirdir.schedule import LONG_REPORTS, Scheduler
from tests.api.inventory import API, errors
from tests.api.test_contracts import Desk

TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


class Renewer(Desk):
    """A desk with one model of switch to cover."""

    entry_: dict[str, Any]


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Renewer:
    made = Renewer(client, inventory)
    made.entry_ = made.catalog()
    return made


def listed(desk: Desk, path: str, tree: dict[str, Any] | None) -> set[str]:
    """Return the HIDs a list answers to a filter, as a section of a report gives it."""
    params: dict[str, Any] = {"limit": 1000}
    if tree is not None:
        params["filter"] = json.dumps(tree)
    response = desk.client.get(API + path, params=params, headers=desk.headers)
    assert response.status_code == 200, response.text
    return {row["hid"] for row in response.json()["items"]}


def worklist(desk: Desk, **params: Any) -> dict[str, Any]:
    return desk.get("/reports/renewals", **params)


# --- the worklist ---------------------------------------------------------------------


def test_the_worklist_lists_each_contract_to_act_on_under_its_vendor_and_agreement(
    desk: Renewer,
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(300))
    ending = desk.contract(
        "CON-END", agreement_hid=agreement["hid"], starts_on=day(-300), ends_on=day(30)
    )
    lapsed = desk.contract(
        "CON-LAP", agreement_hid=agreement["hid"], starts_on=day(-400), ends_on=day(-10)
    )
    pending = desk.contract(
        "CON-PEN",
        agreement_hid=agreement["hid"],
        starts_on=day(-500),
        ends_on=day(-70),
        status="renewal_pending",
    )
    recent = desk.contract(
        "CON-NEW", starts_on=day(-400), ends_on=day(-5), status="renewal_pending"
    )
    far = desk.contract("CON-FAR", starts_on=day(-10), ends_on=day(400))
    renewed = desk.contract("CON-REN", starts_on=day(-300), ends_on=day(20))
    desk.post(
        f"/contracts/{renewed['hid']}/renew",
        {
            "row_version": renewed["row_version"],
            "number": "CON-REN-2",
            "starts_on": day(21),
            "ends_on": day(386),
        },
        200,
    )
    a, b = desk.switch(desk.entry_, "FCW-A"), desk.switch(desk.entry_, "FCW-B")
    desk.cover(ending, a, b)
    desk.cover(far, a)
    found = worklist(desk)
    assert (found["within_days"], found["overdue_after"]) == (90, 60)
    assert found["totals"] == {
        "ending": 1,
        "lapsed": 1,
        "renewal_pending": 2,
        "overdue": 1,
        "ends_with_term": 0,
        "to_review": 0,
        "overlapping": 1,
    }
    # Each count leads to its rows.
    sections = found["sections"]
    assert listed(desk, "/contracts", sections["ending"]["filter"]) == {ending["hid"]}
    assert listed(desk, "/contracts", sections["lapsed"]["filter"]) == {lapsed["hid"]}
    assert listed(desk, "/contracts", sections["renewal_pending"]["filter"]) == {
        pending["hid"],
        recent["hid"],
    }
    assert listed(desk, "/contracts", sections["overdue"]["filter"]) == {pending["hid"]}
    assert listed(desk, "/items", sections["overlapping"]["filter"]) == {a["hid"]}
    # Under the agreement, and by themselves under the vendor, last.
    groups = [(one["vendor"], one["agreement"], one["counts"]) for one in found["groups"]]
    assert groups[0][:2] == ("Cisco", "Cisco Enterprise Agreement")
    assert (groups[0][2]["ending"], groups[0][2]["overdue"]) == (1, 1)
    assert groups[1][:2] == ("Cisco", None)
    assert (groups[1][2]["renewal_pending"], groups[1][2]["overlapping"]) == (1, 1)
    under = found["groups"][0]["filters"]
    assert listed(desk, "/contracts", under["lapsed"]) == {lapsed["hid"]}
    # A page of a list, the soonest end first, with how long each has been pending.
    page = worklist(desk, section="renewal_pending")
    assert [row["number"] for row in page["contracts"]] == ["CON-PEN", "CON-NEW"]
    assert [row["renewal_pending_days"] for row in page["contracts"]] == [70, 5]
    assert [row["renewal_overdue"] for row in page["contracts"]] == [True, False]
    assert page["total"] == 2
    items = worklist(desk, section="overlapping")["items"]
    assert [item["hid"] for item in items] == [a["hid"]]


def test_the_warning_period_and_the_overdue_days_are_settings(
    desk: Renewer, client: TestClient, admin: dict[str, str]
) -> None:
    desk.contract("CON-120", starts_on=day(-10), ends_on=day(120))
    desk.contract("CON-PEN", starts_on=day(-400), ends_on=day(-40), status="renewal_pending")
    assert worklist(desk)["totals"]["ending"] == 0
    assert worklist(desk)["totals"]["overdue"] == 0
    assert worklist(desk, within_days=150)["totals"]["ending"] == 1
    for key, value in (("renewal_warning_days", 180), ("renewal_pending_overdue_days", 30)):
        response = client.put(
            f"{API}/settings/{key}", json={"row_version": 0, "value": value}, headers=admin
        )
        assert response.status_code == 200, response.text
    found = worklist(desk)
    assert (found["within_days"], found["totals"]["ending"]) == (180, 1)
    assert (found["overdue_after"], found["totals"]["overdue"]) == (30, 1)
    overdue = desk.get("/contracts", filter="renewal_overdue:eq:true")
    assert [row["number"] for row in overdue["items"]] == ["CON-PEN"]


def test_a_kept_answer_is_never_one_that_a_change_made_wrong(desk: Renewer) -> None:
    contract = desk.contract("CON-1", starts_on=day(-10), ends_on=day(30))
    assert worklist(desk)["totals"]["ending"] == 1
    desk.change(f"/contracts/{contract['hid']}", ends_on=day(200))
    assert worklist(desk)["totals"]["ending"] == 0
    switch = desk.switch(desk.entry_, "FCW-1")
    before = desk.get("/reports/coverage")["totals"]["uncovered"]
    desk.cover(contract, switch)
    assert desk.get("/reports/coverage")["totals"]["uncovered"] == before - 1


# --- the alert ------------------------------------------------------------------------


def test_the_alert_is_shown_once_a_day(
    desk: Renewer, client: TestClient, viewer: dict[str, str], db: Session
) -> None:
    alert = desk.get("/renewals/alert")
    assert alert["show"] is False
    desk.contract("CON-LAP", starts_on=day(-400), ends_on=day(-10))
    desk.contract("CON-END", starts_on=day(-10), ends_on=day(40))
    alert = desk.get("/renewals/alert")
    assert alert["show"] is True
    assert (alert["lapsed"]["count"], alert["ending"]["count"]) == (1, 1)
    assert alert["lapsed"]["section"] == "lapsed"
    # View-only is never shown it.
    seen_by_viewer = client.get(f"{API}/renewals/alert", headers=viewer).json()
    assert (seen_by_viewer["show"], seen_by_viewer["lapsed"]["count"]) == (False, 1)
    desk.post("/renewals/alert/seen", {"version": alert["version"]}, 200)
    assert desk.get("/renewals/alert")["show"] is False
    # Dismissed, it is not shown again that day, whatever comes onto a list ...
    desk.contract("CON-LAP-2", starts_on=day(-400), ends_on=day(-3))
    again = desk.get("/renewals/alert")
    assert (again["show"], again["lapsed"]["count"], again["lapsed"]["new"]) == (False, 2, 1)
    desk.post("/renewals/alert/seen", {}, 200)
    # ... and it is shown again the next day.
    held = db.scalar(select(RenewalAlertView))
    assert held is not None
    held.as_of = TODAY - timedelta(days=1)
    db.commit()
    assert desk.get("/renewals/alert")["show"] is True


def test_the_alert_counts_the_agreements_too(desk: Renewer) -> None:
    desk.agreement(starts_on=day(-400), ends_on=day(-5))
    alert = desk.get("/renewals/alert")
    assert alert["agreements"] == {"ending": 0, "lapsed": 1, "renewal_pending": 0}
    assert alert["show"] is True


def test_seeing_the_alert_is_a_change_of_ones_own_and_audited(desk: Renewer, db: Session) -> None:
    desk.contract("CON-LAP", starts_on=day(-400), ends_on=day(-10))
    alert = desk.get("/renewals/alert")
    desk.post("/renewals/alert/seen", {"version": alert["version"]}, 200)
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "alert_seen")))
    assert [event.record_type for event in events] == ["user"]


# --- an agreement renewed with its members --------------------------------------------


def _renew(desk: Desk, agreement: dict[str, Any], expect: int = 200, **body: Any) -> Any:
    now = desk.get(f"/agreements/{agreement['hid']}")
    return desk.post(
        f"/agreements/{agreement['hid']}/renew",
        {"row_version": now["row_version"], **body},
        expect,
    )


def test_a_member_given_a_new_number_at_once_is_renewed_with_its_agreement(desk: Renewer) -> None:
    agreement = desk.agreement(starts_on=day(-365), ends_on=day(-1), number="EA-1")
    keeps = desk.contract("CON-KEEP", agreement_hid=agreement["hid"])
    renumbered = desk.contract("CON-OLD", agreement_hid=agreement["hid"])
    alone = desk.contract(
        "CON-OWN", agreement_hid=agreement["hid"], starts_on=day(-100), ends_on=day(100)
    )
    answer = _renew(
        desk,
        agreement,
        number="EA-2",
        starts_on=day(0),
        ends_on=day(364),
        members=[
            {
                "contract_hid": renumbered["hid"],
                "renewal": "new_number",
                "number": "CON-NEW",
                "purchase_reference": "RITM0099",
            }
        ],
    )
    assert {one["contract_hid"]: one["renewal"] for one in answer["members"]} == {
        keeps["hid"]: "same",
        renumbered["hid"]: "new_number",
    }
    # A contract with dates of its own does not share the period, and is not a member.
    assert alone["hid"] not in {one["contract_hid"] for one in answer["members"]}
    now = desk.get(f"/contracts/{renumbered['hid']}")
    assert (now["number"], now["purchase_reference"], now["effective"]["ends_on"]["value"]) == (
        "CON-NEW",
        "RITM0099",
        day(364),
    )
    assert desk.get(f"/contracts/{keeps['hid']}")["number"] == "CON-KEEP"
    (earlier,) = desk.get(f"/contracts/{renumbered['hid']}/terms")
    assert (earlier["number"], earlier["ends_on"], earlier["ends_on_source"]) == (
        "CON-OLD",
        day(-1),
        "agreement",
    )


def test_a_new_number_waits_for_the_agreements_term_and_is_withdrawn_with_it(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(60))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    answer = _renew(
        desk,
        agreement,
        starts_on=day(61),
        ends_on=day(425),
        members=[{"contract_hid": member["hid"], "renewal": "new_number", "number": "CON-2"}],
    )
    assert answer["members"][0]["number"] == "CON-2"
    now = desk.get(f"/contracts/{member['hid']}")
    assert now["number"] == "CON-1"
    assert now["next_term"] == {
        "number": "CON-2",
        "starts_on": day(61),
        "ends_on": day(425),
        "annual_cost": None,
        "purchase_reference": None,
        "with_agreement": True,
    }
    # It answers to both numbers, and the list says when the next term begins.
    assert desk.get("/contracts", filter="next_starts_on:eq:" + day(61))["total"] == 1
    # The agreement's next term moves: the waiting number moves with it, unwritten.
    held = db.get_one(Agreement, agreement["hid"])
    held.next_starts_on = date.fromisoformat(day(70))
    db.commit()
    assert desk.get(f"/contracts/{member['hid']}")["next_term"]["starts_on"] == day(70)
    # Withdrawn with the agreement's term.
    _renew(desk, agreement, withdraw=True)
    assert desk.get(f"/contracts/{member['hid']}")["next_term"] is None
    db.expire_all()
    assert db.get_one(Contract, member["hid"]).next_with_agreement is False


def test_a_waiting_number_is_in_force_from_the_day_the_agreements_term_begins(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(60))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    _renew(
        desk,
        agreement,
        starts_on=day(61),
        ends_on=day(425),
        members=[{"contract_hid": member["hid"], "renewal": "new_number", "number": "CON-2"}],
    )
    # The member was made and given its number long ago, and the agreement's next term
    # began yesterday.
    db.get_one(Contract, member["hid"]).created_at = _moment(-100)
    for event in db.scalars(select(AuditEvent).where(AuditEvent.record_hid == member["hid"])):
        event.at = _moment(-100)
    held = db.get_one(Agreement, agreement["hid"])
    held.ends_on, held.next_starts_on = date.fromisoformat(day(-2)), date.fromisoformat(day(-1))
    db.commit()
    now = desk.get(f"/contracts/{member['hid']}")
    assert (now["number"], now["next_term"]) == ("CON-2", None)
    assert desk.get("/contracts", filter="number:eq:CON-2")["total"] == 1
    # Writing the agreement down writes the member's term down first.
    desk.change(f"/agreements/{agreement['hid']}", notes="written down")
    db.expire_all()
    stored = db.get_one(Contract, member["hid"])
    assert (stored.number, stored.next_number, stored.next_with_agreement) == ("CON-2", None, False)
    (earlier,) = desk.get(f"/contracts/{member['hid']}/terms")
    assert (earlier["number"], earlier["ended_on"], earlier["began_by"]) == (
        "CON-1",
        day(-2),
        "created",
    )
    assert desk.get(f"/contracts/{member['hid']}")["part_began_by"] == "renewal"


def test_a_member_let_go_ends_with_the_present_term_and_stays_listed_until_a_person_says(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    closing = desk.contract("CON-SITE", agreement_hid=agreement["hid"])
    staying = desk.contract("CON-STAY", agreement_hid=agreement["hid"])
    switch = desk.switch(desk.entry_, "FCW-1")
    desk.cover(closing, switch)
    _renew(
        desk,
        agreement,
        starts_on=day(31),
        ends_on=day(395),
        members=[{"contract_hid": closing["hid"], "renewal": "ends"}],
    )
    now = desk.get(f"/contracts/{closing['hid']}")
    assert (now["starts_on"], now["ends_on"], now["ends_with_term"]) == (day(-300), day(30), True)
    assert now["agreement_hid"] == agreement["hid"]
    assert desk.get(f"/items/{switch['hid']}")["covered_until"] == day(30)
    # It is let go: on the worklist's list of that alone, never ending, never alerted.
    found = worklist(desk)
    assert found["totals"]["ends_with_term"] == 1
    assert listed(desk, "/contracts", found["sections"]["ending"]["filter"]) == set()
    # After its end nothing changes by itself: it covers nothing, is not lapsed, and stays
    # on the list of what is let go until a person says it has expired.
    held = db.get_one(Contract, closing["hid"])
    held.starts_on, held.ends_on = date.fromisoformat(day(-400)), date.fromisoformat(day(-2))
    db.commit()
    now = desk.get(f"/contracts/{closing['hid']}")
    assert (now["status"], now["lapsed"], now["covers_today"]) == ("active", False, False)
    found = worklist(desk)
    assert (found["totals"]["lapsed"], found["totals"]["ends_with_term"]) == (0, 1)
    desk.change(f"/contracts/{closing['hid']}", status="expired")
    assert worklist(desk)["totals"]["ends_with_term"] == 0
    assert desk.get(f"/contracts/{staying['hid']}")["ends_with_term"] is False


def test_a_member_is_named_once_and_only_a_member_is_named(desk: Renewer) -> None:
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(30))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    outside = desk.contract("CON-OUT", starts_on=day(-10), ends_on=day(10))
    body = {"starts_on": day(31), "ends_on": day(395)}
    refused = _renew(
        desk, agreement, 422, **body, members=[{"contract_hid": outside["hid"], "renewal": "same"}]
    )
    assert "members.0.contract_hid" in errors(refused)
    refused = _renew(
        desk,
        agreement,
        422,
        **body,
        members=[{"contract_hid": member["hid"], "renewal": "new_number"}],
    )
    assert "members.0.number" in errors(refused)
    refused = _renew(
        desk,
        agreement,
        422,
        **body,
        members=[{"contract_hid": member["hid"]}, {"contract_hid": member["hid"]}],
    )
    assert "members.1.contract_hid" in errors(refused)


# --- what a renewal leaves behind -----------------------------------------------------


def test_a_renewal_leaves_behind_the_items_that_are_not_to_be_renewed(
    desk: Renewer, db: Session
) -> None:
    phone = desk.entry(desk.cisco, pid="CP-8845")
    flagged, overridden = desk.switch(phone, "PH-1"), desk.switch(phone, "PH-2")
    switch = desk.switch(desk.entry_, "FCW-1")
    db.get_one(CatalogEntry, phone["hid"]).do_not_renew = True
    db.get_one(Item, overridden["hid"]).do_not_renew = False
    db.commit()
    contract = desk.contract("CON-1", starts_on=day(-300), ends_on=day(-1))
    desk.cover(contract, flagged, overridden, switch)
    renewed = desk.post(
        f"/contracts/{contract['hid']}/renew",
        {
            "row_version": contract["row_version"],
            "number": "CON-2",
            "starts_on": day(0),
            "ends_on": day(364),
        },
        200,
    )
    assert renewed["left_behind"] == 1
    assert desk.covered(flagged) == (False, None, [])
    assert desk.covered(overridden)[2] == ["CON-2"]
    assert desk.covered(switch)[2] == ["CON-2"]
    coverage = desk.get(f"/contracts/{contract['hid']}/coverage")["items"]
    ends = {row["item"]["hid"]: row["ends_on"] for row in coverage}
    assert (ends[flagged["hid"]], ends[switch["hid"]]) == (day(-1), None)


def test_an_early_renewal_leaves_a_flagged_item_covered_to_the_end_of_the_term(
    desk: Renewer, db: Session
) -> None:
    phone = desk.entry(desk.cisco, pid="CP-8845")
    flagged = desk.switch(phone, "PH-1")
    db.get_one(CatalogEntry, phone["hid"]).do_not_renew = True
    db.commit()
    agreement = desk.agreement(starts_on=day(-300), ends_on=day(40))
    member = desk.contract("CON-1", agreement_hid=agreement["hid"])
    desk.cover(member, flagged)
    answer = _renew(desk, agreement, starts_on=day(41), ends_on=day(405))
    assert answer["left_behind"] == 1
    assert desk.covered(flagged) == (True, day(40), ["CON-1"])


# --- a contract's history across an agreement -----------------------------------------


def test_joining_and_leaving_an_agreement_start_new_parts_of_a_contracts_history(
    desk: Renewer, db: Session
) -> None:
    agreement = desk.agreement(starts_on=day(-200), ends_on=day(165))
    contract = desk.contract("CON-7", starts_on=day(-400), ends_on=day(-1))
    db.get_one(Contract, contract["hid"]).created_at = _moment(-180)
    _event(db, contract["hid"]).at = _moment(-180)
    db.commit()
    desk.change(
        f"/contracts/{contract['hid']}",
        agreement_hid=agreement["hid"],
        starts_on=None,
        ends_on=None,
    )
    (alone,) = desk.get(f"/contracts/{contract['hid']}/terms")
    assert (alone["began_on"], alone["ended_on"], alone["began_by"]) == (
        day(-180),
        day(-1),
        "created",
    )
    assert (alone["agreement_hid"], alone["starts_on"], alone["ends_on"]) == (
        None,
        day(-400),
        day(-1),
    )
    now = desk.get(f"/contracts/{contract['hid']}")
    assert (now["part_began_on"], now["part_began_by"]) == (day(0), "joined")
    # A contract rolled into an agreement on the day it was made lasted no day alone.
    rolled = desk.contract("CON-8", starts_on=day(-10), ends_on=day(10))
    desk.change(f"/contracts/{rolled['hid']}", agreement_hid=agreement["hid"])
    assert desk.get(f"/contracts/{rolled['hid']}/terms") == []
    # A renewal on the day it was made is listed, so that no number goes missing.
    renamed = desk.contract("CON-9", starts_on=day(-10), ends_on=day(10))
    desk.post(
        f"/contracts/{renamed['hid']}/renew",
        {"row_version": renamed["row_version"], "number": "CON-9A"},
        200,
    )
    (first,) = desk.get(f"/contracts/{renamed['hid']}/terms")
    assert (first["number"], first["began_on"], first["ended_on"]) == ("CON-9", day(0), day(0))


def _moment(offset: int) -> datetime:
    return datetime.combine(TODAY + timedelta(days=offset), time(12), tzinfo=UTC)


def _event(db: Session, hid: str) -> AuditEvent:
    found = db.scalars(
        select(AuditEvent).where(AuditEvent.record_hid == hid).order_by(AuditEvent.at)
    ).first()
    assert found is not None
    return found


# --- worked out ahead of the first sign-in ----------------------------------------------


def test_the_alert_of_the_day_is_worked_out_just_after_midnight_and_at_start(
    desk: Renewer, config: Config
) -> None:
    desk.contract("CON-LAP", starts_on=day(-400), ends_on=day(-10))
    kept.drop()
    sessions = make_sessions(make_engine(config.database_url))
    scheduler = Scheduler(sessions, (LONG_REPORTS,))
    start = datetime.now(UTC)
    assert scheduler.run_due(start, starting=True) == ["long reports"]
    with sessions() as db:
        stamp = kept.stamp(db)
    # The day's summary is kept, and the alert is answered from it.
    assert any(key[0] == "renewal_alert" and key[2:] == stamp for key in kept._kept)
    assert desk.get("/renewals/alert")["lapsed"]["count"] == 1
    # It is due again just after the next midnight, and not before.
    assert scheduler.run_due(start + timedelta(minutes=1)) == []
    zone = ZoneInfo("America/New_York")
    # Five minutes past, once the record of the week is made, which another process
    # may make (P-267): at two minutes past it is not due yet.
    midnight = datetime.combine(
        start.astimezone(zone).date() + timedelta(days=1), time(0, 2), tzinfo=zone
    )
    assert scheduler.run_due(midnight) == []
    assert scheduler.run_due(midnight + timedelta(minutes=4)) == ["long reports"]
