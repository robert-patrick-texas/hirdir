import { describe, expect, it } from "vitest";
import {
  dispositionsIn,
  mayBeOnline,
  nextStates,
  onlineText,
  type Rule,
  ruleOf,
  stateNames,
} from "./lifecycle";

function rule(
  sort: number,
  state: string,
  dispositions: string[],
  next_states: string[],
  more: Partial<Rule> = {},
): Rule {
  return {
    hid: `0193a1f4-0000-7000-8000-0000000000${String(sort).padStart(2, "0")}`,
    state,
    sort,
    dispositions,
    keeps_disposition: false,
    may_be_online: [],
    must_be_online: [],
    entry_disposition: null,
    entry_online: null,
    next_states,
    row_version: 1,
    updated_at: "2026-03-01T12:00:00Z",
    ...more,
  };
}

// The rules as a new installation has them, given out of order to show that order is the rule's own.
const RULES: Rule[] = [
  rule(9, "Archived", [], []),
  rule(1, "Purchased", [], ["Delivered"]),
  rule(2, "Delivered", [], ["Assigned"]),
  rule(3, "Assigned", ["Staging", "Spare", "Excess"], ["Test", "Pending-Removal"], {
    entry_disposition: "Staging",
  }),
  rule(4, "Test", ["Staging"], ["Prod", "Down", "Pending-Removal"], {
    may_be_online: ["Staging"],
    entry_disposition: "Staging",
    entry_online: true,
  }),
  rule(5, "Prod", ["Production", "Spare"], ["Down", "Pending-Removal"], {
    may_be_online: ["Production", "Spare"],
    must_be_online: ["Production"],
    entry_disposition: "Production",
    entry_online: true,
  }),
  rule(6, "Down", [], ["Test", "Prod", "Pending-Removal"], { keeps_disposition: true }),
  rule(7, "Pending-Removal", ["Excess"], ["Released", "Assigned"], { keeps_disposition: true }),
  rule(8, "Released", [], ["Archived"]),
];

describe("nextStates", () => {
  it("lists the states in the order of the lifecycle", () => {
    expect(stateNames(RULES)).toEqual([
      "Purchased",
      "Delivered",
      "Assigned",
      "Test",
      "Prod",
      "Down",
      "Pending-Removal",
      "Released",
      "Archived",
    ]);
  });

  it("offers the moves the rule of the item's state allows", () => {
    expect(nextStates(RULES, "Delivered")).toEqual(["Assigned"]);
    expect(nextStates(RULES, "Test")).toEqual(["Prod", "Down", "Pending-Removal"]);
    expect(nextStates(RULES, "Pending-Removal")).toEqual(["Assigned", "Released"]);
    expect(nextStates(RULES, "Archived")).toEqual([]);
  });

  it("offers any state to an item that has none yet", () => {
    expect(nextStates(RULES, null)).toEqual(stateNames(RULES));
    expect(nextStates(RULES, undefined)).toHaveLength(9);
  });

  it("offers every other state for a forced move", () => {
    const forced = nextStates(RULES, "Prod", true);
    expect(forced).toHaveLength(8);
    expect(forced).not.toContain("Prod");
    expect(forced).toContain("Purchased");
    expect(nextStates(RULES, "Archived", true)).toContain("Assigned");
  });

  it("offers nothing for a state the rules do not know", () => {
    expect(nextStates(RULES, "Lost")).toEqual([]);
    expect(ruleOf(RULES, "Lost")).toBeNull();
  });
});

describe("dispositionsIn", () => {
  it("offers what the state allows", () => {
    expect(dispositionsIn(RULES, "Prod", null)).toEqual(["Production", "Spare"]);
    expect(dispositionsIn(RULES, "Assigned", "Production")).toEqual(["Staging", "Spare", "Excess"]);
    expect(dispositionsIn(RULES, "Delivered", "Spare")).toEqual([]);
  });

  it("offers the one the item came with as well, where the state keeps it", () => {
    expect(dispositionsIn(RULES, "Down", "Spare")).toEqual(["Spare"]);
    expect(dispositionsIn(RULES, "Pending-Removal", "Production")).toEqual([
      "Production",
      "Excess",
    ]);
  });

  it("offers any to an item that came with none into a state that keeps it", () => {
    const every = ["Staging", "Production", "Spare", "Excess"];
    expect(dispositionsIn(RULES, "Down", null)).toEqual(every);
    expect(dispositionsIn(RULES, "Pending-Removal", undefined)).toEqual(every);
  });

  it("offers nothing where there is no state", () => {
    expect(dispositionsIn(RULES, null, "Spare")).toEqual([]);
    expect(dispositionsIn(RULES, "", null)).toEqual([]);
  });
});

describe("intent", () => {
  it("knows where an item may be expected online at all", () => {
    expect(mayBeOnline(RULES, "Prod")).toBe(true);
    expect(mayBeOnline(RULES, "Assigned")).toBe(false);
    expect(mayBeOnline(RULES, null)).toBe(false);
  });

  it("is written as words", () => {
    expect(onlineText(true)).toBe("Expected online");
    expect(onlineText(false)).toBe("Expected offline");
    expect(onlineText(null)).toBe("");
  });
});
