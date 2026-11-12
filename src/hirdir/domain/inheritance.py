"""Inheritance: a blank inherits, a value overrides, and the answer says where it came from.

Nothing here writes. An inherited value is worked out each time it is read, so a change
to a catalog entry reaches every item of that model without touching one of them.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from hirdir.db.models import CatalogEntry, Item

ITEM_FIELDS = (
    "est_value",
    "support_weight",
    "annual_support_cost",
    "end_of_sale",
    "end_of_sw_support",
    "end_of_hw_support",
    "ldos",
)


Source = Literal["own", "catalog", "parent_item", "location", "site", "region", "setting", "none"]


@dataclass(frozen=True)
class Effective:
    """A value in force, and the record it came from."""

    value: Any
    source: Source
    source_hid: str | None


NOTHING = Effective(None, "none", None)


def of_item(item: Item, entry: CatalogEntry | None) -> dict[str, Effective]:
    """Return the value in force of each field an item inherits from its catalog entry."""
    found = {}
    for name in ITEM_FIELDS:
        own = getattr(item, name)
        inherited = getattr(entry, name) if entry is not None else None
        if own is not None:
            found[name] = Effective(own, "own", item.hid)
        elif entry is not None and inherited is not None:
            found[name] = Effective(inherited, "catalog", entry.hid)
        else:
            found[name] = NOTHING
    return found


def of_catalog_entry(entry: CatalogEntry, global_discount: Decimal) -> dict[str, Effective]:
    """Return the stack discount in force for a catalog entry."""
    if entry.stack_discount_pct is not None:
        discount = Effective(entry.stack_discount_pct, "own", entry.hid)
    else:
        discount = Effective(global_discount, "setting", None)
    return {"stack_discount_pct": discount}
