// The summary report as words. The server counts; `GET /reports/summary` answers with
// the totals of a view of the items and, when asked, one row for each value of what the
// view is taken by. Nothing is counted or summed here.

import type { Schemas } from "../api/client";
import { CATALOG_KINDS, choiceLabel, optionLabel } from "./options";
import type { Option } from "./patch";

export type Summary = Schemas["SummaryOut"];
export type Totals = Schemas["SummaryTotals"];
export type SummaryRow = Schemas["SummaryRow"];
export type KindCount = Schemas["KindCount"];
export type By = NonNullable<Summary["by"]>;
type Choice = Schemas["ChoiceOut"];

export const SUMMARY_BY: ReadonlyArray<Option & { value: By }> = [
  { value: "vendor", label: "Vendor" },
  { value: "kind", label: "Kind" },
  { value: "type", label: "Type" },
  { value: "function", label: "Function" },
  { value: "owner", label: "Owner" },
  { value: "lifecycle_state", label: "Lifecycle state" },
  { value: "disposition", label: "Disposition" },
  { value: "tag", label: "Tag" },
];

// What to call the row of the items that have none of what the summary is by.
const NONE: Readonly<Record<By, string>> = {
  vendor: "No vendor",
  kind: "No kind",
  type: "No type",
  function: "No function",
  owner: "No owner",
  lifecycle_state: "No state",
  disposition: "No disposition",
  tag: "No tag",
};

export function isBy(value: string): value is By {
  return SUMMARY_BY.some((by) => by.value === value);
}

export function byLabel(by: string | null | undefined): string {
  return SUMMARY_BY.find((known) => known.value === by)?.label ?? by ?? "";
}

/**
 * What to call one row. A kind, a type and a function come as the value a record holds
 * and are shown by the label of that value; the rest come with what people call them.
 * The row of the blank says what is missing.
 */
export function rowLabel(
  by: By,
  row: Pick<SummaryRow, "key" | "label">,
  choices?: readonly Choice[],
): string {
  if (row.key === null) return NONE[by];
  const text = row.label ?? row.key;
  if (by === "kind") return optionLabel(CATALOG_KINDS, text);
  if (by === "type") return choiceLabel(choices, "catalog_type", text);
  if (by === "function") return choiceLabel(choices, "catalog_function", text);
  return text;
}

/** What the reader asked the summary for. */
export interface SummaryView {
  /** The item filter, in the short form. Blank is every item. */
  filter: string;
  by: By | "";
  includeArchived: boolean;
  includeDrafts: boolean;
}

/** The query of `GET /reports/summary` for a view. What is blank or off is left out. */
export function summaryQuery(view: SummaryView): {
  filter?: string;
  by?: By;
  include_archived?: boolean;
  include_drafts?: boolean;
} {
  const filter = view.filter.trim();
  return {
    ...(filter === "" ? {} : { filter }),
    ...(view.by === "" ? {} : { by: view.by }),
    ...(view.includeArchived ? { include_archived: true } : {}),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
}

/** A setting that is a list of words, such as `count_kinds`, or null when it is not known. */
export function settingList(
  settings: ReadonlyArray<{ key: string; value: unknown }> | null | undefined,
  key: string,
): string[] | null {
  const value = settings?.find((setting) => setting.key === key)?.value;
  if (!Array.isArray(value)) return null;
  return value.filter((entry): entry is string => typeof entry === "string");
}

export interface KindsShown {
  /** The kinds the headline component count takes. */
  counted: KindCount[];
  /** The kinds that stand beside it: reported, and not in the headline. */
  beside: KindCount[];
}

/**
 * The kinds of the totals, split as the `count_kinds` setting has them: those the
 * headline component count takes, and those reported beside it. When the setting is
 * not known every kind is listed beside, and none is claimed for the headline.
 */
export function kindsShown(
  kinds: readonly KindCount[],
  countKinds: readonly string[] | null,
): KindsShown {
  if (countKinds === null) return { counted: [], beside: [...kinds] };
  return {
    counted: kinds.filter((kind) => countKinds.includes(kind.kind)),
    beside: kinds.filter((kind) => !countKinds.includes(kind.kind)),
  };
}

/** A kind of catalog entry for people. */
export function kindLabel(kind: string): string {
  return optionLabel(CATALOG_KINDS, kind);
}

/** A whole number with its thousands marked, for a count on a page. */
export function countText(count: number): string {
  return count.toLocaleString("en-US");
}

/**
 * A decimal as the server sent it, with its thousands marked. The digits are those of
 * the text: it never passes through a JavaScript number.
 */
export function amountText(amount: string | null | undefined): string {
  if (!amount) return "";
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(amount.trim());
  if (!match) return amount;
  const [, sign = "", whole = "", fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}
