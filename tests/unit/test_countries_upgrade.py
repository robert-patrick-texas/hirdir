"""The upgrade to 0019 makes the lists of countries and states and turns the countries
and states that addresses hold into their codes where they match exactly (P-321 (9))."""

import json
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import text

from hirdir.db import migrate
from hirdir.db.engine import make_engine

BOOKKEEPING = "'active', '2026-01-01', '2026-01-01', 3"
# The places of a release before, each with the address it was typed with: a region has
# the shipping set alone; a site and a location a street address and a shipping set.
REGIONS = (("r-1", "Americas", {"ship_country": "usa", "ship_state": "tx"}),)
SITES = (
    (
        "s-1",
        "Site-1",
        {
            "country": " U.S. ",
            "state": "texas",
            "ship_country": "Mexico",
            "ship_state": "Coahuila de Zaragoza",
        },
    ),
    ("s-2", "Site-2", {"country": "MX", "state": "Coahuila de Zaragoza", "city": "Saltillo"}),
    # Nothing a list holds: the country is kept, and so is a state of no list.
    ("s-3", "Site-3", {"country": "Untied States", "state": "Texas"}),
    ("s-4", "Site-4", {"country": "US", "state": "Lone Star"}),
    # As they are already: nothing to write.
    ("s-5", "Site-5", {"country": "US", "state": "TX", "ship_country": "CA"}),
)
LOCATIONS = (
    # A blank country is read as the United States, and not written so.
    ("l-1", "Room 1", {"city": "Austin", "state": "texas"}),
    ("l-2", "Room 2", {"country": "united states of america", "ship_country": "U.S.A."}),
)


def _insert(connection: Any, table: str, hid: str, name: str, more: dict[str, Any]) -> None:
    columns = {"hid": hid, "name": name, "name_key": name.casefold(), **more}
    if table == "sites":
        columns |= {"region_hid": "r-1", "ship_same_as_address": 0}
    if table == "locations":
        columns |= {"site_hid": "s-1", "ship_same_as_address": 0}
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    connection.execute(
        text(
            f"INSERT INTO {table} ({names}, record_status, created_at, updated_at,"  # noqa: S608 - the names are the test's own
            f" row_version) VALUES ({values}, {BOOKKEEPING})"
        ),
        columns,
    )


def test_the_upgrade_to_0019_turns_what_the_lists_hold_into_codes(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0018")
    engine = make_engine(url)
    with engine.begin() as connection:
        for table, places in (("regions", REGIONS), ("sites", SITES), ("locations", LOCATIONS)):
            for hid, name, address in places:
                _insert(connection, table, hid, name, address)
    engine.dispose()

    command.upgrade(migrate.alembic_config(url), "0019")
    engine = make_engine(url)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM countries")).scalar() == 55
        assert connection.execute(text("SELECT count(*) FROM states")).scalar() == 633

        def held(table: str, hid: str, *names: str) -> tuple[Any, ...]:
            row = connection.execute(
                text(f"SELECT {', '.join(names)} FROM {table} WHERE hid = :hid"),  # noqa: S608 - the test's own names
                {"hid": hid},
            ).one()
            return tuple(row)

        sets = ("country", "state", "ship_country", "ship_state", "row_version")
        assert held("regions", "r-1", "ship_country", "ship_state", "row_version") == (
            "US",
            "TX",
            4,
        )
        assert held("sites", "s-1", *sets) == ("US", "TX", "MX", "COA", 4)
        assert held("sites", "s-2", *sets) == ("MX", "COA", None, None, 4)
        assert held("sites", "s-3", *sets) == ("Untied States", "Texas", None, None, 3)
        assert held("sites", "s-4", *sets) == ("US", "Lone Star", None, None, 3)
        assert held("sites", "s-5", *sets) == ("US", "TX", "CA", None, 3)
        assert held("locations", "l-1", *sets) == (None, "TX", None, None, 4)
        assert held("locations", "l-2", *sets) == ("US", None, "US", None, 4)

        # One event to each place it changed, by the system, with before and after.
        events = connection.execute(
            text(
                "SELECT record_type, record_hid, actor_hid, via, action, changes FROM"
                " audit_events ORDER BY record_type, record_hid"
            )
        ).all()

        found = {
            (kind, hid): {one["field"]: (one["old"], one["new"]) for one in json.loads(changes)}
            for kind, hid, actor, via, action, changes in events
            if (actor, via, action) == (None, "system", "update")
        }
        assert len(events) == len(found)
        assert found == {
            ("location", "l-1"): {"state": ("texas", "TX")},
            ("location", "l-2"): {
                "country": ("united states of america", "US"),
                "ship_country": ("U.S.A.", "US"),
            },
            ("region", "r-1"): {"ship_country": ("usa", "US"), "ship_state": ("tx", "TX")},
            ("site", "s-1"): {
                "country": (" U.S. ", "US"),
                "state": ("texas", "TX"),
                "ship_country": ("Mexico", "MX"),
                "ship_state": ("Coahuila de Zaragoza", "COA"),
            },
            ("site", "s-2"): {"state": ("Coahuila de Zaragoza", "COA")},
        }
    engine.dispose()

    # Going back, the lists go and the codes stay: each is a country or a state as it
    # may have been typed.
    command.downgrade(migrate.alembic_config(url), "0018")
    with make_engine(url).connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master"))}
        assert not {"countries", "states"} & tables
        row = connection.execute(text("SELECT country, state FROM sites WHERE hid = 's-1'")).one()
        assert tuple(row) == ("US", "TX")
