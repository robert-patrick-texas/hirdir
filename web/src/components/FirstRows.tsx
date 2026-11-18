// A table of many rows, sorted in the browser, shows the first twenty as it is sorted and
// a button that shows them all: the Scoreboard's tables (P-196) and a vendor's models
// (P-211).

import { type ReactNode, useState } from "react";
import { countText } from "../lib/summary";

// A table of more rows than this shows this many, as it is sorted, until Show all.
export const FIRST_ROWS = 20;

/**
 * The rows a table shows: the first twenty as it is sorted, until Show all is pressed.
 * The sort, the rank, the bars and a file saved are of all the rows (P-196). `what` names
 * the rows for a screen reader, after the button's number: "operators", "models".
 */
export function useFirstRows<T>(rows: readonly T[], what: string): { shown: T[]; more: ReactNode } {
  const [all, setAll] = useState(false);
  const many = rows.length > FIRST_ROWS && !all;
  return {
    shown: many ? rows.slice(0, FIRST_ROWS) : [...rows],
    more: many ? (
      <p className="actions">
        <button type="button" onClick={() => setAll(true)}>
          Show all {countText(rows.length)}
          <span className="visually-hidden"> {what}</span>
        </button>
        <span className="muted"> The first {FIRST_ROWS} are shown, as the table is sorted.</span>
      </p>
    ) : null,
  };
}
