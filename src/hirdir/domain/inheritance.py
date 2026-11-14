"""Inheritance: a blank inherits, a value overrides, and the answer says where it came from.

Nothing here writes. An inherited value is worked out each time it is read, so a change
to a catalog entry reaches every item of that model without touching one of them.
"""

from collections.abc import Sequence
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


Source = Literal[
    "own",
    "catalog",
    "parent_item",
    "device_group",
    "location",
    "site",
    "region",
    "setting",
    "none",
]


@dataclass(frozen=True)
class Effective:
    """A value in force, and the record it came from."""

    value: Any
    source: Source
    source_hid: str | None


NOTHING = Effective(None, "none", None)


STANDING = ("lifecycle_state", "disposition", "expected_online")
PARENT_FIELDS = ("owner_hid", "location_hid", *STANDING)


def of_item(
    item: Item, entry: CatalogEntry | None, above: Sequence[Item] = ()
) -> dict[str, Effective]:
    """Return the value in force of each field an item inherits.

    The amounts and the dates come from its catalog entry. A minor item has the owner
    of the nearest item above it that has one, is where the nearest one that has a
    location is, and, when it has no lifecycle state of
    its own, the state, disposition and intent of the nearest one that has a state: the
    three are taken together, because the lifecycle rules check them against one
    another. `above` is the items above it, the nearest first.
    """
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

    def from_nearest(having: str, names: tuple[str, ...]) -> None:
        for holder in (item, *above):
            if getattr(holder, having) is not None:
                source: Source = "own" if holder is item else "parent_item"
                for name in names:
                    value = getattr(holder, name)
                    found[name] = NOTHING if value is None else Effective(value, source, holder.hid)
                return
        for name in names:
            found[name] = NOTHING

    from_nearest("owner_hid", ("owner_hid",))
    from_nearest("location_hid", ("location_hid",))
    from_nearest("lifecycle_state", STANDING)
    return found


def of_catalog_entry(entry: CatalogEntry, global_discount: Decimal) -> dict[str, Effective]:
    """Return the stack discount in force for a catalog entry."""
    if entry.stack_discount_pct is not None:
        discount = Effective(entry.stack_discount_pct, "own", entry.hid)
    else:
        discount = Effective(global_discount, "setting", None)
    return {"stack_discount_pct": discount}
