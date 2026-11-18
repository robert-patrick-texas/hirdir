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


def downgrade() -> None:
    # Going back holds where no item was replaced, or took a place, a second time.
    with op.batch_alter_table("item_replacements") as replacements:
        replacements.drop_index("ix_item_replacements_new_item_hid")
        replacements.drop_index("ix_item_replacements_old_item_hid")
        replacements.drop_constraint("item_replacements_pair_day", type_="unique")
        replacements.create_unique_constraint("item_replacements_old", ["old_item_hid"])
        replacements.create_unique_constraint("item_replacements_new", ["new_item_hid"])
