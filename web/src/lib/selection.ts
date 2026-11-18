// 0.9.7: rows are ticked (P-233). What the buttons that act on the rows chosen in a grid
// say of them, and what the box in the heading shows of the rows on show.

/** How many rows are chosen: the rows ticked, or all that match the filter. */
export interface ChosenCount {
  ticked: number;
  allMatching: boolean;
  /** How many rows the filter keeps, once the server has said. */
  total: number | null;
}

/**
 * The label of a button that acts on the rows chosen, with how many: "Copy (3)", or
 * "Copy (all 1,204)" for all that match. With nothing chosen, or for a button that takes
 * particular rows only while all that match are chosen, the label alone.
 */
export function withCount(label: string, chosen: ChosenCount, rowsOnly = false): string {
  if (chosen.allMatching) {
    if (rowsOnly || chosen.total === null) return label;
    return `${label} (all ${chosen.total.toLocaleString("en-US")})`;
  }
  if (chosen.ticked > 0) return `${label} (${chosen.ticked.toLocaleString("en-US")})`;
  return label;
}

/** What the box in the heading shows: no row on show ticked, some of them, or every one. */
export type TickState = "none" | "some" | "all";

/** The box of the heading, from the rows on show and how many of them are ticked. */
export function tickState(shown: number, ticked: number): TickState {
  if (shown === 0 || ticked === 0) return "none";
  return ticked >= shown ? "all" : "some";
}
