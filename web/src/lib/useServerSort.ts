import { useState } from "react";
import type { Loaded } from "./hooks";
import {
  columnSorts,
  nextSort,
  type SortColumns,
  type SortFields,
  type SortState,
  sortParam,
  sortRows,
} from "./sort";
import type { SortControl } from "./useSorting";

interface Options<T> {
  /** The field of the route's `sort` behind each column the server sorts by. */
  fields: SortFields;
  /**
   * Columns the server does not sort by, which the page composes itself: what a row is
   * sorted by in each, in the browser, while the table holds every row.
   */
  local?: SortColumns<T>;
  /** Called when the sort changes: as to go back to the first page. */
  onChange?: () => void;
}

/** The sorting of a table that the server pages and sorts. */
export interface ServerSort<T> {
  /** What to send as `sort`: undefined for the order the route has by itself. */
  param: string | undefined;
  /** The same, as part of a query: `{ sort: [...] }`, a field to an entry, or nothing. */
  query: { sort?: string[] };
  state: SortState | null;
  /** What the header of a column needs. `holdsAll`: the table holds every row. */
  header: (column: string, holdsAll: boolean) => SortControl;
  /**
   * The rows as they are shown: as the server sent them, or sorted in the browser when
   * the table is sorted by a column the server does not sort by and holds every row.
   */
  arrange: (rows: readonly T[] | null | undefined, holdsAll: boolean) => T[];
  /**
   * What was read, kept on show while the rows are read again in another order: the
   * table does not go away at a click on a header, and the header that was pressed
   * keeps the focus. Wrap the `useLoad` of the rows in it.
   */
  held: <D>(loaded: Loaded<D>) => Loaded<D>;
}

/**
 * Sort a paged table by its headers through the server's `sort`, over the whole list
 * and not the page on show: a click on a header asks for the rows in that order, and
 * another turns it round. The order is the server's also while the table holds every
 * row, so that it does not change when a list grows past a page. The headers are
 * `SortTh`, each with `header(column, holdsAll)`.
 */
export function useServerSort<T>({ fields, local = {}, onChange }: Options<T>): ServerSort<T> {
  const [state, setState] = useState<SortState | null>(null);
  // What was last read, and whether another order of it is being read now.
  const [kept, setKept] = useState<{ data: unknown; pending: boolean }>({
    data: undefined,
    pending: false,
  });
  const param = sortParam(state, fields);

  function by(column: string) {
    setState((was) => nextSort(was, column));
    setKept((was) => ({ ...was, pending: true }));
    onChange?.();
  }

  function held<D>(loaded: Loaded<D>): Loaded<D> {
    if (loaded.data !== undefined) {
      // Remembered during the render that brought it: the next order is shown over it.
      if (kept.data !== loaded.data || kept.pending) {
        setKept({ data: loaded.data, pending: false });
      }
      return loaded;
    }
    if (!kept.pending || loaded.error || kept.data === undefined) return loaded;
    return { ...loaded, data: kept.data as D };
  }

  return {
    param,
    query: param === undefined ? {} : { sort: param.split(",") },
    state,
    header: (column, holdsAll) => {
      const enabled = columnSorts(column, fields, local, holdsAll);
      return { state: enabled ? state : null, by, enabled };
    },
    arrange: (rows, holdsAll) => {
      const all = rows ?? [];
      const inBrowser = state !== null && param === undefined && holdsAll;
      return inBrowser ? sortRows(all, local, state) : [...all];
    },
    held,
  };
}
