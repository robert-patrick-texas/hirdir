// 0.9.13: an operator is made and read with fewer steps (P-280, P-284).
//
// What the Operators page reckons without a page: the label a new operator takes from
// the user chosen as the person behind it, and the gaps Show leads to.

/**
 * The label of a new operator once a user is chosen as the person behind it (P-284): the
 * username, while the label is blank or still what the form filled in, `filled`. A label
 * typed by hand is kept. Without a username the label is as it was.
 */
export function labelFor(typed: string, filled: string, username: string | null): string {
  if (!username) return typed;
  return typed.trim() === "" || typed === filled ? username : typed;
}

/**
 * The gaps of the list of operators (P-280), each the grid's own filter: those with no
 * user behind them, whose person is a contact that is no user or nobody (`scope` is not
 * internal), and among those the open ones, with nobody behind them at all. As the
 * lists of users and of contacts do, Show leads to each by an address of its own.
 */
export const OPERATOR_GAPS: readonly { label: string; filter: string }[] = [
  { label: "Every operator", filter: "" },
  { label: "No user behind it", filter: "scope:ne:internal" },
  { label: "Nobody behind it", filter: "is_open:eq:true" },
];

/** The address of the list of operators started with a filter. */
export function operatorsAddress(filter: string): string {
  return `/operators?${new URLSearchParams({ filter }).toString()}`;
}

/** Whether a gap is the one on show: the list was opened with its filter, or with none. */
export function isGapShown(gap: string, startFilter: string | null): boolean {
  return (startFilter ?? "") === gap;
}
