import { describe, expect, it } from "vitest";
import { itemSearch, MAJOR_ONLY, offered, pickLabel } from "./pick";

describe("itemSearch", () => {
  it("is no search for blank text", () => {
    expect(itemSearch("")).toBeNull();
    expect(itemSearch("   ")).toBeNull();
  });

  it("finds an item by a part of its name, its serial number or its asset tag", () => {
    expect(itemSearch(" site2-sw ")).toEqual({
      or: [
        { field: "name", op: "contains", value: "site2-sw" },
        { field: "hostname", op: "contains", value: "site2-sw" },
        { field: "serial_number", op: "contains", value: "site2-sw" },
        { field: "asset_tag", op: "contains", value: "site2-sw" },
      ],
    });
  });

  it("is narrowed by what the page asks for, as to major items", () => {
    const filter = itemSearch("FCW0000X", MAJOR_ONLY);
    expect(filter).toMatchObject({ and: [{ or: expect.any(Array) }, MAJOR_ONLY] });
  });

  it("sends no more text than a value of a filter may hold", () => {
    const filter = itemSearch("x".repeat(5000)) as { or: Array<{ value: string }> };
    expect(filter.or[0]?.value).toHaveLength(200);
  });
});

describe("pickLabel", () => {
  it("names an item with its PID and serial number", () => {
    expect(
      pickLabel({
        hid: "i-1",
        name: "site2-sw-access-01",
        serial_number: "FCW0000X001",
        catalog: { pid: "EN-4800-48P" },
      }),
    ).toBe("site2-sw-access-01 · EN-4800-48P · FCW0000X001");
  });

  it("takes the PID of an item as another record names it", () => {
    expect(pickLabel({ hid: "i-1", name: "ps-a", pid: "PWR-715", serial_number: null })).toBe(
      "ps-a · PWR-715",
    );
  });

  it("does with what there is", () => {
    expect(pickLabel({ hid: "i-1", hostname: "site2-ap-01" })).toBe("site2-ap-01");
    expect(pickLabel({ hid: "i-1", serial_number: "FCW0000X002" })).toBe("FCW0000X002");
  });
});

describe("offered", () => {
  it("leaves out the items that are taken already", () => {
    const found = [{ hid: "i-1" }, { hid: "i-2" }, { hid: "i-3" }];
    expect(offered(found, ["i-2"])).toEqual([{ hid: "i-1" }, { hid: "i-3" }]);
    expect(offered(found, [])).toHaveLength(3);
  });
});
