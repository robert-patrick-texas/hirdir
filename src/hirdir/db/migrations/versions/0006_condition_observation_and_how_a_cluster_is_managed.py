"""condition, observation and how a cluster is managed

Revision: 0006
Revises: 0005

An item gains `condition`, `observed_status` and `observed_at`. A device group gains
`managed_as`, `expected_members`, what is observed of it, and the master that is seen
with the moment it was seen. Every cluster there is so far is managed as one node, as
0.4.0 counted it. Loads the `item_condition` list with its defaults, written out here
so that this migration does the same thing whatever a later release changes. No table
is created.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

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
