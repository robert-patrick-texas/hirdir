import { describe, expect, it } from "vitest";
import {
  axisTicks,
  balanceBands,
  type CapacityRecord,
  namedWeeks,
  pathThrough,
  shapeThrough,
  stackedSupply,
  trendCategories,
  trendPoints,
  trendTop,
} from "./trend";

function view(demand: string, supply: string, staff: string, tools: string) {
  const balance = (Number(supply) - Number(demand)).toFixed(2);
  return {
    support_weight: "2400",
    infrastructure_demand: "8",
    other_demand: (Number(demand) - 8).toFixed(2),
    demand,
    supply,
    balance,
    coverage_pct: null,
    own_units: staff,
    outside_units: tools,
    by_category: [
      { category: "staff", label: "Staff", lines: 2, units: staff, annual_cost: "0.00" },
      { category: "tools", label: "Tools", lines: 1, units: tools, annual_cost: "0.00" },
    ],
  };
}

function record(week: string, demand: string, supply: string, more: Partial<CapacityRecord> = {}) {
  const staff = (Number(supply) * 0.75).toFixed(2);
  const tools = (Number(supply) - Number(staff)).toFixed(2);
  return {
    hid: `r-${week}`,
    week_of: week,
    recorded_at: `${week}T05:00:00Z`,
    weight_per_resource_unit: "300",
    adjusted: false,
    note: null,
    row_version: 1,
    created_at: `${week}T05:00:00Z`,
    updated_at: `${week}T05:00:00Z`,
    active: view(demand, supply, staff, tools),
    with_drafts: view(demand, supply, staff, tools),
    ...more,
  } satisfies CapacityRecord;
}

describe("the weeks of the trend", () => {
  const records = [record("2026-11-09", "10", "11"), record("2026-11-02", "10", "9")];

  it("are the oldest first, with the figures of the view asked for", () => {
    const points = trendPoints(records, "active");
    expect(points.map((point) => point.week)).toEqual(["2026-11-02", "2026-11-09"]);
    expect(points[0]).toMatchObject({ demand: 10, supply: 9, balance: -1, infrastructure: 8 });
    expect(points[0]?.categories).toEqual({ staff: 6.75, tools: 2.25 });
    expect(points[0]?.text.balance).toBe("-1.00");
  });

  it("keep a corrected week's totals beside its parts as they were recorded", () => {
    const corrected = record("2026-11-02", "10", "9", { adjusted: true, note: "a late start" });
    corrected.active = { ...corrected.active, supply: "9.5", balance: "-0.5" };
    const [point] = trendPoints([corrected], "active");
    expect(point).toMatchObject({ adjusted: true, supply: 9.5, note: "a late start" });
    // The parts are as recorded, and no longer add up to the corrected supply.
    expect((point?.categories.staff ?? 0) + (point?.categories.tools ?? 0)).toBe(9);
    expect(trendTop(point ? [point] : [])).toBe(10);
  });

  it("name each category once, in the order the records list them", () => {
    expect(trendCategories(records, "with_drafts")).toEqual([
      { category: "staff", label: "Staff" },
      { category: "tools", label: "Tools" },
    ]);
  });
});

describe("the band of the balance", () => {
  it("lies over where supply is above demand and short where it is below", () => {
    const points = trendPoints(
      [record("2026-11-02", "10", "12"), record("2026-11-09", "10", "11")],
      "active",
    );
    expect(balanceBands(points)).toEqual([
      {
        tone: "over",
        points: [
          [0, 12],
          [1, 11],
          [1, 10],
          [0, 10],
        ],
      },
    ]);
  });

  it("is cut where the two lines cross, each part with its own tone", () => {
    const points = trendPoints(
      [record("2026-11-02", "10", "12"), record("2026-11-09", "10", "8")],
      "active",
    );
    const [first, second] = balanceBands(points);
    expect(first?.tone).toBe("over");
    expect(second?.tone).toBe("short");
    // Halfway, where 12 and 8 meet the demand of 10.
    expect(first?.points[1]).toEqual([0.5, 10]);
    expect(second?.points[0]).toEqual([0.5, 10]);
  });

  it("is nothing for a single week, or where the lines lie on each other", () => {
    expect(balanceBands(trendPoints([record("2026-11-02", "10", "12")], "active"))).toEqual([]);
    const even = trendPoints(
      [record("2026-11-02", "10", "10"), record("2026-11-09", "10", "10")],
      "active",
    );
    expect(balanceBands(even)).toEqual([]);
  });
});

describe("the supply stacked by category", () => {
  it("puts each category on the ones before it", () => {
    const records = [record("2026-11-02", "10", "8"), record("2026-11-09", "10", "12")];
    const points = trendPoints(records, "active");
    const [staff, tools] = stackedSupply(points, trendCategories(records, "active"));
    expect(staff).toMatchObject({ category: "staff", lower: [0, 0], upper: [6, 9] });
    expect(tools).toMatchObject({ category: "tools", lower: [6, 9], upper: [8, 12] });
  });
});

describe("the axes", () => {
  it("step in round amounts from nothing to the top or beyond", () => {
    expect(axisTicks(10)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(axisTicks(9.6)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(axisTicks(0.4)).toEqual([0, 0.1, 0.2, 0.3, 0.4]);
    expect(axisTicks(0)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
  });

  it("name every week while there is room, and otherwise every so many, the last among them", () => {
    expect(namedWeeks(3, 10)).toEqual([0, 1, 2]);
    expect(namedWeeks(10, 4)).toEqual([0, 3, 6, 9]);
    expect(namedWeeks(0, 4)).toEqual([]);
  });

  it("draw paths through points in pixels", () => {
    expect(
      pathThrough([
        [0, 10],
        [20.04, 5.55],
      ]),
    ).toBe("M0 10 L20 5.6");
    expect(shapeThrough([])).toBe("");
    expect(
      shapeThrough([
        [0, 0],
        [1, 1],
      ]),
    ).toBe("M0 0 L1 1 Z");
  });
});
