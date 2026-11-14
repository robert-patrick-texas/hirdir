"""contracts, purchases, external systems and capacity lines

Revision: 0008
Revises: 0007

Creates the support agreements, the contracts that may be grouped into them and the
coverage of items under the contracts, the purchase requests and
their lines, the external systems and the registrations of items and groups with
them, and the capacity lines. An item gains `purchase_line_hid`, the line it arrived
on. Loads the `capacity_category` list with its defaults, written out here so that
this migration does the same thing whatever a later release changes.

No record there is so far is changed: every item is under no contract, arrived on no
line and is registered nowhere until somebody says so.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CAPACITY_CATEGORIES = [
    ("staff", "Staff"),
    ("professional_services", "Professional services"),
    ("smart_hands", "Smart hands"),
    ("tools", "Tools"),
    ("services", "Services"),
    ("other_work", "Other work"),
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
    op.create_table(
        "agreements",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("number", sa.String(100)),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid"), nullable=False),
        sa.Column("reseller_hid", sa.String(36), sa.ForeignKey("vendors.hid")),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("support_level", sa.String(200)),
        sa.Column("purchase_reference", sa.String(200)),
        sa.Column("account_manager", sa.Text),
        sa.Column("support_contact", sa.Text),
        sa.Column("support_url", sa.String(2000)),
        sa.Column("notes", sa.Text),
        sa.Column("annual_cost", sa.BigInteger),
        sa.Column("next_number", sa.String(100)),
        sa.Column("next_starts_on", sa.Date),
        sa.Column("next_ends_on", sa.Date),
        sa.Column("next_annual_cost", sa.BigInteger),
        sa.Column("next_purchase_reference", sa.String(200)),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("name_key", name="agreements_name"),
    )
    op.create_index("ix_agreements_vendor_hid", "agreements", ["vendor_hid"])
    op.create_index("ix_agreements_reseller_hid", "agreements", ["reseller_hid"])
    op.create_table(
        "contracts",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("number_key", sa.String(100), nullable=False),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid"), nullable=False),
        sa.Column("agreement_hid", sa.String(36), sa.ForeignKey("agreements.hid")),
        sa.Column("reseller_hid", sa.String(36), sa.ForeignKey("vendors.hid")),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("support_level", sa.String(200)),
        sa.Column("purchase_reference", sa.String(200)),
        sa.Column("account_manager", sa.Text),
        sa.Column("support_contact", sa.Text),
        sa.Column("support_url", sa.String(2000)),
        sa.Column("notes", sa.Text),
        sa.Column("annual_cost", sa.BigInteger),
        sa.Column("next_number", sa.String(100)),
        sa.Column("next_starts_on", sa.Date),
        sa.Column("next_ends_on", sa.Date),
        sa.Column("next_annual_cost", sa.BigInteger),
        sa.Column("next_purchase_reference", sa.String(200)),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("vendor_hid", "number_key", name="contracts_vendor_number"),
    )
    op.create_index("ix_contracts_number_key", "contracts", ["number_key"])
    op.create_index("ix_contracts_vendor_hid", "contracts", ["vendor_hid"])
    op.create_index("ix_contracts_reseller_hid", "contracts", ["reseller_hid"])
    op.create_index("ix_contracts_agreement_hid", "contracts", ["agreement_hid"])
    op.create_table(
        "contract_coverage",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("contract_hid", sa.String(36), sa.ForeignKey("contracts.hid"), nullable=False),
        sa.Column("item_hid", sa.String(36), sa.ForeignKey("items.hid"), nullable=False),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("left_service", sa.Boolean, nullable=False),
        *_bookkeeping(),
    )
    op.create_index("ix_contract_coverage_contract_hid", "contract_coverage", ["contract_hid"])
    op.create_index("ix_contract_coverage_item_hid", "contract_coverage", ["item_hid"])
    op.create_table(
        "purchase_requests",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("reference_key", sa.String(100), nullable=False),
        sa.Column("requested_on", sa.Date),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("notes", sa.Text),
        *_bookkeeping(),
        sa.UniqueConstraint("reference_key", name="purchase_requests_reference"),
    )
    op.create_table(
        "purchase_lines",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column(
            "request_hid", sa.String(36), sa.ForeignKey("purchase_requests.hid"), nullable=False
        ),
        sa.Column("line", sa.Integer, nullable=False),
        sa.Column(
            "catalog_entry_hid",
            sa.String(36),
            sa.ForeignKey("catalog_entries.hid"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("destination_site_hid", sa.String(36), sa.ForeignKey("sites.hid")),
        sa.Column("expected_on", sa.Date),
        sa.Column("notes", sa.Text),
        *_bookkeeping(),
        sa.UniqueConstraint("request_hid", "line", name="purchase_lines_request_line"),
    )
    for column in ("request_hid", "catalog_entry_hid", "destination_site_hid"):
        op.create_index(f"ix_purchase_lines_{column}", "purchase_lines", [column])
    with op.batch_alter_table("items") as items:
        items.add_column(sa.Column("purchase_line_hid", sa.String(36)))
        items.create_foreign_key(
            "fk_items_purchase_line_hid", "purchase_lines", ["purchase_line_hid"], ["hid"]
        )
        items.create_index("ix_items_purchase_line_hid", ["purchase_line_hid"])
    op.create_table(
        "external_systems",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("url", sa.String(2000)),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("name_key", name="external_systems_name"),
    )
    op.create_table(
        "registrations",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column(
            "system_hid", sa.String(36), sa.ForeignKey("external_systems.hid"), nullable=False
        ),
        sa.Column("item_hid", sa.String(36), sa.ForeignKey("items.hid")),
        sa.Column("group_hid", sa.String(36), sa.ForeignKey("device_groups.hid")),
        sa.Column("external_id", sa.String(200)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("confirmed_at", sa.DateTime()),
        *_bookkeeping(),
        sa.CheckConstraint(
            "(item_hid IS NULL) <> (group_hid IS NULL)", name="registrations_one_holder"
        ),
        sa.UniqueConstraint("system_hid", "item_hid", name="registrations_system_item"),
        sa.UniqueConstraint("system_hid", "group_hid", name="registrations_system_group"),
    )
    for column in ("system_hid", "item_hid", "group_hid"):
        op.create_index(f"ix_registrations_{column}", "registrations", [column])
    _load_defaults("capacity_category", CAPACITY_CATEGORIES)
    # The table that is created last: the package test puts one of this name in the way
    # to see that an upgrade which fails is undone whole.
    op.create_table(
        "capacity_lines",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False),
        sa.Column("quantity", sa.BigInteger, nullable=False),
        sa.Column("units_each", sa.BigInteger, nullable=False),
        sa.Column("annual_cost", sa.BigInteger),
        sa.Column("vendor_hid", sa.String(36), sa.ForeignKey("vendors.hid")),
        sa.Column("region_hid", sa.String(36), sa.ForeignKey("regions.hid")),
        sa.Column("site_hid", sa.String(36), sa.ForeignKey("sites.hid")),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column("record_status", sa.String(10), nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("side", "name_key", name="capacity_lines_side_name"),
        sa.CheckConstraint(
            "region_hid IS NULL OR site_hid IS NULL", name="capacity_lines_one_place"
        ),
    )
    for column in ("category", "vendor_hid", "region_hid", "site_hid"):
        op.create_index(f"ix_capacity_lines_{column}", "capacity_lines", [column])


def downgrade() -> None:
    op.drop_table("capacity_lines")
    op.drop_table("registrations")
    op.drop_table("external_systems")
    with op.batch_alter_table("items") as items:
        items.drop_index("ix_items_purchase_line_hid")
        items.drop_constraint("fk_items_purchase_line_hid", type_="foreignkey")
        items.drop_column("purchase_line_hid")
    op.drop_table("purchase_lines")
    op.drop_table("purchase_requests")
    op.drop_table("contract_coverage")
    op.drop_table("contracts")
    op.drop_table("agreements")
