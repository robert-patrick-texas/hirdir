import { describe, expect, it } from "vitest";
import {
  amountText,
  byLabel,
  conditionLabel,
  countText,
  isBy,
  isManagementBy,
  kindLabel,
  kindsShown,
  MANAGEMENT_BY,
  rowLabel,
  SUMMARY_BY,
  settingList,
  summaryQuery,
} from "./summary";

const OWNER = "0193a1f4-0000-7000-8000-000000000001";
const CHOICES = [
  {
    hid: "c-1",
    list: "catalog_type",
    value: "access-point",
    label: "Access point",
    sort: 1,
    active: true,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  },
  {
    hid: "c-2",
    list: "item_condition",
    value: "suspect",
    label: "Suspect",
    sort: 4,
    active: true,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  },
];
const KINDS = [
  { key: "hardware", label: "hardware", items: 46, component_count: 42 },
  { key: "virtual_machine", label: "virtual_machine", items: 3, component_count: 3 },
  { key: "software", label: "software", items: 5, component_count: 4 },
  { key: "service", label: "service", items: 2, component_count: 2 },
];

describe("what a summary is by", () => {
  it("offers the ten groupings the server has", () => {
    expect(SUMMARY_BY.map((by) => by.value)).toEqual([
      "vendor",
      "kind",
      "type",
      "function",
      "owner",
      "lifecycle_state",
      "disposition",
      "condition",
      "health",
      "tag",
    ]);
    expect(isBy("owner")).toBe(true);
    expect(isBy("health")).toBe(true);
    expect(isBy("site")).toBe(false);
    expect(byLabel("lifecycle_state")).toBe("Lifecycle state");
    expect(byLabel(null)).toBe("");
  });

  it("offers the management report its six, with neither condition nor health", () => {
    expect(MANAGEMENT_BY.map((by) => by.value)).toEqual([
      "vendor",
      "kind",
      "type",
      "function",
      "owner",
      "tag",
    ]);
    expect(isManagementBy("vendor")).toBe(true);
    expect(isManagementBy("health")).toBe(false);
    expect(isManagementBy("condition")).toBe(false);
    expect(isManagementBy("lifecycle_state")).toBe(false);
    // By site arrives with sites.
    expect(isManagementBy("site")).toBe(false);
  });
});

describe("rowLabel", () => {
  it("shows a record by what people call it", () => {
    expect(rowLabel("owner", { key: OWNER, label: "Network Engineering" })).toBe(
      "Network Engineering",
    );
    expect(rowLabel("lifecycle_state", { key: "Prod", label: "Prod" })).toBe("Prod");
  });

  it("shows a kind, a type and a function by the label of the value", () => {
    expect(rowLabel("kind", { key: "virtual_machine", label: "virtual_machine" })).toBe(
      "Virtual machine",
    );
    expect(rowLabel("type", { key: "access-point", label: "access-point" }, CHOICES)).toBe(
      "Access point",
    );
    expect(rowLabel("function", { key: "core", label: "core" }, CHOICES)).toBe("core");
  });

  it("shows a condition by the label of its list, and a health by its word", () => {
    expect(rowLabel("condition", { key: "suspect", label: "suspect" }, CHOICES)).toBe("Suspect");
    expect(rowLabel("condition", { key: null, label: null }, CHOICES)).toBe("No condition");
    expect(rowLabel("health", { key: "degraded", label: "degraded" })).toBe("Degraded");
    expect(rowLabel("health", { key: "unknown", label: null })).toBe("Unknown");
  });

  it("names the components of one condition in the totals", () => {
    expect(conditionLabel({ key: "suspect", label: "Suspect" }, CHOICES)).toBe("Suspect");
    expect(conditionLabel({ key: "suspect", label: null }, CHOICES)).toBe("Suspect");
    expect(conditionLabel({ key: "burnt", label: null }, CHOICES)).toBe("burnt");
    expect(conditionLabel({ key: null, label: null }, CHOICES)).toBe("No condition");
  });

  it("says what the items of the blank row lack", () => {
    expect(rowLabel("owner", { key: null, label: null })).toBe("No owner");
    expect(rowLabel("tag", { key: null, label: null })).toBe("No tag");
    expect(rowLabel("lifecycle_state", { key: null, label: null })).toBe("No state");
  });

  it("falls back on the key when the server sent no label", () => {
    expect(rowLabel("vendor", { key: OWNER, label: null })).toBe(OWNER);
  });
});

