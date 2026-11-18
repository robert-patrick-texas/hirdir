import { describe, expect, it } from "vitest";
import { parseShort } from "./filter";
import { minorWhat, sparesPath } from "./minor";

const psu = {
  catalog_entry_hid: "CE-0001",
  catalog: { pid: "EX-PSU-650", model_name: "Example 650 W supply", type: "power-supply" },
  position: "PS1",
  parent: { hid: "IT-0001" },
  effective: { location_hid: { site: "Example North", site_hid: "ST-0001" } },
};

describe("the line under the heading of a minor item (P-216)", () => {
  it("names its type and its model", () => {
    expect(minorWhat(psu, "Power supply")).toBe("Power supply · EX-PSU-650, Example 650 W supply");
    expect(minorWhat({ catalog: { ...psu.catalog, model_name: null } }, "")).toBe("EX-PSU-650");
    expect(minorWhat({ catalog: null }, "Power supply")).toBe("");
  });

  it("leads to the spares of its model at its site, minor items among them", () => {
    const path = sparesPath(psu);
    expect(path).not.toBeNull();
    const url = new URL(path ?? "", "http://example.net");
    expect(url.pathname).toBe("/items");
    expect(url.searchParams.get("minor")).toBe("1");
    expect(parseShort(url.searchParams.get("filter") ?? "")).toEqual({
      ok: true,
      filter: {
        and: [
          { field: "catalog_entry_hid", op: "eq", value: "CE-0001" },
          { field: "site_hid", op: "eq", value: "ST-0001" },
          { field: "effective.disposition", op: "eq", value: "Spare" },
        ],
      },
    });
  });

  it("has no such link for an item with no model or no site", () => {
    expect(sparesPath({ ...psu, catalog_entry_hid: null })).toBeNull();
    expect(
      sparesPath({ ...psu, effective: { location_hid: { site: null, site_hid: null } } }),
    ).toBe(null);
  });
});
