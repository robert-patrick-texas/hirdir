"""the notes of a user

Revision: 0016
Revises: 0015

A user has notes (P-281): `users.notes`, free text, what the account is for, who asked
for it, when it is to end. It is the account's, beside the notes of the contact, which
are the person's; a service account, which is no person, has these alone.

The column is added blank. No row is changed and no event is written.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as users:
        users.add_column(sa.Column("notes", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("users") as users:
        users.drop_column("notes")
