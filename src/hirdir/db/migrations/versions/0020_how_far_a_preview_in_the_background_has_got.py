"""how far a preview in the background has got

Revision: 0020
Revises: 0019

A preview of more than a hundred rows is worked in the background, as an apply is
(P-325): the job is `previewing` until the process of the background work has worked
every row, and says how far it has got in `import_jobs.rows_previewed`, of `row_count`.

Every job before this was previewed whole in its request, so the column is added with
each job's `row_count`. No other row is changed and no event is written.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_jobs") as jobs:
        jobs.add_column(sa.Column("rows_previewed", sa.Integer, nullable=False, server_default="0"))
    op.execute("UPDATE import_jobs SET rows_previewed = row_count")


def downgrade() -> None:
    with op.batch_alter_table("import_jobs") as jobs:
        jobs.drop_column("rows_previewed")
