// 0.8.0: the view of the report of what circuits cost, and where each row leads (P-151).
// Every name and number here is invented.

import { describe, expect, it } from "vitest";
import {
  type CircuitCostRow,
  circuitCostsParams,
  circuitCostsQuery,
  circuitCostsRowLabel,
  circuitCostsView,
  circuitsPath,
} from "./circuitCosts";

const CARRIER = "0193a1f4-0000-7000-8000-00000000e001";
const SITE = "0193a1f4-0000-7000-8000-00000000e002";

function row(more: Partial<CircuitCostRow>): CircuitCostRow {
  return {
    key: CARRIER,
    label: "Example Telecom",
    circuits: 2,
    cost: "8700.00",
    monthly_cost: "1000.00",
    annual_cost: "12000.00",
    filter: { field: "billed_by", op: "eq", value: CARRIER },
    ...more,
  };
}

describe("the view of the report", () => {
  it("is of the present year, by carrier, unless the address says otherwise", () => {
    expect(circuitCostsView(new URLSearchParams())).toEqual({
      year: "",
      by: "carrier",
      filter: "",
      includeDrafts: false,
    });
    const asked = circuitCostsView(
      new URLSearchParams({ year: "2027", by: "site", filter: "name:contains:wan", drafts: "1" }),
    );
    expect(asked).toEqual({
      year: "2027",
      by: "site",
      filter: "name:contains:wan",
      includeDrafts: true,
    });
    expect(circuitCostsQuery(asked)).toEqual({
      fiscal_year: 2027,
      by: "site",
      filter: "name:contains:wan",
      include_drafts: true,
    });
    expect(circuitCostsParams(asked)).toEqual({
      year: "2027",
      by: "site",
      filter: "name:contains:wan",
      drafts: "1",
    });
  });

  it("takes no grouping it does not know, nor a year that is not one", () => {
    const view = circuitCostsView(new URLSearchParams({ by: "vendor", year: "27" }));
    expect(view.by).toBe("carrier");
    expect(view.year).toBe("");
    expect(circuitCostsParams(view)).toEqual({});
    expect(circuitCostsQuery(view)).toEqual({ by: "carrier" });
  });
});

describe("a row of the report", () => {
  it("is called by its label, and the row of what has none by what it has none of", () => {
    expect(circuitCostsRowLabel("carrier", row({}))).toBe("Example Telecom");
    expect(circuitCostsRowLabel("carrier", row({ key: null, label: null }))).toBe("No carrier");
    expect(circuitCostsRowLabel("group", row({ key: null, label: null }))).toBe("In no group");
  });

  it("leads to the circuits it counted, in the view the report says its filters are of", () => {
    const view = { include_archived: true, include_drafts: false };
    expect(circuitsPath(row({}), view)).toBe(
      `/circuits?filter=${encodeURIComponent(`billed_by:eq:${CARRIER}`)}&archived=1`,
    );
    const both = row({
      filter: {
        and: [
          { field: "name", op: "contains", value: "wan" },
          { field: "cost_site_hid", op: "eq", value: SITE },
        ],
      },
    });
    // A space of the short form is written as the address writes one.
    expect(circuitsPath(both, { include_archived: true, include_drafts: true })).toBe(
      `/circuits?filter=name%3Acontains%3Awan+cost_site_hid%3Aeq%3A${SITE}&archived=1&drafts=1`,
    );
    expect(circuitsPath(row({}), { include_archived: false, include_drafts: false })).toBe(
      `/circuits?filter=${encodeURIComponent(`billed_by:eq:${CARRIER}`)}`,
    );
  });

  it("hands on a filter the short form cannot say as a tree", () => {
    const window = {
      and: [
        { field: "billed_by", op: "eq", value: CARRIER },
        {
          or: [
            { field: "a_activated_on", op: "empty", value: true },
            { field: "a_activated_on", op: "lte", value: "2025-12-31" },
          ],
        },
      ],
    };
    const path = circuitsPath(row({ filter: window }), {
      include_archived: true,
      include_drafts: false,
    });
    const asked = new URLSearchParams(path?.split("?")[1] ?? "");
    expect(JSON.parse(asked.get("filter") ?? "")).toEqual(window);
    expect(asked.get("archived")).toBe("1");
  });

  it("leads nowhere without a filter", () => {
    expect(
      circuitsPath(row({ filter: null }), { include_archived: true, include_drafts: false }),
    ).toBeNull();
  });
});
