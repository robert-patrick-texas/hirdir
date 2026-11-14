"""Moving in: what is planned for a place is there once the place is in use.

A place that was a draft has been made active. Every item and device group with a plan
of its own for a location thereby in use is moved: its location becomes the planned
one, and the plan is cleared. What has its plan from above, from the group it is in or
from the item it is in, and a location of its own, gives that location up: it goes
with what it is in, and is where that is from now on. Each is a change of one record,
with an entry of its own in the audit trail under the request that opened the place,
all in one transaction. A retired record is left where it is.

Making a place active is so a change that reaches into the inventory. `opening` says
what it would bring about before it is made, for whoever is about to make it.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import DeviceGroup, DeviceGroupMember, Item
from hirdir.domain import descent, geography, groups, items, records
from hirdir.domain.audit import AuditContext

MODELS: tuple[tuple[Any, str], ...] = ((Item, "item"), (DeviceGroup, "device_group"))


@dataclass
class _Plan:
    """What a move would do: the records that arrive by a plan of their own, those
    that give their own location up to go with what they are in, and how many items
    and groups are there afterwards, those among them that are not written to."""

    arriving: dict[str, list[Any]] = field(default_factory=dict)
    groups_along: list[DeviceGroup] = field(default_factory=list)
    items_along: list[Item] = field(default_factory=list)
    items: int = 0
    device_groups: int = 0

    @property
    def changed(self) -> int:
        """How many records are written to, each with an entry of its own."""
        arriving = sum(len(found) for found in self.arriving.values())
        return arriving + len(self.groups_along) + len(self.items_along)


@dataclass(frozen=True)
class Opening:
    """What making a place active would bring about."""

    record_status: str
    # The nearest place above that is not active: nothing moves until it is too.
    waits_for: geography.Place | None
    items: int
    device_groups: int
    changed: int


def _ready(db: Session, as_active: Collection[str] = ()) -> list[str]:
    """Return the locations that something is planned for and that are in use, taking
    the places named as active whatever they are."""
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
    ready = []
    for hid in sorted(hid for hid in planned if hid):
        location = atlas.location(hid)
        if location is None:
            continue
        chain = atlas.chain(geography.Place("location", location))
        if all(one.record.record_status == "active" or one.hid in as_active for one in chain):
            ready.append(hid)
    return ready


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


def _plan(db: Session, ready: list[str]) -> _Plan:
    """Return what moving into some locations would do."""
    plan = _Plan()
    if not ready:
        return plan
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
        plan.arriving[record_type] = found
    into = set(ready)
    # The groups nested in a group that arrives go with it, unless they have a plan of
    # their own: those with a location of their own give it up.
    moving_groups: list[DeviceGroup] = plan.arriving["device_group"]
    nested = _within(
        db,
        DeviceGroup,
        DeviceGroup.parent_group_hid,
        [group.hid for group in moving_groups],
        groups.MAX_NESTING,
    )
    plans = descent.of_groups(db, nested, "planned_location_hid")
    following = [
        group
        for group in nested
        if group.planned_location_hid is None and plans[group.hid].value in into
    ]
    plan.groups_along = [group for group in following if group.location_hid is not None]
    plan.device_groups = len(moving_groups) + len(following)
    # And so do the members of those groups, and what is in an item that arrives.
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
    tops = {item.hid: item for item in (*members, *plan.arriving["item"])}
    beneath = _within(db, Item, Item.parent_item_hid, list(tops), items.MAX_DEPTH)
    candidates = {item.hid: item for item in (*tops.values(), *beneath)}
    unplanned = [item for item in candidates.values() if item.planned_location_hid is None]
    going = descent.of_items(
        db, unplanned, items.lines_above(db, unplanned), "planned_location_hid"
    )
    with_it = [item for item in unplanned if going[item.hid].value in into]
    plan.items_along = [item for item in with_it if item.location_hid is not None]
    plan.items = len(plan.arriving["item"]) + len(with_it)
    return plan


def opening(db: Session, place: geography.Place) -> Opening:
    """Return what making a place active would bring about: how many items and device
    groups would be there, and how many records would be written to for it.

    While a place above it is not active nothing moves, and the answer names the
    nearest such place: the numbers are then what moves once that one, and any other
    above, is active too. For a place that is active already they are what is still
    planned for a place beneath it that is not.
    """
    atlas = geography.Atlas(db)
    chain = atlas.chain(place)
    above = [one for one in chain if one.hid != place.hid]
    waits_for = next((one for one in above if one.record.record_status != "active"), None)
    already = set(_ready(db))
    opened = [hid for hid in _ready(db, {one.hid for one in chain}) if hid not in already]
    # Of those, the ones at or beneath this place: another room that the places above
    # would open too is not this one's.
    atlas.read_locations(opened)
    ready = []
    for hid in opened:
        location = atlas.location(hid)
        if location is not None and any(
            one.hid == place.hid for one in atlas.chain(geography.Place("location", location))
        ):
            ready.append(hid)
    plan = _plan(db, ready)
    return Opening(
        record_status=place.record.record_status,
        waits_for=waits_for,
        items=plan.items,
        device_groups=plan.device_groups,
        changed=plan.changed,
    )


def move_in(db: Session, context: AuditContext) -> int:
    """Move what is planned for a location now in use into it. Return how many records
    were changed."""
    # Who goes along is seen before anything is moved: the plans they have from above
    # are gone once the records above them have arrived.
    plan = _plan(db, _ready(db))
    for _, record_type in MODELS:
        for record in plan.arriving.get(record_type, []):
            records.apply(
                db,
                context,
                record_type,
                record,
                None,
                {"location_hid": record.planned_location_hid, "planned_location_hid": None},
            )
    for record_type, along in (("device_group", plan.groups_along), ("item", plan.items_along)):
        for record in along:
            # It is where what it is in is: its own place is given up.
            records.apply(db, context, record_type, record, None, {"location_hid": None})
    return plan.changed
