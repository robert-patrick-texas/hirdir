import type { ReactNode } from "react";
import { ariaSort, sortMark } from "../lib/sort";
import type { SortControl } from "../lib/useSorting";

interface SortThProps {
  /** The sorting of the table, from `useSorting`. */
  sort: SortControl;
  /** The name of the column, as the table's sorting has it. */
  column: string;
  className?: string;
  children?: ReactNode;
}

/**
 * The header of a column that a table is sorted by: a button, so that it is reached and
 * pressed from the keyboard. A click sorts by the column, another turns the order round.
 * The header says which column the table is sorted by and which way, in `aria-sort` and
 * with a mark. In a table that does not hold all of its rows it is a plain header.
 */
export function SortTh({ sort, column, className, children }: SortThProps) {
  if (!sort.enabled) {
    return (
      <th scope="col" className={className}>
        {children}
      </th>
    );
  }
  const mark = sortMark(sort.state, column);
  return (
    <th scope="col" className={className} aria-sort={ariaSort(sort.state, column)}>
      <button
        type="button"
        className="sort-header"
        data-sort={column}
        title="Sort by this column. Again turns the order round."
        onClick={() => sort.by(column)}
      >
        {children}
        <span className="sort-mark" aria-hidden="true">
          {mark}
        </span>
      </button>
    </th>
  );
}
