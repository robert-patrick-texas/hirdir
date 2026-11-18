import { describe, expect, it } from "vitest";
import {
  entryLabel,
  entrySearch,
  entrySeen,
  firstThen,
  itemSearch,
  MAJOR_ONLY,
  memberOffer,
  offered,
  pickLabel,
  placeText,
  sawEntries,
} from "./pick";

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

describe("entrySearch", () => {
  it("is no search for blank text", () => {
    expect(entrySearch("  ")).toBeNull();
  });

  it("looks for each word in the PID, the model name and the vendor's name", () => {
    const where = (value: string) => ({
      or: [
        { field: "pid", op: "contains", value },
        { field: "model_name", op: "contains", value },
        { field: "vendor", op: "contains", value },
      ],
    });
    expect(entrySearch("48P")).toEqual(where("48P"));
    expect(entrySearch(" sample  48P ")).toEqual({ and: [where("sample"), where("48P")] });
  });
});

describe("entryLabel", () => {
  it("puts the vendor beside the PID, then the model", () => {
    const vendor = { hid: "v-1", name: "Sample Networks" };
    expect(entryLabel({ pid: "SN-48P", model_name: "Edge Switch", vendor })).toBe(
      "SN-48P · Sample Networks · Edge Switch",
    );
    expect(entryLabel({ pid: "SN-48P", model_name: null, vendor: "Sample Networks" })).toBe(
      "SN-48P · Sample Networks",
    );
  });
});

describe("sawEntries", () => {
  it("keeps the entries a search offered, by HID", () => {
    const entry = { hid: "e-1", pid: "SN-48P", vendor: { hid: "v-1", name: "Sample Networks" } };
    expect(entrySeen("e-1")).toBeUndefined();
    sawEntries([entry]);
    expect(entrySeen("e-1")).toBe(entry);
  });
});

describe("firstThen", () => {
  it("puts the first search's items first, each item once, at most the limit", () => {
    const spares = [{ hid: "s-2" }, { hid: "s-9" }];
    const every = [{ hid: "a-1" }, { hid: "s-2" }, { hid: "b-3" }, { hid: "s-9" }];
    expect(firstThen(spares, every, 8).map((item) => item.hid)).toEqual([
      "s-2",
      "s-9",
      "a-1",
      "b-3",
    ]);
    expect(firstThen(spares, every, 3).map((item) => item.hid)).toEqual(["s-2", "s-9", "a-1"]);
    expect(firstThen([], every, 2).map((item) => item.hid)).toEqual(["a-1", "s-2"]);
  });
});

describe("placeText", () => {
  it("says where a place is without its region", () => {
    expect(placeText("Campus Works > Campus 07 > IDF 03")).toBe("Campus 07 > IDF 03");
    expect(placeText("Campus Works")).toBe("Campus Works");
    expect(placeText(null)).toBe("");
  });
});

describe("memberOffer", () => {
  const spare = {
    lifecycle_state: "Prod",
    effective: {
      disposition: { value: "Spare" },
      location_hid: { label: "Campus Works > Campus 40 > Spares Depot" },
    },
    groups: [],
  };
  const member = {
    lifecycle_state: "Prod",
    effective: {
      disposition: { value: "Production" },
      location_hid: { label: "Campus Works > Campus 07 > IDF 03" },
    },
    groups: [
      { name: "cw07-idf03-acc1", type: "stack", position: 2 },
      { name: "lab-switches", type: "custom", position: null },
    ],
  };

  it("says a candidate's state, disposition and place, and that it may be chosen", () => {
    expect(memberOffer(spare, "stack")).toEqual({
      facts: "Prod · Spare · Campus 40 > Spares Depot",
      refused: "",
    });
  });

  it("names the stack a candidate is in with its position, and refuses it for another stack", () => {
    const said = memberOffer(member, "stack");
    expect(said.facts).toBe(
      "Prod · Production · Campus 07 > IDF 03 · member 2 of the stack cw07-idf03-acc1",
    );
    expect(said.refused).toBe(
      "It is in the stack cw07-idf03-acc1 already: an item is in one stack at a time. End that membership first.",
    );
  });

  it("lets a member of a stack be chosen for a group of another type", () => {
    expect(memberOffer(member, "cluster").refused).toBe("");
    expect(memberOffer(member, "custom").refused).toBe("");
  });

  it("refuses an item in a state that joins no group, and says where an item with none is", () => {
    const released = { lifecycle_state: "Released", effective: null, groups: [] };
    expect(memberOffer(released, "custom")).toEqual({
      facts: "Released · no location",
      refused: "An item in Released joins no group.",
    });
  });
});
