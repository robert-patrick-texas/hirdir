"""The operator: the one person of the team who looks after an item or a device group.

An item has its own, or that of the item above it, or that of a group it is a member
of, or that of a group that group is nested in. Nothing is copied down: the operator
in force is worked out when it is read, here for a page of records, and in
`hirdir.io.fields` for the database to filter, sort and count by. A test holds the two
together.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hirdir.db.models import DeviceGroup, Item
from hirdir.domain import groups
from hirdir.domain.inheritance import NOTHING, Effective

# Which of an item's groups says who its operator is, the first that has one: the
# stack before the cluster before the controller domain before any other group.
GROUP_ORDER = ("stack", "cluster", "controller_domain", "custom")
SOURCE_GROUP = "device_group"


def of_groups(db: Session, found: Sequence[DeviceGroup]) -> dict[str, Effective]:
    """Return the operator in force of each group: its own, or that of the nearest
    group it is nested in that has one."""
    held: dict[str, DeviceGroup] = {group.hid: group for group in found}
    wanted = {group.parent_group_hid for group in found}
    for _ in range(groups.MAX_NESTING + 1):
        missing = {hid for hid in wanted if hid and hid not in held}
        if not missing:
            break
        level = list(db.scalars(select(DeviceGroup).where(DeviceGroup.hid.in_(missing))))
        held.update((group.hid, group) for group in level)
        wanted = {group.parent_group_hid for group in level}
    in_force: dict[str, Effective] = {}
    for group in found:
        at: DeviceGroup | None = group
        seen: set[str] = set()
        result = NOTHING
        while at is not None and at.hid not in seen:
            seen.add(at.hid)
            if at.operator_hid is not None:
                source = "own" if at is group else SOURCE_GROUP
                result = Effective(at.operator_hid, source, at.hid)
                break
            at = held.get(at.parent_group_hid or "")
        in_force[group.hid] = result
    return in_force


def of_items(
    db: Session, found: Sequence[Item], lines: Mapping[str, Sequence[Item]]
) -> dict[str, Effective]:
    """Return the operator in force of each item, and where it came from.

    `lines` gives the items above each item, the nearest first. The item's own comes
    first, then that of the nearest item above it, then that of a group the item at
    the top of the line is a current member of.
    """
    in_force: dict[str, Effective] = {}
    tops: dict[str, str] = {}
    for item in found:
        line = [item, *lines[item.hid]]
        holder = next((one for one in line if one.operator_hid is not None), None)
        if holder is not None:
            source = "own" if holder is item else "parent_item"
            in_force[item.hid] = Effective(holder.operator_hid, source, holder.hid)
        else:
            tops[item.hid] = line[-1].hid
    from_above = from_groups(db, sorted(set(tops.values())))
    for hid, top in tops.items():
        in_force[hid] = from_above[top]
    return in_force


def from_groups(db: Session, item_hids: Sequence[str]) -> dict[str, Effective]:
    """Return the operator each item has from the groups it is a current member of:
    that of the first group, in the order of `GROUP_ORDER` and then by name, that has
    one in force."""
    memberships = groups.memberships_of(db, item_hids)
    its_groups = {group.hid: group for listed in memberships.values() for _, group in listed}
    by_group = of_groups(db, list(its_groups.values()))
    found: dict[str, Effective] = {}
    for hid in item_hids:
        ordered = sorted(
            (group for _, group in memberships[hid]),
            key=lambda group: (GROUP_ORDER.index(group.type), group.name_key, group.hid),
        )
        chosen = next(
            (by_group[group.hid] for group in ordered if by_group[group.hid].value is not None),
            None,
        )
        found[hid] = (
            NOTHING if chosen is None else Effective(chosen.value, SOURCE_GROUP, chosen.source_hid)
        )
    return found


def group_reach() -> Any:
    """Return, as a table, each group that has an operator in force with that operator:
    its own, or that of the nearest group it is nested in."""
    inner: Any = aliased(DeviceGroup)
    start = (
        select(
            DeviceGroup.hid.label("group_hid"),
            DeviceGroup.operator_hid.label("operator_hid"),
        )
        .where(DeviceGroup.operator_hid.is_not(None))
        .cte(recursive=True)
    )
    return start.union_all(
        select(inner.hid, start.c.operator_hid).where(
            inner.parent_group_hid == start.c.group_hid, inner.operator_hid.is_(None)
        )
    )
