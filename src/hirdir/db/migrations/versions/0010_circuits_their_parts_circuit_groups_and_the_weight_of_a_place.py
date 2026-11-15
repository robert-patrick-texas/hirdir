"""circuits, their parts, circuit groups and the weight of a place

Revision: 0010
Revises: 0009

Telecommunication circuits beside the inventory, in `circuits`, with the carriers
beside the primary one in `circuit_carriers`, the lines of their monthly cost in
`circuit_costs`, the devices they connect in `circuit_devices`, and the contacts they
name of their own in `circuit_contacts`. A vendor names its account team and its
support desk in `vendor_contacts`. Circuits are put into groups, `circuit_groups`, a
circuit into any number of them through `circuit_group_members`. A region, a site and a
location gain `support_weight`. Loads the `circuit_type` and `carrier_role` lists with
their defaults, written out here so that the migration does not change with the code.

Nothing that is held changes: no place is given a weight, no setting is set, and there
is no circuit until somebody enters one.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TRUE = sa.true()

CIRCUIT_TYPES = [
    ("internet", "Internet"),
    ("mpls", "MPLS"),
    ("point_to_point", "Point-to-point"),
    ("dark_fiber", "Dark fiber"),
    ("wavelength", "Wavelength"),
    ("voice", "Voice"),
    ("other", "Other"),
]
CARRIER_ROLES = [
    ("local_exchange", "Local exchange carrier"),
    ("cross_connect", "Cross-connect provider"),
    ("last_mile", "Last mile"),
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


def _load_defaults(list_name: str, values: list[tuple[str, str]]) -> None:
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
        .execute(sa.select(choices.c.value_key).where(choices.c.list == list_name))
        .scalars()
    )
    # A site may have entered values of its own already: those are left as they are.
    op.bulk_insert(
        choices,
        [
            {
                "hid": str(uuid.uuid7()),
                "list": list_name,
                "value": value,
                "value_key": value.casefold(),
                "label": label,
                "sort": (place + 1) * 10,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "row_version": 1,
            }
            for place, (value, label) in enumerate(values)
            if value.casefold() not in there
        ],
    )


def upgrade() -> None:
    for table in ("regions", "sites", "locations"):
        with op.batch_alter_table(table) as place:
            place.add_column(sa.Column("support_weight", sa.BigInteger))
    op.create_table(
        "circuits",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("enterprise_circuit_id", sa.String(100)),
        sa.Column("enterprise_circuit_id_key", sa.String(100)),
        sa.Column("description", sa.Text),
        sa.Column("circuit_type", sa.String(40)),
        sa.Column("port_mbps", sa.BigInteger),
        sa.Column("down_mbps", sa.BigInteger),
        sa.Column("up_mbps", sa.BigInteger),
        sa.Column("a_location_hid", sa.String(36), sa.ForeignKey("locations.hid")),
        sa.Column("a_note", sa.String(200)),
        sa.Column("z_location_hid", sa.String(36), sa.ForeignKey("locations.hid")),
        sa.Column("z_note", sa.String(200)),
        sa.Column("cost_side", sa.String(1), nullable=False),
        sa.Column("carrier_hid", sa.String(36), sa.ForeignKey("vendors.hid")),
        sa.Column("carrier_circuit_number", sa.String(100)),
        sa.Column("carrier_number_key", sa.String(100)),
        sa.Column("billing_account", sa.String(100)),
        sa.Column("billing_contract", sa.String(200)),
        sa.Column("installed_on", sa.Date),
        sa.Column("activated_on", sa.Date),
        sa.Column("disconnected_on", sa.Date),
        sa.Column("production", sa.Boolean, nullable=False, server_default=TRUE),
        sa.Column("support_weight", sa.BigInteger),
        sa.Column("owner_hid", sa.String(36), sa.ForeignKey("owners.hid")),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("enterprise_circuit_id_key", name="circuits_enterprise_circuit_id"),
        sa.UniqueConstraint("carrier_hid", "carrier_number_key", name="circuits_carrier_number"),
        sa.CheckConstraint(
            "a_location_hid IS NOT NULL OR z_location_hid IS NOT NULL", name="circuits_one_side"
        ),
    )
    for column in (
        "name_key",
        "a_location_hid",
        "z_location_hid",
        "carrier_hid",
        "carrier_number_key",
        "owner_hid",
    ):
        op.create_index(f"ix_circuits_{column}", "circuits", [column])
    op.create_table(
        "circuit_carriers",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("circuit_hid", sa.String(36), sa.ForeignKey("circuits.hid"), nullable=False),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid"), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("circuit_number", sa.String(100)),
        sa.Column("circuit_number_key", sa.String(100)),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text),
        *_bookkeeping(),
        sa.UniqueConstraint("circuit_hid", "vendor_hid", name="circuit_carriers_once"),
        sa.UniqueConstraint("vendor_hid", "circuit_number_key", name="circuit_carriers_number"),
    )
    for column in ("circuit_hid", "vendor_hid", "circuit_number_key"):
        op.create_index(f"ix_circuit_carriers_{column}", "circuit_carriers", [column])
    op.create_table(
        "circuit_costs",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("circuit_hid", sa.String(36), sa.ForeignKey("circuits.hid"), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("description_key", sa.String(200), nullable=False),
        sa.Column("monthly_cost", sa.BigInteger, nullable=False),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid")),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("notes", sa.Text),
        *_bookkeeping(),
        sa.UniqueConstraint("circuit_hid", "description_key", name="circuit_costs_description"),
    )
    for column in ("circuit_hid", "vendor_hid"):
        op.create_index(f"ix_circuit_costs_{column}", "circuit_costs", [column])
    op.create_table(
        "circuit_devices",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("circuit_hid", sa.String(36), sa.ForeignKey("circuits.hid"), nullable=False),
        sa.Column("item_hid", sa.String(36), sa.ForeignKey("items.hid")),
        sa.Column("group_hid", sa.String(36), sa.ForeignKey("device_groups.hid")),
        sa.Column("side", sa.String(1), nullable=False),
        sa.Column("notes", sa.Text),
        *_bookkeeping(),
        sa.CheckConstraint("(item_hid IS NULL) <> (group_hid IS NULL)", name="circuit_devices_one"),
        sa.UniqueConstraint("circuit_hid", "item_hid", name="circuit_devices_item_once"),
        sa.UniqueConstraint("circuit_hid", "group_hid", name="circuit_devices_group_once"),
    )
    for column in ("circuit_hid", "item_hid", "group_hid"):
        op.create_index(f"ix_circuit_devices_{column}", "circuit_devices", [column])
    op.create_table(
        "vendor_contacts",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid"), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("vendor_hid", "role", "contact_hid", name="vendor_contacts_once"),
    )
    for column in ("vendor_hid", "contact_hid"):
        op.create_index(f"ix_vendor_contacts_{column}", "vendor_contacts", [column])
    op.create_table(
        "circuit_contacts",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("circuit_hid", sa.String(36), sa.ForeignKey("circuits.hid"), nullable=False),
        sa.Column("side", sa.String(1)),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid"), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint(
            "circuit_hid", "side", "role", "contact_hid", name="circuit_contacts_once"
        ),
    )
    for column in ("circuit_hid", "contact_hid"):
        op.create_index(f"ix_circuit_contacts_{column}", "circuit_contacts", [column])
    op.create_table(
        "circuit_groups",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("owner_hid", sa.String(36), sa.ForeignKey("owners.hid")),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("name_key", name="circuit_groups_name"),
    )
    op.create_index("ix_circuit_groups_owner_hid", "circuit_groups", ["owner_hid"])
    op.create_table(
        "circuit_group_members",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("group_hid", sa.String(36), sa.ForeignKey("circuit_groups.hid"), nullable=False),
        sa.Column("circuit_hid", sa.String(36), sa.ForeignKey("circuits.hid"), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("group_hid", "circuit_hid", name="circuit_group_members_once"),
    )
    for column in ("group_hid", "circuit_hid"):
        op.create_index(f"ix_circuit_group_members_{column}", "circuit_group_members", [column])
    _load_defaults("circuit_type", CIRCUIT_TYPES)
    _load_defaults("carrier_role", CARRIER_ROLES)


def downgrade() -> None:
    choices = sa.table("choices", sa.column("list", sa.String))
    op.execute(choices.delete().where(choices.c.list.in_(("circuit_type", "carrier_role"))))
    for table in (
        "circuit_group_members",
        "circuit_groups",
        "circuit_contacts",
        "vendor_contacts",
        "circuit_devices",
        "circuit_costs",
        "circuit_carriers",
        "circuits",
    ):
        op.drop_table(table)
    for table in ("locations", "sites", "regions"):
        with op.batch_alter_table(table) as place:
            place.drop_column("support_weight")
