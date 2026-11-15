// The trend of the capacity balance: one point a week, from the records the server keeps.
//
// Nothing is worked out here that the server answers: each record holds its demand, its
// supply and its balance, and the parts as they were recorded. This lays them out to be
// drawn: where each point falls, the lines through them, the band of the balance between
// demand and supply, and the supply stacked by category. A week that was corrected keeps
// its corrected totals, which are what the two lines go through, and its parts as they
// were recorded, which then need not add up to them.

import type { Schemas } from "../api/client";
import { decimalValue } from "./sort";

export type CapacityRecord = Schemas["CapacityRecordOut"];
export type TrendView = "active" | "with_drafts";

/** One week of the trend, in resource units, for one view. */
export interface TrendPoint {
  hid: string;
  week: string;
  demand: number;
  supply: number;
  balance: number;
  infrastructure: number;
  other: number;
  /** The supply of each category, as it was recorded. */
  categories: Readonly<Record<string, number>>;
  adjusted: boolean;
  note: string | null;
  /** The figures as the server sent them, to be shown as they are. */
  text: {
    demand: string;
    supply: string;
    balance: string;
    coverage: string | null;
    infrastructure: string;
    other: string;
  };
}

function units(value: string | null | undefined): number {
  return decimalValue(value) ?? 0;
}

/** The weeks of the trend for one view, the oldest first, whatever order they came in. */
export function trendPoints(records: readonly CapacityRecord[], view: TrendView): TrendPoint[] {
  return [...records]
    .sort((one, other) => one.week_of.localeCompare(other.week_of))
    .map((record) => {
      const figures = record[view];
      const categories: Record<string, number> = {};
      for (const row of figures.by_category) categories[row.category] = units(row.units);
      return {
        hid: record.hid,
        week: record.week_of,
        demand: units(figures.demand),
        supply: units(figures.supply),
        balance: units(figures.balance),
        infrastructure: units(figures.infrastructure_demand),
        other: units(figures.other_demand),
        categories,
        adjusted: record.adjusted,
        note: record.note,
        text: {
          demand: figures.demand,
          supply: figures.supply,
          balance: figures.balance,
          coverage: figures.coverage_pct,
          infrastructure: figures.infrastructure_demand,
          other: figures.other_demand,
        },
      };
    });
}

export interface Category {
  category: string;
  label: string;
}

/**
 * The categories of supply the weeks hold, each once, in the order the records list
 * them: the order of the list of choices, as the report has it.
 */
export function trendCategories(records: readonly CapacityRecord[], view: TrendView): Category[] {
  const seen = new Map<string, string>();
  for (const record of records) {
    for (const row of record[view].by_category) {
      if (!seen.has(row.category)) seen.set(row.category, row.label);
    }
  }
  return [...seen].map(([category, label]) => ({ category, label }));
}

/**
 * Round steps for an axis from 0 to at least `top`: 1, 2 or 5 times a power of ten, so
 * that there are about `count` of them.
 */
export function axisTicks(top: number, count = 5): number[] {
  const highest = Number.isFinite(top) && top > 0 ? top : 1;
  const rough = highest / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(rough));
  const step =
    [1, 2, 5, 10].map((times) => times * power).find((size) => size >= rough) ?? 10 * power;
  // Each kept to the digits of the step, so that three steps of 0.1 are 0.3.
  const digits = Math.max(0, -Math.floor(Math.log10(step)));
  const ticks: number[] = [];
  for (let place = 0; ; place += 1) {
    const at = Number((place * step).toFixed(digits));
    ticks.push(at);
    if (at >= highest) return ticks;
  }
}

/** A point of the plot, in the units of the data: the week's place, and an amount. */
export type At = readonly [x: number, y: number];

/** The band of the balance between the two lines over one stretch, and which way it lies. */
export interface Band {
  tone: "over" | "short";
  points: At[];
}

/**
 * The balance between demand and supply as bands, week to week: where supply is above
 * demand the band is `over`, where it is below `short`. A stretch where the two lines
 * cross is cut where they cross, so each part takes its own tone.
 */
export function balanceBands(points: readonly TrendPoint[]): Band[] {
  const bands: Band[] = [];
  for (let place = 0; place + 1 < points.length; place += 1) {
    const one = points[place];
    const next = points[place + 1];
    if (!one || !next) continue;
    const before = one.supply - one.demand;
    const after = next.supply - next.demand;
    if (before === 0 && after === 0) continue;
    if (before * after >= 0) {
      bands.push({
        tone: before + after >= 0 ? "over" : "short",
        points: [
          [place, one.supply],
          [place + 1, next.supply],
          [place + 1, next.demand],
          [place, one.demand],
        ],
      });
      continue;
    }
    // They cross: where the difference comes to nothing along the stretch.
    const share = before / (before - after);
    const cross: At = [place + share, one.demand + share * (next.demand - one.demand)];
    bands.push({
      tone: before > 0 ? "over" : "short",
      points: [[place, one.supply], cross, [place, one.demand]],
    });
    bands.push({
      tone: after > 0 ? "over" : "short",
      points: [cross, [place + 1, next.supply], [place + 1, next.demand]],
    });
  }
  return bands;
}

/** The supply of one category, stacked on those before it: its lower edge and its upper. */
export interface Layer {
  category: string;
  label: string;
  lower: number[];
  upper: number[];
}

/** The supply of each week stacked by category, as recorded, the first category lowest. */
export function stackedSupply(points: readonly TrendPoint[], categories: readonly Category[]) {
  const base = points.map(() => 0);
  return categories.map(({ category, label }): Layer => {
    const lower = [...base];
    points.forEach((point, place) => {
      base[place] = (base[place] ?? 0) + (point.categories[category] ?? 0);
    });
    return { category, label, lower, upper: [...base] };
  });
}

/** The highest amount the plot has to hold: of the lines, and of the parts stacked. */
export function trendTop(points: readonly TrendPoint[]): number {
  let top = 0;
  for (const point of points) {
    const stacked = Object.values(point.categories).reduce((sum, value) => sum + value, 0);
    top = Math.max(top, point.demand, point.supply, stacked, point.infrastructure + point.other);
  }
  return top;
}

/** A path through points already in pixels: "M x y L x y …". */
export function pathThrough(points: readonly At[]): string {
  return points
    .map(([x, y], place) => `${place === 0 ? "M" : "L"}${round(x)} ${round(y)}`)
    .join(" ");
}

/** A closed shape through points already in pixels. */
export function shapeThrough(points: readonly At[]): string {
  return points.length === 0 ? "" : `${pathThrough(points)} Z`;
}

function round(value: number): string {
  return String(Math.round(value * 10) / 10);
}

/**
 * Which weeks are named under the axis: every one while there is room, and otherwise
 * every so many, the last always among them.
 */
export function namedWeeks(count: number, room: number): number[] {
  if (count <= 0) return [];
  const most = Math.max(1, Math.floor(room));
  const step = Math.max(1, Math.ceil(count / most));
  const named: number[] = [];
  for (let place = count - 1; place >= 0; place -= step) named.unshift(place);
  return named;
}
