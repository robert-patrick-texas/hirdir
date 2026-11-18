"""Replacing an item: for an RMA, a project or a refresh, two records are linked.

The item that left and the item that took its place both remain. The new item takes
over the place of the old one in every group it was a current member of, so that a
stack is the same stack, with the same HID, through the replacement of its master, and
in every circuit it was connected to.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import Item, ItemReplacement
from hirdir.domain import audit, choices, circuit_records, groups, items, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound, StaleVersion

RECORD_TYPE = "item_replacement"
FIELDS = ("old_item_hid", "new_item_hid", "reason", "reference", "replaced_on")
MAX_REFERENCE = 200


def latest_first() -> list[Any]:
    """The order of replacements, the latest first: by the day, then by when entered."""
    return [
        ItemReplacement.replaced_on.desc(),
        ItemReplacement.created_at.desc(),
        ItemReplacement.hid.desc(),
    ]


def of_items(
    db: Session, item_hids: list[str]
) -> tuple[dict[str, list[ItemReplacement]], dict[str, list[ItemReplacement]]]:
    """Return, for the items, the replacements each was replaced by and those it made,
    the latest first (P-241). An item that is part of none has empty lists."""
    replaced_by: dict[str, list[ItemReplacement]] = {hid: [] for hid in item_hids}
    replaces: dict[str, list[ItemReplacement]] = {hid: [] for hid in item_hids}
    if not item_hids:
        return replaced_by, replaces
    for found in db.scalars(
        select(ItemReplacement)
        .where(
            or_(
                ItemReplacement.old_item_hid.in_(item_hids),
                ItemReplacement.new_item_hid.in_(item_hids),
            )
        )
        .order_by(*latest_first())
    ):
        if found.old_item_hid in replaced_by:
            replaced_by[found.old_item_hid].append(found)
        if found.new_item_hid in replaces:
            replaces[found.new_item_hid].append(found)
    return replaced_by, replaces


def _refuse_same_day(db: Session, old: Item, new: Item, day: date) -> None:
    """Refuse a second replacement of one item by the same other on one day (P-241)."""
    twin = db.scalar(
        select(ItemReplacement).where(
            ItemReplacement.old_item_hid == old.hid,
            ItemReplacement.new_item_hid == new.hid,
            ItemReplacement.replaced_on == day,
        )
    )
    if twin is not None:
        label = f"{items.shown_name(old)} replaced by {items.shown_name(new)}"
        raise Conflict(
            f"{label} on {day} is recorded already",
            {"new_item_hid": f"this item took the place of the other on {day} already"},
            Existing(RECORD_TYPE, twin.hid, label),
        )


def _coming(
    db: Session, old: Item, drop_identity: Any, disposition: Any, expected_online: Any
) -> tuple[bool, dict[str, Any]]:
    """Return whether the item that comes gives up its name and place, and what it is to
    have, refusing `drop_identity` where the item that leaves is in no stack."""
    if drop_identity is None:
        drop_identity = False
    if not isinstance(drop_identity, bool):
        raise Invalid("drop_identity is not acceptable", {"drop_identity": "true or false"})
    if drop_identity and not any(
        group.type == "stack" for _, group in groups.memberships_of(db, [old.hid])[old.hid]
    ):
        raise Invalid(
            f"{items.shown_name(old)} is a current member of no stack",
            {
                "drop_identity": "the item that comes takes a stack's name and place only "
                "where the item that leaves is a current member of a stack"
            },
        )
    named = {
        name: value
        for name, value in (("disposition", disposition), ("expected_online", expected_online))
        if value is not None
    }
    return drop_identity, {**(dict.fromkeys(groups.IDENTITY) if drop_identity else {}), **named}


def _take_over(db: Session, context: AuditContext, old: Item, new: Item, day: date) -> None:
    """Give the new item the old one's place in each group it is a current member of."""
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
        # The role is handed over, the mark of the intended master with it. The master
        # that was seen is not: nobody has seen the new item as master yet, and the old
        # one's leaving clears it.
        if new.lifecycle_state in items.OUT_OF_HANDS:
            raise Invalid(
                f"{items.shown_name(new)} has left the team's hands",
                {
                    "new_item_hid": f"an item in {new.lifecycle_state} is in no group, and "
                    f"the item it would replace is a member of {group.name}"
                },
            )
        # The old membership ends first, so that its position is free for the new item,
        # which takes it as it is (P-219).
        groups.update_member(db, context, group.hid, member.hid, None, {"left_on": day})
        groups.add_members(
            db,
            context,
            group.hid,
            [{"item_hid": new.hid, "role": role, "position": position, "joined_on": day}],
            handed_over=True,
        )


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
    drop_identity: Any = False,
    disposition: Any = None,
    expected_online: Any = None,
    old_item: Mapping[str, Any] | None = None,
) -> ItemReplacement:
    """Record that one item took the place of another, and hand over its memberships.

    The item that takes the place is one that exists, named by its HID, or is created
    here from its fields. Neither item is moved by a rule: each is changed as the
    request names alone (P-242). With `drop_identity`, where the old item is a current
    member of a stack, the new one gives up its own name, addresses and place as a
    member that joins a stack does, and `disposition` and `expected_online` are its own
    from the change. `old_item` is what the old item is to have, as the end of a
    membership gives it, once its memberships have ended. All of it is one change: a
    refusal of any part leaves nothing done.
    """
    dialect.hold_other_writers(db)
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
    drop, coming = _coming(db, old, drop_identity, disposition, expected_online)
    if old_item and day > groups.today(db):
        # What becomes of the old item is done as the request is, and not on a day to come.
        raise Invalid(
            "the item that leaves is given what becomes of it on the day it is replaced",
            {"replaced_on": "with old_item, a day that has come: today or before"},
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
        _refuse_same_day(db, old, new, day)
    replacement = ItemReplacement(
        old_item_hid=old.hid,
        new_item_hid=new.hid,
        reason=reason,
        reference=reference,
        replaced_on=day,
    )
    records.created(db, context, RECORD_TYPE, replacement, FIELDS)
    db.flush()
    _take_over(db, context, old, new, day)
    # And the circuits it was connected to, on the same sides (P-147).
    circuit_records.hand_over(db, context, old.hid, new.hid)
    # Then what the request names of each item, by that item's rules, each change saying
    # the replacement it came from (P-242).
    replacing = audit.because(context, "replacing", None, replacement.hid)
    if coming:
        groups.take_on(db, replacing, new, drop, coming, "")
    if old_item:
        of_old = audit.because(
            context, "replacing", None, replacement.hid, of=(items.RECORD_TYPE, old.hid)
        )
        groups.give_back(db, of_old, old.hid, old_item, "old_item.")
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


def get_replacement(db: Session, hid: str) -> ItemReplacement:
    """Return the replacement with hid."""
    replacement = db.get(ItemReplacement, hid)
    if replacement is None:
        raise NotFound(f"there is no replacement {hid}")
    return replacement


def remove_replacement(db: Session, context: AuditContext, hid: str, reason: Any) -> None:
    """Remove a replacement that was a mistake, for an Admin, with a reason (P-238).

    The audit event of the removal holds the replacement as it was and the reason, and
    each of the two items has an event of it in its own history. What the replacement
    handed over, memberships and connections of circuits, stays as it is: each is a
    fact of its own, put right where it is kept. The two items are then as any other.
    """
    dialect.hold_other_writers(db)
    replacement = get_replacement(db, hid)
    why = records.clean(reason)
    if not why:
        raise Invalid(
            "a replacement is removed with a reason",
            {"reason": "say why the replacement was a mistake"},
        )
    audit.record(
        db,
        context,
        "delete",
        RECORD_TYPE,
        replacement.hid,
        [
            *(
                change(name, records.jsonable(getattr(replacement, name)), None)
                for name in FIELDS
                if getattr(replacement, name) is not None
            ),
            change("removal_reason", None, why),
        ],
    )
    pair = (
        (replacement.old_item_hid, "replaced_by", replacement.new_item_hid),
        (replacement.new_item_hid, "replaces", replacement.old_item_hid),
    )
    for item_hid, field, other in pair:
        # Each item says so in its own history, and a copy read before is stale.
        records.touch(db.get_one(Item, item_hid), context, None)
        audit.record(
            db,
            context,
            "replacement_removed",
            items.RECORD_TYPE,
            item_hid,
            [
                change(field, other, None),
                change("replacement", replacement.hid, None),
                change("removal_reason", None, why),
            ],
        )
    db.delete(replacement)
    db.flush()


def update_replacement(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> ItemReplacement:
    """Change why a replacement was made, or the reference it was made under.

    Which item took the place of which, and on what day, is not changed: the
    memberships were handed over then.
    """
    replacement = get_replacement(db, hid)
    values: dict[str, Any] = {}
    for name in ("old_item_hid", "new_item_hid", "replaced_on"):
        if name in fields and fields[name] != getattr(replacement, name):
            raise Invalid(
                "a replacement is not made a second time",
                {name: "which item took the place of which, and when, is not changed"},
            )
    if "reason" in fields:
        given = records.clean(fields["reason"])
        if not given:
            raise Invalid("a replacement has a reason", {"reason": "must not be blank"})
        values["reason"] = (
            given
            if records.key(given) == replacement.reason
            else choices.checked(db, "replacement_reason", given, "reason")
        )
    if "reference" in fields:
        reference = records.clean(fields["reference"])
        if reference is not None and len(reference) > MAX_REFERENCE:
            raise Invalid(
                "the reference is too long", {"reference": f"at most {MAX_REFERENCE} characters"}
            )
        values["reference"] = reference
    records.apply(db, context, RECORD_TYPE, replacement, row_version, values)
    return replacement
