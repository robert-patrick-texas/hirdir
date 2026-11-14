// The scoreboard: who looks after how much, and where. It is the summary by operator
// and by site, with the operators in force among the items of each row. The server
// counts and weighs; this puts the rows in order, the most support weight first, sets
// apart what nobody is assigned to, works out each row's share of the view, and builds
// the links and the file that go with the tables.
//
// A support weight is a decimal with two places, sent as text. It is added up and
// compared here as a whole number of hundredths, never as a floating-point number.

import type { Schemas } from "../api/client";
import { itemsPath } from "./filter";
import { markOf } from "./operators";

export type ScoreRow = Schemas["SummaryRow"];
export type RowOperator = Schemas["RowOperator"];

/** A decimal with at most two places, as a whole number of hundredths. Not a number: 0. */
export function hundredths(amount: string | null | undefined): number {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?\d*$/.exec((amount ?? "").trim());
  if (!match) return 0;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const value = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return sign === "-" ? -value : value;
}

/** A whole number of hundredths as a decimal with two places: `1250` is `12.50`. */
export function fromHundredths(value: number): string {
  const sign = value < 0 ? "-" : "";
  const digits = String(Math.abs(Math.trunc(value))).padStart(3, "0");
  return `${sign}${digits.slice(0, -2)}.${digits.slice(-2)}`;
}

type Weighed = Pick<ScoreRow, "support_weight" | "component_count" | "items"> & {
  label?: string | null;
};

/**
 * The order of a scoreboard: the most support weight first, then the most components,
 * then the most items, then by name, so that the order is steady.
 */
export function byLoad(one: Weighed, other: Weighed): number {
  return (
    hundredths(other.support_weight) - hundredths(one.support_weight) ||
    other.component_count - one.component_count ||
    other.items - one.items ||
    (one.label ?? "").localeCompare(other.label ?? "")
  );
}

/**
 * The rows of a scoreboard, in order, and the blank row set apart: what nobody is
 * assigned to in a summary by operator, the items that are nowhere in one by site.
 */
export function ranked<T extends Weighed & { key: string | null }>(
  rows: readonly T[] | null | undefined,
): { rows: T[]; blank: T | null } {
  const named = (rows ?? []).filter((row) => row.key !== null);
  return {
    rows: [...named].sort(byLoad),
    blank: (rows ?? []).find((row) => row.key === null) ?? null,
  };
}

/**
 * A part of the view's support weight, in hundredths of a per cent of the whole, so
 * that a share is exact to two places. Nothing of nothing is no share.
 */
export function share(part: string, whole: string): number {
  const all = hundredths(whole);
  if (all <= 0) return 0;
  return Math.max(0, Math.min(10000, Math.round((hundredths(part) * 10000) / all)));
}

/** A share as people read it: `42%`, `8.5%`, and `under 0.1%` for what is nearly nothing. */
export function shareText(part: string, whole: string): string {
  const value = share(part, whole);
  if (value === 0) return hundredths(part) > 0 && hundredths(whole) > 0 ? "under 0.1%" : "0%";
  const tenths = Math.round(value / 10);
  if (tenths === 0) return "under 0.1%";
  return tenths % 10 === 0 ? `${tenths / 10}%` : `${Math.floor(tenths / 10)}.${tenths % 10}%`;
}

/** The mark of the operator a row of a summary by operator is of, from what the row lists. */
export function operatorOfRow(row: Pick<ScoreRow, "key" | "label" | "operators">) {
  if (row.key === null) return null;
  const listed = row.operators?.find((operator) => operator.hid === row.key);
  if (listed) return markOf(listed);
  // The row names the operator by its HID and its label, whatever else is not sent.
  return markOf({
    hid: row.key,
    label: row.label,
    colour: null,
    contact: null,
    is_open: false,
  });
}

