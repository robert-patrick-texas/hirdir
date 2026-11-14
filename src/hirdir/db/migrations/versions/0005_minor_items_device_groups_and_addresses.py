"""minor items, device groups, networks and addresses

Revision: 0005
Revises: 0004

An item gains `parent_item_hid` and `position`, for minor items. Creates the
replacements of items, the device groups with their memberships, and the networks with
the addresses of items and groups. Loads the `replacement_reason` list with its
defaults, written out here so that this migration does the same thing whatever a later
release changes. No item there is so far is changed: each is a major item, as before.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

REPLACEMENT_REASONS = [
    ("rma", "RMA"),
    ("refresh", "Refresh"),
    ("project", "Project"),
    ("upgrade", "Upgrade"),
    ("other", "Other"),
]


def _bookkeeping() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("row_version", sa.Integer, nullable=False),
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
    connection = op.get_bind()
    there = set(
        connection.execute(
            sa.select(choices.c.value_key).where(choices.c.list == "replacement_reason")
        ).scalars()
    )
    # A site may have entered reasons of its own already: those are left as they are.
    op.bulk_insert(
        choices,
        [
            {
                "hid": str(uuid.uuid7()),
                "list": "replacement_reason",
                "value": value,
                "value_key": value.casefold(),
                "label": label,
                "sort": (place + 1) * 10,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "row_version": 1,
            }
            for place, (value, label) in enumerate(REPLACEMENT_REASONS)
            if value.casefold() not in there
        ],
    )


def upgrade() -> None:
    with op.batch_alter_table("items") as items:
        items.add_column(sa.Column("parent_item_hid", sa.String(36)))
        items.add_column(sa.Column("position", sa.String(100)))
        items.create_foreign_key("fk_items_parent_item_hid", "items", ["parent_item_hid"], ["hid"])
        items.create_index("ix_items_parent_item_hid", ["parent_item_hid"])
    op.create_table(
        "item_replacements",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("old_item_hid", sa.String(36), sa.ForeignKey("items.hid"), nullable=False),
        sa.Column("new_item_hid", sa.String(36), sa.ForeignKey("items.hid"), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(200)),
        sa.Column("replaced_on", sa.Date, nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("old_item_hid", name="item_replacements_old"),
        sa.UniqueConstraint("new_item_hid", name="item_replacements_new"),
    )
    op.create_table(
        "device_groups",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("hostname", sa.String(255)),
        sa.Column("fqdn", sa.String(255)),
        sa.Column("parent_group_hid", sa.String(36), sa.ForeignKey("device_groups.hid")),
        sa.Column("owner_hid", sa.String(36), sa.ForeignKey("owners.hid")),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("name_key", name="device_groups_name"),
    )
    op.create_index("ix_device_groups_type", "device_groups", ["type"])
    op.create_index("ix_device_groups_parent_group_hid", "device_groups", ["parent_group_hid"])
    op.create_index("ix_device_groups_owner_hid", "device_groups", ["owner_hid"])
    op.create_table(
        "device_group_members",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("group_hid", sa.String(36), sa.ForeignKey("device_groups.hid"), nullable=False),
        sa.Column("item_hid", sa.String(36), sa.ForeignKey("items.hid"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer),
        sa.Column("joined_on", sa.Date, nullable=False),
        sa.Column("left_on", sa.Date),
        *_bookkeeping(),
    )
    op.create_index("ix_device_group_members_group_hid", "device_group_members", ["group_hid"])
    op.create_index("ix_device_group_members_item_hid", "device_group_members", ["item_hid"])
    op.create_table(
        "networks",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("label_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("label_key", name="networks_label"),
    )
    # The table that is created last: the package test puts one of this name in the way
    # to see that an upgrade which fails is undone whole.
    op.create_table(
        "addresses",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("item_hid", sa.String(36), sa.ForeignKey("items.hid")),
        sa.Column("group_hid", sa.String(36), sa.ForeignKey("device_groups.hid")),
        sa.Column("address", sa.String(45), nullable=False),
        sa.Column("network_hid", sa.String(36), sa.ForeignKey("networks.hid")),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False),
        *_bookkeeping(),
        sa.CheckConstraint(
            "(item_hid IS NOT NULL) + (group_hid IS NOT NULL) = 1", name="addresses_one_holder"
        ),
    )
    op.create_index("ix_addresses_item_hid", "addresses", ["item_hid"])
    op.create_index("ix_addresses_group_hid", "addresses", ["group_hid"])
    op.create_index("ix_addresses_address", "addresses", ["address"])
    op.create_index("ix_addresses_network_hid", "addresses", ["network_hid"])
    _load_defaults()


def downgrade() -> None:
    op.drop_table("addresses")
    op.drop_table("networks")
    op.drop_table("device_group_members")
    op.drop_table("device_groups")
    op.drop_table("item_replacements")
    with op.batch_alter_table("items") as items:
        items.drop_index("ix_items_parent_item_hid")
        items.drop_constraint("fk_items_parent_item_hid", type_="foreignkey")
        items.drop_column("position")
        items.drop_column("parent_item_hid")
