// Places: regions, the sites in them and the locations within a site, as words and as
// rows of a page. The server works out every path, every count and what a place has in
// force; nothing of that is worked out again here. This only lays the answers out.

import type { Schemas } from "../api/client";
import { all, any, type FilterNode, itemsPath } from "./filter";
import type { Option } from "./patch";

export type Region = Schemas["RegionOut"];
export type Site = Schemas["SiteOut"];
export type Location = Schemas["LocationOut"];
export type Place = Region | Site | Location;
export type TreeNode = Schemas["GeographyNode"];
export type Tree = Schemas["GeographyTree"];
export type PlaceCount = Schemas["PlaceCount"];
export type PlaceEffective = Schemas["PlaceEffective"];
export type RoleContacts = Schemas["RoleContacts"];
export type Assignment = Schemas["AssignmentOut"];
export type ShipAddress = Schemas["ShipAddress"];
type Choice = Schemas["ChoiceOut"];

export const LEVELS = ["region", "site", "location"] as const;
export type Level = (typeof LEVELS)[number];

/** What separates the names of a path. No name holds it. */
export const PATH_SEPARATOR = " > ";

/** The list of choices a contact's role is taken from, and the one a location's kind is. */
export const CONTACT_ROLE_LIST = "contact_role";
export const LOCATION_KIND_LIST = "location_kind";

const LABELS: Readonly<Record<Level, string>> = {
  region: "Region",
  site: "Site",
  location: "Location",
};

export function isLevel(value: string | undefined): value is Level {
  return (LEVELS as readonly string[]).includes(value ?? "");
}

export function levelLabel(level: string): string {
  return isLevel(level) ? LABELS[level] : level;
}

/** The field of an assignment that names its place, by the level of the place. */
export const ASSIGNED_TO: Readonly<Record<Level, "region_hid" | "site_hid" | "location_hid">> = {
  region: "region_hid",
  site: "site_hid",
  location: "location_hid",
};

/** The page of one place, as a path of the app. */
export function placePath(level: string, hid: string): string {
  return `/geography/${encodeURIComponent(level)}/${encodeURIComponent(hid)}`;
}

/** The grid of items at or beneath a place: the item list, filtered by the server. */
export function itemsWithin(hid: string): string {
  return itemsPath(`location:within:${hid}`);
}

/** The name of a place, from its path: what stands after the last separator. */
export function nameOf(path: string | null | undefined): string {
  if (!path) return "";
  return path.split(PATH_SEPARATOR).at(-1) ?? "";
}

// The longest word of a search that is sent, and how many words are.
const LONGEST = 200;
const MOST_WORDS = 8;

/**
 * The filter that finds locations by what was typed. The list of locations is filtered
 * by the name of a location, of the location it is in, of its site and of the region
 * the site is in, and by its code and its site's, so each word typed has to be in one of
 * those: `site-2 102` finds Room 102 of Site-2, and a path that is pasted, from the
 * region the site is in down, finds its location. The regions above that one are not
 * searched: the list has no filter on the whole path.
 * A `>` between words, as in a path, separates them as a space does. Blank text is no
 * search.
 */
export function locationSearch(typed: string): FilterNode | null {
  const words = typed
    .split(/[\s>]+/)
    .map((word) => word.slice(0, LONGEST))
    .filter((word) => word !== "")
    .slice(0, MOST_WORDS);
  return all(
    ...words.map((value) =>
      any(
        { field: "name", op: "contains", value },
        { field: "parent.name", op: "contains", value },
        { field: "site.name", op: "contains", value },
        { field: "code", op: "contains", value },
        { field: "site.code", op: "contains", value },
        { field: "region.name", op: "contains", value },
      ),
    ),
  );
}

/** What the reader asked the tree for: a view of the items, as the item list has it. */
export interface TreeView {
  /** The item filter, in the short form. Blank is every item. */
  filter: string;
  includeArchived: boolean;
  includeDrafts: boolean;
}

