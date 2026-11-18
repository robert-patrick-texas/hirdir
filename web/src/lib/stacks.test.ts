import { describe, expect, it } from "vitest";
import { ITEM_WORDS, parseFilter } from "./filter";
import {
  dropsOf,
  dropsText,
  groupWords,
  joinStanding,
  type LeavingRules,
  leavingBody,
  leavingPreset,
  leavingText,
  listed,
  memberText,
  namedBy,
  offeredPosition,
  refusedRows,
  sameWords,
  stackOf,
} from "./stacks";

describe("offeredPosition (P-219)", () => {
  it("offers the stack's next position, passing over those of the same request", () => {
    expect(offeredPosition(2, [1, 3, 4])).toBe(2);
    expect(offeredPosition(2, [1, 3, 4, 2])).toBe(5);
    expect(offeredPosition(2, [1, 2, null])).toBe(3);
  });

  it("offers the lowest free from 1 where the server names none, as for a new group", () => {
    expect(offeredPosition(null, [])).toBe(1);
    expect(offeredPosition(undefined, [1, 2, 4])).toBe(3);
  });
});

describe("refusedRows (P-219)", () => {
  const sent = [{ item_hid: "i-1" }, { item_hid: "i-2" }];
  const holder = { record_type: "item", hid: "i-9", label: "FCW0000X009" };

  it("puts each refusal beside the row of the item sent at its place", () => {
    const rows = refusedRows(
      sent,
      { "members.1.position": "Position 2 of the stack is held by another member." },
      holder,
    );
    expect(rows.errors).toEqual({ "i-2": "Position 2 of the stack is held by another member." });
    expect(rows.holders).toEqual({ "i-2": { to: "/items/i-9", label: "FCW0000X009" } });
  });

  it("names no holder for a refusal of another field", () => {
    const rows = refusedRows(sent, { "members.0.disposition": "Not in Prod." }, holder);
    expect(rows.errors).toEqual({ "i-1": "Not in Prod." });
    expect(rows.holders).toEqual({});
    expect(refusedRows(sent, {}, null)).toEqual({ errors: {}, holders: {} });
  });
});

