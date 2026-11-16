// 0.8.0: the support weight of the capacity report in its parts, and a balance tried
// beside the balance in force (P-155, P-156). Nothing is added up here: every number is
// the server's, set side by side.

import type { CapacityReport, CapacityView, MeasureKind } from "./capacity";
import { MEASURES } from "./capacity";

type Counts = CapacityView["defaulted"];

/** One part of the support weight, in both views: its weight, and how many counted at a default and were raised. */
export interface PartRow {
  key: "items" | "places" | "circuits";
  label: string;
  /** What the counts are of: the major items, the sites, the circuits. */
  counted: string;
  active: PartView;
  drafts: PartView;
}

export interface PartView {
  weight: string;
  defaulted: number;
  raised: number;
}

function part(view: CapacityView, weight: string, which: keyof Counts): PartView {
  return { weight, defaulted: view.defaulted[which], raised: view.raised[which] };
}

/**
 * The parts of the support weight, the items, the places and the circuits, each with
 * how many of its kind counted at the default and how many were raised to the minimum.
 * A region and a location count their own weight alone, so the counts of the places are
 * of the sites.
 */
export function partRows(report: CapacityReport): PartRow[] {
  const { active, with_drafts: drafts } = report;
  return [
    {
      key: "items",
      label: "The items",
      counted: "major items",
      active: part(active, active.items_weight, "items"),
      drafts: part(drafts, drafts.items_weight, "items"),
    },
    {
      key: "places",
      label: "The places",
      counted: "sites",
      active: part(active, active.places_weight, "sites"),
      drafts: part(drafts, drafts.places_weight, "sites"),
    },
    {
      key: "circuits",
      label: "The circuits",
      counted: "circuits",
      active: part(active, active.circuits_weight, "circuits"),
      drafts: part(drafts, drafts.circuits_weight, "circuits"),
    },
  ];
}

/** How a figure of a comparison is written: a measure, or a count of things. */
export type CompareKind = MeasureKind | "count";

/** One figure of the report, in force and tried, without the drafts and with them. */
export interface CompareRow {
  key: string;
  label: string;
  kind: CompareKind;
  inForce: { active: string | null; drafts: string | null };
  tried: { active: string | null; drafts: string | null };
  /** The figure tried is not the one in force, in either view. */
  differs: boolean;
}

type Pick = (view: CapacityView) => string | null;

function row(
  key: string,
  label: string,
  kind: CompareKind,
  pick: Pick,
  inForce: CapacityReport,
  tried: CapacityReport,
): CompareRow {
  const one = { active: pick(inForce.active), drafts: pick(inForce.with_drafts) };
  const other = { active: pick(tried.active), drafts: pick(tried.with_drafts) };
  return {
    key,
    label,
    kind,
    inForce: one,
    tried: other,
    differs: one.active !== other.active || one.drafts !== other.drafts,
  };
}

const COUNTS: ReadonlyArray<[which: keyof Counts, noun: string]> = [
  ["items", "major items"],
  ["sites", "sites"],
  ["circuits", "circuits"],
];

/**
 * The balance tried beside the balance in force, figure by figure: every measure of a
 * view, the weight per resource unit, how many of each kind counted at a default and were
 * raised, and the supply of each category. The categories are those of the view in force,
 * which lists every one that supplies.
 */
export function compareRows(inForce: CapacityReport, tried: CapacityReport): CompareRow[] {
  const rows: CompareRow[] = [
    {
      key: "weight_per_resource_unit",
      label: "Support weight one resource unit carries",
      kind: "weight",
      inForce: {
        active: inForce.weight_per_resource_unit,
        drafts: inForce.weight_per_resource_unit,
      },
      tried: { active: tried.weight_per_resource_unit, drafts: tried.weight_per_resource_unit },
      differs: inForce.weight_per_resource_unit !== tried.weight_per_resource_unit,
    },
    ...MEASURES.map((measure) =>
      row(measure.key, measure.label, measure.kind, (view) => view[measure.key], inForce, tried),
    ),
  ];
  for (const [which, noun] of COUNTS) {
    rows.push(
      row(
        `defaulted.${which}`,
        `${capital(noun)} counted at a default`,
        "count",
        (view) => String(view.defaulted[which]),
        inForce,
        tried,
      ),
    );
  }
  for (const [which, noun] of COUNTS) {
    rows.push(
      row(
        `raised.${which}`,
        `${capital(noun)} raised to a minimum`,
        "count",
        (view) => String(view.raised[which]),
        inForce,
        tried,
      ),
    );
  }
  for (const category of inForce.active.by_category) {
    const units = (view: CapacityView) =>
      view.by_category.find((one) => one.category === category.category)?.units ?? null;
    rows.push(
      row(
        `category.${category.category}`,
        `Supply: ${category.label}`,
        "units",
        units,
        inForce,
        tried,
      ),
    );
  }
  return rows;
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
