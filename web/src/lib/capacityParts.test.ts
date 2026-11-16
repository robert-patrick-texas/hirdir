// 0.8.0: the support weight in its parts, and a balance tried beside the one in force
// (P-155, P-156). Every number here is invented.

import { describe, expect, it } from "vitest";
import type { CapacityReport, CapacityView } from "./capacity";
import { compareRows, partRows } from "./capacityParts";

function view(more: Partial<CapacityView> = {}): CapacityView {
  return {
    support_weight: "2409",
    items_weight: "2400",
    places_weight: "6",
    circuits_weight: "3",
    defaulted: { items: 12, sites: 2, circuits: 0 },
    raised: { items: 3, sites: 0, circuits: 1 },
    infrastructure_demand: "8.03",
    other_demand: "2",
    demand: "10.03",
    supply: "9",
    balance: "-1.03",
    coverage_pct: "89.73",
    own_units: "6",
    own_share_pct: "66.67",
    outside_units: "3",
    annual_cost: "0.00",
    by_category: [
      { category: "staff", label: "Staff", lines: 3, units: "6", annual_cost: "0.00" },
      { category: "tools", label: "Tools", lines: 1, units: "3", annual_cost: "0.00" },
    ],
    multiplying_lines: [],
    demand_by_region: [],
    ...more,
  };
}

function report(active: Partial<CapacityView> = {}, drafts: Partial<CapacityView> = {}) {
  return {
    as_of: "2026-11-14",
    weight_per_resource_unit: "300",
    active: view(active),
    with_drafts: view(drafts),
  } satisfies CapacityReport;
}

describe("the parts of the support weight", () => {
  it("are the items, the places and the circuits, each with its counts, in both views", () => {
    const rows = partRows(
      report({}, { places_weight: "9", defaulted: { items: 12, sites: 3, circuits: 0 } }),
    );
    expect(
      rows.map((row) => [row.key, row.active.weight, row.active.defaulted, row.active.raised]),
    ).toEqual([
      ["items", "2400", 12, 3],
      ["places", "6", 2, 0],
      ["circuits", "3", 0, 1],
    ]);
    expect(rows[1]?.drafts).toEqual({ weight: "9", defaulted: 3, raised: 0 });
    expect(rows[1]?.counted).toBe("sites");
  });
});

describe("the balance tried beside the one in force", () => {
  it("sets every figure of both side by side, and marks what differs", () => {
    const inForce = report();
    const tried = {
      ...report(
        {
          places_weight: "16",
          support_weight: "2419",
          defaulted: { items: 12, sites: 4, circuits: 0 },
          balance: "1.06",
          by_category: [
            { category: "staff", label: "Staff", lines: 4, units: "8", annual_cost: "0.00" },
            { category: "tools", label: "Tools", lines: 1, units: "3", annual_cost: "0.00" },
          ],
        },
        {},
      ),
      weight_per_resource_unit: "250",
    };
    const rows = compareRows(inForce, tried);
    const byKey = new Map(rows.map((row) => [row.key, row]));
    expect(byKey.get("weight_per_resource_unit")).toMatchObject({
      inForce: { active: "300", drafts: "300" },
      tried: { active: "250", drafts: "250" },
      differs: true,
    });
    expect(byKey.get("places_weight")).toMatchObject({
      inForce: { active: "6", drafts: "6" },
      tried: { active: "16", drafts: "6" },
      differs: true,
    });
    expect(byKey.get("defaulted.sites")).toMatchObject({
      label: "Sites counted at a default",
      kind: "count",
      inForce: { active: "2" },
      tried: { active: "4" },
      differs: true,
    });
    expect(byKey.get("raised.circuits")?.differs).toBe(false);
    expect(byKey.get("category.staff")).toMatchObject({
      label: "Supply: Staff",
      tried: { active: "8", drafts: "6" },
      differs: true,
    });
    expect(byKey.get("category.tools")?.differs).toBe(false);
    expect(byKey.get("supply")?.differs).toBe(false);
    // One row for each figure, once.
    expect(new Set(rows.map((row) => row.key)).size).toBe(rows.length);
  });
});
