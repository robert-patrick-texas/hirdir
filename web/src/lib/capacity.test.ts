import { describe, expect, it } from "vitest";
import {
  balanceTone,
  balanceWords,
  type CapacityView,
  capacityLinePath,
  MEASURES,
  measureText,
  SIDES,
  supplyCategories,
} from "./capacity";

const choice = (value: string, label: string, active = true) => ({
  hid: `c-${value}`,
  list: "capacity_category",
  value,
  label,
  sort: 0,
  active,
  row_version: 1,
  created_at: "2026-01-31T19:05:09Z",
  updated_at: "2026-01-31T19:05:09Z",
});

const CHOICES = [
  choice("staff", "Staff"),
  choice("professional_services", "Professional services"),
  choice("smart_hands", "Smart hands"),
  choice("tools", "Tools"),
  choice("services", "Services"),
  choice("other_work", "Other work"),
  choice("interns", "Interns", false),
  { ...choice("rma", "RMA"), list: "replacement_reason" },
];

/** The worked example of the data model page: demand 10, supply 9. */
const example: CapacityView = {
  support_weight: "2400",
  infrastructure_demand: "8",
  other_demand: "2",
  demand: "10",
  supply: "9",
  balance: "-1",
  coverage_pct: "90",
  own_units: "6",
  own_share_pct: "66.67",
  outside_units: "3",
  annual_cost: "57000.00",
  by_category: [],
};

describe("the categories of a supply line", () => {
  it("are the active values of the list, without the one that is of the demand side", () => {
    expect(supplyCategories(CHOICES).map((option) => option.value)).toEqual([
      "staff",
      "professional_services",
      "smart_hands",
      "tools",
      "services",
    ]);
  });

  it("offer the one a line already holds, though it is no longer active", () => {
    expect(supplyCategories(CHOICES, "interns").map((option) => option.value)).toContain("interns");
    expect(supplyCategories(undefined)).toEqual([]);
  });

  it("are of one side or the other", () => {
    expect(SIDES.map((side) => side.value)).toEqual(["supply", "demand"]);
  });
});

describe("the measures of a view of the balance", () => {
  it("are every number the server answers for a view, each once", () => {
    const keys = MEASURES.map((measure) => measure.key).sort();
    const answered = Object.keys(example)
      .filter((key) => key !== "by_category")
      .sort();
    expect(keys).toEqual(answered);
  });

  it("put demand before supply, and the balance and the coverage after both", () => {
    const order = MEASURES.map((measure) => measure.key);
    expect(order.indexOf("demand")).toBeLessThan(order.indexOf("supply"));
    expect(order.indexOf("supply")).toBeLessThan(order.indexOf("balance"));
    expect(order.indexOf("balance")).toBeLessThan(order.indexOf("coverage_pct"));
  });

  it("are written with the digits the server sent", () => {
    expect(measureText("9", "units")).toBe("9");
    expect(measureText("66.67", "percent")).toBe("66.67%");
    expect(measureText("57000.00", "money")).toBe("57,000.00");
    expect(measureText("2400", "weight")).toBe("2,400");
  });

  it("write a shortfall with a minus sign, and a blank coverage as a dash", () => {
    expect(measureText("-1", "units")).toBe("−1");
    expect(measureText("-1234.5", "units")).toBe("−1,234.5");
    expect(measureText(null, "percent")).toBe("—");
    expect(measureText("", "percent")).toBe("—");
  });
});

describe("how a balance stands", () => {
  it("is short when demand is more than supply", () => {
    expect(balanceTone(example.balance)).toBe("short");
    expect(balanceWords("-0.5")).toContain("Short");
  });

  it("is even at zero, however it is written", () => {
    expect(balanceTone("0")).toBe("even");
    expect(balanceTone("0.00")).toBe("even");
    expect(balanceTone("-0.00")).toBe("even");
    expect(balanceWords("0")).toBe("Supply meets demand");
  });

  it("is over when supply is more than demand", () => {
    expect(balanceTone("6.89")).toBe("over");
    expect(balanceWords("6.89")).toBe("Supply is more than demand");
  });
});

describe("capacityLinePath", () => {
  it("leads to a line by its HID", () => {
    expect(capacityLinePath("l-1")).toBe("/capacity/l-1");
  });
});
