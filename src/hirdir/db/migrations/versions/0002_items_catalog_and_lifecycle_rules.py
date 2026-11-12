"""items, the catalog and the lifecycle rules

Revision: 0002
Revises: 0001

Creates vendors, catalog entries, owners, items, tags, choices, settings and the
lifecycle rules, and loads the choices and the rules with their defaults. The defaults
are written out here, and not read from the application, so that this migration does
the same thing whatever a later release changes.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CHOICES = {
    "catalog_type": [
        ("switch", "Switch"),
        ("router", "Router"),
        ("firewall", "Firewall"),
        ("wireless-controller", "Wireless controller"),
        ("access-point", "Access point"),
        ("phone", "Phone"),
        ("server", "Server"),
        ("chassis", "Chassis"),
        ("virtual-machine", "Virtual machine"),
        ("test-equipment", "Test equipment"),
        ("power-supply", "Power supply"),
        ("line-card", "Line card"),
        ("module", "Module"),
        ("application", "Application"),
        ("service", "Service"),
    ],
    "catalog_function": [
        ("access", "Access"),
        ("aggregation", "Aggregation"),
        ("core", "Core"),
        ("edge", "Edge"),
        ("wan", "WAN"),
        ("data-center", "Data center"),
        ("wireless", "Wireless"),
        ("voice", "Voice"),
        ("security", "Security"),
        ("management", "Management"),
        ("lab", "Lab"),
    ],
    "state_reason": [
        ("received", "Received"),
        ("staged", "Staged"),
        ("deployed", "Deployed"),
        ("maintenance", "Maintenance"),
        ("suspended", "Suspended"),
        ("rma", "RMA"),
        ("lost", "Lost"),
        ("found", "Found"),
        ("returned", "Returned"),
        ("retired", "Retired"),
        ("decommissioned", "Decommissioned"),
        ("disposed", "Disposed"),
        ("correction", "Correction"),
    ],
}

# state, dispositions, keeps_disposition, may_be_online, must_be_online,
# entry_disposition, entry_online, next_states
LIFECYCLE_RULES = [
    ("Purchased", [], False, [], [], None, None, ["Delivered"]),
    ("Delivered", [], False, [], [], None, None, ["Assigned"]),
    (
        "Assigned",
        ["Staging", "Spare", "Excess"],
        False,
        [],
        [],
        "Staging",
        None,
        ["Test", "Pending-Removal"],
    ),
    (
        "Test",
        ["Staging"],
        False,
        ["Staging"],
        [],
        "Staging",
        True,
        ["Prod", "Down", "Pending-Removal"],
    ),
    (
        "Prod",
        ["Production", "Spare"],
        False,
        ["Production", "Spare"],
        ["Production"],
        "Production",
        True,
        ["Down", "Pending-Removal"],
    ),
    ("Down", [], True, [], [], None, None, ["Test", "Prod", "Pending-Removal"]),
    ("Pending-Removal", ["Excess"], True, [], [], None, None, ["Released", "Assigned"]),
    ("Released", [], False, [], [], None, None, ["Archived"]),
    ("Archived", [], False, [], [], None, None, []),
]


def _hid() -> str:
    return str(uuid.uuid7())


def _load_defaults() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    kept = {"created_at": now, "updated_at": now, "row_version": 1}
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
    op.bulk_insert(
        choices,
        [
            {
                "hid": _hid(),
                "list": name,
                "value": value,
                "value_key": value.casefold(),
                "label": label,
                "sort": (place + 1) * 10,
                "active": True,
                **kept,
            }
            for name, values in CHOICES.items()
            for place, (value, label) in enumerate(values)
        ],
    )
    rules = sa.table(
        "lifecycle_rules",
        sa.column("hid", sa.String),
        sa.column("state", sa.String),
        sa.column("sort", sa.Integer),
        sa.column("dispositions", sa.JSON),
        sa.column("keeps_disposition", sa.Boolean),
        sa.column("may_be_online", sa.JSON),
        sa.column("must_be_online", sa.JSON),
        sa.column("entry_disposition", sa.String),
        sa.column("entry_online", sa.Boolean),
        sa.column("next_states", sa.JSON),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("row_version", sa.Integer),
    )
    op.bulk_insert(
        rules,
        [
            {
                "hid": _hid(),
                "state": state,
                "sort": (place + 1) * 10,
                "dispositions": dispositions,
                "keeps_disposition": keeps,
                "may_be_online": may,
                "must_be_online": must,
                "entry_disposition": entry_disposition,
                "entry_online": entry_online,
                "next_states": next_states,
                **kept,
            }
            for place, (
                state,
                dispositions,
                keeps,
                may,
                must,
                entry_disposition,
                entry_online,
                next_states,
            ) in enumerate(LIFECYCLE_RULES)
        ],
    )


def upgrade() -> None:
    op.create_table(
        "choices",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("list", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("value_key", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("list", "value_key", name="choices_list_value"),
    )
    op.create_table(
        "lifecycle_rules",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("dispositions", sa.JSON(), nullable=False),
        sa.Column("keeps_disposition", sa.Boolean(), nullable=False),
        sa.Column("may_be_online", sa.JSON(), nullable=False),
        sa.Column("must_be_online", sa.JSON(), nullable=False),
        sa.Column("entry_disposition", sa.String(length=12), nullable=True),
        sa.Column("entry_online", sa.Boolean(), nullable=True),
        sa.Column("next_states", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("state"),
    )
    op.create_table(
        "owners",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("label_key", sa.String(length=200), nullable=False),
        sa.Column("organization", sa.String(length=200), nullable=True),
        sa.Column("is_external", sa.Boolean(), nullable=False),
        sa.Column("exception_reason", sa.Text(), nullable=True),
        sa.Column("record_status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("label_key"),
    )
    op.create_table(
        "settings",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "tags",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("label_key", sa.String(length=100), nullable=False),
        sa.Column("colour", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("label_key"),
    )
    op.create_table(
        "vendors",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("name_key"),
    )
    op.create_table(
        "catalog_entries",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("vendor_hid", sa.String(length=36), nullable=False),
        sa.Column("pid", sa.String(length=100), nullable=False),
        sa.Column("pid_key", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=True),
        sa.Column("function", sa.String(length=40), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("end_of_sale", sa.Date(), nullable=True),
        sa.Column("end_of_sw_support", sa.Date(), nullable=True),
        sa.Column("end_of_hw_support", sa.Date(), nullable=True),
        sa.Column("ldos", sa.Date(), nullable=True),
        sa.Column("est_value", sa.BigInteger(), nullable=True),
        sa.Column("support_weight", sa.BigInteger(), nullable=True),
        sa.Column("annual_support_cost", sa.BigInteger(), nullable=True),
        sa.Column("stack_discount_pct", sa.BigInteger(), nullable=True),
        sa.Column("successor_hid", sa.String(length=36), nullable=True),
        sa.Column("review_status", sa.String(length=12), nullable=False),
        sa.Column("record_status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["successor_hid"],
            ["catalog_entries.hid"],
        ),
        sa.ForeignKeyConstraint(
            ["vendor_hid"],
            ["vendors.hid"],
        ),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("vendor_hid", "pid_key", name="catalog_entries_vendor_pid"),
    )
    with op.batch_alter_table("catalog_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_catalog_entries_vendor_hid"), ["vendor_hid"], unique=False
        )

    op.create_table(
        "tag_links",
        sa.Column("tag_hid", sa.String(length=36), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_hid", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_hid"],
            ["tags.hid"],
        ),
        sa.PrimaryKeyConstraint("tag_hid", "record_type", "record_hid"),
    )
    with op.batch_alter_table("tag_links", schema=None) as batch_op:
        batch_op.create_index("tag_links_record", ["record_type", "record_hid"], unique=False)

    op.create_table(
        "items",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("catalog_entry_hid", sa.String(length=36), nullable=True),
        sa.Column("serial_number", sa.String(length=100), nullable=True),
        sa.Column("serial_key", sa.String(length=100), nullable=True),
        sa.Column("mac_address", sa.String(length=12), nullable=True),
        sa.Column("asset_tag", sa.String(length=100), nullable=True),
        sa.Column("asset_tag_key", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("fqdn", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=True),
        sa.Column("disposition", sa.String(length=12), nullable=True),
        sa.Column("expected_online", sa.Boolean(), nullable=True),
        sa.Column("state_reason", sa.String(length=40), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(), nullable=True),
        sa.Column("owner_hid", sa.String(length=36), nullable=True),
        sa.Column("procured_on", sa.Date(), nullable=True),
        sa.Column("delivered_on", sa.Date(), nullable=True),
        sa.Column("in_service_on", sa.Date(), nullable=True),
        sa.Column("warranty_start", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("est_value", sa.BigInteger(), nullable=True),
        sa.Column("support_weight", sa.BigInteger(), nullable=True),
        sa.Column("annual_support_cost", sa.BigInteger(), nullable=True),
        sa.Column("end_of_sale", sa.Date(), nullable=True),
        sa.Column("end_of_sw_support", sa.Date(), nullable=True),
        sa.Column("end_of_hw_support", sa.Date(), nullable=True),
        sa.Column("ldos", sa.Date(), nullable=True),
        sa.Column("record_status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_entry_hid"],
            ["catalog_entries.hid"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_hid"],
            ["owners.hid"],
        ),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("asset_tag_key"),
        sa.UniqueConstraint("catalog_entry_hid", "serial_key", name="items_catalog_serial"),
    )
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index("items_updated_at", ["updated_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_items_catalog_entry_hid"), ["catalog_entry_hid"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_items_disposition"), ["disposition"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_items_end_of_hw_support"), ["end_of_hw_support"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_items_end_of_sale"), ["end_of_sale"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_items_end_of_sw_support"), ["end_of_sw_support"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_items_hostname"), ["hostname"], unique=False)
        batch_op.create_index(batch_op.f("ix_items_ldos"), ["ldos"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_items_lifecycle_state"), ["lifecycle_state"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_items_mac_address"), ["mac_address"], unique=False)
        batch_op.create_index(batch_op.f("ix_items_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_items_owner_hid"), ["owner_hid"], unique=False)
        batch_op.create_index(batch_op.f("ix_items_serial_key"), ["serial_key"], unique=False)

    _load_defaults()


def downgrade() -> None:
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_items_serial_key"))
        batch_op.drop_index(batch_op.f("ix_items_owner_hid"))
        batch_op.drop_index(batch_op.f("ix_items_name"))
        batch_op.drop_index(batch_op.f("ix_items_mac_address"))
        batch_op.drop_index(batch_op.f("ix_items_lifecycle_state"))
        batch_op.drop_index(batch_op.f("ix_items_ldos"))
        batch_op.drop_index(batch_op.f("ix_items_hostname"))
        batch_op.drop_index(batch_op.f("ix_items_end_of_sw_support"))
        batch_op.drop_index(batch_op.f("ix_items_end_of_sale"))
        batch_op.drop_index(batch_op.f("ix_items_end_of_hw_support"))
        batch_op.drop_index(batch_op.f("ix_items_disposition"))
        batch_op.drop_index(batch_op.f("ix_items_catalog_entry_hid"))
        batch_op.drop_index("items_updated_at")

    op.drop_table("items")
    with op.batch_alter_table("tag_links", schema=None) as batch_op:
        batch_op.drop_index("tag_links_record")

    op.drop_table("tag_links")
    with op.batch_alter_table("catalog_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_catalog_entries_vendor_hid"))

    op.drop_table("catalog_entries")
    op.drop_table("vendors")
    op.drop_table("tags")
    op.drop_table("settings")
    op.drop_table("owners")
    op.drop_table("lifecycle_rules")
    op.drop_table("choices")
