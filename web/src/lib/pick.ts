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

// 0.9.6: a catalog entry is chosen by searching for it (P-200). An inventory may hold
// hundreds of models, so they are never listed whole in a form.

/** What a search needs to know of a catalog entry to offer it. */
export interface PickableEntry {
  hid: string;
  pid: string;
  model_name?: string | null;
  vendor: { hid: string; name: string };
  record_status?: string;
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
