import { describe, expect, it } from "vitest";
import { newItemJoining, replaceWaits } from "./replacing";

describe("what a new item made in Replace is known by (P-242, P-243)", () => {
  it("holds what is typed, and nothing blank", () => {
    expect(
      newItemJoining({
        hostname: " site2-sw-new01 ",
        serial_number: "EXS0001",
        catalog_entry_hid: "0193a1f4-0401",
        name: "",
        asset_tag: "   ",
      }),
    ).toEqual({
      hostname: "site2-sw-new01",
      serial_number: "EXS0001",
      catalog_entry_hid: "0193a1f4-0401",
    });
  });
});

describe("Replace waits for an item a stack would leave with nothing to be known by", () => {
  const alone = { drop: true, joining: newItemJoining({ hostname: "site2-sw-new01" }) };

  it("waits in a stack for one known by its host name alone that takes the stack's name", () => {
    expect(replaceWaits(true, alone)).toBe(true);
  });

  it("does not wait for a new item with a serial number and its model, or a name", () => {
    const serial = newItemJoining({
      hostname: "site2-sw-new01",
      serial_number: "EXS0001",
      catalog_entry_hid: "0193a1f4-0401",
    });
    expect(replaceWaits(true, { drop: true, joining: serial })).toBe(false);
    expect(
      replaceWaits(true, {
        drop: true,
        joining: newItemJoining({ hostname: "site2-sw-new01", name: "New 01" }),
      }),
    ).toBe(false);
  });

  it("does not wait where the box is unticked, or out of a stack", () => {
    expect(replaceWaits(true, { ...alone, drop: false })).toBe(false);
    expect(replaceWaits(false, alone)).toBe(false);
    expect(replaceWaits(true, null)).toBe(false);
  });
});
