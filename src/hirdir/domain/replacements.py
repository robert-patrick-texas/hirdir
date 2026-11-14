"""Replacing an item: for an RMA, a project or a refresh, two records are linked.

The item that left and the item that took its place both remain. The new item takes
over the place of the old one in every group it was a current member of, so that a
stack is the same stack, with the same HID, through the replacement of its master.
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import DeviceGroup, Item, ItemReplacement
from hirdir.domain import audit, choices, groups, items, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, StaleVersion

RECORD_TYPE = "item_replacement"
FIELDS = ("old_item_hid", "new_item_hid", "reason", "reference", "replaced_on")
MAX_REFERENCE = 200


def of_items(
    db: Session, item_hids: list[str]
) -> tuple[dict[str, ItemReplacement], dict[str, ItemReplacement]]:
    """Return, for the items, the replacement each was replaced by and the one it made."""
    if not item_hids:
        return {}, {}
    replaced_by = {
        found.old_item_hid: found
        for found in db.scalars(
            select(ItemReplacement).where(ItemReplacement.old_item_hid.in_(item_hids))
        )
    }
    replaces = {
        found.new_item_hid: found
        for found in db.scalars(
            select(ItemReplacement).where(ItemReplacement.new_item_hid.in_(item_hids))
        )
    }
    return replaced_by, replaces


def _take_over(
    db: Session, context: AuditContext, old: Item, new: Item, day: date
) -> list[DeviceGroup]:
    """Give the new item the old one's place in each group it is a current member of."""
    touched = []
    for member, group in groups.memberships_of(db, [old.hid])[old.hid]:
        if day < member.joined_on:
            raise Invalid(
                "the day of the replacement is not acceptable",
                {
                    "replaced_on": f"the item joined {group.name} on {member.joined_on}, "
                    "after this day"
                },
            )
        role, position = member.role, member.position
        records.apply(db, context, groups.MEMBER_TYPE, member, None, {"left_on": day})
        groups.add_members(
            db,
            context,
            group.hid,
            [{"item_hid": new.hid, "role": role, "position": position, "joined_on": day}],
            check=False,
        )
        touched.append(group)
    return touched


def replace(
    db: Session,
    context: AuditContext,
    old_hid: str,
    row_version: int,
    *,
    reason: Any,
    new_item_hid: str | None = None,
    new_item: dict[str, Any] | None = None,
    reference: Any = None,
    replaced_on: date | None = None,
) -> ItemReplacement:
    """Record that one item took the place of another, and hand over its memberships.

    The item that takes the place is one that exists, named by its HID, or is created
    here from its fields. Neither item is moved in the lifecycle.
    """
    old = items.get_item(db, old_hid)
    if old.row_version != row_version:
        raise StaleVersion(
            f"this record is at version {old.row_version}, "
            f"and the change was made against version {row_version}"
        )
    if (new_item_hid is None) == (new_item is None):
        raise Invalid(
            "name the item that takes the place",
            {"new_item_hid": "give the HID of an item, or the fields of a new one, and not both"},
        )
    given = records.clean(reason)
    if not given:
        raise Invalid("a replacement has a reason", {"reason": "say why the item was replaced"})
    reason = choices.checked(db, "replacement_reason", given, "reason")
    reference = records.clean(reference)
    if reference is not None and len(reference) > MAX_REFERENCE:
        raise Invalid(
            "the reference is too long", {"reference": f"at most {MAX_REFERENCE} characters"}
        )
    day = groups.today(db) if replaced_on is None else replaced_on
    taken = db.scalar(select(ItemReplacement).where(ItemReplacement.old_item_hid == old.hid))
    if taken is not None:
        raise Conflict(
            "this item has been replaced already",
            {"new_item_hid": f"it was replaced by {taken.new_item_hid} on {taken.replaced_on}"},
        )
    if new_item is not None:
        new = items.create_item(db, context, dict(new_item))
    else:
        if new_item_hid == old.hid:
            raise Invalid(
                "an item does not take its own place",
                {"new_item_hid": "name another item"},
            )
        found = db.get(Item, new_item_hid)
        if found is None:
            raise Invalid(
                "there is no such item", {"new_item_hid": f"there is no item {new_item_hid}"}
            )
        if found.record_status == "retired":
            raise Invalid("the item is retired", {"new_item_hid": "this item is retired"})
        new = found
        taken = db.scalar(select(ItemReplacement).where(ItemReplacement.new_item_hid == new.hid))
        if taken is not None:
            raise Conflict(
                "this item took the place of another already",
                {"new_item_hid": f"it took the place of {taken.old_item_hid}"},
            )
    replacement = ItemReplacement(
        old_item_hid=old.hid,
        new_item_hid=new.hid,
        reason=reason,
        reference=reference,
        replaced_on=day,
    )
    records.created(db, context, RECORD_TYPE, replacement, FIELDS)
    for group in _take_over(db, context, old, new, day):
        groups.check_group(db, group)
    # Both items say so in their own history, and a copy of either read before this is
    # stale from here on.
    for item, field, other in ((old, "replaced_by", new), (new, "replaces", old)):
        records.touch(item, context, None)
        audit.record(
            db,
            context,
            "replace",
            items.RECORD_TYPE,
            item.hid,
            [
                change(field, None, other.hid),
                change("reason", None, reason),
                change("reference", None, reference),
                change("replaced_on", None, day.isoformat()),
            ],
        )
    db.flush()
    return replacement
