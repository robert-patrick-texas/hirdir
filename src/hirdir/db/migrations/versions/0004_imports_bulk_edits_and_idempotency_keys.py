"""imports, bulk edits and idempotency keys

Revision: 0004
Revises: 0003

Creates the stored previews of imports and bulk edits with their rows, and the keys of
requests that may be sent twice. A vendor gains `review_status`, as a catalog entry
has, and every vendor there is so far is `reviewed`.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vendors") as vendors:
        vendors.add_column(
            sa.Column("review_status", sa.String(12), nullable=False, server_default="reviewed")
        )
    op.create_table(
        "import_jobs",
        sa.Column("hid", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("entity", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("file_name", sa.String(255)),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("created", sa.Integer, nullable=False),
        sa.Column("updated", sa.Integer, nullable=False),
        sa.Column("unchanged", sa.Integer, nullable=False),
        sa.Column("rejected", sa.Integer, nullable=False),
        sa.Column("skip_rejected", sa.Boolean),
        sa.Column("failure", sa.Text),
        sa.Column("applied_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by", sa.String(36)),
    )
    op.create_index("import_jobs_created_at", "import_jobs", ["created_at"])
    op.create_table(
        "import_rows",
        sa.Column("job_hid", sa.String(36), sa.ForeignKey("import_jobs.hid"), primary_key=True),
        sa.Column("row", sa.Integer, primary_key=True),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("record_hid", sa.String(36)),
        sa.Column("row_version", sa.Integer),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("values", sa.JSON, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("reasons", sa.JSON, nullable=False),
        sa.Column("notes", sa.JSON, nullable=False),
    )
    op.create_index("ix_import_rows_outcome", "import_rows", ["outcome"])
    op.create_table(
        "idempotency_keys",
        sa.Column("user_hid", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Integer),
        sa.Column("body", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("idempotency_keys_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("import_rows")
    op.drop_table("import_jobs")
    with op.batch_alter_table("vendors") as vendors:
        vendors.drop_column("review_status")
