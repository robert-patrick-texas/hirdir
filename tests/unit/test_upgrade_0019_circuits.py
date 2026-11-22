"""The circuits of the upgrade to 0019 (P-320 (10)): the three dates renamed to the A
side's, the Z side's added blank, and every circuit group a collection, so that no
circuit's dates change and none is in service on another day than before."""

from datetime import date
from pathlib import Path

from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from hirdir.db import migrate
from hirdir.db.engine import make_engine
from hirdir.db.models import Circuit
from hirdir.domain import circuits

# Each circuit before the upgrade: its HID, its cost side, its status and its three dates.
HELD = (
    ("c-1", "a", "active", "2025-03-03", "2025-03-10", None),
    ("c-2", "z", "active", None, "2025-06-01", "2027-06-30"),
    ("c-3", "z", "retired", "2024-01-08", "2024-01-15", "2026-02-28"),
    ("c-4", "a", "draft", None, "2027-02-01", None),
)
DAYS = (date(2024, 6, 1), date(2025, 3, 9), date(2025, 6, 1), date(2026, 3, 1), date(2027, 7, 1))


def _was_in_service(
    status: str, activated: str | None, disconnected: str | None, day: date
) -> bool:
    """Say whether a circuit was in service on a day as 0.9.17 read it: by its dates."""
    if status == "retired" and disconnected is None:
        return False
    if status not in ("active", "retired"):
        return False
    began = date.fromisoformat(activated) if activated else None
    ended = date.fromisoformat(disconnected) if disconnected else None
    return not (began and day < began) and not (ended and day > ended)


def test_the_upgrade_to_0019_keeps_every_circuits_dates_and_service(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hirdir.db'}"
    command.upgrade(migrate.alembic_config(url), "0018")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO regions (hid, name, name_key, record_status, created_at,"
                " updated_at, row_version) VALUES ('r-1', 'Americas', 'americas', 'active',"
                " '2026-01-01', '2026-01-01', 3)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO sites (hid, name, name_key, region_hid, ship_same_as_address,"
                " record_status, created_at, updated_at, row_version) VALUES ('s-1', 'Site-2',"
                " 'site-2', 'r-1', 1, 'active', '2026-01-01', '2026-01-01', 3)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO locations (hid, name, name_key, site_hid, ship_same_as_address,"
                " record_status, created_at, updated_at, row_version) VALUES ('l-1', 'Room 102',"
                " 'room 102', 's-1', 1, 'active', '2026-01-01', '2026-01-01', 3)"
            )
        )
        for hid, side, status, installed, activated, disconnected in HELD:
            connection.execute(
                text(
                    "INSERT INTO circuits (hid, name, name_key, a_location_hid, z_note,"
                    " cost_side, installed_on, activated_on, disconnected_on, record_status,"
                    " created_at, updated_at, row_version) VALUES (:hid, :hid, :hid, 'l-1',"
                    " 'carrier network', :side, :installed, :activated, :disconnected, :status,"
                    " '2026-01-01', '2026-01-01', 3)"
                ),
                {
                    "hid": hid,
                    "side": side,
                    "status": status,
                    "installed": installed,
                    "activated": activated,
                    "disconnected": disconnected,
                },
            )
        for hid, status in (("g-1", "active"), ("g-2", "retired")):
            connection.execute(
                text(
                    "INSERT INTO circuit_groups (hid, name, name_key, record_status, created_at,"
                    " updated_at, row_version) VALUES (:hid, :hid, :hid, :status, '2026-01-01',"
                    " '2026-01-01', 3)"
                ),
                {"hid": hid, "status": status},
            )
        connection.execute(
            text(
                "INSERT INTO circuit_group_members (hid, group_hid, circuit_hid, created_at,"
                " updated_at, row_version) VALUES ('m-1', 'g-1', 'c-2', '2026-01-01',"
                " '2026-01-01', 3)"
            )
        )
    engine.dispose()

    command.upgrade(migrate.alembic_config(url), "0019")
    engine = make_engine(url)
    with engine.begin() as connection:
        names = {column["name"] for column in inspect(connection).get_columns("circuits")}
        assert not names & {"installed_on", "activated_on", "disconnected_on"}
        rows = connection.execute(
            text(
                "SELECT hid, cost_side, record_status, a_installed_on, a_activated_on,"
                " a_disconnected_on, z_installed_on, z_activated_on, z_disconnected_on,"
                " z_group_hid, row_version FROM circuits ORDER BY hid"
            )
        ).all()
        assert [tuple(row) for row in rows] == [(*held, None, None, None, None, 3) for held in HELD]
        groups = connection.execute(
            text("SELECT hid, kind, carrier_hid, record_status, row_version FROM circuit_groups")
        ).all()
        assert sorted(tuple(row) for row in groups) == [
            ("g-1", "collection", None, "active", 3),
            ("g-2", "collection", None, "retired", 3),
        ]
        assert connection.execute(text("SELECT circuit_hid FROM circuit_group_members")).all() == [
            ("c-2",)
        ]
        # No event is written of a circuit or a group: nothing of theirs changed.
        written = connection.execute(
            text(
                "SELECT count(*) FROM audit_events"
                " WHERE record_type IN ('circuit', 'circuit_group')"
            )
        ).scalar()
        assert written == 0
    # Each is in service on the days it was, by its own side's dates or, counted at the
    # Z side, by the Z side's, blank and read as the A side's.
    with Session(engine) as db:
        upgraded = {one.hid: one for one in db.scalars(select(Circuit))}
        for hid, _, status, _, activated, disconnected in HELD:
            for day in DAYS:
                assert circuits.in_service_on(upgraded[hid], day) == _was_in_service(
                    status, activated, disconnected, day
                ), (hid, day)
    # A Z side that names a network, with no note of its own, as 0.9.18 allows.
    with engine.begin() as connection:
        connection.execute(text("UPDATE circuit_groups SET kind = 'network' WHERE hid = 'g-1'"))
        connection.execute(
            text("UPDATE circuits SET z_note = NULL, z_group_hid = 'g-1' WHERE hid = 'c-4'")
        )
    engine.dispose()

    command.downgrade(migrate.alembic_config(url), "0018")
    with make_engine(url).connect() as connection:
        rows = connection.execute(
            text(
                "SELECT hid, cost_side, record_status, installed_on, activated_on,"
                " disconnected_on FROM circuits ORDER BY hid"
            )
        ).all()
        assert [tuple(row) for row in rows] == list(HELD)
        # Going back, it keeps the network's name as its note, which 0.9.17 needs of a
        # side with no location.
        notes = connection.execute(text("SELECT hid, z_note FROM circuits ORDER BY hid")).all()
        assert [tuple(row) for row in notes] == [
            ("c-1", "carrier network"),
            ("c-2", "carrier network"),
            ("c-3", "carrier network"),
            ("c-4", "g-1"),
        ]
        # And it is in the network by a membership, beside the one added by hand.
        members = connection.execute(
            text("SELECT group_hid, circuit_hid FROM circuit_group_members ORDER BY circuit_hid")
        ).all()
        assert [tuple(row) for row in members] == [("g-1", "c-2"), ("g-1", "c-4")]
        names = {column["name"] for column in inspect(connection).get_columns("circuit_groups")}
        assert not names & {"kind", "carrier_hid"}
