// Finding an item to point at: the item a minor item is in, a member for a group, the
// item that takes another's place. An inventory may hold tens of thousands of items, so
// they are never listed whole: what is typed is sent to the server as a filter of the
// item list, and the first few that match are offered.

import { all, any, type FilterNode } from "./filter";
import { itemName } from "./format";

// How many items a search offers.
export const PICK_LIMIT = 8;
// The longest text sent as a value of the filter.
const LONGEST = 200;

/** What a search needs to know of an item to offer it. */
export interface Pickable {
  hid: string;
  name?: string | null;
  hostname?: string | null;
  serial_number?: string | null;
  asset_tag?: string | null;
  /** The PID, on an item as another record names it. */
  pid?: string | null;
  catalog?: { pid: string } | null;
}

/**
 * The filter that finds items by what was typed: a part of the name (or of the hostname
 * that stands in for a blank name), of the serial number or of the asset tag. Blank
 * text is no search. `only` narrows it, as to major items for the members of a stack.
 */
export function itemSearch(typed: string, only: FilterNode | null = null): FilterNode | null {
  const value = typed.trim().slice(0, LONGEST);
  if (value === "") return null;
  return all(
    any(
      { field: "name", op: "contains", value },
      { field: "hostname", op: "contains", value },
      { field: "serial_number", op: "contains", value },
      { field: "asset_tag", op: "contains", value },
    ),
    only,
  );
}

/** Major items only: the members of a stack and of a cluster are major items. */
export const MAJOR_ONLY: FilterNode = { field: "is_major", op: "eq", value: true };

/** An item as a search offers it: its name, then its PID and serial number when it has them. */
export function pickLabel(item: Pickable): string {
  const name = itemName(item);
  const pid = item.catalog?.pid ?? item.pid ?? "";
  // An item with no name is called by its serial number already: it is not said twice.
  const serial = item.serial_number && item.serial_number !== name ? item.serial_number : "";
  return [name, pid, serial].filter(Boolean).join(" · ");
}

/** The items a search found, without those that may not be chosen again. */
export function offered<T extends Pickable>(found: readonly T[], taken: readonly string[]): T[] {
  return found.filter((item) => !taken.includes(item.hid));
}

// 0.9.6: the picker of members says where each candidate stands, and offers the spares
// first (P-221).

/** The spares: the items whose disposition in force is Spare, offered first to a group. */
export const SPARES: FilterNode = { field: "effective.disposition", op: "eq", value: "Spare" };

/**
 * The items of two searches as one list, those of the first first: the spares, then the
 * rest of every item that matches, each once, at most `limit`.
 */
export function firstThen<T extends { hid: string }>(
  first: readonly T[],
  every: readonly T[],
  limit: number,
): T[] {
  const seen = new Set(first.map((item) => item.hid));
  return [...first, ...every.filter((item) => !seen.has(item.hid))].slice(0, limit);
}

/** What the picker of members needs to know of an item to say where it stands. */
export interface Standing {
  lifecycle_state?: string | null;
  effective?: {
    disposition?: { value?: unknown } | null;
    location_hid?: { label?: string | null } | null;
  } | null;
  groups?: ReadonlyArray<{ name: string; type: string; position: number | null }>;
}

/** What an offer says of an item beside it, and why it may not be chosen, blank if it may. */
export interface OfferFacts {
  facts: string;
  refused: string;
}

// The types of group an item is a current member of one at most, and their names.
const ONE_AT_A_TIME: Readonly<Record<string, string>> = { stack: "stack", cluster: "cluster" };
// The states an item in which joins no group: it has left the inventory, or is leaving it.
const JOINS_NONE: readonly string[] = ["Released", "Archived"];

/** Where a place is, by its path without the region: "Campus 07 > IDF 03". */
export function placeText(path: string | null | undefined): string {
  if (!path) return "";
  const parts = path.split(" > ");
  return parts.length > 1 ? parts.slice(1).join(" > ") : path;
}

/** A membership as a candidate's offer says it: "member 2 of the stack cw07-idf03-acc1". */
function memberOf(group: { name: string; type: string; position: number | null }): string {
  const kind = ONE_AT_A_TIME[group.type] ?? "group";
  const number = group.position === null ? "member" : `member ${group.position}`;
  return `${number} of the ${kind} ${group.name}`;
}

/**
 * Where a candidate for a group stands: its state and disposition, where it is, and the
 * stack or cluster it is in with its position. An item that is in a group of the type of
 * one at a time already, or in a state that joins no group, is refused by the server: it
 * is shown, and says why it cannot be chosen.
 */
export function memberOffer(item: Standing, type: string): OfferFacts {
  const disposition = item.effective?.disposition?.value;
  const place = placeText(item.effective?.location_hid?.label);
  const memberships = (item.groups ?? []).filter((group) => group.type in ONE_AT_A_TIME);
  const facts = [
    item.lifecycle_state ?? "",
    typeof disposition === "string" ? disposition : "",
    place === "" ? "no location" : place,
    ...memberships.map(memberOf),
  ]
    .filter(Boolean)
    .join(" · ");
  const state = item.lifecycle_state ?? "";
  const kind = ONE_AT_A_TIME[type];
  const holding = kind ? memberships.find((group) => group.type === type) : undefined;
  let refused = "";
  if (JOINS_NONE.includes(state)) {
    refused = `An item in ${state} joins no group.`;
  } else if (kind && holding) {
    refused = `It is in the ${kind} ${holding.name} already: an item is in one ${kind} at a time. End that membership first.`;
  }
  return { facts, refused };
}

// 0.9.6: a catalog entry is chosen by searching for it (P-200). An inventory may hold
// hundreds of models, so they are never listed whole in a form.

/** What a search needs to know of a catalog entry to offer it. */
export interface PickableEntry {
  hid: string;
  pid: string;
  model_name?: string | null;
  vendor: { hid: string; name: string };
  record_status?: string;
  /** 0.9.8: its kind, which says whether an item of it runs on a host (P-246). */
  kind?: string;
}

// The most words of what was typed that are looked for.
const MOST_WORDS = 6;

/**
 * The filter that finds catalog entries by what was typed: each word is looked for in the
 * PID, the model name and the vendor's name, and every word must be found in one of them.
 * Blank text is no search.
 */
export function entrySearch(typed: string): FilterNode | null {
  const words = typed.trim().slice(0, LONGEST).split(/\s+/).filter(Boolean).slice(0, MOST_WORDS);
  if (words.length === 0) return null;
  return all(
    ...words.map((value) =>
      any(
        { field: "pid", op: "contains", value },
        { field: "model_name", op: "contains", value },
        { field: "vendor", op: "contains", value },
      ),
    ),
  );
}

/** A catalog entry as a search offers it: its PID with its vendor beside it, then its model. */
export function entryLabel(entry: {
  pid: string;
  model_name?: string | null;
  vendor: string | { name: string };
}): string {
  const vendor = typeof entry.vendor === "string" ? entry.vendor : entry.vendor.name;
  return [entry.pid, vendor, entry.model_name ?? ""].filter(Boolean).join(" · ");
}

// The catalog entries a search has offered in this page, by HID: a form that names an
// entry by its vendor and PID, as a bulk edit does, finds the one chosen here.
const seen = new Map<string, PickableEntry>();

/** Note the catalog entries a search offered, or one that was read or made. */
export function sawEntries(entries: readonly PickableEntry[]): void {
  for (const entry of entries) seen.set(entry.hid, entry);
}

/** A catalog entry a search has offered, by its HID. */
export function entrySeen(hid: string): PickableEntry | undefined {
  return seen.get(hid);
}
