// The rank and the bars of a table of a report (P-178, P-180). Every table of the
// summary, the management report and the scoreboard has a rank, from 1 for the most, by
// the column it is sorted by, two rows of one count sharing a rank and the blank row
// ranked with none; and beside each count a bar, as long as the count is to the largest
// of its column. The table holds all of its rows, so both are worked out here, from
// what the server counted: nothing is counted again.
//
// A table may be sorted by a column that is no count, its name or the operators involved,
// or come in the order the server sent it. The rank is then by the column of counts the
// table names for it: the support weight on the scoreboard, which is how it is ordered
// at first, and the first count of every other table.

import type { SortState } from "./sort";

/** A column of counts: what a row holds in it, and what the column is called after "by". */
export interface CountColumn<T> {
  /** What a row holds, as a number to rank by and to draw: null where it holds nothing. */
  value: (row: T) => number | null;
  /** What is written for it: `1,250`, `12.50`. */
  text: (row: T) => string;
  /** What the column is called in "ranked by …": `items`, `support weight`. */
  label: string;
}

/** The columns of counts of a table, by the names its sorting has for them. */
export type CountColumns<T> = Readonly<Record<string, CountColumn<T>>>;

export interface RankOptions<T> {
  /** The column the rank is by when the table is sorted by none of its counts. */
  fallback: string;
  /** True for the blank row, of what has none of what the table is by: it has no rank. */
  blank: (row: T) => boolean;
}

export interface Ranking<T> {
  /** The column the rank is by. */
  column: string;
  /** What that column is called in "ranked by …". */
  label: string;
  /** The rank of a row, from 1 for the most; null for the blank row, and for a row with nothing. */
  rank: (row: T) => number | null;
  /** How long a row's bar is in a column, from 0 to 1 of the largest of that column. */
  share: (column: string, row: T) => number;
  /** What a row has written in a column. */
  text: (column: string, row: T) => string;
  /** How many characters the longest text of a column has, so that its bars line up. */
  figure: (column: string) => number;
}

/** The column the rank is by: that of the sorting where it is a count, else the fallback. */
export function rankColumn(
  state: SortState | null,
  counts: Readonly<Record<string, unknown>>,
  fallback: string,
): string {
  return state && Object.hasOwn(counts, state.column) ? state.column : fallback;
}

/**
 * The rank of each row by a value, from 1 for the most. Two of one value share a rank,
 * and the next after them is ranked as if they had not: 1, 2, 2, 4. The blank row and a
 * row with no value are left out: they have no rank, and take no place from the others.
 */
export function ranks<T>(
  rows: readonly T[],
  value: (row: T) => number | null,
  blank: (row: T) => boolean,
): Map<T, number> {
  const ranked = rows
    .filter((row) => !blank(row))
    .map((row) => ({ row, value: value(row) }))
    .filter((one): one is { row: T; value: number } => isCount(one.value));
  const values = ranked.map((one) => one.value).sort((one, other) => other - one);
  const out = new Map<T, number>();
  for (const one of ranked) out.set(one.row, values.indexOf(one.value) + 1);
  return out;
}

/** How long a bar is, from 0 to 1: a count beside the largest of its column. */
export function barShare(value: number | null, largest: number): number {
  if (!isCount(value) || largest <= 0 || value <= 0) return 0;
  return Math.min(1, value / largest);
}

/** The largest value of a column, or 0 where nothing in it is above 0. */
export function largestOf<T>(rows: readonly T[], value: (row: T) => number | null): number {
  return rows.reduce((most, row) => {
    const one = value(row);
    return isCount(one) && one > most ? one : most;
  }, 0);
}

/** The rank and the bars of a table, sorted as `state` says. */
export function ranking<T>(
  rows: readonly T[],
  state: SortState | null,
  counts: CountColumns<T>,
  { fallback, blank }: RankOptions<T>,
): Ranking<T> {
  const column = rankColumn(state, counts, fallback);
  const by = counts[column];
  const ranked = by ? ranks(rows, by.value, blank) : new Map<T, number>();
  const largest = new Map<string, number>();
  const widest = new Map<string, number>();
  for (const [name, count] of Object.entries(counts)) {
    largest.set(name, largestOf(rows, count.value));
    widest.set(
      name,
      rows.reduce((most, row) => Math.max(most, count.text(row).length), 0),
    );
  }
  return {
    column,
    label: by?.label ?? "",
    rank: (row) => ranked.get(row) ?? null,
    share: (name, row) => {
      const count = counts[name];
      return count ? barShare(count.value(row), largest.get(name) ?? 0) : 0;
    },
    text: (name, row) => counts[name]?.text(row) ?? "",
    figure: (name) => widest.get(name) ?? 0,
  };
}

function isCount(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
