"""Every count of the summary and of the management report opens the items it counts
(P-206): the item list asked with the filter the report gives counts what it says."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit
from hirdir.io import examples, filters, reports
from tests.api.inventory import Maker
from tests.conftest import VIEWER_CODE, sign_in

HEALTHS = ("good", "degraded", "failed", "unknown")


@pytest.fixture(scope="module")
def stocked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Maker]:
    """The fictional examples, loaded once for this module, read by a View-only user."""
    config = Config(state_dir=tmp_path_factory.mktemp("lists"), trusted_proxies=("testclient",))
    migrate.upgrade(config.database_url)
    with make_sessions(make_engine(config.database_url))() as session:
        examples.load(session, examples.folder())
        user, _ = accounts.create_user(
            session, audit.SYSTEM, username="vic", access_code=VIEWER_CODE
        )
        accounts.grant_role(session, audit.SYSTEM, role="viewer", user_hid=user.hid)
        session.commit()
    with TestClient(create_app(config)) as client:
        yield Maker(client, sign_in(client, "vic", VIEWER_CODE))


def joined(*texts: str | None) -> str:
    """Join filters of a report by AND, as the web joins a row's to a count's condition."""
    trees = [filters.to_tree(filters.parse(text)) for text in texts]
    return filters.as_text(filters.both(*trees))


def listed(make: Maker, text: str, view: dict[str, Any]) -> int:
    """How many items the item list holds for a filter of a report, minor items and all."""
    query: dict[str, Any] = {key: "true" for key, on in view.items() if on}
    return make.get("/items", filter=text, limit=1, fields="hid", **query)["total"]


def held(make: Maker, counted: dict[str, Any], view: dict[str, Any], when: dict[str, Any]) -> None:
    """Check that the item list holds what each count of a row or a total says."""
    assert counted["filter"] is not None, counted
    where = f"{counted.get('key')} {counted.get('label')}"
    assert listed(make, counted["filter"], view) == counted["items"], where
    components = joined(counted["filter"], when["component_count"])
    assert listed(make, components, view) == counted["component_count"], where
    for health, condition in when.get("by_health", {}).items():
        if health in counted.get("by_health", {}):
            text = joined(counted["filter"], condition)
            assert listed(make, text, view) == counted["by_health"][health], (where, health)


VIEWS = [
    {},
    {"include_archived": True, "include_drafts": True},
]


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("by", reports.SUMMARY_BY)
def test_each_count_of_the_summary_is_what_its_filter_lists(
    stocked: Maker, by: str, view: dict[str, Any]
) -> None:
    query: dict[str, Any] = {key: "true" for key, on in view.items() if on}
    answer = stocked.get("/reports/summary", by=by, **query)
    when = answer["conditions"]
    assert set(when["by_health"]) == set(HEALTHS)
    assert answer["rows"], by
    for row in answer["rows"]:
        held(stocked, row, view, when)


@pytest.mark.parametrize("view", VIEWS)
def test_each_total_of_the_summary_is_what_its_filter_lists(
    stocked: Maker, view: dict[str, Any]
) -> None:
    query: dict[str, Any] = {key: "true" for key, on in view.items() if on}
    answer = stocked.get("/reports/summary", **query)
    when = answer["conditions"]
    totals = answer["totals"]
    assert totals["filter"] == ""
    held(stocked, totals, view, when)
    for condition in totals["by_condition"]:
        held(stocked, condition, view, {"component_count": when["component_count"]})
    for kind in totals["by_kind"]:
        held(stocked, kind, view, {"component_count": when["component_count_by_kind"]})


@pytest.mark.parametrize("by", reports.MANAGEMENT_BY)
def test_each_count_of_the_management_report_is_what_its_filter_lists(
    stocked: Maker, by: str
) -> None:
    answer = stocked.get("/reports/management", by=by)
    when = answer["conditions"]
    held(stocked, answer["totals"], {}, when)
    assert answer["rows"], by
    for row in answer["rows"]:
        held(stocked, row, {}, when)


def test_a_filter_of_the_view_is_in_the_filter_of_each_count(stocked: Maker) -> None:
    view = "catalog.type:eq:switch"
    answer = stocked.get("/reports/summary", filter=view, by="site")
    assert answer["totals"]["filter"] == view
    for row in answer["rows"]:
        assert row["filter"].startswith(f"{view} "), row
        held(stocked, row, {}, answer["conditions"])
    # The short form where it can say it, and the tree in JSON where it cannot.
    by_kind = stocked.get("/reports/summary", by="kind")["rows"]
    hardware = next(row for row in by_kind if row["key"] == "hardware")
    assert hardware["filter"].startswith('{"or": ')
    software = next((row for row in by_kind if row["key"] == "software"), None)
    if software is not None:
        assert software["filter"] == "catalog.kind:eq:software"


def test_a_filter_too_large_to_join_a_count_to_is_given_as_none(stocked: Maker) -> None:
    conditions = [filters.where("hostname", "ne", f"ex-{place}") for place in range(95)]
    tree = {"and": conditions}
    answer = stocked.client.get(
        "/api/v1/reports/summary",
        params={"filter": filters.as_text(tree), "by": "vendor"},
        headers=stocked.headers,
    ).json()
    assert answer["totals"]["filter"] is None
    assert {row["filter"] for row in answer["rows"]} == {None}


def test_a_filter_too_long_to_send_with_a_count_is_given_as_none(stocked: Maker) -> None:
    # Few conditions, each long: within the conditions and the depth a filter may have,
    # and as long as a filter may be once a count's condition is joined to it.
    def view(length: int) -> str:
        return filters.as_text(
            {
                "and": [
                    filters.where("hostname", "ne", f"{place:02d}" + "x" * length)
                    for place in range(30)
                ]
            }
        )

    def asked(text: str) -> dict[str, Any]:
        answer = stocked.client.get(
            "/api/v1/reports/summary",
            params={"filter": text, "by": "vendor"},
            headers=stocked.headers,
        )
        assert answer.status_code == 200, answer.text
        return answer.json()

    long = view(240)
    assert filters.MAX_FILTER_LENGTH - 600 < len(long) <= filters.MAX_FILTER_LENGTH
    answer = asked(long)
    assert answer["totals"]["filter"] is None
    assert {row["filter"] for row in answer["rows"]} == {None}

    # One that leaves room is answered, and every count of it can be sent to the list.
    answer = asked(view(150))
    assert answer["totals"]["filter"] is not None
    for when in (
        answer["conditions"]["component_count"],
        *answer["conditions"]["by_health"].values(),
    ):
        text = joined(answer["totals"]["filter"], when)
        assert len(text) <= filters.MAX_FILTER_LENGTH
        listed(stocked, text, {})
