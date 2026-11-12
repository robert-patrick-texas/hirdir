"""access records and audit events

Revision: 0001
Revises: nothing
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor_hid", sa.String(length=36), nullable=True),
        sa.Column("via", sa.String(length=10), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_hid", sa.String(length=36), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index("audit_events_at", ["at"], unique=False)
        batch_op.create_index("audit_events_record", ["record_type", "record_hid"], unique=False)

    op.create_table(
        "user_groups",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("name_key", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("name_key"),
    )
    op.create_table(
        "users",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("username_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("is_service_account", sa.Boolean(), nullable=False),
        sa.Column("access_code_hash", sa.Text(), nullable=True),
        sa.Column("tokens_valid_after", sa.BigInteger(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("last_sign_in_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("username_key"),
    )
    op.create_table(
        "role_grants",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("user_hid", sa.String(length=36), nullable=True),
        sa.Column("group_hid", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "(user_hid IS NOT NULL) + (group_hid IS NOT NULL) = 1", name="role_grants_one_target"
        ),
        sa.ForeignKeyConstraint(
            ["group_hid"],
            ["user_groups.hid"],
        ),
        sa.ForeignKeyConstraint(
            ["user_hid"],
            ["users.hid"],
        ),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("role", "group_hid", name="role_grants_group_once"),
        sa.UniqueConstraint("role", "user_hid", name="role_grants_user_once"),
    )
    op.create_table(
        "service_tokens",
        sa.Column("hid", sa.String(length=36), nullable=False),
        sa.Column("user_hid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_hid"],
            ["users.hid"],
        ),
        sa.PrimaryKeyConstraint("hid"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("service_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_service_tokens_user_hid"), ["user_hid"], unique=False)

    op.create_table(
        "user_group_members",
        sa.Column("user_hid", sa.String(length=36), nullable=False),
        sa.Column("group_hid", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_hid"],
            ["user_groups.hid"],
        ),
        sa.ForeignKeyConstraint(
            ["user_hid"],
            ["users.hid"],
        ),
        sa.PrimaryKeyConstraint("user_hid", "group_hid"),
    )


def downgrade() -> None:
    op.drop_table("user_group_members")
    with op.batch_alter_table("service_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_service_tokens_user_hid"))

    op.drop_table("service_tokens")
    op.drop_table("role_grants")
    op.drop_table("users")
    op.drop_table("user_groups")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index("audit_events_record")
        batch_op.drop_index("audit_events_at")

    op.drop_table("audit_events")
