"""the dates of each side of a circuit, networks, and the lists of countries and states

Revision: 0019
Revises: 0018

A circuit's dates are its A side's (P-317, P-320): `installed_on`, `activated_on` and
`disconnected_on` are renamed `a_installed_on`, `a_activated_on` and
`a_disconnected_on`, and the Z side's three are added, blank, a blank one being read as
the A side's. No date changes, and no circuit's service: a circuit whose `cost_side` is
`z` has its Z side's dates read as its A side's.

A circuit group has a kind (P-319): `network` or `collection`, every group made before
being a `collection`, and a network may name its carrier, a vendor. A circuit's Z side
may name a network, `z_group_hid`, and never a location as well.

The lists of countries and states (P-318, P-321) are made and loaded with every country
of the Americas and its subdivisions, from the ISO 3166 data of `iso-codes`, kept beside
this file in `0019_iso3166_americas.json` so that the migration does not change with
the code. Then the street address and the shipping set of every region, site and
location has its country turned into its code where it is a listed code or name,
without regard to case and to spaces before or after, or `USA`, `U.S.`, `U.S.A.` or
`United States of America`, and its state into its code where it is a code or a name of
the country in force, a blank country being read as the United States. Anything else
is kept as it was typed, to be chosen by a person; a country of spaces alone is made
blank. Each place changed has an audit event by `system` with the values before and
after. The downgrade keeps the codes, gives a Z side that named a network the
network's name as its note, where it had none, and puts a circuit into the network its
Z side named, where it was not in it by hand.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

LISTS = Path(__file__).with_name("0019_iso3166_americas.json")
DATES = ("installed_on", "activated_on", "disconnected_on")
US = "US"
US_TOO = ("usa", "u.s.", "u.s.a.", "united states of america")
SETS = ("", "ship_")
PLACES = (
    ("regions", "region", ("ship_",)),
    ("sites", "site", SETS),
    ("locations", "location", SETS),
)


def _key(text: str) -> str:
    return text.strip().casefold()


def _bookkeeping() -> list[sa.Column[Any]]:
    return [
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("row_version", sa.Integer, nullable=False),
    ]


def _circuits() -> None:
    with op.batch_alter_table("circuit_groups") as groups:
        groups.add_column(
            sa.Column("kind", sa.String(20), nullable=False, server_default="collection")
        )
        groups.add_column(sa.Column("carrier_hid", sa.String(36)))
        groups.create_foreign_key(
            "fk_circuit_groups_carrier_hid", "vendors", ["carrier_hid"], ["hid"]
        )
        groups.create_index("ix_circuit_groups_carrier_hid", ["carrier_hid"], unique=False)
    with op.batch_alter_table("circuits") as circuits:
        for name in DATES:
            circuits.alter_column(name, new_column_name=f"a_{name}", existing_type=sa.Date)
        for name in DATES:
            circuits.add_column(sa.Column(f"z_{name}", sa.Date))
        circuits.add_column(sa.Column("z_group_hid", sa.String(36)))
        circuits.create_foreign_key(
            "fk_circuits_z_group_hid", "circuit_groups", ["z_group_hid"], ["hid"]
        )
        circuits.create_index("ix_circuits_z_group_hid", ["z_group_hid"], unique=False)
        circuits.create_check_constraint(
            "circuits_z_location_or_group", "z_location_hid IS NULL OR z_group_hid IS NULL"
        )


def _lists(now: datetime) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Make and load the two lists; return how a country and a state are found."""
    countries = op.create_table(
        "countries",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("code", name="countries_code"),
        sa.UniqueConstraint("name_key", name="countries_name"),
    )
    states = op.create_table(
        "states",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("country", "code", name="states_code"),
        sa.UniqueConstraint("country", "name_key", name="states_name"),
    )
    op.create_index("ix_states_country", "states", ["country"])
    data = json.loads(LISTS.read_text(encoding="utf-8"))
    kept = {"created_at": now, "updated_at": now, "row_version": 1}
    op.bulk_insert(
        countries,
        [
            {"hid": str(uuid.uuid7()), "code": code, "name": name, "name_key": _key(name), **kept}
            for code, name in data["countries"]
        ],
    )
    op.bulk_insert(
        states,
        [
            {
                "hid": str(uuid.uuid7()),
                "country": country,
                "code": code,
                "name": name,
                "name_key": _key(name),
                **kept,
            }
            for country, code, name in data["states"]
        ],
    )
    found_country: dict[str, str] = {}
    for code, name in data["countries"]:
        found_country[_key(code)] = code
        found_country[_key(name)] = code
    for alias in US_TOO:
        found_country[alias] = US
    found_state: dict[str, dict[str, str]] = {}
    for country, code, name in data["states"]:
        mine = found_state.setdefault(country, {})
        mine[_key(code)] = code
        mine[_key(name)] = code
    return found_country, found_state


