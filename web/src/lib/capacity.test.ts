import { describe, expect, it } from "vitest";
import {
  balanceTone,
  balanceWords,
  type CapacityLine,
  type CapacityReport,
  type CapacityView,
  capacityLinePath,
  EFFECTS,
  lineForForm,
  MEASURES,
  MULTIPLYING_CATEGORIES,
  measureText,
  multiplies,
  regionRows,
  SIDES,
  staffLineOptions,
  supplyCategories,
  targetsText,
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
  multiplying_lines: [],
  demand_by_region: [],
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
      .filter((key) => !["by_category", "multiplying_lines", "demand_by_region"].includes(key))
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

function line(name: string, more: Partial<CapacityLine> = {}): CapacityLine {
  return {
    hid: `l-${name}`,
    side: "supply",
    category: "staff",
    category_label: "Staff",
    name,
    effect: "add",
    quantity: "1",
    units_each: "1",
    units: "1",
    factor: null,
    share: null,
    applies_to: [],
    in_date: true,
    annual_cost: null,
    vendor: null,
    vendor_hid: null,
    region: null,
    region_hid: null,
    site: null,
    site_hid: null,
    starts_on: null,
    ends_on: null,
    notes: null,
    record_status: "active",
    row_version: 1,
    created_at: "2026-11-02T14:00:00Z",
    updated_at: "2026-11-02T14:00:00Z",
    ...more,
  };
}

describe("a line that multiplies", () => {
  const lines = [
    line("Network engineer"),
    line("Junior network engineer", { record_status: "draft" }),
    line("Retired engineer", { record_status: "retired" }),
    line("Escalation partner", { category: "professional_services" }),
    line("AI assistant", { category: "tools", effect: "multiply" }),
    line("Site consolidation project", { side: "demand", category: "other_work" }),
  ];

  it("is a tool or a service, and is told from a line that adds", () => {
    expect(EFFECTS.map((effect) => effect.value)).toEqual(["add", "multiply"]);
    expect(MULTIPLYING_CATEGORIES).toEqual(["tools", "services"]);
    expect(multiplies(line("x", { effect: "multiply" }))).toBe(true);
    expect(multiplies(line("x"))).toBe(false);
  });

  it("works on the staff lines that add and are not retired, drafts among them", () => {
    expect(staffLineOptions(lines)).toEqual([
      { value: "l-Network engineer", label: "Network engineer" },
      { value: "l-Junior network engineer", label: "Junior network engineer (draft)" },
    ]);
  });

  it("keeps the lines it works on already, whatever they are now", () => {
    const assistant = line("AI assistant", {
      effect: "multiply",
      applies_to: [{ hid: "l-Retired engineer", name: "Retired engineer" }],
    });
    expect(staffLineOptions(lines, assistant).map((option) => option.label)).toContain(
      "Retired engineer",
    );
    expect(lineForForm(assistant).applies_to).toEqual(["l-Retired engineer"]);
  });

  it("names the lines it works on with their units where they count", () => {
    const multiplying = {
      hid: "l-ai",
      name: "AI assistant",
      category: "services",
      factor: "1.25",
      share: "0.5",
      base_units: "4.8",
      units: "0.6",
      applies_to: [
        { hid: "l-1", name: "Network engineer", counted: true, units: "3" },
        { hid: "l-2", name: "Retired engineer", counted: false, units: "0" },
      ],
    };
    expect(targetsText(multiplying)).toBe("Network engineer (3), Retired engineer");
  });
});

describe("the demand of each region", () => {
  const region = (path: string | null, weight: string, parent: string | null = null) => ({
    region_hid: path ? `r-${path}` : null,
    parent_region_hid: parent,
    path,
    support_weight: weight,
    infrastructure_demand: String(Number(weight) / 300),
    share_pct: "25",
  });
  const report: CapacityReport = {
    as_of: "2026-11-15",
    weight_per_resource_unit: "300",
    active: {
      ...example,
      demand_by_region: [region("Americas", "1800"), region(null, "120")],
    },
    with_drafts: {
      ...example,
      demand_by_region: [
        region("Americas", "1800"),
        region("Americas > Central", "600", "r-Americas"),
        region("Europe", "480"),
        region(null, "150"),
      ],
    },
  };

  it("is one row for each region of either view, by path, and what is nowhere last", () => {
    const rows = regionRows(report);
    expect(rows.map((row) => row.path)).toEqual(["Americas", "Americas > Central", "Europe", null]);
    expect(rows.map((row) => row.depth)).toEqual([0, 1, 0, 0]);
  });

  it("holds each view's own figures, and none where a view has no such row", () => {
    const [americas, central, , nowhere] = regionRows(report);
    expect(americas?.active?.support_weight).toBe("1800");
    expect(central?.active).toBeNull();
    expect(central?.drafts?.support_weight).toBe("600");
    expect(nowhere?.key).toBe("");
    expect(nowhere?.active?.support_weight).toBe("120");
    expect(nowhere?.drafts?.support_weight).toBe("150");
  });
});
