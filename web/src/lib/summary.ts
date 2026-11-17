// The two reports of a view of the items, as words. The server counts. The summary,
// `GET /reports/summary`, is for the people who run the network: components, managed
// nodes, support weight and health, and no money. The management report,
// `GET /reports/management`, is for the people who pay for it: estimated value and
// annual support cost, and neither condition nor health. Each answers with the totals
// of the view and, when asked, one row for each value of what the view is taken by.
// Nothing is counted or summed here.

import type { Schemas } from "../api/client";
import { CONDITION_LIST, HEALTHS, healthLabel } from "./health";
import { CATALOG_KINDS, choiceLabel, optionLabel } from "./options";
import type { Option } from "./patch";
import type { CountColumns } from "./rank";
import { decimalValue } from "./sort";

export type Summary = Schemas["SummaryOut"];
export type Totals = Schemas["SummaryTotals"];
export type SummaryRow = Schemas["SummaryRow"];
/** The items and the components that share one value: a kind, or a condition. */
export type Counted = Schemas["Counted"];
export type By = NonNullable<Summary["by"]>;
export type Management = Schemas["ManagementOut"];
export type ManagementMeasures = Schemas["ManagementMeasures"];
export type ManagementRow = Schemas["ManagementRow"];
export type ManagementBy = NonNullable<Management["by"]>;
type Choice = Schemas["ChoiceOut"];

export const SUMMARY_BY: ReadonlyArray<Option & { value: By }> = [
  { value: "vendor", label: "Vendor" },
  { value: "kind", label: "Kind" },
  { value: "type", label: "Type" },
  { value: "function", label: "Function" },
  { value: "owner", label: "Owner" },
  { value: "operator", label: "Operator" },
  { value: "site", label: "Site" },
  { value: "region", label: "Region" },
  { value: "contract", label: "Contract" },
  { value: "lifecycle_state", label: "Lifecycle state" },
  { value: "disposition", label: "Disposition" },
  { value: "condition", label: "Condition" },
  { value: "health", label: "Health" },
  { value: "tag", label: "Tag" },
];

/**
 * What the management report can be by. By site comes first: it is what the report
 * shows unless asked otherwise, and the report has no view of the totals alone.
 */
export const MANAGEMENT_BY: ReadonlyArray<Option & { value: ManagementBy }> = [
  { value: "site", label: "Site" },
  { value: "region", label: "Region" },
  { value: "vendor", label: "Vendor" },
  { value: "kind", label: "Kind" },
  { value: "type", label: "Type" },
  { value: "function", label: "Function" },
  { value: "owner", label: "Owner" },
  { value: "operator", label: "Operator" },
  { value: "contract", label: "Contract" },
  { value: "tag", label: "Tag" },
];

// What to call the row of the items that have none of what the summary is by.
const NONE: Readonly<Record<By, string>> = {
  vendor: "No vendor",
  kind: "No kind",
  type: "No type",
  function: "No function",
  owner: "No owner",
  // What nobody of the team is assigned to look after.
  operator: "Nobody is assigned",
  // The items that are nowhere: no location in force, and so no site and no region.
  site: "Nowhere: no location",
  region: "Nowhere: no location",
  // What no contract covers today.
  contract: "Under no contract",
  // The items under no device group, and those with no catalog entry.
  group: "In no group",
  model: "No model",
  lifecycle_state: "No state",
  disposition: "No disposition",
  condition: "No condition",
  health: "No health",
  tag: "No tag",
};

export function isBy(value: string): value is By {
  return SUMMARY_BY.some((by) => by.value === value);
}

export function isManagementBy(value: string): value is ManagementBy {
  return MANAGEMENT_BY.some((by) => by.value === value);
}

export function byLabel(by: string | null | undefined): string {
  return SUMMARY_BY.find((known) => known.value === by)?.label ?? by ?? "";
}

/** True for what a report is by when its rows are places, each labelled with its path. */
export function isByPlace(by: string | null | undefined): by is "site" | "region" {
  return by === "site" || by === "region";
}

