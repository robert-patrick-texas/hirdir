"""Why a record has each value it has from elsewhere: the walk, step by step (P-176).

The value in force of an item's location, planned location, operator and owner is the
first value of a walk up from the item, one record at a time: its own, then its own
groups, then the item it is in and that item's groups, and, for the operator, then the
place chain of where it is (P-175). The values of its model are its own, then its catalog
entry's, and for the support weight of a major item then the setting. This module walks
the same way and says what each step holds: which decides, which is passed over, which
holds nothing. It uses the rules that the value in force is worked out by, so the two
cannot differ, and a test holds them together.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from hirdir.db.models import CatalogEntry, DeviceGroup, Item, Location, Operator, Owner, Vendor
from hirdir.domain import descent, geography, groups, inheritance, operators, weights
from hirdir.domain import items as item_rules

Outcome = Literal["decides", "passed_over", "nothing", "retired", "raises"]
StepLevel = Literal[
    "own", "device_group", "parent_item", "catalog", "setting", "location", "site", "region"
]
# The four values an item has from its groups and from the item it is in.
GROUP_FIELDS = ("location_hid", "planned_location_hid", "operator_hid", "owner_hid")
CATALOG_FIELDS = inheritance.ITEM_FIELDS


@dataclass
class Step:
    """One record the walk looks at, and what it holds there."""

    level: StepLevel
    hid: str | None
    name: str | None
    value: Any
    label: str | None = None
    type: str | None = None
    rank: int | None = None
    via_hid: str | None = None
    via_name: str | None = None
    retired: bool = False
    outcome: Outcome = "nothing"


@dataclass
class Walk:
    """The walk of one value: what is in force, what an own value replaces, the steps."""

    field: str
    value: Any = None
    label: str | None = None
    source: str = "none"
    source_hid: str | None = None
    overrides: Any = None
    overrides_label: str | None = None
    steps: list[Step] = field(default_factory=list)


def _decided(name: str, steps: list[Step]) -> Walk:
    """Mark the steps of a walk and say what it comes to: the first that holds a value
    decides, a later one that holds one is passed over, and a retired operator is passed
    over as retired, as if it were not there."""
    walk = Walk(field=name, steps=steps)
    for step in steps:
        if step.retired:
            # A retired operator, or a retired group, which passes nothing down.
            step.outcome = "retired"
        elif step.value is None:
            step.outcome = "nothing"
        elif walk.source == "none":
            step.outcome = "decides"
            walk.value, walk.label = step.value, step.label
            walk.source = step.level
            walk.source_hid = step.via_hid or step.hid
        else:
            step.outcome = "passed_over"
            if walk.source == "own" and walk.overrides is None:
                walk.overrides, walk.overrides_label = step.value, step.label
    return walk


class _Names:
    """What the walk names its values by, read once for every step."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.atlas = geography.Atlas(db)

    def of(self, name: str, value: Any) -> str | None:
        if value is None:
            return None
        if name in ("location_hid", "planned_location_hid"):
            self.atlas.read_locations([value])
            return self.atlas.location_path(value) or None
        if name == "operator_hid":
            operator = self.db.get(Operator, value)
            return operator.label if operator is not None else None
        if name == "owner_hid":
            owner = self.db.get(Owner, value)
            return owner.label if owner is not None else None
        return None


def _group_steps(
    db: Session, name: str, one: Item, gone: set[str], names: _Names, rank_from: int = 1
) -> list[Step]:
    """Return the steps of the groups one record of the line is a current member of, in
    the order they are ranked, each with what it has in force and where from."""
    member_of = [group for _, group in groups.memberships_of(db, [one.hid])[one.hid]]
    ordered = sorted(
        member_of,
        key=lambda group: (descent.GROUP_ORDER.index(group.type), group.name_key, group.hid),
    )
    in_force = descent.of_groups(db, ordered, name, gone)
    steps = []
    for rank, group in enumerate(ordered, start=rank_from):
        found = in_force[group.hid]
        own = getattr(group, name)
        if found.value is None and own is not None and own in gone:
            # Its own is a retired operator, and nothing comes from above it.
            steps.append(
                Step(
                    level="device_group",
                    hid=group.hid,
                    name=group.name,
                    value=own,
                    label=names.of(name, own),
                    type=group.type,
                    rank=rank,
                    retired=True,
                )
            )
            continue
        via = None
        if found.value is not None and found.source_hid != group.hid:
            via = db.get(DeviceGroup, found.source_hid)
        steps.append(
            Step(
                level="device_group",
                hid=group.hid,
                name=group.name,
                value=found.value,
                label=names.of(name, found.value),
                type=group.type,
                rank=rank,
                via_hid=via.hid if via is not None else None,
                via_name=via.name if via is not None else None,
            )
        )
    return steps