describe("what joining a stack removes (P-217)", () => {
  const spare = {
    hostname: "spare-sw-017",
    fqdn: "spare-sw-017.example.net",
    addresses: [{ address: "192.0.2.17" }, { address: "2001:db8::17" }],
    location: { path: "Campus Works > Campus 40 > Spares Depot" },
    lifecycle_state: "Prod",
    disposition: "Spare",
  };

  it("lists the host name, the FQDN, each address and its own location", () => {
    expect(dropsOf(spare)).toEqual([
      "the host name spare-sw-017",
      "the FQDN spare-sw-017.example.net",
      "the address 192.0.2.17",
      "the address 2001:db8::17",
      "its own location Campus Works > Campus 40 > Spares Depot",
    ]);
    expect(dropsText("spare-sw-017", { hostname: "spare-sw-017" })).toBe(
      "Removed from spare-sw-017: the host name spare-sw-017. The stack's are in force for it.",
    );
  });

  it("says that nothing is removed from a switch that has none of them", () => {
    expect(dropsText("FCW0000X001", {})).toBe(
      "FCW0000X001 has no host name, FQDN, address or location of its own: nothing is removed.",
    );
  });

  it("offers a spare Production and expected online, where its state allows them", () => {
    expect(joinStanding(spare, ["Production", "Spare"], [true])).toEqual({
      disposition: "Production",
      online: "true",
    });
    expect(joinStanding(spare, ["Staging", "Spare", "Excess"], [false])).toEqual({
      disposition: "",
      online: "",
    });
    expect(joinStanding({ ...spare, disposition: "Production" }, ["Production"], [true])).toEqual({
      disposition: "",
      online: "",
    });
  });

  it("lists words as they are said", () => {
    expect(listed([])).toBe("");
    expect(listed(["a"])).toBe("a");
    expect(listed(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("what becomes of a member that leaves (P-218)", () => {
  const prod: LeavingRules = {
    next: ["Down", "Pending-Removal"],
    dispositions: (state) =>
      state === "Prod" ? ["Production", "Spare"] : state === "Pending-Removal" ? ["Excess"] : [],
    reasons: ["rma", "retired", "returned"],
  };

  it("fills the spare pool: Spare, not expected online, the state as it is", () => {
    expect(leavingPreset("pool", "Prod", prod)).toEqual({
      hostname: "",
      fqdn: "",
      location_hid: "",
      lifecycle_state: "",
      state_reason: "",
      disposition: "Spare",
      online: "false",
    });
  });

  it("fills a return to the manufacturer and excess with Pending-Removal and their reasons", () => {
    expect(leavingPreset("returned", "Prod", prod)).toMatchObject({
      lifecycle_state: "Pending-Removal",
      state_reason: "rma",
      disposition: "",
      online: "false",
    });
    expect(leavingPreset("excess", "Prod", prod)).toMatchObject({
      lifecycle_state: "Pending-Removal",
      state_reason: "retired",
      disposition: "Excess",
    });
    expect(leavingPreset("nothing", "Prod", prod)).toBeNull();
  });

  it("fills only what the rules allow: no move the state does not have, no reason not published", () => {
    const stuck: LeavingRules = { next: ["Released"], dispositions: () => [], reasons: [] };
    expect(leavingPreset("excess", "Pending-Removal", stuck)).toMatchObject({
      lifecycle_state: "",
      state_reason: "",
      disposition: "",
    });
    expect(leavingPreset("pool", "Down", stuck)).toMatchObject({ disposition: "" });
  });

  it("sends what is filled and leaves out what is blank, a reason only with a move", () => {
    const pool = leavingPreset("pool", "Prod", prod);
    expect(pool).not.toBeNull();
    if (!pool) return;
    const body = leavingBody({
      ...pool,
      hostname: " spare-sw-901 ",
      fqdn: "spare-sw-901.example.net",
      location_hid: "l-1",
      state_reason: "returned",
    });
    expect(body).toEqual({
      hostname: "spare-sw-901",
      fqdn: "spare-sw-901.example.net",
      location_hid: "l-1",
      disposition: "Spare",
      expected_online: false,
    });
    expect(leavingText(body)).toBe(
      "named spare-sw-901, given its place, given the disposition Spare and not expected online",
    );
    const excess = leavingPreset("excess", "Prod", prod);
    expect(excess && leavingBody(excess)).toEqual({
      lifecycle_state: "Pending-Removal",
      state_reason: "retired",
      disposition: "Excess",
      expected_online: false,
    });
  });
});

describe("groupWords", () => {
  it("finds the words the plain words of the item list look for in the groups' names", () => {
    const read = parseFilter("cw07-idf03-acc1 FCW9", ITEM_WORDS);
    expect(read.ok).toBe(true);
    const words = read.ok ? groupWords(read.filter) : [];
    expect(words).toEqual(["cw07-idf03-acc1", "FCW9"]);
  });

  it("takes each word once, a condition of the short form too, and nothing blank", () => {
    expect(
      groupWords({
        and: [
          { field: "group.name", op: "eq", value: "core-pair" },
          { or: [{ field: "group.name", op: "contains", value: "core-pair" }] },
          { field: "group.name", op: "contains", value: "  " },
          { field: "group.name", op: "prefix", value: "edge" },
          { field: "hostname", op: "contains", value: "edge" },
        ],
      }),
    ).toEqual(["core-pair"]);
    expect(groupWords(null)).toEqual([]);
  });
});

describe("namedBy", () => {
  it("finds a group whose name or host name is one of the words", () => {
    expect(namedBy(["cw07-idf03-acc1"])).toEqual({
      or: [
        { field: "name", op: "eq", value: "cw07-idf03-acc1" },
        { field: "hostname", op: "eq", value: "cw07-idf03-acc1" },
      ],
    });
    expect(namedBy([])).toBeNull();
  });
});

describe("sameWords", () => {
  it("is true for the same words in the same order", () => {
    expect(sameWords(["a", "b"], ["a", "b"])).toBe(true);
    expect(sameWords(["a", "b"], ["b", "a"])).toBe(false);
    expect(sameWords([], ["a"])).toBe(false);
  });
});

describe("memberText", () => {
  const stack = { group_hid: "g-1", name: "cw07-idf03-acc1", type: "stack", position: 2 };
  const custom = { group_hid: "g-2", name: "lab-switches", type: "custom", position: null };

  it("names a member by its stack and its position", () => {
    expect(memberText([custom, stack])).toBe("cw07-idf03-acc1 #2");
    expect(memberText([{ ...stack, position: null }])).toBe("cw07-idf03-acc1");
  });

  it("is blank for an item in no stack", () => {
    expect(memberText([custom])).toBe("");
    expect(stackOf([custom])).toBeUndefined();
  });
});