/**
 * What to call one row. A kind, a type, a function, a condition and a health come as the
 * value a record holds and are shown by the label of that value; the rest come with what
 * people call them, a site and a region with their path. The row of the blank says what
 * is missing.
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
  if (by === "condition") return choiceLabel(choices, CONDITION_LIST, text);
  if (by === "health") return healthLabel(text);
  return text;
}

/** What to call the components of one condition, in the totals. Those with none say so. */
export function conditionLabel(
  row: Pick<Counted, "key" | "label">,
  choices?: readonly Choice[],
): string {
  if (row.key === null) return NONE.condition;
  return choiceLabel(choices, CONDITION_LIST, row.label ?? row.key);
}

/** What the reader asked a report for. `B` is what that report can be by. */
export interface ReportView<B extends string = By> {
  /** The item filter, in the short form. Blank is every item. */
  filter: string;
  by: B | "";
  includeArchived: boolean;
  includeDrafts: boolean;
}

/** What the reader asked the summary for. */
export type SummaryView = ReportView<By>;

/**
 * The query of `GET /reports/summary` or of `GET /reports/management` for a view. What
 * is blank or off is left out.
 */
export function summaryQuery<B extends string = By>(
  view: ReportView<B>,
): {
  filter?: string;
  by?: B;
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
  counted: Counted[];
  /** The kinds that stand beside it: reported, and not in the headline. */
  beside: Counted[];
}

/**
 * The kinds of the totals, split as the `count_kinds` setting has them: those the
 * headline component count takes, and those reported beside it. When the setting is
 * not known every kind is listed beside, and none is claimed for the headline.
 */
export function kindsShown(
  kinds: readonly Counted[],
  countKinds: readonly string[] | null,
): KindsShown {
  if (countKinds === null) return { counted: [], beside: [...kinds] };
  const taken = (kind: Counted) => kind.key !== null && countKinds.includes(kind.key);
  return {
    counted: kinds.filter(taken),
    beside: kinds.filter((kind) => !taken(kind)),
  };
}

/** A kind of catalog entry for people. */
export function kindLabel(kind: string | null): string {
  return kind === null ? NONE.kind : optionLabel(CATALOG_KINDS, kind);
}

/**
 * The counts of a row of the summary that it is ranked by and drawn with a bar beside,
 * by the names its sorting has for them (P-180). It is ranked by items until a header of
 * another count is pressed.
 */
export const SUMMARY_COUNTS: CountColumns<SummaryRow> = {
  items: { value: (row) => row.items, text: (row) => countText(row.items), label: "items" },
  component_count: {
    value: (row) => row.component_count,
    text: (row) => countText(row.component_count),
    label: "components",
  },
  managed_node_count: {
    value: (row) => row.managed_node_count,
    text: (row) => countText(row.managed_node_count),
    label: "managed nodes",
  },
  support_weight: {
    value: (row) => decimalValue(row.support_weight),
    text: (row) => amountText(row.support_weight),
    label: "support weight",
  },
  ...Object.fromEntries(
    HEALTHS.map((health) => [
      `health.${health.value}`,
      {
        value: (row: SummaryRow) => row.by_health[health.value],
        text: (row: SummaryRow) => countText(row.by_health[health.value]),
        label: `components of ${health.label.toLowerCase()} health`,
      },
    ]),
  ),
};

/** The counts of a row of the management report, as `SUMMARY_COUNTS` has those of the summary. */
export const MANAGEMENT_COUNTS: CountColumns<ManagementRow> = {
  items: { value: (row) => row.items, text: (row) => countText(row.items), label: "items" },
  component_count: {
    value: (row) => row.component_count,
    text: (row) => countText(row.component_count),
    label: "components",
  },
  est_value: {
    value: (row) => decimalValue(row.est_value),
    text: (row) => amountText(row.est_value),
    label: "estimated value",
  },
  annual_support_cost: {
    value: (row) => decimalValue(row.annual_support_cost),
    text: (row) => amountText(row.annual_support_cost),
    label: "annual support cost",
  },
};

/** The counts of the totals by kind and by condition, as `SUMMARY_COUNTS` has those of a row. */
export const COUNTED_COUNTS: CountColumns<Counted> = {
  items: { value: (row) => row.items, text: (row) => countText(row.items), label: "items" },
  components: {
    value: (row) => row.component_count,
    text: (row) => countText(row.component_count),
    label: "components",
  },
};

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
