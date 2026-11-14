"""What a record has from the record above it, down each hierarchy.

A minor item has what the item above it has, and an item what a group it is a member
of has, and a group what the group it is nested in has: its location, its planned
location and its operator, wherever it says nothing of its own. Nothing is copied
down. What is in force is worked out when it is read, here for a page of records, and
in `hirdir.io.fields` for the database to filter, sort and count by. A test holds the
two together.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hirdir.db.models import DeviceGroup, Item
from hirdir.domain import groups
from hirdir.domain.inheritance import NOTHING, Effective

# Which of an item's groups decides, the first that has a value: the stack before the
# cluster before the controller domain before any other group.
GROUP_ORDER = ("stack", "cluster", "controller_domain", "custom")
SOURCE_GROUP = "device_group"
NONE: frozenset[str] = frozenset()


def _held(record: Any, field: str, skip: Collection[str]) -> str | None:
    """Return what a record itself says in a field, passing over a value that is skipped."""
    value = getattr(record, field)
    return value if value is not None and value not in skip else None


def of_groups(
    db: Session, found: Sequence[DeviceGroup], field: str, skip: Collection[str] = NONE
) -> dict[str, Effective]:
    """Return what each group has in force in a field: its own, or that of the nearest
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
            value = _held(at, field, skip)
            if value is not None:
                result = Effective(value, "own" if at is group else SOURCE_GROUP, at.hid)
                break
            at = held.get(at.parent_group_hid or "")
        in_force[group.hid] = result
    return in_force


def from_groups(
    db: Session, item_hids: Sequence[str], field: str, skip: Collection[str] = NONE
) -> dict[str, Effective]:
    """Return what each item has from the groups it is a current member of: that of the
    first group, in the order of `GROUP_ORDER` and then by name, that has one in force."""
    memberships = groups.memberships_of(db, item_hids)
    its_groups = {group.hid: group for listed in memberships.values() for _, group in listed}
    by_group = of_groups(db, list(its_groups.values()), field, skip)
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


def of_items(
    db: Session,
    found: Sequence[Item],
    lines: Mapping[str, Sequence[Item]],
    field: str,
    skip: Collection[str] = NONE,
) -> dict[str, Effective]:
    """Return what each item has in force in a field, and where it came from.

    `lines` gives the items above each item, the nearest first. The item's own comes
    first, then that of the nearest item above it, then that of a group the item at
    the top of the line is a current member of.
    """
    in_force: dict[str, Effective] = {}
    tops: dict[str, str] = {}
    for item in found:
        line = [item, *lines[item.hid]]
        holder = next((one for one in line if _held(one, field, skip) is not None), None)
        if holder is not None:
            source = "own" if holder is item else "parent_item"
            in_force[item.hid] = Effective(getattr(holder, field), source, holder.hid)
        else:
            tops[item.hid] = line[-1].hid
    if tops:
        by_group = from_groups(db, sorted(set(tops.values())), field, skip)
        for hid, top in tops.items():
            in_force[hid] = by_group[top]
    return in_force


def group_reach(field: str, live: Any = None) -> Any:
    """Return, as a table, each group that has a value in force in a field with that
    value: its own, or that of the nearest group it is nested in.

    `live` turns a column into the value it stands for, or nothing: an operator that
    is retired stands for nothing.
    """

    def value(group: Any) -> Any:
        column = getattr(group, field)
        return live(column) if live is not None else column

    inner: Any = aliased(DeviceGroup)
    start = (
        select(DeviceGroup.hid.label("group_hid"), value(DeviceGroup).label("value"))
        .where(value(DeviceGroup).is_not(None))
        .cte(recursive=True)
    )
    return start.union_all(
        select(inner.hid, start.c.value).where(
            inner.parent_group_hid == start.c.group_hid, value(inner).is_(None)
        )
    )
