// Sorting a table that holds all of its rows, in the browser, by its headers. A click on
// a header sorts by that column, and another turns the order round. Text sorts without
// regard to case, numbers as numbers, dates as dates, and blanks last whichever way the
// order runs. A grid that the server pages is not sorted here: the server sorts it, over
// the whole list.

/** What a column is sorted by, for one row: text, a number, a truth value, or nothing. */
export type SortValue = string | number | boolean | null | undefined;

/** The columns a table is sorted by: for each, what a row is sorted by in it. */
export type SortColumns<T> = Readonly<Record<string, (row: T) => SortValue>>;

/** The column a table is sorted by and which way. Null is the order the rows came in. */
export interface SortState {
  column: string;
  descending: boolean;
}

/** What `aria-sort` says on the header of a column. */
export type AriaSort = "ascending" | "descending" | "none";

const TEXT = new Intl.Collator("en", { sensitivity: "base", numeric: true });

/** True for what sorts last, whichever way the order runs: nothing, and blank text. */
export function isBlank(value: SortValue): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "number") return Number.isNaN(value);
  return typeof value === "string" && value.trim() === "";
}

/**
 * A date or a time as the server writes it, as a number to sort by: a date is sorted as
 * a date, also beside a time of the same day. Nothing, and what is no date, is blank.
 */
export function dateValue(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}

/** A decimal as the server writes it, such as a support weight, as a number to sort by. */
export function decimalValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isNaN(number) ? null : number;
}

function rank(value: SortValue): number | string {
  if (typeof value === "boolean") return value ? 1 : 0;
  return value as number | string;
}

/**
 * Compare two values that are not blank, in ascending order: numbers as numbers, text
 * without regard to case and with the digits in it read as numbers, so that Site-2
 * comes before Site-10. A number comes before text.
 */
export function compareValues(one: SortValue, other: SortValue): number {
  const first = rank(one);
  const second = rank(other);
  if (typeof first === "number" && typeof second === "number") return first - second;
  if (typeof first === "number") return -1;
  if (typeof second === "number") return 1;
  return TEXT.compare(first, second);
}

/**
 * The rows in the order of the state: by that column, turned round when it says so,
 * blanks last either way. Rows that are equal keep the order they came in, and so does
 * every row when there is no state, or no such column.
 */
export function sortRows<T>(
  rows: readonly T[],
  columns: SortColumns<T>,
  state: SortState | null,
): T[] {
  const value = state ? columns[state.column] : undefined;
  if (!state || !value) return [...rows];
  const turn = state.descending ? -1 : 1;
  return rows
    .map((row, place) => ({ row, place, by: value(row) }))
    .sort((one, other) => {
      const blank = Number(isBlank(one.by)) - Number(isBlank(other.by));
      if (blank !== 0) return blank;
      if (isBlank(one.by)) return one.place - other.place;
      return turn * compareValues(one.by, other.by) || one.place - other.place;
    })
    .map((entry) => entry.row);
}

/**
 * The state after a click on the header of a column: sorted by it, ascending, and turned
 * round by a click on the column the table is sorted by already.
 */
export function nextSort(state: SortState | null, column: string): SortState {
  if (state?.column === column) return { column, descending: !state.descending };
  return { column, descending: false };
}

/** What the header of a column says of the order: which way, or that it is not by it. */
export function ariaSort(state: SortState | null, column: string): AriaSort {
  if (state?.column !== column) return "none";
  return state.descending ? "descending" : "ascending";
}

/** The mark beside the header the table is sorted by: which way the order runs. */
export function sortMark(state: SortState | null, column: string): string {
  if (state?.column !== column) return "";
  return state.descending ? "▼" : "▲";
}