/**
 * The query of `GET /geography/tree` for a view. The regions and sites are asked for
 * with `locations` false, and the inside of one site with that site as `root`. What is
 * blank or off is left out.
 */
export function treeQuery(
  view: TreeView,
  part: { root?: string; locations?: boolean } = {},
): {
  filter?: string;
  root?: string;
  locations?: boolean;
  include_archived?: boolean;
  include_drafts?: boolean;
} {
  const filter = view.filter.trim();
  return {
    ...(filter === "" ? {} : { filter }),
    ...(part.root === undefined ? {} : { root: part.root }),
    ...(part.locations === false ? { locations: false } : {}),
    ...(view.includeArchived ? { include_archived: true } : {}),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
}

/** One row of the tree as a page shows it: a place, and how far in it stands. */
export interface TreeRow {
  node: TreeNode;
  depth: number;
  /** Whether what is in it is on show. A site is opened by the page, which fetches it. */
  open: boolean;
  /** Whether it has anything the tree was given to show beneath it. */
  hasChildren: boolean;
}

/**
 * The rows of a tree, top down, each place before what is in it. What is in a place
 * named in `closed` is left out. Sites are given with nothing in them when the tree was
 * asked for without locations: the page shows the inside of a site when it is opened.
 */
export function treeRows(
  nodes: readonly TreeNode[],
  closed: ReadonlySet<string> = new Set(),
  depth = 0,
): TreeRow[] {
  const rows: TreeRow[] = [];
  for (const node of nodes) {
    const open = !closed.has(node.hid);
    rows.push({ node, depth, open, hasChildren: node.children.length > 0 });
    if (open) rows.push(...treeRows(node.children, closed, depth + 1));
  }
  return rows;
}

/** The deepest a row is drawn indented. Beyond it rows stand at the same depth. */
export const DEEPEST_DRAWN = 16;

export function drawnDepth(depth: number): number {
  return Math.max(0, Math.min(depth, DEEPEST_DRAWN));
}

/** A row beneath the tree: items that are in none of its places, and the whole view. */
export interface CountRow {
  key: "unplaced" | "hidden" | "totals";
  label: string;
  count: PlaceCount;
}

/**
 * The rows that make the numbers add up: the items that are nowhere, the items in
 * places the view leaves out when there are any, and the whole view. The roots of the
 * tree and the first two come to the last.
 */
export function countRows(tree: Pick<Tree, "unplaced" | "hidden" | "totals">): CountRow[] {
  const rows: CountRow[] = [
    { key: "unplaced", label: "Nowhere: items with no location", count: tree.unplaced },
  ];
  if (tree.hidden.items > 0 || tree.hidden.component_count > 0) {
    rows.push({
      key: "hidden",
      label: "In places this view leaves out",
      count: tree.hidden,
    });
  }
  rows.push({ key: "totals", label: "All items in view", count: tree.totals });
  return rows;
}

type PlaceSource = RoleContacts["source"];

/** True for what a place has from a level above it, and not of its own. */
export function fromAbove(source: PlaceSource): boolean {
  return source !== "own" && source !== "none";
}

/**
 * What to say of a role nobody is in. A level that said "none here, and do not look
 * further up" is named: the place itself, or the one above it that said so.
 */
export function noContactText(
  role: Pick<RoleContacts, "source" | "source_path" | "stopped">,
): string {
  if (!role.stopped) return "Nobody";
  if (role.source === "own") return "None here, and nothing further up is looked at";
  const where = role.source_path ? ` ${role.source_path}` : "";
  return `None: the ${role.source}${where} says so, and nothing further up is looked at`;
}

/** An address as lines to read: the street, then the city with its state and code, then the country. */
export function addressLines(address: Partial<ShipAddress> | null | undefined): string[] {
  if (!address) return [];
  const city = [address.city, address.state].filter(Boolean).join(", ");
  return [
    address.address1,
    address.address2,
    [city, address.postal_code].filter(Boolean).join(" "),
    address.country,
  ].filter((line): line is string => Boolean(line));
}

const ADDRESS_FIELDS = ["address1", "address2", "city", "state", "postal_code", "country"] as const;

/** The street address of a site or a location, or its shipping address, as an address. */
export function addressOf(
  place: Readonly<Record<string, unknown>>,
  prefix: "" | "ship_" = "",
): ShipAddress {
  const read = (field: (typeof ADDRESS_FIELDS)[number]): string | null => {
    const value = place[`${prefix}${field}`];
    return typeof value === "string" && value !== "" ? value : null;
  };
  return {
    address1: read("address1"),
    address2: read("address2"),
    city: read("city"),
    state: read("state"),
    postal_code: read("postal_code"),
    country: read("country"),
  };
}

/** What one place itself says of one role: the contacts it assigns, or that it has none. */
export interface OwnRole {
  role: string;
  label: string;
  /** Its assignments with a contact, by priority. */
  assigned: Assignment[];
  /** The assignment that says "none here, and do not look further up", if there is one. */
  stop: Assignment | null;
}

/**
 * The assignments of one place, by role, in the order of the list of roles. Every active
 * role is there, also with nothing assigned, and so is a role that is no longer active
 * while something is still assigned in it.
 */
export function ownRoles(
  assignments: readonly Assignment[],
  choices: readonly Choice[] | undefined,
): OwnRole[] {
  const roles = new Map<string, OwnRole>();
  for (const choice of choices ?? []) {
    if (choice.list !== CONTACT_ROLE_LIST || !choice.active) continue;
    roles.set(choice.value, { role: choice.value, label: choice.label, assigned: [], stop: null });
  }
  for (const assignment of assignments) {
    let entry = roles.get(assignment.role);
    if (!entry) {
      const known = (choices ?? []).find(
        (choice) => choice.list === CONTACT_ROLE_LIST && choice.value === assignment.role,
      );
      entry = {
        role: assignment.role,
        label: known?.label ?? assignment.role,
        assigned: [],
        stop: null,
      };
      roles.set(assignment.role, entry);
    }
    if (assignment.stop_inheritance && assignment.contact === null) entry.stop = assignment;
    else entry.assigned.push(assignment);
  }
  for (const entry of roles.values()) {
    entry.assigned.sort(
      (one, other) =>
        one.priority - other.priority ||
        (one.contact?.name ?? "").localeCompare(other.contact?.name ?? ""),
    );
  }
  return [...roles.values()];
}

/**
 * The regions a region may be moved into: every one but itself and the ones within it.
 * The server refuses a region beneath itself all the same.
 */
export function regionsToMoveTo(
  regions: ReadonlyArray<Pick<Region, "hid" | "path">>,
  moving: Pick<Region, "hid" | "path">,
): Option[] {
  return regions
    .filter(
      (region) =>
        region.hid !== moving.hid && !region.path.startsWith(moving.path + PATH_SEPARATOR),
    )
    .map((region) => ({ value: region.hid, label: region.path }));
}

/**
 * The locations of a site that a location may be moved into: every one but itself and
 * the ones within it.
 */
export function locationsToMoveTo(
  locations: ReadonlyArray<Pick<Location, "hid" | "path">>,
  moving: Pick<Location, "hid" | "path">,
): Option[] {
  return locations
    .filter(
      (location) =>
        location.hid !== moving.hid && !location.path.startsWith(moving.path + PATH_SEPARATOR),
    )
    .map((location) => ({ value: location.hid, label: location.path }));
}

/** A contact as one line: the name, then the organization, the address and the number. */
export function contactLine(contact: {
  name: string;
  organization?: string | null;
  email?: string | null;
  phone?: string | null;
}): string {
  return [contact.name, contact.organization, contact.email, contact.phone]
    .filter(Boolean)
    .join(" · ");
}