def _addresses(
    now: datetime, found_country: dict[str, str], found_state: dict[str, dict[str, str]]
) -> None:
    """Turn into its code each country and state held that a list holds (P-321)."""
    bind = op.get_bind()
    events: list[dict[str, Any]] = []
    for table_name, record_type, sets in PLACES:
        columns = [f"{prefix}{field}" for prefix in sets for field in ("state", "country")]
        table = sa.table(
            table_name,
            sa.column("hid", sa.String),
            sa.column("updated_at", sa.DateTime),
            sa.column("row_version", sa.Integer),
            *(sa.column(name, sa.String) for name in columns),
        )
        rows = bind.execute(
            sa.select(table.c.hid, *(table.c[name] for name in columns)).order_by(table.c.hid)
        ).all()
        for row in rows:
            values = dict(zip(columns, row[1:], strict=True))
            changed: dict[str, str | None] = {}
            for prefix in sets:
                country = values[f"{prefix}country"]
                state = values[f"{prefix}state"]
                code = found_country.get(_key(country)) if country and country.strip() else None
                if code is not None and code != country:
                    changed[f"{prefix}country"] = code
                elif country is not None and not country.strip():
                    # A country of spaces alone is blank, and is held so, as it is read.
                    changed[f"{prefix}country"] = None
                # A blank country is read as the United States, and is not written so.
                in_force = (
                    code if code is not None else (US if not (country or "").strip() else None)
                )
                if in_force is not None and state and state.strip():
                    listed = found_state.get(in_force, {}).get(_key(state))
                    if listed is not None and listed != state:
                        changed[f"{prefix}state"] = listed
            if not changed:
                continue
            bind.execute(
                table.update()
                .where(table.c.hid == row.hid)
                .values(**changed, updated_at=now, row_version=table.c.row_version + 1)
            )
            events.append(
                {
                    "hid": str(uuid.uuid7()),
                    "at": now,
                    "actor_hid": None,
                    "via": "system",
                    "request_id": "upgrade-0019",
                    "action": "update",
                    "record_type": record_type,
                    "record_hid": row.hid,
                    "changes": [
                        {"field": field, "old": values[field], "new": new}
                        for field, new in changed.items()
                    ],
                }
            )
    if events:
        audit = sa.table(
            "audit_events",
            sa.column("hid", sa.String),
            sa.column("at", sa.DateTime),
            sa.column("actor_hid", sa.String),
            sa.column("via", sa.String),
            sa.column("request_id", sa.String),
            sa.column("action", sa.String),
            sa.column("record_type", sa.String),
            sa.column("record_hid", sa.String),
            sa.column("changes", sa.JSON),
        )
        op.bulk_insert(audit, events)


def upgrade() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    _circuits()
    found_country, found_state = _lists(now)
    _addresses(now, found_country, found_state)


def downgrade() -> None:
    # The codes the upgrade wrote into addresses stay: each is a country or a state as it
    # may have been typed. The lists go, and so do the dates of the Z side and its network.
    op.drop_index("ix_states_country", table_name="states")
    op.drop_table("states")
    op.drop_table("countries")
    # A Z side that named a network keeps its name as its note, which a side with no
    # location needs in 0.9.17.
    groups = sa.table("circuit_groups", sa.column("hid", sa.String), sa.column("name", sa.String))
    held = sa.table(
        "circuits",
        sa.column("z_group_hid", sa.String),
        sa.column("z_note", sa.String),
    )
    op.execute(
        held.update()
        .where(held.c.z_group_hid.is_not(None), held.c.z_note.is_(None))
        .values(
            z_note=sa.select(groups.c.name)
            .where(groups.c.hid == held.c.z_group_hid)
            .scalar_subquery()
        )
    )
    # And it stays in the network, by a membership, where it was there by its Z side
    # alone, so that 0.9.17 counts the group as 0.9.18 did.
    bind = op.get_bind()
    members = sa.table(
        "circuit_group_members",
        sa.column("hid", sa.String),
        sa.column("group_hid", sa.String),
        sa.column("circuit_hid", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    naming = sa.table("circuits", sa.column("hid", sa.String), sa.column("z_group_hid", sa.String))
    there = {
        (row.group_hid, row.circuit_hid)
        for row in bind.execute(sa.select(members.c.group_hid, members.c.circuit_hid))
    }
    now = datetime.now(UTC).replace(tzinfo=None)
    added = [
        {
            "hid": str(uuid.uuid7()),
            "group_hid": group,
            "circuit_hid": circuit,
            "created_at": now,
            "updated_at": now,
            "row_version": 1,
        }
        for circuit, group in bind.execute(
            sa.select(naming.c.hid, naming.c.z_group_hid)
            .where(naming.c.z_group_hid.is_not(None))
            .order_by(naming.c.hid)
        )
        if (group, circuit) not in there
    ]
    if added:
        op.bulk_insert(members, added)
    with op.batch_alter_table("circuits") as circuits:
        circuits.drop_constraint("circuits_z_location_or_group", type_="check")
        circuits.drop_index("ix_circuits_z_group_hid")
        circuits.drop_constraint("fk_circuits_z_group_hid", type_="foreignkey")
        circuits.drop_column("z_group_hid")
        for name in DATES:
            circuits.drop_column(f"z_{name}")
        for name in DATES:
            circuits.alter_column(f"a_{name}", new_column_name=name, existing_type=sa.Date)
    with op.batch_alter_table("circuit_groups") as groups:
        groups.drop_index("ix_circuit_groups_carrier_hid")
        groups.drop_constraint("fk_circuit_groups_carrier_hid", type_="foreignkey")
        groups.drop_column("carrier_hid")
        groups.drop_column("kind")
