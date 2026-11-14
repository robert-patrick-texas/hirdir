"""Moving in: what is planned for a place is there once the place is in use.

A place that was a draft has been made active. Every item and device group with a plan
of its own for a location thereby in use is moved: its location becomes the planned
one, and the plan is cleared. What has its plan from above, from the group it is in or
from the item it is in, and a location of its own, gives that location up: it goes
with what it is in, and is where that is from now on. Each is a change of one record,
with an entry of its own in the audit trail under the request that opened the place,
all in one transaction. A retired record is left where it is.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import DeviceGroup, DeviceGroupMember, Item
from hirdir.domain import descent, geography, groups, items, records
from hirdir.domain.audit import AuditContext

MODELS: tuple[tuple[Any, str], ...] = ((Item, "item"), (DeviceGroup, "device_group"))


def _ready(db: Session) -> list[str]:
    """Return the locations that something is planned for and that are now in use."""
    planned: set[str | None] = set()
    for model, _ in MODELS:
        planned.update(
            db.scalars(
                select(model.planned_location_hid)
                .where(model.planned_location_hid.is_not(None), model.record_status != "retired")
                .distinct()
            )
        )
    atlas = geography.Atlas(db)
    atlas.read_locations(planned)
    return [
        hid
        for hid in sorted(hid for hid in planned if hid)
        if (location := atlas.location(hid)) is not None and geography.in_use(atlas, location)
    ]


def _within(db: Session, model: Any, parent: Any, hids: list[str], depth: int) -> list[Any]:
    """Return the records beneath some records, level by level."""
    found: list[Any] = []
    level = hids
    for _ in range(depth):
        if not level:
            break
        below = list(
            db.scalars(select(model).where(parent.in_(level), model.record_status != "retired"))
        )
        found += below
        level = [record.hid for record in below]
    return found


def _going_along(
    db: Session, arriving: dict[str, list[Any]], ready: set[str]
) -> tuple[list[DeviceGroup], list[Item]]:
    """Return the groups and the items that have a location of their own and no plan of
    their own, and whose plan in force, from what they are in, is for a place now in
    use: they go with what they are in."""
    moving_groups: list[DeviceGroup] = arriving["device_group"]
    nested = _within(
        db,
        DeviceGroup,
        DeviceGroup.parent_group_hid,
        [group.hid for group in moving_groups],
        groups.MAX_NESTING,
    )
    plans = descent.of_groups(db, nested, "planned_location_hid")
    groups_along = [
        group
        for group in nested
        if group.planned_location_hid is None
        and group.location_hid is not None
        and plans[group.hid].value in ready
    ]
    in_groups = [group.hid for group in (*moving_groups, *nested)]
    members: list[Item] = []
    for start in range(0, len(in_groups), 500):
        members += db.scalars(
            select(Item)
            .join(DeviceGroupMember, DeviceGroupMember.item_hid == Item.hid)
            .where(
                DeviceGroupMember.group_hid.in_(in_groups[start : start + 500]),
                DeviceGroupMember.left_on.is_(None),
                Item.record_status != "retired",
            )
        )
    tops = {item.hid: item for item in (*members, *arriving["item"])}
    beneath = _within(db, Item, Item.parent_item_hid, list(tops), items.MAX_DEPTH)
    candidates = {item.hid: item for item in (*tops.values(), *beneath)}
    waiting = [
        item
        for item in candidates.values()
        if item.planned_location_hid is None and item.location_hid is not None
    ]
    going = descent.of_items(db, waiting, items.lines_above(db, waiting), "planned_location_hid")
    return groups_along, [item for item in waiting if going[item.hid].value in ready]


def move_in(db: Session, context: AuditContext) -> int:
    """Move what is planned for a location now in use into it. Return how many records
    were changed."""
    ready = _ready(db)
    if not ready:
        return 0
    arriving: dict[str, list[Any]] = {}
    for model, record_type in MODELS:
        found: list[Any] = []
        for start in range(0, len(ready), 500):
            found += db.scalars(
                select(model)
                .where(
                    model.planned_location_hid.in_(ready[start : start + 500]),
                    model.record_status != "retired",
                )
                .order_by(model.hid)
            )
        arriving[record_type] = found
    # Who goes along is seen before anything is moved: the plans they have from above
    # are gone once the records above them have arrived.
    groups_along, items_along = _going_along(db, arriving, set(ready))
    changed = 0
    for _, record_type in MODELS:
        for record in arriving[record_type]:
            records.apply(
                db,
                context,
                record_type,
                record,
                None,
                {"location_hid": record.planned_location_hid, "planned_location_hid": None},
            )
            changed += 1
    for record_type, along in (("device_group", groups_along), ("item", items_along)):
        for record in along:
            # It is where what it is in is: its own place is given up.
            records.apply(db, context, record_type, record, None, {"location_hid": None})
            changed += 1
    return changed
