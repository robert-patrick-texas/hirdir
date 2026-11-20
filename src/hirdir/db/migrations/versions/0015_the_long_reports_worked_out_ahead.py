"""the long reports worked out ahead

Revision: 0015
Revises: 0014

The long reports of the day, the coverage report, the renewal worklist, the summary of
the renewal alert and the capacity balance, are worked out ahead by the second process
of the service and kept where the server finds them (P-275): `kept_answers`, a row to
each report, with the request whole, the newest audit event and the day it is good
for, the version of `hirdir` that worked it out, when, and the answer. A row is no
record: it is given only while nothing could have changed it, and is worked out again
from the records.

No row is changed and no event is written. The table starts empty, and the second
process fills it when it starts.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kept_answers",
        sa.Column("report", sa.String(40), primary_key=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("newest_event_hid", sa.String(36)),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("kept_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    # What the table holds is worked out again from the records, so nothing is lost.
    op.drop_table("kept_answers")
