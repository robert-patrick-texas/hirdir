import { describe, expect, it } from "vitest";
import {
  type Effective,
  effectiveText,
  inheritHint,
  isInherited,
  sourceHint,
  sourceLabel,
} from "./effective";

const ENTRY = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22";
const fromCatalog: Effective = { value: "18000.00", source: "catalog", source_hid: ENTRY };
const own: Effective = {
  value: "21000.50",
  source: "own",
  source_hid: "0193a1f4-0000-7000-8000-000000000001",
};
const fromSetting: Effective = { value: "50", source: "setting", source_hid: null };
const nothing: Effective = { value: null, source: "none", source_hid: null };

describe("values in force", () => {
  it("shows the value as the server sent it, digit for digit", () => {
    expect(effectiveText(fromCatalog)).toBe("18000.00");
    expect(effectiveText(own)).toBe("21000.50");
    expect(effectiveText(nothing)).toBe("");
    expect(effectiveText(undefined)).toBe("");
  });

  it("calls a value inherited when it came from anywhere but the record itself", () => {
    expect(isInherited(fromCatalog)).toBe(true);
    expect(isInherited(fromSetting)).toBe(true);
    expect(isInherited({ value: "Room 102", source: "parent_item", source_hid: ENTRY })).toBe(true);
    expect(isInherited(own)).toBe(false);
    expect(isInherited(nothing)).toBe(false);
    expect(isInherited(null)).toBe(false);
  });

  it("names the source in a table", () => {
    expect(sourceLabel(fromCatalog)).toBe("From the catalog entry");
    expect(sourceLabel(fromSetting)).toBe("From the global setting");
    expect(sourceLabel(own)).toBe("Set here");
    expect(sourceLabel(nothing)).toBe("Not set");
    expect(sourceLabel({ value: "x", source: "site", source_hid: ENTRY })).toBe("From the site");
  });

  it("names the source on hover, for an inherited value only", () => {
    expect(sourceHint(fromCatalog)).toBe("Inherited from the catalog entry");
    expect(sourceHint(fromSetting)).toBe("Inherited from the global setting");
    expect(sourceHint(own)).toBe("");
    expect(sourceHint(nothing)).toBe("");
  });
});

describe("inheritHint", () => {
  it("says what a blank inherits", () => {
    expect(inheritHint(null, fromCatalog)).toBe("Blank inherits 18000.00 from the catalog entry.");
    expect(inheritHint("", fromSetting)).toBe("Blank inherits 50 from the global setting.");
  });

  it("says that an override can be cleared", () => {
    expect(inheritHint("21000.50", null)).toBe("Set here. Clear it to inherit again.");
  });

  it("says when there is nothing to inherit", () => {
    expect(inheritHint(null, nothing)).toBe("Blank, and nothing to inherit.");
    expect(inheritHint(undefined, null)).toBe("Blank, and nothing to inherit.");
  });
});
