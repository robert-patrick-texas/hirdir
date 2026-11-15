"""Gear whose support is not to be renewed: the flag `do_not_renew`.

A catalog entry says it of a model, true or false and false unless said, and every item
of the model has it, with the source `catalog`. An item says otherwise with a value of
its own, and blank inherits again. A minor item has its own model's, as for every value
of the catalog. The flag in force is worked out when it is read, here for a set of items
at once and as SQL for the database to filter by: nothing is copied down.

An item in service whose flag is in force and that no contract covers is no gap. A
renewal of a contract leaves such an item behind.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, false, func, select
from sqlalchemy.orm import Session

from hirdir.db.models import CatalogEntry, Item
from hirdir.domain.errors import Invalid

FIELD = "do_not_renew"
AT_ONCE = 500


def checked(value: Any, inherits: bool) -> bool | None:
    """Return the flag a change gives. For an item, blank is to inherit; for a catalog
    entry, blank is false."""
    if value is None:
        return None if inherits else False
    if not isinstance(value, bool):
        raise Invalid("do_not_renew is not acceptable", {FIELD: "true or false"})
    return value


def value_of(item: Any = Item, entry: Any = CatalogEntry) -> ColumnElement[Any]:
    """Return the flag in force as SQL, where the item's model is joined as `entry`: the
    item's own, or its model's, and blank for an item with neither."""
    return func.coalesce(item.do_not_renew, entry.do_not_renew, type_=item.do_not_renew.type)


def in_force(item: Any = Item) -> ColumnElement[bool]:
    """Return the test that an item's flag is in force, as SQL, wherever `item` is in
    the statement: its own, or its model's. Its model is read by itself, so the
    statement need not join it."""
    model = (
        select(CatalogEntry.do_not_renew)
        .where(CatalogEntry.hid == item.catalog_entry_hid)
        .correlate(item)
        .scalar_subquery()
    )
    return func.coalesce(item.do_not_renew, model, false()).is_(True)


def flagged(db: Session, item_hids: Iterable[str]) -> set[str]:
    """Return which of the items have the flag in force: each read with its model, a
    few hundred items to a statement and not one at a time."""
    wanted = sorted(set(item_hids))
    found: set[str] = set()
    for start in range(0, len(wanted), AT_ONCE):
        found.update(
            db.scalars(
                select(Item.hid)
                .outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
                .where(
                    Item.hid.in_(wanted[start : start + AT_ONCE]),
                    func.coalesce(Item.do_not_renew, CatalogEntry.do_not_renew, false()).is_(True),
                )
            )
        )
    return found
