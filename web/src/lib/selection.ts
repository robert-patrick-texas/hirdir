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

/**
 * The rows that Shift with a press, or with Space, ticks: from the row last pressed
 * without Shift to this one, whichever comes first; this one alone where none was.
 */
export function shiftRange(anchor: number | null, to: number): [first: number, last: number] {
  if (anchor === null) return [to, to];
  return anchor <= to ? [anchor, to] : [to, anchor];
}

/**
 * What the list says when a Shift range crossed rows the grid has not read: they cannot
 * be ticked unread, and the rest of the range is ticked without them.
 */
export function unreadText(unread: number): string {
  if (unread <= 0) return "";
  const rows = unread === 1 ? "1 row" : `${unread.toLocaleString("en-US")} rows`;
  return `${rows} between ${unread === 1 ? "was" : "were"} not read yet, and so not ticked: scroll through them, then press again with Shift`;
}

/** What the box in the heading shows: no row ticked, some, or every row of the list. */
export type TickState = "none" | "some" | "all";

/**
 * The box of the heading, from the rows read so far, how many of them are ticked, and how
 * many the list holds. It is ticked only when every row of the list is read and ticked:
 * the rows read may be a part of the list, as the first block of 260 (0.9.7 review).
 */
export function tickState(read: number, ticked: number, total: number | null): TickState {
  if (read === 0 || ticked === 0) return "none";
  return ticked >= read && total !== null && read >= total ? "all" : "some";
}

/** What the box of the heading does when pressed, as its name says it. */
export function tickName(read: number, everyReadTicked: boolean): string {
  const rows = `${read.toLocaleString("en-US")} ${read === 1 ? "row" : "rows"} read so far`;
  return everyReadTicked ? `Clear the ${rows}` : `Tick the ${rows}`;
}
