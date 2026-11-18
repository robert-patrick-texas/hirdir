"""an item replaced more than once

Revision: 0013
Revises: 0012

An item is replaced, and takes another's place, as often as that happens (P-241): a
spare goes round a pool, and a switch that came back takes the place of the one that
took its own. `item_replacements` loses its two uniquenesses, of the item that left
and of the item that came, and has an index on each in their place, since each is
still what a replacement is looked for by. What is unique from now on is the two items
with the day: one item does not take the place of the same other twice on one day.

No row is changed and no event is written: every replacement that is held was the
only one of each of its items, and so is the only one of its two items on its day.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("item_replacements") as replacements:
        replacements.drop_constraint("item_replacements_old", type_="unique")
        replacements.drop_constraint("item_replacements_new", type_="unique")
        replacements.create_unique_constraint(
            "item_replacements_pair_day", ["old_item_hid", "new_item_hid", "replaced_on"]
        )
        replacements.create_index("ix_item_replacements_old_item_hid", ["old_item_hid"])
        replacements.create_index("ix_item_replacements_new_item_hid", ["new_item_hid"])


def _more_than_once(column: str) -> int:
    """Return how many items are in more than one replacement as `column`."""
    held = sa.table("item_replacements", sa.column("old_item_hid"), sa.column("new_item_hid"))
    item = held.c[column]
    twice = sa.select(item).group_by(item).having(sa.func.count() > 1).subquery()
    counted = op.get_bind().execute(sa.select(sa.func.count()).select_from(twice))
    return int(counted.scalar() or 0)


def downgrade() -> None:
    # Going back holds where no item was replaced, or took a place, a second time. Where
    # one was, it is refused in words before the copy of the table would fail on it.
    left, came = _more_than_once("old_item_hid"), _more_than_once("new_item_hid")
    if left or came:
        raise RuntimeError(
            f"{left} items were replaced more than once and {came} items took the place of "
            "another more than once, which the schema before 0013 cannot hold: go back to "
            "0.9.7 by the backup the upgrade made, as install.md says under 'Going back to "
            "the release before'"
        )
    with op.batch_alter_table("item_replacements") as replacements:
        replacements.drop_index("ix_item_replacements_new_item_hid")
        replacements.drop_index("ix_item_replacements_old_item_hid")
        replacements.drop_constraint("item_replacements_pair_day", type_="unique")
        replacements.create_unique_constraint("item_replacements_old", ["old_item_hid"])
        replacements.create_unique_constraint("item_replacements_new", ["new_item_hid"])
