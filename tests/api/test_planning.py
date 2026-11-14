"""The reports that look ahead: end of life, replacements, and the portfolio of a vendor."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db import dialect
from hirdir.io import planning
from tests.api.inventory import API, Maker, errors

TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _switch(make: Maker, entry: dict[str, Any], serial: str, **more: Any) -> dict[str, Any]:
    more.setdefault("lifecycle_state", "Prod")
    return make.item(catalog_entry_hid=entry["hid"], serial_number=serial, **more)


def test_the_end_of_life_report_is_past_and_approaching_for_each_date(
    make: Maker, admin: dict
) -> None:
    cisco = make.vendor()
    old = make.entry(cisco, "WS-C3850-48P", ldos=day(-40), end_of_sale=day(-900))
    ageing = make.entry(cisco, "C9200L-48P", ldos=day(400))
    lasting = make.entry(cisco, "C9300-48P", ldos=day(3000))
    undated = make.entry(cisco, "C9500-24Y4C")
    past = _switch(make, old, "FOC-1")
    near = _switch(make, ageing, "JAE-1")
    # An item's own date overrides its model's.
    sooner = _switch(make, lasting, "FCW-1", ldos=day(30))
    _switch(make, lasting, "FCW-2")
    _switch(make, undated, "FCW-3")
    supply = make.item(
        catalog_entry_hid=old["hid"], serial_number="LIT-1", parent_item_hid=near["hid"]
    )

    report = make.get("/reports/end-of-life")
    assert (report["date"], report["within_days"], report["section"]) == ("ldos", 730, None)
    assert report["dates"]["ldos"] == {
        "past": {"items": 2, "component_count": 1},
        "approaching": {"items": 2, "component_count": 2},
    }
    assert report["dates"]["end_of_sale"]["past"] == {"items": 2, "component_count": 1}
    assert report["dates"]["end_of_hw_support"]["approaching"] == {"items": 0, "component_count": 0}
    assert sum(row["items"] for row in report["by_fiscal_year"]) == 5
    for name, expected in (("past", [past, supply]), ("approaching", [sooner, near])):
        page = make.get("/reports/end-of-life", section=name, sort="effective.ldos,-is_major")
        assert [item["hid"] for item in page["items"]] == [one["hid"] for one in expected], name
        section = page["sections"][name]
        assert page["total"] == section["count"] == len(expected)
        same = make.post("/items/query", {"filter": section["filter"]}, 200)
        assert {item["hid"] for item in same["items"]} == {one["hid"] for one in expected}
    # A shorter horizon, another date, and a view that is filtered.
    assert (
        make.get("/reports/end-of-life", within_days=100)["dates"]["ldos"]["approaching"]["items"]
        == 1
    )
    by_sale = make.get("/reports/end-of-life", date="end_of_sale", section="past")
    assert {item["hid"] for item in by_sale["items"]} == {past["hid"], supply["hid"]}
    major = make.get("/reports/end-of-life", filter="is_major:eq:true")
    assert major["dates"]["ldos"]["past"]["items"] == 1
    assert "query.date" in errors(make.get("/reports/end-of-life", 422, date="birthday"))
    # The fiscal year is named for the calendar year it ends in.
    client, headers = make.client, admin
    put = client.put(
        f"{API}/settings/fiscal_year_start_month",
        json={"row_version": 0, "value": 10},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    years = make.get("/reports/end-of-life")["by_fiscal_year"]
    assert all(row["starts_on"].endswith("-10-01") for row in years)
    assert all(row["ends_on"] == f"{row['fiscal_year']}-09-30" for row in years)


def test_a_fiscal_year_is_named_for_the_year_it_ends_in() -> None:
    assert planning.fiscal_year(date(2027, 6, 30), 1) == (
        2027,
        date(2027, 1, 1),
        date(2027, 12, 31),
    )
    assert planning.fiscal_year(date(2027, 6, 30), 10) == (
        2027,
        date(2026, 10, 1),
        date(2027, 9, 30),
    )
    assert planning.fiscal_year(date(2027, 10, 1), 10)[0] == 2028
    assert planning.fiscal_year(date(2028, 2, 29), 3) == (2028, date(2027, 3, 1), date(2028, 2, 29))


def test_the_replacements_are_listed_with_the_count_of_each_reason(make: Maker) -> None:
    entry = make.entry(make.vendor())
    olds = make.switches(entry, "old", 3)
    news = make.switches(entry, "new", 3)
    for old, new, reason, on in zip(
        olds,
        news,
        ("rma", "rma", "refresh"),
        ("2026-03-01", "2026-05-01", "2026-04-01"),
        strict=True,
    ):
        make.post(
            f"/items/{old['hid']}/replace",
            {
                "row_version": old["row_version"],
                "new_item_hid": new["hid"],
                "reason": reason,
                "reference": f"RMA-{on}",
                "replaced_on": on,
            },
        )
    report = make.get("/reports/replacements")
    assert report["total"] == 3
    # The newest first.
    assert [row["replaced_on"] for row in report["items"]] == [
        "2026-05-01",
        "2026-04-01",
        "2026-03-01",
    ]
    first = report["items"][0]
    assert (first["old_item"]["name"], first["new_item"]["name"], first["reason_label"]) == (
        "old-02",
        "new-02",
        "RMA",
    )
    assert [(one["reason"], one["count"]) for one in report["by_reason"]] == [
        ("rma", 2),
        ("refresh", 1),
    ]
    narrowed = make.get(
        "/reports/replacements", filter="reason:eq:rma replaced_on:gte:2026-04-01", sort="old.name"
    )
    assert (narrowed["total"], narrowed["by_reason"]) == (
        1,
        [{"reason": "rma", "label": "RMA", "count": 1}],
    )
    assert make.get("/reports/replacements", filter="new.serial_number:eq:NEW-003")["total"] == 1
    assert (
        make.get("/reports/replacements", limit=1, offset=1)["items"][0]["replaced_on"]
        == "2026-04-01"
    )


def test_the_portfolio_is_everything_from_one_vendor(make: Maker) -> None:
    cisco, juniper = make.vendor(), make.vendor("Juniper")
    switch = make.entry(
        cisco,
        est_value="18000.00",
        support_weight="1",
        annual_support_cost="1200.00",
        ldos="2034-04-30",
    )
    licence = make.entry(
        cisco, "DNA-ADV", kind="software", support_weight="0.5", annual_support_cost="300.00"
    )
    first, second = (_switch(make, switch, f"FCW-{n}") for n in range(2))
    _switch(make, switch, "FCW-9", record_status="draft")
    make.item(
        catalog_entry_hid=licence["hid"], name="DNA Advantage", quantity=3, lifecycle_state="Prod"
    )
    make.item(catalog_entry_hid=make.entry(juniper, "EX4400-48P")["hid"], serial_number="JN-1")
    agreement = make.post("/agreements", {"name": "Cisco EA", "vendor_hid": cisco["hid"]})
    contract = make.post(
        "/contracts", {"number": "CON-1", "agreement_hid": agreement["hid"], "ends_on": day(200)}
    )
    through = make.post(
        "/contracts",
        {"number": "JNP-1", "vendor_hid": juniper["hid"], "reseller_hid": cisco["hid"]},
    )
    make.post(f"/contracts/{contract['hid']}/coverage", {"items": [{"item_hid": first["hid"]}]})
    make.post(
        "/capacity-lines",
        {
            "side": "supply",
            "category": "professional_services",
            "name": "Advanced services",
            "units_each": "1",
            "vendor_hid": cisco["hid"],
        },
    )

    portfolio = make.get(f"/vendors/{cisco['hid']}/portfolio")
    assert portfolio["vendor"] == {"hid": cisco["hid"], "name": "Cisco"}
    assert portfolio["totals"] == {
        "items": 3,
        "component_count": 2,
        "support_weight": "3.5",
        "est_value": "36000.00",
        "annual_support_cost": "3300.00",
        "covered": 1,
        "uncovered": 2,
    }
    kinds = {row["kind"]: row for row in portfolio["kinds"]}
    assert list(kinds) == ["hardware", "virtual_machine", "software", "service"]
    assert (kinds["hardware"]["items"], kinds["software"]["annual_support_cost"]) == (2, "900.00")
    assert kinds["service"] == {
        "kind": "service",
        "items": 0,
        "component_count": 0,
        "support_weight": "0",
        "est_value": "0.00",
        "annual_support_cost": "0.00",
        "covered": 0,
        "uncovered": 0,
    }
    models = {row["pid"]: row for row in portfolio["models"]}
    assert list(models) == ["C9300-48P", "DNA-ADV"]
    assert (models["C9300-48P"]["covered"], models["C9300-48P"]["covered_until"]) == (1, day(200))
    assert (models["C9300-48P"]["ldos"], models["DNA-ADV"]["covered_until"]) == ("2034-04-30", None)
    assert [one["name"] for one in portfolio["agreements"]] == ["Cisco EA"]
    # The contracts it provides, and the one that was bought through it.
    assert [one["number"] for one in portfolio["contracts"]] == ["CON-1", "JNP-1"]
    assert through["reseller"]["name"] == "Cisco"
    assert [one["name"] for one in portfolio["capacity_lines"]] == ["Advanced services"]
    listed = make.post("/items/query", {"filter": portfolio["filter"]}, 200)
    assert listed["total"] == 3
    assert (
        make.get(f"/vendors/{cisco['hid']}/portfolio", include_drafts="true")["totals"]["items"]
        == 4
    )
    assert make.get(f"/vendors/{second['hid']}/portfolio", 404)["status"] == 404


def test_today_is_the_applications_day_and_is_worked_out_once(
    db: Session, client: TestClient, admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The day that "in force today" is of is the application's, by its `time_zone`
    setting, and a statement works it out once and not for every row."""
    assert db.scalar(select(dialect.today())) == clock.today()
    put = client.put(
        f"{API}/settings/time_zone",
        json={"row_version": 0, "value": "Pacific/Kiritimati"},
        headers=admin,
    )
    assert put.status_code == 200, put.text
    db.rollback()
    assert db.scalar(select(dialect.today())) == clock.today("Pacific/Kiritimati")
    calls = []
    real = dialect._sqlite_today

    def counted(setting: Any) -> str:
        calls.append(setting)
        return real(setting)

    connection: Any = db.connection().connection.driver_connection
    connection.create_function("hirdir_today", 1, counted)
    db.execute(text("CREATE TEMP TABLE many AS SELECT value FROM json_each('[1,2,3,4,5,6,7,8]')"))
    found = db.execute(select(text("many.value"), dialect.today()).select_from(text("many"))).all()
    assert len(found) == 8
    assert len(calls) == 1
