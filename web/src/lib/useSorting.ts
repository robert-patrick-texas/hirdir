import { useState } from "react";
import { nextSort, type SortColumns, type SortState, sortRows } from "./sort";

/** What a header needs of the sorting of its table. */
export interface SortControl {
  /** The column the table is sorted by and which way: null for the order it came in. */
  state: SortState | null;
  /** Sort by a column, or turn the order round when the table is sorted by it already. */
  by: (column: string) => void;
  /** False for a table that does not hold all of its rows: its headers do not sort. */
  enabled: boolean;
}

/** The sorting of one table: its rows in order, and what its headers need. */
export interface Sorting<T> extends SortControl {
  rows: T[];
  /** Back to the order the rows came in. */
  reset: () => void;
}

interface Options<T> {
  /** The order at first: left out, the rows are in the order they came in. */
  initial?: SortState;
  /**
   * Whether the table holds all of its rows. A table that shows one page of more is not
   * sorted in the browser: that would sort the page on show alone.
   */
  enabled?: boolean;
  /**
   * The rows kept last in every order, as the blank row of the summary and of the
   * management report is (P-181). Left out, every row sorts with the others.
   */
  last?: (row: T) => boolean;
  /** The columns whose first click sorts the most first, as the worst health is. */
  descendingFirst?: readonly string[];
}

/**
 * Sort the rows of a table by its headers, in the browser. `columns` says for each
 * sortable column what a row is sorted by; the headers are `SortTh`, each with the name
 * of its column.
 */
export function useSorting<T>(
  rows: readonly T[] | null | undefined,
  columns: SortColumns<T>,
  { initial, enabled = true, last, descendingFirst = [] }: Options<T> = {},
): Sorting<T> {
  const [state, setState] = useState<SortState | null>(initial ?? null);
  const all = rows ?? [];
  const sorted = enabled ? sortRows(all, columns, state) : [...all];
  return {
    rows: last ? [...sorted.filter((row) => !last(row)), ...sorted.filter(last)] : sorted,
    state: enabled ? state : null,
    by: (column) => setState((was) => nextSort(was, column, descendingFirst.includes(column))),
    reset: () => setState(initial ?? null),
    enabled,
  };
}
