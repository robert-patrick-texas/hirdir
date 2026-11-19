"""What a record has from the record above it, down each hierarchy.

An item has what a group it is a member of has, a minor item then what the item above
it has, and a group what the group it is nested in has: its location, its planned
location, its operator and its owner, wherever it says nothing of its own. The rules are
said whole under "Groups, and which of them decides" on the data model page. Nothing is copied
down. What is in force is worked out when it is read, here for a page of records, and
in `hirdir.io.fields` for the database to filter, sort and count by. A test holds the
two together.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hirdir.db.models import DeviceGroup, Item
from hirdir.domain import groups, items
from hirdir.domain.inheritance import NOTHING, Effective

# Which of an item's groups decides, the first that has a value: the stack before the
# cluster before the controller domain before any other group.
GROUP_ORDER = ("stack", "cluster", "controller_domain", "custom")
RETIRED = "retired"
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
    group it is nested in that has one. A group that is retired passes nothing down: the
    walk up stops at it."""
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
            if at is not None and at.record_status == RETIRED:
                break
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

    `lines` gives the items above each item, the nearest first. The walk goes up one
    record at a time (P-175): the item's own value, then its own groups, then the item
    it is in and that item's groups, and so on to the top; and for what runs on a host,
    then the host and its groups, and on from it in the same way, or the stack or the
    cluster it runs on, which answers as a group does (P-246). The groups of one record
    are ranked as `from_groups` ranks them. A value had through a host says `host`,
    where the record it is had from holds it, and `device_group` where a group does.
    """
    walks = items.walks_above(db, found, lines)
    # Only the groups of the records that the walk reaches before a value of its own.
    wanted: set[str] = set()
    hosting: dict[str, DeviceGroup] = {}
    for item in found:
        for one in (item, *(step.record for step in walks[item.hid])):
            if isinstance(one, DeviceGroup):
                hosting[one.hid] = one
                break
            if _held(one, field, skip) is not None:
                break
            wanted.add(one.hid)
    by_group = from_groups(db, sorted(wanted), field, skip) if wanted else {}
    # A stack or a cluster that something runs on, as it answers: a retired one passes
    # nothing down.
    live = [group for group in hosting.values() if group.record_status != RETIRED]
    by_host = of_groups(db, live, field, skip) if live else {}
    in_force: dict[str, Effective] = {}
    for item in found:
        result = NOTHING
        steps = [items.Above(item, "parent_item"), *walks[item.hid]]
        for step in steps:
            one = step.record
            if isinstance(one, DeviceGroup):
                held = by_host.get(one.hid, NOTHING)
                if held.value is not None:
                    by_itself = held.source == "own"
                    result = Effective(
                        held.value, "host" if by_itself else SOURCE_GROUP, held.source_hid
                    )
                break
            value = _held(one, field, skip)
            if value is not None:
                result = Effective(value, "own" if one is item else step.source, one.hid)
                break
            grouped = by_group[one.hid]
            if grouped.value is not None:
                result = grouped
                break
        in_force[item.hid] = result
    return in_force


def group_reach(field: str, live: Any = None) -> Any:
    """Return, as a table, each group that has a value in force in a field with that
    value: its own, or that of the nearest group it is nested in; and `holder_hid`, the
    group that holds it. A group that is retired passes nothing down to the groups nested
    in it, as `of_groups` has it.

    `live` turns a column into the value it stands for, or nothing: an operator that
    is retired stands for nothing.
    """

    def value(group: Any) -> Any:
        column = getattr(group, field)
        return live(column) if live is not None else column

    inner: Any = aliased(DeviceGroup)
    start = (
        select(
            DeviceGroup.hid.label("group_hid"),
            value(DeviceGroup).label("value"),
            DeviceGroup.hid.label("holder_hid"),
            (DeviceGroup.record_status != RETIRED).label("passes"),
        )
        .where(value(DeviceGroup).is_not(None))
        .cte(recursive=True)
    )
    return start.union_all(
        select(inner.hid, start.c.value, start.c.holder_hid, inner.record_status != RETIRED).where(
            inner.parent_group_hid == start.c.group_hid, value(inner).is_(None), start.c.passes
        )
    )