def _place_steps(
    db: Session, location_hid: str | None, gone: set[str], names: _Names
) -> list[Step]:
    """Return the steps of the place chain of a location, for an operator: the location,
    the locations above it, its site and each region outward."""
    if location_hid is None:
        return []
    location = db.get(Location, location_hid)
    if location is None:
        return []
    steps = []
    for place in names.atlas.chain(geography.Place("location", location)):
        value = place.record.operator_hid
        steps.append(
            Step(
                level=place.level,
                hid=place.hid,
                name=names.atlas.path(place),
                value=value,
                label=names.of("operator_hid", value),
                retired=value in gone,
            )
        )
    return steps


def _line_walk(
    db: Session, item: Item, line: Sequence[Item], name: str, gone: set[str], names: _Names
) -> list[Step]:
    """Return the steps of an item's walk up its line for one of the four values."""
    steps: list[Step] = []
    for one in line:
        value = getattr(one, name)
        steps.append(
            Step(
                level="own" if one is item else "parent_item",
                hid=one.hid,
                name=item_rules.shown_name(one),
                value=value,
                label=names.of(name, value),
                retired=name == "operator_hid" and value in gone,
            )
        )
        steps += _group_steps(db, name, one, gone if name == "operator_hid" else set(), names)
    return steps


def of_item(db: Session, item: Item) -> list[Walk]:
    """Return the walk of every value an item may have from elsewhere."""
    line = [item, *item_rules.lines_above(db, [item])[item.hid]]
    gone = operators.released(db)
    names = _Names(db)
    walks = []
    location = None
    for name in GROUP_FIELDS:
        steps = _line_walk(db, item, line, name, gone, names)
        if name == "operator_hid":
            steps += _place_steps(db, location, gone, names)
        walk = _decided(name, steps)
        if name == "location_hid":
            location = walk.value
        walks.append(walk)
    walks += _catalog_walks(db, item)
    return walks


def _catalog_walks(db: Session, item: Item) -> list[Walk]:
    """Return the walks of the values of an item's model: its own, then its catalog
    entry's, and for the support weight of a major item then the default, and the
    minimum where it raises what was found."""
    entry = db.get(CatalogEntry, item.catalog_entry_hid) if item.catalog_entry_hid else None
    entry_name = None
    if entry is not None:
        vendor = db.get(Vendor, entry.vendor_hid)
        entry_name = f"{vendor.name} {entry.pid}" if vendor is not None else entry.pid
    figures = weights.in_force(db)
    walks = []
    for name in CATALOG_FIELDS:
        steps = [
            Step(
                level="own",
                hid=item.hid,
                name=item_rules.shown_name(item),
                value=getattr(item, name),
            )
        ]
        if entry is not None:
            steps.append(
                Step(level="catalog", hid=entry.hid, name=entry_name, value=getattr(entry, name))
            )
        major = item.parent_item_hid is None
        if name == "support_weight" and major:
            default = figures.default("item")
            steps.append(
                Step(level="setting", hid=None, name=weights.default_key("item"), value=default)
            )
        walk = _decided(name, steps)
        if name == "support_weight" and major:
            # The minimum raises what was found, and the value keeps where it came from,
            # as the record has it (P-155).
            minimum = figures.minimum("item")
            raised = walk.value is not None and minimum is not None and walk.value < minimum
            steps.append(
                Step(
                    level="setting",
                    hid=None,
                    name=weights.minimum_key("item"),
                    value=minimum,
                    outcome="raises" if raised else "nothing" if minimum is None else "passed_over",
                )
            )
            if raised:
                walk.value = minimum
        walks.append(walk)
    return walks


def of_group(db: Session, group: DeviceGroup) -> list[Walk]:
    """Return the walk of every value a group may have from the groups it is nested in:
    its own, then each group it is nested in, the nearest first."""
    gone = operators.released(db)
    names = _Names(db)
    chain = [group]
    seen = {group.hid}
    while chain[-1].parent_group_hid and len(chain) <= groups.MAX_NESTING:
        above = db.get(DeviceGroup, chain[-1].parent_group_hid)
        if above is None or above.hid in seen:
            break
        seen.add(above.hid)
        chain.append(above)
        # A group that is retired passes nothing down: it is the last step, and retired.
        if above.record_status == descent.RETIRED:
            break
    walks = []
    for name in GROUP_FIELDS:
        steps = []
        for one in chain:
            value = getattr(one, name)
            steps.append(
                Step(
                    level="own" if one is group else "device_group",
                    hid=one.hid,
                    name=one.name,
                    value=value,
                    label=names.of(name, value),
                    type=one.type,
                    retired=(name == "operator_hid" and value in gone)
                    or (one is not group and one.record_status == descent.RETIRED),
                )
            )
        walks.append(_decided(name, steps))
    return walks
