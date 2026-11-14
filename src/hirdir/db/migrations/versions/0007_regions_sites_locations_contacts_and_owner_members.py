"""regions, sites, locations, contacts and the members of owners

Revision: 0007
Revises: 0006

Creates the contacts, the operators, which are labels with a contact behind them, the
regions, the sites and the locations within them, the assignments of contacts to those
places, and the members of owners. An item and a device group gain `location_hid` and
`operator_hid`, and an item `planned_location_hid`. Loads the `contact_role` and `location_kind`
lists with their defaults, written out here so that this migration does the same thing
whatever a later release changes.

No record there is so far is changed: every item and every group is nowhere until
somebody says where it is, and has no operator until it is given one.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

CONTACT_ROLES = [
    ("shipping", "Shipping"),
    ("technical", "Technical"),
    ("federal", "Federal"),
    ("operational", "Operational"),
    ("escalation", "Escalation"),
]
LOCATION_KINDS = [
    ("building", "Building"),
    ("floor", "Floor"),
    ("room", "Room"),
    ("rack", "Rack"),
    ("warehouse", "Warehouse"),
    ("other", "Other"),
]
ADDRESS = ("address1", "address2", "city", "state", "postal_code", "country")


def _bookkeeping() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("row_version", sa.Integer, nullable=False),
    ]


def _street() -> list[sa.Column]:
    return [sa.Column(name, sa.String(200)) for name in ADDRESS]


def _shipping() -> list[sa.Column]:
    return [
        *(sa.Column(f"ship_{name}", sa.String(200)) for name in ADDRESS),
        sa.Column("ship_instructions", sa.Text),
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
    op.create_table(
        "contacts",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("organization", sa.String(200)),
        sa.Column("email", sa.String(254)),
        sa.Column("email_key", sa.String(254)),
        sa.Column("phone", sa.String(50)),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("email_key", name="contacts_email"),
    )
    op.create_index("ix_contacts_name_key", "contacts", ["name_key"])
    op.create_table(
        "operators",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("label_key", sa.String(40), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("colour", sa.String(20)),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid")),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("label_key", name="operators_label"),
    )
    op.create_index("ix_operators_contact_hid", "operators", ["contact_hid"])
    op.create_table(
        "regions",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(40)),
        sa.Column("code_key", sa.String(40)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("parent_region_hid", sa.String(36), sa.ForeignKey("regions.hid")),
        *_shipping(),
        sa.Column("operator_hid", sa.String(36), sa.ForeignKey("operators.hid")),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("code_key", name="regions_code"),
    )
    op.create_index("ix_regions_parent_region_hid", "regions", ["parent_region_hid"])
    op.create_index("ix_regions_operator_hid", "regions", ["operator_hid"])
    op.create_table(
        "sites",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(40)),
        sa.Column("code_key", sa.String(40)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("region_hid", sa.String(36), sa.ForeignKey("regions.hid"), nullable=False),
        *_street(),
        *_shipping(),
        sa.Column("ship_same_as_address", sa.Boolean, nullable=False),
        sa.Column("operator_hid", sa.String(36), sa.ForeignKey("operators.hid")),
        sa.Column("latitude", sa.BigInteger),
        sa.Column("longitude", sa.BigInteger),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("code_key", name="sites_code"),
        sa.UniqueConstraint("region_hid", "name_key", name="sites_region_name"),
    )
    op.create_index("ix_sites_region_hid", "sites", ["region_hid"])
    op.create_index("ix_sites_operator_hid", "sites", ["operator_hid"])
    op.create_table(
        "locations",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(40)),
        sa.Column("code_key", sa.String(40)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("site_hid", sa.String(36), sa.ForeignKey("sites.hid"), nullable=False),
        sa.Column("parent_location_hid", sa.String(36), sa.ForeignKey("locations.hid")),
        sa.Column("kind", sa.String(40)),
        *_street(),
        *_shipping(),
        sa.Column("ship_same_as_address", sa.Boolean, nullable=False),
        sa.Column("operator_hid", sa.String(36), sa.ForeignKey("operators.hid")),
        sa.Column("latitude", sa.BigInteger),
        sa.Column("longitude", sa.BigInteger),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("site_hid", "code_key", name="locations_site_code"),
    )
    op.create_index("ix_locations_site_hid", "locations", ["site_hid"])
    op.create_index("ix_locations_parent_location_hid", "locations", ["parent_location_hid"])
    op.create_index("ix_locations_operator_hid", "locations", ["operator_hid"])
    op.create_table(
        "contact_assignments",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid")),
        sa.Column("region_hid", sa.String(36), sa.ForeignKey("regions.hid")),
        sa.Column("site_hid", sa.String(36), sa.ForeignKey("sites.hid")),
        sa.Column("location_hid", sa.String(36), sa.ForeignKey("locations.hid")),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("stop_inheritance", sa.Boolean, nullable=False),
        *_bookkeeping(),
        sa.CheckConstraint(
            "(CASE WHEN region_hid IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN site_hid IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN location_hid IS NULL THEN 0 ELSE 1 END) = 1",
            name="contact_assignments_one_place",
        ),
    )
    for column in ("contact_hid", "region_hid", "site_hid", "location_hid"):
        op.create_index(f"ix_contact_assignments_{column}", "contact_assignments", [column])
    with op.batch_alter_table("items") as items:
        items.add_column(sa.Column("location_hid", sa.String(36)))
        items.add_column(sa.Column("planned_location_hid", sa.String(36)))
        items.add_column(sa.Column("operator_hid", sa.String(36)))
        items.create_foreign_key("fk_items_location_hid", "locations", ["location_hid"], ["hid"])
        items.create_foreign_key(
            "fk_items_planned_location_hid", "locations", ["planned_location_hid"], ["hid"]
        )
        items.create_foreign_key("fk_items_operator_hid", "operators", ["operator_hid"], ["hid"])
        items.create_index("ix_items_location_hid", ["location_hid"])
        items.create_index("ix_items_planned_location_hid", ["planned_location_hid"])
        items.create_index("ix_items_operator_hid", ["operator_hid"])
    with op.batch_alter_table("device_groups") as groups:
        groups.add_column(sa.Column("location_hid", sa.String(36)))
        groups.create_foreign_key(
            "fk_device_groups_location_hid", "locations", ["location_hid"], ["hid"]
        )
        groups.add_column(sa.Column("operator_hid", sa.String(36)))
        groups.create_foreign_key(
            "fk_device_groups_operator_hid", "operators", ["operator_hid"], ["hid"]
        )
        groups.create_index("ix_device_groups_location_hid", ["location_hid"])
        groups.create_index("ix_device_groups_operator_hid", ["operator_hid"])
    _load_defaults("contact_role", CONTACT_ROLES)
    _load_defaults("location_kind", LOCATION_KINDS)
    # The table that is created last: the package test puts one of this name in the way
    # to see that an upgrade which fails is undone whole.
    op.create_table(
        "owner_members",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("owner_hid", sa.String(36), sa.ForeignKey("owners.hid"), nullable=False),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("owner_hid", "contact_hid", name="owner_members_once"),
    )
    op.create_index("ix_owner_members_owner_hid", "owner_members", ["owner_hid"])
    op.create_index("ix_owner_members_contact_hid", "owner_members", ["contact_hid"])


def downgrade() -> None:
    op.drop_table("owner_members")
    with op.batch_alter_table("device_groups") as groups:
        groups.drop_index("ix_device_groups_operator_hid")
        groups.drop_index("ix_device_groups_location_hid")
        groups.drop_constraint("fk_device_groups_operator_hid", type_="foreignkey")
        groups.drop_constraint("fk_device_groups_location_hid", type_="foreignkey")
        groups.drop_column("operator_hid")
        groups.drop_column("location_hid")
    with op.batch_alter_table("items") as items:
        items.drop_index("ix_items_operator_hid")
        items.drop_index("ix_items_planned_location_hid")
        items.drop_index("ix_items_location_hid")
        items.drop_constraint("fk_items_operator_hid", type_="foreignkey")
        items.drop_constraint("fk_items_planned_location_hid", type_="foreignkey")
        items.drop_constraint("fk_items_location_hid", type_="foreignkey")
        items.drop_column("operator_hid")
        items.drop_column("planned_location_hid")
        items.drop_column("location_hid")
    op.drop_table("contact_assignments")
    op.drop_table("locations")
    op.drop_table("sites")
    op.drop_table("regions")
    op.drop_table("operators")
    op.drop_table("contacts")
