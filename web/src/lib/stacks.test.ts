import { describe, expect, it } from "vitest";
import { ITEM_WORDS, parseFilter } from "./filter";
import {
  dropsOf,
  dropsText,
  groupWords,
  joinedText,
  joinStanding,
  type LeavingRules,
  leavingBody,
  leavingPreset,
  leavingText,
  listed,
  madeStackText,
  makeStackGoes,
  makeStackText,
  memberText,
  namedBy,
  offeredPosition,
  refusedRows,
  replacedText,
  saidWords,
  sameWords,
  stackOf,
  withOwn,
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

  it("says what the add did: the position, what was removed and what it is now", () => {
    expect(
      joinedText(
        "cw07-idf03-acc1",
        "spare-sw-017",
        5,
        { drop_identity: true, disposition: "Production", expected_online: true },
        { hostname: "spare-sw-017", addresses: [{ address: "192.0.2.17" }] },
      ),
    ).toBe(
      "spare-sw-017 was added to cw07-idf03-acc1 as member 5. It takes the stack's name and place: the host name spare-sw-017 and the address 192.0.2.17 removed. It is Production and expected online now.",
    );
    expect(joinedText("lab-stack", "FCW0000X001", null, {}, undefined)).toBe(
      "FCW0000X001 was added to lab-stack.",
    );
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
      condition: "",
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

describe("another choice of what becomes of it keeps what was typed", () => {
  const rules: LeavingRules = {
    next: ["Pending-Removal"],
    dispositions: () => ["Production", "Spare"],
    reasons: ["rma"],
    conditions: ["good", "failed", "dead"],
  };

  it("fills only what the person has not typed or set by hand", () => {
    const returned = leavingPreset("returned", "Prod", rules);
    expect(returned).not.toBeNull();
    if (!returned) return;
    const own = { hostname: "spare-sw-901", condition: "dead" };
    expect(withOwn(returned, own)).toMatchObject({
      hostname: "spare-sw-901",
      condition: "dead",
      lifecycle_state: "Pending-Removal",
      state_reason: "rma",
    });
    // Nothing typed: the choice's own.
    expect(withOwn(returned, {})).toEqual(returned);
  });
});

describe("the condition of a member that leaves (P-245)", () => {
  const rules: LeavingRules = {
    next: ["Down", "Pending-Removal"],
    dispositions: () => ["Production", "Spare", "Excess"],
    reasons: ["rma", "retired"],
    conditions: ["good", "failed", "dead"],
  };

  it("starts a return to the manufacturer at Failed, and the others as it is", () => {
    expect(leavingPreset("returned", "Prod", rules)).toMatchObject({ condition: "failed" });
    expect(leavingPreset("pool", "Prod", rules)).toMatchObject({ condition: "" });
    expect(leavingPreset("excess", "Prod", rules)).toMatchObject({ condition: "" });
  });

  it("fills no condition the list does not publish, nor any where the form has no field", () => {
    expect(leavingPreset("returned", "Prod", { ...rules, conditions: ["good"] })).toMatchObject({
      condition: "",
    });
    const { conditions: _, ...without } = rules;
    expect(leavingPreset("returned", "Prod", without)).toMatchObject({ condition: "" });
  });

  it("sends the condition chosen, and says it by its label", () => {
    const returned = leavingPreset("returned", "Prod", rules);
    expect(returned).not.toBeNull();
    if (!returned) return;
    const body = leavingBody(returned);
    expect(body).toEqual({
      lifecycle_state: "Pending-Removal",
      state_reason: "rma",
      expected_online: false,
      condition: "failed",
    });
    expect(leavingText(body, (value) => (value === "failed" ? "Failed" : value))).toBe(
      "moved to Pending-Removal, not expected online and marked Failed",
    );
    expect(leavingBody({ ...returned, condition: "" })).not.toHaveProperty("condition");
  });
});

describe("what the answer to a replacement says (P-242)", () => {
  const old = { text: "FCW0000X002", to: "/items/o-1" };
  const came = { text: "FCW0000X091", to: "/items/n-1" };

  it("names both items as links, the place taken, what the one that came lost and is", () => {
    const parts = replacedText({
      old,
      came,
      group: "site2-sw-stack9",
      position: 2,
      sent: { drop_identity: true, disposition: "Production", expected_online: true },
      joining: { hostname: "spare-sw-091", addresses: [{ address: "192.0.2.91" }] },
      leaving: { lifecycle_state: "Pending-Removal", condition: "failed" },
      conditionLabel: () => "Failed",
    });
    expect(parts.slice(0, 3)).toEqual([old, " was replaced by ", came]);
    expect(saidWords(parts)).toBe(
      "FCW0000X002 was replaced by FCW0000X091 as member 2 of site2-sw-stack9. It takes the stack's name and place: the host name spare-sw-091 and the address 192.0.2.91 removed. It is Production and expected online now. The item that left was moved to Pending-Removal and marked Failed.",
    );
  });

  it("is read as the words of its parts", () => {
    expect(saidWords(["a ", { to: "/x", text: "b" }, "."])).toBe("a b.");
  });

  it("says no more than was sent, outside a stack", () => {
    expect(saidWords(replacedText({ old, came, sent: {} }))).toBe(
      "FCW0000X002 was replaced by FCW0000X091.",
    );
  });
});

describe("a switch that stands alone made a stack (P-243)", () => {
  it("says what goes to the stack, each only where the switch has it", () => {
    const item = {
      hostname: "cw05-lab-sw1",
      fqdn: "cw05-lab-sw1.example.net",
      addresses: [{}, {}],
      location: { path: "Campus > C05 > Lab" },
      planned_location: null,
      owner: { label: "Network Engineering" },
      operator: null,
    };
    expect(makeStackGoes(item)).toEqual([
      "the host name cw05-lab-sw1",
      "the FQDN cw05-lab-sw1.example.net",
      "its 2 addresses",
      "the location Campus > C05 > Lab",
      "the owner Network Engineering",
    ]);
    expect(makeStackGoes({ addresses: [{}] })).toEqual(["its address"]);
    expect(makeStackText("cw05-lab-sw1", item)).toMatch(
      /^To the stack from cw05-lab-sw1: the host name cw05-lab-sw1, .* and the owner Network Engineering\. cw05-lab-sw1 gives them up/,
    );
    expect(makeStackText("FCW1", {})).toMatch(
      /^FCW1 has no host name, FQDN, address, place, owner or operator of its own/,
    );
  });

  it("says what was made, with how many more members", () => {
    expect(madeStackText("s1", "sw1", 0)).toBe("The stack s1 was made of sw1, member 1.");
    expect(madeStackText("s1", "sw1", 1)).toBe(
      "The stack s1 was made of sw1, member 1, with 1 more member.",
    );
  });
});
