"""what runs on a host, and what a tool reports

Revision: 0014
Revises: 0013

A virtual machine, a virtual context and a container are items that run on another
record (P-226, P-246). An item gains `host_item_hid` and `host_group_hid`, the host a
person names, an item or a stack or a cluster, of which it has one at most; and
`observed_host_hid` with `host_observed_at`, the item it was seen to run on and when.

An import of items may be read from an external system, and be everything that system
reports (P-248): an import job gains `system_hid`, `complete` and `not_reported`, how
many items it marked as reported no more.

No row is changed and no event is written: every item has no host, and every import
job was read from no system. The kinds `virtual_context` and `container` of a model,
and the status `not_reported` of a registration, are values that the columns hold as
they are.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

HOSTS = (
    ("host_item_hid", "items"),
    ("host_group_hid", "device_groups"),
    ("observed_host_hid", "items"),
)


def upgrade() -> None:
    with op.batch_alter_table("items") as items:
        for name, _ in HOSTS:
            items.add_column(sa.Column(name, sa.String(36)))
        items.add_column(sa.Column("host_observed_at", sa.DateTime()))
        for name, table in HOSTS:
            items.create_foreign_key(f"fk_items_{name}", table, [name], ["hid"])
            items.create_index(f"ix_items_{name}", [name])
        items.create_check_constraint(
            "items_one_host", "host_item_hid IS NULL OR host_group_hid IS NULL"
        )
    with op.batch_alter_table("import_jobs") as jobs:
        jobs.add_column(sa.Column("system_hid", sa.String(36)))
        jobs.add_column(sa.Column("complete", sa.Boolean))
        jobs.add_column(sa.Column("not_reported", sa.Integer, nullable=False, server_default="0"))
        jobs.create_foreign_key(
            "fk_import_jobs_system_hid", "external_systems", ["system_hid"], ["hid"]
        )


def downgrade() -> None:
    # Going back loses what runs on what, and which system an import was read from.
    with op.batch_alter_table("import_jobs") as jobs:
        jobs.drop_constraint("fk_import_jobs_system_hid", type_="foreignkey")
        for name in ("not_reported", "complete", "system_hid"):
            jobs.drop_column(name)
    with op.batch_alter_table("items") as items:
        items.drop_constraint("items_one_host", type_="check")
        for name, _ in reversed(HOSTS):
            items.drop_index(f"ix_items_{name}")
            items.drop_constraint(f"fk_items_{name}", type_="foreignkey")
        items.drop_column("host_observed_at")
        for name, _ in reversed(HOSTS):
            items.drop_column(name)
