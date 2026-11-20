"""a retired user

Revision: 0017
Revises: 0016

A user has a record status (P-292, P-296): `users.record_status`, `active` or
`retired`. A retired account is that of somebody who has left, kept for the audit trail
and for what it did; `disabled`, which stays, is an account that may not sign in for
now.

The column is added as `active` for every user. No other value of a row is changed and
no event is written.
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as users:
        users.add_column(
            sa.Column("record_status", sa.String(10), nullable=False, server_default="active")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as users:
        users.drop_column("record_status")
