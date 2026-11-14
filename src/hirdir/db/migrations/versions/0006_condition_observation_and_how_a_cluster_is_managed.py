"""condition, observation and how a cluster is managed

Revision: 0006
Revises: 0005

An item gains `condition`, `observed_status` and `observed_at`. A device group gains
`managed_as`, `expected_members`, what is observed of it, and the master that is seen
with the moment it was seen. Every cluster there is so far is managed as one node, as
0.4.0 counted it. Loads the `item_condition` list with its defaults, written out here
so that this migration does the same thing whatever a later release changes. No table
is created.

An item that had already left the team's hands, to Released or to Archived, and was
still a member of a group, ceases to be one on the day of the upgrade, with an audit
event for each membership: from this release such an item is in no group.
"""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# The time zone of an installation that has not set one, as it was at this release.
DEFAULT_ZONE = "America/New_York"

CONDITIONS = [
    ("untested", "Untested"),
    ("good", "Good"),
    ("degraded", "Degraded"),
    ("suspect", "Suspect"),
    ("failed", "Failed"),
    ("dead", "Dead"),
]


def _load_defaults() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    choices = sa.table(
        "choices",
        sa.column("hid", sa.String),
        sa.column("list", sa.String),
        sa.column("value", sa.String),
        sa.column("value_key", sa.String),
        sa.column("label", sa.String),
        sa.column("sort", sa.Integer),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    there = set(
        op.get_bind()
        .execute(sa.select(choices.c.value_key).where(choices.c.list == "item_condition"))
        .scalars()
    )
    # A site may have entered conditions of its own already: those are left as they are.
    op.bulk_insert(
        choices,
        [
            {
                "hid": str(uuid.uuid7()),
                "list": "item_condition",
                "value": value,
                "value_key": value.casefold(),
                "label": label,
                "sort": (place + 1) * 10,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "row_version": 1,
            }
            for place, (value, label) in enumerate(CONDITIONS)
            if value.casefold() not in there
        ],
    )


def upgrade() -> None:
    with op.batch_alter_table("items") as items:
        items.add_column(sa.Column("condition", sa.String(40)))
        items.add_column(sa.Column("observed_status", sa.String(12)))
        items.add_column(sa.Column("observed_at", sa.DateTime()))
        items.create_index("ix_items_condition", ["condition"])
        items.create_index("ix_items_observed_status", ["observed_status"])
    with op.batch_alter_table("device_groups") as groups:
        groups.add_column(sa.Column("managed_as", sa.String(20)))
        groups.add_column(sa.Column("expected_members", sa.Integer))
        groups.add_column(sa.Column("observed_status", sa.String(12)))
        groups.add_column(sa.Column("observed_at", sa.DateTime()))
        groups.add_column(sa.Column("observed_master_hid", sa.String(36)))
        groups.add_column(sa.Column("master_observed_at", sa.DateTime()))
        groups.create_foreign_key(
            "fk_device_groups_observed_master_hid", "items", ["observed_master_hid"], ["hid"]
        )
    groups_table = sa.table(
        "device_groups", sa.column("type", sa.String), sa.column("managed_as", sa.String)
    )
    op.execute(
        groups_table.update().where(groups_table.c.type == "cluster").values(managed_as="one")
    )
    _load_defaults()
    _end_memberships_out_of_hands()


def _today(connection: sa.Connection, moment: datetime) -> date:
    """Return the day it is in the application's time zone, as every other date is told."""
    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.JSON))
    zone = connection.execute(
        sa.select(settings.c.value).where(settings.c.key == "time_zone")
    ).scalar()
    try:
        return moment.astimezone(ZoneInfo(zone if isinstance(zone, str) else DEFAULT_ZONE)).date()
    except ZoneInfoNotFoundError, ValueError:
        return moment.astimezone(ZoneInfo(DEFAULT_ZONE)).date()


def _end_memberships_out_of_hands() -> None:
    """End the memberships of the items that left the team's hands before this release."""
    members = sa.table(
        "device_group_members",
        sa.column("hid", sa.String),
        sa.column("item_hid", sa.String),
        sa.column("joined_on", sa.Date),
        sa.column("left_on", sa.Date),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    items = sa.table("items", sa.column("hid", sa.String), sa.column("lifecycle_state", sa.String))
    events = sa.table(
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
    connection = op.get_bind()
    moment = datetime.now(UTC)
    now = moment.replace(tzinfo=None)
    today = _today(connection, moment)
    gone = connection.execute(
        sa.select(members.c.hid, members.c.joined_on, members.c.row_version)
        .join(items, items.c.hid == members.c.item_hid)
        .where(members.c.left_on.is_(None), items.c.lifecycle_state.in_(("Released", "Archived")))
    ).all()
    for hid, joined_on, row_version in gone:
        # A membership that began on a later day than this one ends on the day it began.
        left = max(today, joined_on)
        connection.execute(
            members.update()
            .where(members.c.hid == hid)
            .values(left_on=left, updated_at=now, row_version=row_version + 1)
        )
    op.bulk_insert(
        events,
        [
            {
                "hid": str(uuid.uuid7()),
                "at": now,
                "actor_hid": None,
                "via": "system",
                "request_id": "",
                "action": "update",
                "record_type": "device_group_member",
                "record_hid": hid,
                "changes": [
                    {"field": "left_on", "old": None, "new": max(now.date(), joined).isoformat()}
                ],
            }
            for hid, joined, _ in gone
        ],
    )


def downgrade() -> None:
    with op.batch_alter_table("device_groups") as groups:
        groups.drop_constraint("fk_device_groups_observed_master_hid", type_="foreignkey")
        for name in (
            "master_observed_at",
            "observed_master_hid",
            "observed_at",
            "observed_status",
            "expected_members",
            "managed_as",
        ):
            groups.drop_column(name)
    with op.batch_alter_table("items") as items:
        items.drop_index("ix_items_observed_status")
        items.drop_index("ix_items_condition")
        for name in ("observed_at", "observed_status", "condition"):
            items.drop_column(name)
