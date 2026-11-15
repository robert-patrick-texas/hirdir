"""Scenarios S41 and S42 of docs/build-plan.md, against a real server process."""

import json
from datetime import date, timedelta
from typing import Any

import pytest

from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_item_scenarios import IVY
from tests.acceptance.test_money_scenarios import Money

TODAY = date.today()


def day(offset: int) -> str:
    """Return a day well clear of today, so that the application's day and this host's
    agree on it."""
    return (TODAY + timedelta(days=offset)).isoformat()


@pytest.fixture
def money(server: Server) -> Money:
    """The scenarios are worked by a user with the Inventory role, not by the Admin."""
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Money(server.sign_in(*IVY))


def rows(money: Money, path: str, tree: dict[str, Any] | None) -> set[str]:
    """Return the HIDs of the rows a filter of a report leads to."""
    params: dict[str, Any] = {"limit": 1000}
    if tree is not None:
        params["filter"] = json.dumps(tree)
    return {row["hid"] for row in money.get(path, **params)["items"]}


def test_s41_the_worklist_lists_what_to_act_on_and_the_alert_is_shown_once(
    money: Money,
) -> None:
    money.post("/vendors", {"name": "Cisco"})
    entry = money.entry("C9300-48P")
    cisco = money.get("/vendors", filter="name:eq:Cisco")["items"][0]
    agreement = money.post(
        "/agreements",
        {
            "name": "Cisco Enterprise Agreement",
            "vendor_hid": cisco["hid"],
            "starts_on": day(-300),
            "ends_on": day(300),
        },
    )
    within = {"agreement_hid": agreement["hid"]}
    ending = money.contract("CON-ENDING", starts_on=day(-300), ends_on=day(30), **within)
    lapsed = money.contract("CON-LAPSED", starts_on=day(-400), ends_on=day(-10), **within)
    pending = money.contract(
        "CON-PENDING", starts_on=day(-500), ends_on=day(-75), status="renewal_pending", **within
    )
    other = money.contract("CON-OTHER", starts_on=day(-10), ends_on=day(400), **within)
    switch = money.item(entry, "FCW0000X041", lifecycle_state="Prod")
    money.cover(ending, switch)
    money.cover(other, switch)

    found = money.get("/reports/renewals")
    assert found["totals"] == {
        "ending": 1,
        "lapsed": 1,
        "renewal_pending": 1,
        "overdue": 1,
        "ends_with_term": 0,
        "overlapping": 1,
    }
    (group,) = found["groups"]
    assert (group["vendor"], group["agreement"]) == ("Cisco", "Cisco Enterprise Agreement")
    assert group["counts"]["overdue"] == 1
    # Each count leads to its rows.
    for name, expected in (
        ("ending", ending),
        ("lapsed", lapsed),
        ("renewal_pending", pending),
        ("overdue", pending),
    ):
        assert rows(money, "/contracts", group["filters"][name]) == {expected["hid"]}
    assert rows(money, "/items", group["filters"]["overlapping"]) == {switch["hid"]}
    page = money.get("/reports/renewals", section="overdue")
    (overdue,) = page["contracts"]
    assert (overdue["number"], overdue["renewal_pending_days"], overdue["renewal_overdue"]) == (
        "CON-PENDING",
        75,
        True,
    )

    # After signing in, the alert counts them, and once seen is not shown again ...
    alert = money.get("/renewals/alert")
    assert alert["show"] is True
    counts = [alert[name]["count"] for name in ("lapsed", "renewal_pending", "ending")]
    assert (counts, alert["overdue"]) == ([1, 1, 1], 1)
    money.post("/renewals/alert/seen", {"version": alert["version"]}, expect=200)
    assert money.get("/renewals/alert")["show"] is False
    # ... until another contract lapses.
    money.contract("CON-LAPSED-2", starts_on=day(-400), ends_on=day(-2), **within)
    again = money.get("/renewals/alert")
    assert (again["show"], again["lapsed"]["count"], again["lapsed"]["new"]) == (True, 2, 1)