/** How much is under labels that nobody is behind: the rows of the operators that are open. */
export function underOpenLabels(rows: readonly ScoreRow[]): {
  labels: number;
  items: number;
  components: number;
  support_weight: string;
} {
  const open = rows.filter((row) => operatorOfRow(row)?.open === true);
  return {
    labels: open.length,
    items: open.reduce((sum, row) => sum + row.items, 0),
    components: open.reduce((sum, row) => sum + row.component_count, 0),
    support_weight: fromHundredths(
      open.reduce((sum, row) => sum + hundredths(row.support_weight), 0),
    ),
  };
}

/**
 * The grid of the items of one row: the filter of the view, with the condition of the
 * row added to it. Only a filter in the short form can be added to: for a view asked
 * for with a filter tree there is no such link, and null is answered.
 */
export function rowItemsPath(viewFilter: string, condition: string): string | null {
  const filter = viewFilter.trim();
  if (filter.startsWith("{")) return null;
  return itemsPath(`${filter} ${condition}`.trim());
}

/** The condition that keeps the items of one operator, or those nobody is assigned to. */
export function operatorCondition(hid: string | null): string {
  return hid === null ? "effective.operator_hid:empty:true" : `effective.operator_hid:eq:${hid}`;
}

/** The condition that keeps the items at or beneath one site, or those that are nowhere. */
export function siteCondition(hid: string | null): string {
  return hid === null ? "location:empty:true" : `location:within:${hid}`;
}

/**
 * Rows of cells as CSV text, as RFC 4180 has it. A cell that begins with `=`, `+`, `-`
 * or `@` is written with a leading apostrophe, as an export of the server is, so that a
 * spreadsheet does not run it as a formula.
 */
export function toCsv(rows: ReadonlyArray<ReadonlyArray<string | number>>): string {
  const cell = (value: string | number): string => {
    let text = String(value);
    if (typeof value === "string" && /^'*[=+\-@]/.test(text)) text = `'${text}`;
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return rows.map((row) => `${row.map(cell).join(",")}\r\n`).join("");
}

/** The operators table as a file: one line for each, what nobody is assigned to last. */
export function operatorsCsv(rows: readonly ScoreRow[], blank: ScoreRow | null, whole: string) {
  const line = (row: ScoreRow): Array<string | number> => {
    const mark = operatorOfRow(row);
    return [
      row.key ?? "",
      mark?.label ?? "",
      mark?.person ?? "",
      mark ? (mark.open ? "true" : "false") : "",
      row.component_count,
      row.managed_node_count,
      row.items,
      row.support_weight,
      shareText(row.support_weight, whole),
      row.by_health.good,
      row.by_health.degraded,
      row.by_health.failed,
      row.by_health.unknown,
    ];
  };
  return toCsv([
    [
      "operator_hid",
      "operator",
      "person",
      "open",
      "components",
      "managed_nodes",
      "items",
      "support_weight",
      "share",
      "good",
      "degraded",
      "failed",
      "unknown",
    ],
    ...rows.map(line),
    ...(blank ? [line(blank)] : []),
  ]);
}

/** The operators involved in a row, as one cell of a file: `Op2 3 (4.50); nobody 1 (1.00)`. */
export function involvedText(operators: readonly RowOperator[] | null | undefined): string {
  return (operators ?? [])
    .map(
      (operator) =>
        `${operator.hid === null ? "nobody" : (operator.label ?? operator.hid)} ${operator.component_count} (${operator.support_weight})`,
    )
    .join("; ");
}

/** The sites table as a file: one line for each, the items that are nowhere last. */
export function sitesCsv(rows: readonly ScoreRow[], blank: ScoreRow | null) {
  const line = (row: ScoreRow): Array<string | number> => [
    row.key ?? "",
    row.label ?? "",
    row.component_count,
    row.managed_node_count,
    row.items,
    row.support_weight,
    involvedText(row.operators),
  ];
  return toCsv([
    [
      "site_hid",
      "site",
      "components",
      "managed_nodes",
      "items",
      "support_weight",
      "operators: components (support weight)",
    ],
    ...rows.map(line),
    ...(blank ? [line(blank)] : []),
  ]);
}
