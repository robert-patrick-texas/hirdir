"""support weight in hundredths

Revision: 0003
Revises: 0002

Support weight was kept to three decimal places, in thousandths. It is kept to two, like
money and percentages, so what is stored becomes hundredths, rounded to the nearest.
No column changes its type.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE catalog_entries SET support_weight = (support_weight + 5) / 10"
        " WHERE support_weight IS NOT NULL"
    )
    op.execute(
        "UPDATE items SET support_weight = (support_weight + 5) / 10"
        " WHERE support_weight IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE catalog_entries SET support_weight = support_weight * 10"
        " WHERE support_weight IS NOT NULL"
    )
    op.execute(
        "UPDATE items SET support_weight = support_weight * 10 WHERE support_weight IS NOT NULL"
    )
