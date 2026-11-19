// What an operator is on, as the server answers it from `GET /operators/{hid}/assignments`
// (P-177): the places and the groups given it as their own, each with the items that have
// it from there, what beneath has it too and what beneath is someone else's, and the items
// given it and those that have it from the item they are in. Every count comes with the
// filter of the item list that lists exactly those items. This turns the answer into the
// boxes of the tree on the operator's page; nothing is counted here.

import type { Schemas } from "../api/client";
import type { TreeColumn, TreeCount, TreeNode } from "../components/BoxTree";
import { itemsViewPath } from "./filter";
import { groupTypeLabel } from "./groups";
import { levelLabel, placePath } from "./places";

export type Assignments = Schemas["OperatorAssignments"];
export type ItemCount = Schemas["ItemCount"];

/** A count of items, with its words for one and for many, as a link to those items. */
export function itemCount(
  key: string,
  count: ItemCount,
  one: string,
  many: string,
  view: { includeDrafts?: boolean; includeArchived?: boolean } = {},
): TreeCount {
  return {
    key,
    value: count.count,
    label: count.count === 1 ? one : many,
    href: itemsViewPath({
      filter: count.filter,
      ...(view.includeDrafts ? { include_drafts: true } : {}),
      ...(view.includeArchived ? { include_archived: true } : {}),
    }),
  };
}

/** A count that is no link: how many places or groups beneath have it too. */
function plainCount(key: string, value: number, one: string, many: string): TreeCount {
  return { key, value, label: value === 1 ? one : many, href: null };
}

/**
 * A path beneath another as the box beneath it shows it: what follows the path above,
 * `Building 1 > Room 102` beneath `Americas > Site-2`. A path that does not begin with it
 * is shown whole.
 */
export function pathBeneath(path: string, above: string): string {
  for (const separator of [" > ", " › ", " / "]) {
    const start = `${above}${separator}`;
    if (path.startsWith(start) && path.length > start.length) return path.slice(start.length);
  }
  return path;
}

type View = { includeDrafts?: boolean; includeArchived?: boolean };

/** The boxes of the places given the operator, each with the places beneath that have it. */
export function placeNodes(assignments: Assignments, view: View = {}): TreeNode[] {
  return assignments.places.map((place) => ({
    key: place.hid,
    kind: levelLabel(place.level).toLowerCase(),
    title: place.path,
    href: placePath(place.level, place.hid),
    counts: [
      itemCount("items", place.items, "item has it from here", "items have it from here", view),
      plainCount(
        "places_beneath",
        place.places_beneath.count,
        "place beneath has it",
        "places beneath have it",
      ),
    ],
    exceptions: itemCount(
      "exceptions",
      place.exceptions,
      "item beneath has another operator",
      "items beneath have another operator",
      view,
    ),
    beneath: place.places_beneath.shown.map((below) => ({
      key: below.hid,
      kind: levelLabel(below.level).toLowerCase(),
      title: pathBeneath(below.path, place.path),
      href: placePath(below.level, below.hid),
      counts: [],
    })),
    more:
      place.places_beneath.more > 0
        ? {
            count: place.places_beneath.more,
            noun: "places, under Geography",
            href: placePath(place.level, place.hid),
          }
        : null,
  }));
}

/** The boxes of the groups given the operator, each with the groups nested in it that have it. */
export function groupNodes(assignments: Assignments, view: View = {}): TreeNode[] {
  return assignments.groups.map((group) => ({
    key: group.hid,
    kind: groupTypeLabel(group.type).toLowerCase(),
    title: group.name,
    href: `/groups/${encodeURIComponent(group.hid)}`,
    counts: [
      itemCount("items", group.items, "item has it from it", "items have it from it", view),
      plainCount(
        "groups_beneath",
        group.groups_beneath.count,
        "nested group has it",
        "nested groups have it",
      ),
    ],
    exceptions: itemCount(
      "exceptions",
      group.exceptions,
      "item under it has another operator",
      "items under it have another operator",
      view,
    ),
    beneath: group.groups_beneath.shown.map((below) => ({
      key: below.hid,
      kind: groupTypeLabel(below.type).toLowerCase(),
      title: below.name,
      href: `/groups/${encodeURIComponent(below.hid)}`,
      counts: [],
    })),
    more:
      group.groups_beneath.more > 0
        ? {
            count: group.groups_beneath.more,
            noun: "groups, on the group's page",
            href: `/groups/${encodeURIComponent(group.hid)}`,
          }
        : null,
  }));
}

/** The boxes of the items given it as their own, and of the items that have it from an item above them. */
export function ownNodes(assignments: Assignments, view: View = {}): TreeNode[] {
  return [
    {
      key: "own",
      title: "Given it as their own",
      counts: [itemCount("own", assignments.own, "item", "items", view)],
    },
    {
      key: "from_item",
      // 0.9.8: and what runs on an item, from the item it runs on (P-246).
      title: "From the item they are installed in or run on",
      counts: [itemCount("from_item", assignments.from_item, "item", "items", view)],
    },
  ];
}

/** The columns of the tree beneath the operator: its places, its groups and its own items. */
export function assignmentColumns(assignments: Assignments, view: View = {}): TreeColumn[] {
  return [
    {
      key: "places",
      heading: "Places given it",
      nodes: placeNodes(assignments, view),
      empty: "No place is given it as its own.",
    },
    {
      key: "groups",
      heading: "Groups given it",
      nodes: groupNodes(assignments, view),
      empty: "No group is given it as its own.",
    },
    {
      key: "own",
      heading: "Items given it",
      nodes: ownNodes(assignments, view),
      empty: "No item is given it as its own.",
    },
  ];
}

/** The count at the top of the tree: every item the operator is in force for. */
export function totalCount(assignments: Assignments, view: View = {}): TreeCount {
  return itemCount("totals", assignments.totals, "item in force", "items in force", view);
}
