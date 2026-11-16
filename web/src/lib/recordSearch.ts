// Finding the records a reference may be put on: catalog entries, regions, sites,
// locations, circuits and items (P-158). What is typed is sent to the list of each kind
// as a filter, and what they answer is offered together, a few of each kind in turn, so
// that one kind with many matches does not hide the others.

import { all, any, type FilterNode } from "./filter";
import type { RecordKind } from "./references";

// The longest text sent as a value of a filter, and the most words a search is made of.
const LONGEST = 200;
const MOST_WORDS = 8;

/** The words of what was typed: a path's separators are no words. */
function wordsOf(typed: string): string[] {
  return typed
    .split(/[\s>]+/)
    .map((word) => word.slice(0, LONGEST))
    .filter((word) => word !== "")
    .slice(0, MOST_WORDS);
}

/** Each word in one of the fields. Blank text is no search. */
function eachWordIn(typed: string, fields: readonly string[]): FilterNode | null {
  return all(
    ...wordsOf(typed).map((value) =>
      any(...fields.map((field) => ({ field, op: "contains" as const, value }))),
    ),
  );
}

/** A catalog entry by its vendor, its PID or its model name: "Cisco C9300". */
export function entrySearch(typed: string): FilterNode | null {
  return eachWordIn(typed, ["vendor", "pid", "model_name"]);
}

/** A region by its name or code, or by the name of the region it is in. */
export function regionSearch(typed: string): FilterNode | null {
  return eachWordIn(typed, ["name", "code", "parent.name"]);
}

/** A site by its name or code, or by the name of its region. */
export function siteSearch(typed: string): FilterNode | null {
  return eachWordIn(typed, ["name", "code", "region.name"]);
}

/** What one kind of record offers. */
export interface Found<T> {
  kind: RecordKind;
  offers: T[];
  total: number;
}

/**
 * The offers of every kind, taken one of each kind in turn in the order the kinds are
 * given, up to `limit`, and how many there are in all.
 */
export function interleaved<T>(
  found: readonly Found<T>[],
  limit: number,
): { offers: T[]; total: number } {
  const offers: T[] = [];
  const longest = Math.max(0, ...found.map((one) => one.offers.length));
  for (let place = 0; place < longest && offers.length < limit; place += 1) {
    for (const one of found) {
      const offer = one.offers[place];
      if (offer !== undefined && offers.length < limit) offers.push(offer);
    }
  }
  return { offers, total: found.reduce((sum, one) => sum + one.total, 0) };
}

const KIND_LABELS: Readonly<Record<RecordKind, string>> = {
  catalog_entry: "catalog entry",
  region: "region",
  site: "site",
  location: "location",
  circuit: "circuit",
  item: "item",
};

/** What is said beside an offer: its kind, and that it is a draft. */
export function offerNote(kind: RecordKind, status: string | null | undefined): string {
  return [KIND_LABELS[kind], status === "draft" ? "draft" : ""].filter(Boolean).join(", ");
}
