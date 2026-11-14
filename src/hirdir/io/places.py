"""The geography as one tree, with what is at or beneath each place.

The counts are those of a view of the items, the one the item list shows for the same
filter, taken at each location by the database and added up here: an item is in one
place, so the count of a region is the sum of what is in it.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.db.models import DeviceGroup, Location, Region, Site
from hirdir.domain import geography, records
from hirdir.domain.errors import Invalid
from hirdir.io import fields, reports


@dataclass
class Count:
    """The items and the components of a set of items."""

    items: int = 0
    component_count: int = 0

    def add(self, items: int, components: int) -> None:
        """Count some more."""
        self.items += items
        self.component_count += components


@dataclass
class Node(Count):
    """A region, a site or a location, with what is at or beneath it."""

    level: str = ""
    hid: str = ""
    name: str = ""
    code: str | None = None
    kind: str | None = None
    path: str = ""
    record_status: str = "active"
    # The items planned for it or for a place beneath it, which are not there yet.
    planned: int = 0
    planned_groups: int = 0
    children: list[Node] = field(default_factory=list)


@dataclass
class Tree:
    """The tree of places, and the counts that stand beside it."""

    totals: Count
    unplaced: Count
    hidden: Count
    roots: list[Node]


def tree(
    db: Session,
    *,
    filter_: Any = None,
    root: str | None = None,
    locations: bool = True,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> Tree:
    """Return the regions, their sites and the locations within them, each with the
    items and the components at or beneath it.

    A place that is a draft or retired is in the tree only when the view asks for such
    records, and what is in a place the view leaves out is counted as hidden. `root`
    names one place to start from, which is shown whatever the view says, and without
    `locations` the tree stops at the sites. The counts beside the tree are those of
    the whole view, whatever place it starts from.
    """
    start = None
    if root is not None and root.strip():
        start = geography.find_place(db, root)
        if start is None:
            raise Invalid(
                "there is no such place",
                {"root": f"there is no region, site or location {root}"},
            )
    nodes: dict[str, Node] = {}
    above: dict[str, str | None] = {}
    # Only what the tree shows of each place is read: a site may have thousands of
    # locations, and a whole record of each would be most of the work.
    for hid, name, code, status, parent in db.execute(
        select(Region.hid, Region.name, Region.code, Region.record_status, Region.parent_region_hid)
    ):
        nodes[hid] = Node(
            level=geography.REGION, hid=hid, name=name, code=code, record_status=status
        )
        above[hid] = parent
    for hid, name, code, status, region_hid in db.execute(
        select(Site.hid, Site.name, Site.code, Site.record_status, Site.region_hid)
    ):
        nodes[hid] = Node(level=geography.SITE, hid=hid, name=name, code=code, record_status=status)
        above[hid] = region_hid
    for hid, name, code, kind, status, parent, site_hid in db.execute(
        select(
            Location.hid,
            Location.name,
            Location.code,
            Location.kind,
            Location.record_status,
            Location.parent_location_hid,
            Location.site_hid,
        )
    ):
        nodes[hid] = Node(
            level=geography.LOCATION,
            hid=hid,
            name=name,
            code=code,
            kind=kind,
            record_status=status,
        )
        above[hid] = parent or site_hid

    def in_view(node: Node) -> bool:
        if node.record_status == "draft":
            return include_drafts
        return node.record_status != "retired" or include_archived

    def reckon(asked_for: str | None) -> dict[str, bool]:
        """Return, for each place, whether it is shown: in the view, with everything
        above it. A place that is asked for by name is shown whatever the view says."""
        shown: dict[str, bool] = {}
        for hid in nodes:
            line: list[str] = []
            at: str | None = hid
            while at is not None and at not in shown and at not in line:
                line.append(at)
                at = above.get(at)
            for one in reversed(line):
                parent = above.get(one)
                shown[one] = one == asked_for or (
                    one in nodes
                    and in_view(nodes[one])
                    and (parent is None or shown.get(parent, False))
                )
        return shown

    # What the view shows, by which `hidden` is counted, whatever place is asked for;
    # and what the tree shows, in which the place that was asked for always is.
    in_the_view = reckon(None)
    in_the_tree = reckon(start.hid) if start is not None else in_the_view

    def visible(hid: str) -> bool:
        return in_the_tree.get(hid, False)

    totals, unplaced, hidden = Count(), Count(), Count()
    counted = reports.by_location(
        db, filter_=filter_, include_archived=include_archived, include_drafts=include_drafts
    )
    for hid, (items, components) in counted.items():
        totals.add(items, components)
        if hid is None:
            unplaced.add(items, components)
            continue
        if not in_the_view.get(hid, False):
            hidden.add(items, components)
        if visible(hid):
            at: str | None = hid
            seen: set[str] = set()
            while at is not None and at in nodes and at not in seen:
                seen.add(at)
                nodes[at].add(items, components)
                at = above.get(at)

    going = reports.by_planned_location(
        db, filter_=filter_, include_archived=include_archived, include_drafts=include_drafts
    )
    for hid, count in going.items():
        at = hid
        seen = set()
        while at is not None and at in nodes and at not in seen:
            seen.add(at)
            nodes[at].planned += count
            at = above.get(at)

    going_to = fields.GROUP_PLANNED_IN_FORCE
    groups_view = [going_to.is_not(None)]
    if not include_drafts:
        groups_view.append(DeviceGroup.record_status != "draft")
    if not include_archived:
        groups_view.append(DeviceGroup.record_status != "retired")
    groups_going = db.execute(select(going_to, func.count()).where(*groups_view).group_by(going_to))
    for hid, count in groups_going:
        at = hid
        seen = set()
        while at is not None and at in nodes and at not in seen:
            seen.add(at)
            nodes[at].planned_groups += count
            at = above.get(at)

    order = {geography.REGION: 0, geography.SITE: 1, geography.LOCATION: 2}
    tops: list[Node] = []
    for hid, node in nodes.items():
        if not visible(hid) or (node.level == geography.LOCATION and not locations):
            continue
        parent = above.get(hid)
        if parent is None:
            tops.append(node)
        elif parent in nodes:
            nodes[parent].children.append(node)

    def in_order(found: list[Node]) -> list[Node]:
        return sorted(found, key=lambda node: (order[node.level], records.key(node.name), node.hid))

    def finish(node: Node, parent_path: str, seen: frozenset[str]) -> None:
        node.path = f"{parent_path}{geography.JOINED}{node.name}" if parent_path else node.name
        node.children = in_order(node.children)
        for child in node.children:
            if child.hid not in seen:
                finish(child, node.path, seen | {child.hid})

    if start is None:
        roots = in_order(tops)
        for top in roots:
            finish(top, "", frozenset({top.hid}))
    else:
        top = nodes[start.hid]
        atlas = geography.Atlas(db)
        whole = atlas.path(start)
        outer = whole[: -len(top.name)].removesuffix(geography.JOINED)
        finish(top, outer, frozenset({top.hid}))
        roots = [top]
    return Tree(totals=totals, unplaced=unplaced, hidden=hidden, roots=roots)