describe("summaryQuery", () => {
  it("leaves out what is blank or off", () => {
    expect(
      summaryQuery({ filter: " ", by: "", includeArchived: false, includeDrafts: false }),
    ).toEqual({});
  });

  it("sends the filter as it was typed, with what the view is by and the switches", () => {
    expect(
      summaryQuery({
        filter: " tags:has:refresh-2030 ",
        by: "owner",
        includeArchived: true,
        includeDrafts: true,
      }),
    ).toEqual({
      filter: "tags:has:refresh-2030",
      by: "owner",
      include_archived: true,
      include_drafts: true,
    });
  });

  it("is the query of the management report too", () => {
    expect(
      summaryQuery<"vendor" | "tag">({
        filter: "catalog.kind:eq:hardware",
        by: "vendor",
        includeArchived: false,
        includeDrafts: false,
      }),
    ).toEqual({ filter: "catalog.kind:eq:hardware", by: "vendor" });
  });
});

describe("the kinds beside the headline", () => {
  it("reads a setting that is a list of words", () => {
    const settings = [
      { key: "currency", value: "USD" },
      { key: "count_kinds", value: ["hardware", "virtual_machine"] },
    ];
    expect(settingList(settings, "count_kinds")).toEqual(["hardware", "virtual_machine"]);
    expect(settingList(settings, "currency")).toBeNull();
    expect(settingList(undefined, "count_kinds")).toBeNull();
  });

  it("splits the kinds as the setting has them", () => {
    const shown = kindsShown(KINDS, ["hardware", "virtual_machine"]);
    expect(shown.counted.map((kind) => kind.key)).toEqual(["hardware", "virtual_machine"]);
    expect(shown.beside.map((kind) => kind.key)).toEqual(["software", "service"]);
  });

  it("puts the items of no kind beside the headline", () => {
    const none = { key: null, label: null, items: 2, component_count: 2 };
    const shown = kindsShown([...KINDS, none], ["hardware"]);
    expect(shown.counted.map((kind) => kind.key)).toEqual(["hardware"]);
    expect(shown.beside).toContain(none);
    expect(kindLabel(null)).toBe("No kind");
  });

  it("claims no kind for the headline when the setting is not known", () => {
    const shown = kindsShown(KINDS, null);
    expect(shown.counted).toEqual([]);
    expect(shown.beside).toHaveLength(4);
  });

  it("names a kind for people", () => {
    expect(kindLabel("virtual_machine")).toBe("Virtual machine");
    expect(kindLabel("appliance")).toBe("appliance");
  });
});

describe("numbers on the page", () => {
  it("marks the thousands of a count", () => {
    expect(countText(42)).toBe("42");
    expect(countText(50000)).toBe("50,000");
  });

  it("marks the thousands of an amount and keeps every digit the server sent", () => {
    expect(amountText("18000.00")).toBe("18,000.00");
    expect(amountText("2.80")).toBe("2.80");
    expect(amountText("1234567.50")).toBe("1,234,567.50");
    expect(amountText("900719925474099312345.67")).toBe("900,719,925,474,099,312,345.67");
    expect(amountText("0.00")).toBe("0.00");
  });

  it("shows what is no amount as it came, and nothing for nothing", () => {
    expect(amountText("n/a")).toBe("n/a");
    expect(amountText(null)).toBe("");
    expect(amountText("")).toBe("");
  });
});
