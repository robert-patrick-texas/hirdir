"""renewals, contacts of contracts, capacity records and links

Revision: 0009
Revises: 0008

A catalog entry and an item gain `do_not_renew`, a contract `ends_with_term` and
`next_with_agreement`. Agreements and contracts gain contact records, in
`contract_contacts`. A purchase line's model becomes optional, beside the part number
and the description that procurement gave it. A capacity line gains `effect`, `factor`
and `share`, and the staff lines a line that multiplies works on, in
`capacity_line_targets`; its `quantity` and `units_each` become optional, for such a
line. The balance is kept week by week in `capacity_records`. A region, a site, a
location and a catalog entry gain `links`. An import job gains how far an apply has
got and what it did, and each row what the apply did with it. What a person last saw of
the renewal alert is kept in `renewal_alert_views`.

Nothing that is held changes, with one exception that is said: a job that was applied
before this release, as one transaction, is given the counts that an apply now keeps,
`rows_done` its rows and `applied` the rows it applied, so that it reads as what it was.
No model is flagged, no contract is marked, no line loses its model, and no record of
the balance is made: the server makes the first on the Monday after, or when it starts.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

EMPTY_LIST = sa.text("'[]'")
FALSE = sa.false()


def _bookkeeping() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("row_version", sa.Integer, nullable=False),
    ]


def _links() -> sa.Column:
    return sa.Column("links", sa.JSON, nullable=False, server_default=EMPTY_LIST)


def upgrade() -> None:
    with op.batch_alter_table("catalog_entries") as catalog:
        catalog.add_column(
            sa.Column("do_not_renew", sa.Boolean, nullable=False, server_default=FALSE)
        )
        catalog.add_column(_links())
    with op.batch_alter_table("items") as items:
        items.add_column(sa.Column("do_not_renew", sa.Boolean))
    for table in ("regions", "sites", "locations"):
        with op.batch_alter_table(table) as place:
            place.add_column(_links())
    with op.batch_alter_table("contracts") as contracts:
        contracts.add_column(
            sa.Column("next_with_agreement", sa.Boolean, nullable=False, server_default=FALSE)
        )
        contracts.add_column(
            sa.Column("ends_with_term", sa.Boolean, nullable=False, server_default=FALSE)
        )
    with op.batch_alter_table("purchase_lines") as lines:
        lines.alter_column("catalog_entry_hid", existing_type=sa.String(36), nullable=True)
        lines.add_column(sa.Column("part_number", sa.String(100)))
        lines.add_column(sa.Column("description", sa.Text))
    with op.batch_alter_table("capacity_lines") as capacity:
        capacity.add_column(
            sa.Column("effect", sa.String(10), nullable=False, server_default="add")
        )
        capacity.alter_column("quantity", existing_type=sa.BigInteger, nullable=True)
        capacity.alter_column("units_each", existing_type=sa.BigInteger, nullable=True)
        capacity.add_column(sa.Column("factor", sa.BigInteger))
        capacity.add_column(sa.Column("share", sa.BigInteger))
    with op.batch_alter_table("import_jobs") as jobs:
        for name in ("rows_done", "applied", "stale"):
            jobs.add_column(sa.Column(name, sa.Integer, nullable=False, server_default="0"))
    with op.batch_alter_table("import_rows") as rows:
        rows.add_column(sa.Column("applied_outcome", sa.String(10)))
        rows.add_column(
            sa.Column("applied_reasons", sa.JSON, nullable=False, server_default=EMPTY_LIST)
        )
    # A job applied before this release was applied whole, as one transaction: every row
    # was worked, and every row that was not rejected was applied.
    jobs_table = sa.table(
        "import_jobs",
        sa.column("status", sa.String),
        sa.column("row_count", sa.Integer),
        sa.column("created", sa.Integer),
        sa.column("updated", sa.Integer),
        sa.column("unchanged", sa.Integer),
        sa.column("rows_done", sa.Integer),
        sa.column("applied", sa.Integer),
    )
    op.execute(
        jobs_table.update()
        .where(jobs_table.c.status == "applied")
        .values(
            rows_done=jobs_table.c.row_count,
            applied=jobs_table.c.created + jobs_table.c.updated + jobs_table.c.unchanged,
        )
    )
    op.create_table(
        "contract_contacts",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("agreement_hid", sa.String(36), sa.ForeignKey("agreements.hid")),
        sa.Column("contract_hid", sa.String(36), sa.ForeignKey("contracts.hid")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("contact_hid", sa.String(36), sa.ForeignKey("contacts.hid"), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        *_bookkeeping(),
        sa.CheckConstraint(
            "(agreement_hid IS NULL) <> (contract_hid IS NULL)", name="contract_contacts_one_holder"
        ),
        sa.UniqueConstraint(
            "agreement_hid", "role", "contact_hid", name="contract_contacts_agreement_once"
        ),
        sa.UniqueConstraint(
            "contract_hid", "role", "contact_hid", name="contract_contacts_contract_once"
        ),
    )
    for column in ("agreement_hid", "contract_hid", "contact_hid"):
        op.create_index(f"ix_contract_contacts_{column}", "contract_contacts", [column])
    op.create_table(
        "capacity_line_targets",
        sa.Column("line_hid", sa.String(36), sa.ForeignKey("capacity_lines.hid"), primary_key=True),
        sa.Column(
            "target_hid", sa.String(36), sa.ForeignKey("capacity_lines.hid"), primary_key=True
        ),
    )
    op.create_index("ix_capacity_line_targets_target_hid", "capacity_line_targets", ["target_hid"])
    op.create_table(
        "renewal_alert_views",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("user_hid", sa.String(36), sa.ForeignKey("users.hid"), nullable=False),
        sa.Column("seen_at", sa.DateTime, nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("lapsed", sa.JSON, nullable=False),
        sa.Column("renewal_pending", sa.JSON, nullable=False),
        sa.Column("ending", sa.JSON, nullable=False),
        *_bookkeeping(),
        sa.UniqueConstraint("user_hid", name="renewal_alert_views_user"),
    )
    op.create_table(
        "capacity_records",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("week_of", sa.Date, nullable=False),
        sa.Column("recorded_at", sa.DateTime, nullable=False),
        sa.Column("weight_per_resource_unit", sa.BigInteger, nullable=False),
        sa.Column("active", sa.JSON, nullable=False),
        sa.Column("with_drafts", sa.JSON, nullable=False),
        sa.Column("adjusted", sa.Boolean, nullable=False),
        sa.Column("note", sa.Text),
        *_bookkeeping(),
        sa.UniqueConstraint("week_of", name="capacity_records_week"),
    )


def downgrade() -> None:
    op.drop_table("capacity_records")
    op.drop_table("renewal_alert_views")
    op.drop_table("capacity_line_targets")
    op.drop_table("contract_contacts")
    with op.batch_alter_table("import_rows") as rows:
        rows.drop_column("applied_reasons")
        rows.drop_column("applied_outcome")
    with op.batch_alter_table("import_jobs") as jobs:
        for name in ("stale", "applied", "rows_done"):
            jobs.drop_column(name)
    with op.batch_alter_table("capacity_lines") as capacity:
        capacity.drop_column("share")
        capacity.drop_column("factor")
        capacity.alter_column("units_each", existing_type=sa.BigInteger, nullable=False)
        capacity.alter_column("quantity", existing_type=sa.BigInteger, nullable=False)
        capacity.drop_column("effect")
    with op.batch_alter_table("purchase_lines") as lines:
        lines.drop_column("description")
        lines.drop_column("part_number")
        lines.alter_column("catalog_entry_hid", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("contracts") as contracts:
        contracts.drop_column("ends_with_term")
        contracts.drop_column("next_with_agreement")
    for table in ("locations", "sites", "regions"):
        with op.batch_alter_table(table) as place:
            place.drop_column("links")
    with op.batch_alter_table("items") as items:
        items.drop_column("do_not_renew")
    with op.batch_alter_table("catalog_entries") as catalog:
        catalog.drop_column("links")
        catalog.drop_column("do_not_renew")
