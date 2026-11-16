// 0.8.0: the report of what circuits cost, by fiscal year (P-151). The view the report is
// of is in the address of its page; the cost of each row is the server's, worked out as
// the carrier bills a part month, and nothing is added up here.

import type { Schemas } from "../api/client";
import { filterText, viewFilter } from "./filter";
import type { Option } from "./patch";

export type CircuitCosts = Schemas["CircuitCostsOut"];
export type CircuitCostRow = Schemas["CircuitCostRow"];
export type CircuitCostsBy = CircuitCosts["by"];

/** What the report may be by: by carrier unless another is chosen. */
export const CIRCUIT_COSTS_BY: ReadonlyArray<Option & { value: CircuitCostsBy }> = [
  { value: "carrier", label: "Carrier" },
  { value: "site", label: "Site" },
  { value: "region", label: "Region" },
  { value: "group", label: "Circuit group" },
  { value: "circuit_type", label: "Type" },
  { value: "owner", label: "Owner" },
  { value: "tag", label: "Tag" },
];

export function isCircuitCostsBy(value: string): value is CircuitCostsBy {
  return CIRCUIT_COSTS_BY.some((option) => option.value === value);
}

export function circuitCostsByLabel(by: string): string {
  return CIRCUIT_COSTS_BY.find((option) => option.value === by)?.label ?? by;
}

/** What the row of the circuits that have no value of the grouping is called. */
const NONE: Readonly<Record<CircuitCostsBy, string>> = {
  carrier: "No carrier",
  site: "At no site",
  region: "In no region",
  group: "In no group",
  circuit_type: "No type",
  owner: "No owner",
  tag: "No tag",
};

/** What a row is called: its label, or what the circuits with none have none of. */
export function circuitCostsRowLabel(by: CircuitCostsBy, row: CircuitCostRow): string {
  if (row.key === null) return NONE[by];
  return row.label ?? row.key;
}

/** The view of the report, as the address of its page holds it. */
export interface CircuitCostsView {
  /** The fiscal year, named for the calendar year it ends in. Blank: the present one. */
  year: string;
  by: CircuitCostsBy;
  /** A filter of the circuit list, in the short form or as JSON. */
  filter: string;
  includeDrafts: boolean;
}

export function circuitCostsView(params: URLSearchParams): CircuitCostsView {
  const by = params.get("by") ?? "";
  const year = (params.get("year") ?? "").trim();
  return {
    year: /^\d{4}$/.test(year) ? year : "",
    by: isCircuitCostsBy(by) ? by : "carrier",
    filter: params.get("filter") ?? "",
    includeDrafts: params.get("drafts") === "1",
  };
}

export function circuitCostsParams(view: CircuitCostsView): Record<string, string> {
  return {
    ...(view.year ? { year: view.year } : {}),
    ...(view.by !== "carrier" ? { by: view.by } : {}),
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
  };
}

/** The query of `GET /reports/circuit-costs` for a view. */
export function circuitCostsQuery(view: CircuitCostsView): {
  fiscal_year?: number;
  by: CircuitCostsBy;
  filter?: string;
  include_drafts?: boolean;
} {
  return {
    ...(view.year ? { fiscal_year: Number(view.year) } : {}),
    by: view.by,
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
}

/**
 * The circuit grid on the circuits of a row, as a path of the app: the row's filter in
 * the address, as the item grid takes one. A circuit that was disconnected and retired
 * during the year counts in it, so the grid is asked for retired circuits too, greyed;
 * and for the drafts where the report counted them. A row whose filter is more than the
 * grammar takes has none, and leads nowhere; the totals of a report of every circuit have
 * none either, and lead to every circuit.
 */
export function circuitsPath(
  row: Pick<CircuitCostRow, "filter">,
  includeDrafts: boolean,
  totals = false,
): string | null {
  const filter = viewFilter(row.filter);
  if (filter === null && !totals) return null;
  const query = new URLSearchParams({ filter: filterText(filter), archived: "1" });
  if (includeDrafts) query.set("drafts", "1");
  return `/circuits?${query.toString()}`;
}
