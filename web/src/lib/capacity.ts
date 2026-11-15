// Capacity: the lines of supply and of other work, and the balance the server works out
// from them and from the support weight of the inventory. Nothing is added up here: the
// report is shown as it is answered, twice, without the drafts and with them.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type CapacityLine = Schemas["CapacityLineOut"];
export type CapacityReport = Schemas["CapacityOut"];
export type CapacityView = Schemas["CapacityView"];
type Choice = Schemas["ChoiceOut"];

export const SIDES: readonly Option[] = [
  { value: "supply", label: "Supply" },
  { value: "demand", label: "Demand" },
];

/** The list of choices the categories of a line come from. */
export const CATEGORY_LIST = "capacity_category";
/** The one category of a demand line: work that is not the infrastructure. */
export const OTHER_WORK = "other_work";

export function capacityLinePath(hid: string): string {
  return `/capacity/${encodeURIComponent(hid)}`;
}

/**
 * The categories a supply line may have: the active values of the list, without the one
 * that is of the demand side, and with the one the line already holds.
 */
export function supplyCategories(
  choices: readonly Choice[] | undefined,
  current: string | null = null,
): Option[] {
  return (choices ?? [])
    .filter(
      (choice) =>
        choice.list === CATEGORY_LIST &&
        choice.value !== OTHER_WORK &&
        (choice.active || choice.value === current),
    )
    .map((choice) => ({ value: choice.value, label: choice.label }));
}

/** How one measure of the report is written. */
export type MeasureKind = "units" | "weight" | "percent" | "money";

export interface Measure {
  key: Exclude<keyof CapacityView, "by_category" | "multiplying_lines" | "demand_by_region">;
  label: string;
  kind: MeasureKind;
  /** What the measure is, for whoever has not met it. */
  about: string;
}

/** The measures of one view of the report, demand first, then supply and what follows. */
export const MEASURES: readonly Measure[] = [
  {
    key: "support_weight",
    label: "Support weight of the inventory",
    kind: "weight",
    about: "Of the items in the states that carry weight.",
  },
  {
    key: "infrastructure_demand",
    label: "Infrastructure demand",
    kind: "units",
    about: "The support weight in resource units.",
  },
  {
    key: "other_demand",
    label: "Other work",
    kind: "units",
    about: "The demand lines in date: projects, a transition.",
  },
  { key: "demand", label: "Demand", kind: "units", about: "Infrastructure and other work." },
  { key: "supply", label: "Supply", kind: "units", about: "The supply lines in date." },
  { key: "balance", label: "Balance", kind: "units", about: "Supply less demand." },
  {
    key: "coverage_pct",
    label: "Coverage",
    kind: "percent",
    about: "Supply over demand. Blank when there is no demand.",
  },
  {
    key: "own_units",
    label: "The team's own positions",
    kind: "units",
    about: "The supply of the category Staff.",
  },
  {
    key: "own_share_pct",
    label: "Share that is the team's own",
    kind: "percent",
    about: "The team's own positions over the whole supply.",
  },
  {
    key: "outside_units",
    label: "Everything else",
    kind: "units",
    about: "Services, smart hands, tools: the supply that is not staff.",
  },
  {
    key: "annual_cost",
    label: "Annual cost of the supply",
    kind: "money",
    about: "What the supply lines say they cost a year.",
  },
];

function marked(amount: string): string {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(amount.trim());
  if (!match) return amount;
  const [, sign = "", whole = "", fraction = ""] = match;
  // A minus sign and not a hyphen, so that a shortfall is read as one.
  return `${sign ? "−" : ""}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

/**
 * One measure as text, with the digits the server sent: a percentage with its sign, and
 * a dash for one that is blank, as the coverage is when there is no demand.
 */
export function measureText(value: string | null | undefined, kind: MeasureKind): string {
  if (value === null || value === undefined || value === "") return "—";
  return kind === "percent" ? `${marked(value)}%` : marked(value);
}

/** How a balance stands: supply short of demand, even with it, or over it. */
export function balanceTone(balance: string | null | undefined): "short" | "even" | "over" {
  const text = (balance ?? "").trim();
  if (text.startsWith("-") && /[1-9]/.test(text)) return "short";
  return /[1-9]/.test(text) ? "over" : "even";
}

/** The balance in words, beside its number. */
export function balanceWords(balance: string | null | undefined): string {
  const tone = balanceTone(balance);
  if (tone === "short") return "Short: demand is more than supply";
  return tone === "over" ? "Supply is more than demand" : "Supply meets demand";
}

/** One row of demand beside supply: what it is, and its units in each of the two views. */
export interface BalanceRow {
  key: string;
  side: "Demand" | "Supply";
  name: string;
  /** The units without the drafts, and with them. */
  active: string;
  drafts: string;
  /** How many lines make it up: nothing for the infrastructure, which is no line. */
  lines: number | null;
  draftLines: number | null;
  cost: string | null;
  draftCost: string | null;
}

/**
 * Demand beside supply, as rows of one table: the two parts of the demand, then each
 * category of the supply, each with what the report answers for it in both views. The
 * categories are those of the view without the drafts, which lists every one that
 * supplies, also one with no line.
 */
export function balanceRows(report: CapacityReport): BalanceRow[] {
  const demand = (key: "infrastructure_demand" | "other_demand", name: string): BalanceRow => ({
    key,
    side: "Demand",
    name,
    active: report.active[key],
    drafts: report.with_drafts[key],
    lines: null,
    draftLines: null,
    cost: null,
    draftCost: null,
  });
  const drafts = new Map(report.with_drafts.by_category.map((row) => [row.category, row]));
  return [
    demand("infrastructure_demand", "Infrastructure: the support weight of the inventory"),
    demand("other_demand", "Other work"),
    ...report.active.by_category.map((row): BalanceRow => {
      const other = drafts.get(row.category);
      return {
        key: row.category,
        side: "Supply",
        name: row.label,
        active: row.units,
        drafts: other?.units ?? row.units,
        lines: row.lines,
        draftLines: other?.lines ?? row.lines,
        cost: row.annual_cost,
        draftCost: other?.annual_cost ?? row.annual_cost,
      };
    }),
  ];
}
