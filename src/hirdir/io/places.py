"""The geography as one tree, with what is at or beneath each place.

The counts are those of a view of the items, the one the item list shows for the same
filter, taken at each location by the database and added up here: an item is in one
place, so the count of a region is the sum of what is in it.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Location, Region, Site
from hirdir.domain import geography, records
from hirdir.domain.errors import Invalid
from hirdir.io import reports


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
    names one place to start from, and without `locations` the tree stops at the sites.
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
    for region in db.scalars(select(Region)):
        nodes[region.hid] = Node(
            level=geography.REGION,
            hid=region.hid,
            name=region.name,
            code=region.code,
            record_status=region.record_status,
        )
        above[region.hid] = region.parent_region_hid
    for site in db.scalars(select(Site)):
        nodes[site.hid] = Node(
            level=geography.SITE,
            hid=site.hid,
            name=site.name,
            code=site.code,
            record_status=site.record_status,
        )
        above[site.hid] = site.region_hid
    for location in db.scalars(select(Location)):
        nodes[location.hid] = Node(
            level=geography.LOCATION,
            hid=location.hid,
            name=location.name,
            code=location.code,
            kind=location.kind,
            record_status=location.record_status,
        )
        above[location.hid] = location.parent_location_hid or location.site_hid

    def in_view(node: Node) -> bool:
        if node.record_status == "draft":
            return include_drafts
        return node.record_status != "retired" or include_archived

    shown: dict[str, bool] = {}

    def visible(hid: str) -> bool:
        """Say whether a place is in the tree: in the view, with everything above it.

        The place the tree starts from is always shown: it was asked for by name.
        """
        line: list[str] = []
        at: str | None = hid
        while at is not None and at not in shown and at not in line:
            line.append(at)
            if start is not None and at == start.hid:
                shown[at] = True
                break
            at = above.get(at)
        for one in reversed(line):
            if one not in shown:
                parent = above.get(one)
                shown[one] = (
                    one in nodes
                    and in_view(nodes[one])
                    and (parent is None or shown.get(parent, False))
                )
        return shown[hid]

    totals, unplaced, hidden = Count(), Count(), Count()
    counted = reports.by_location(
        db, filter_=filter_, include_archived=include_archived, include_drafts=include_drafts
    )
    for hid, (items, components) in counted.items():
        totals.add(items, components)
        if hid is None:
            unplaced.add(items, components)
        elif hid not in nodes or not visible(hid):
            hidden.add(items, components)
        else:
            at: str | None = hid
            seen: set[str] = set()
            while at is not None and at in nodes and at not in seen:
                seen.add(at)
                nodes[at].add(items, components)
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
