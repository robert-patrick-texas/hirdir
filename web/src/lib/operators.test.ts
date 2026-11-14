import { describe, expect, it } from "vitest";
import {
  contactLabel,
  contactSearch,
  groupOperatorSource,
  itemOperatorSource,
  operatedGroupsPath,
  operatedItemsPath,
  operatorHint,
  UNASSIGNED,
  unassignedComponents,
  unassignedPath,
} from "./operators";

const LEE = "0193a1f4-0000-7000-8000-0000000000d1";
const SWITCH = "0193a1f4-0000-7000-8000-0000000000d2";
const STACK = "0193a1f4-0000-7000-8000-0000000000d3";
const DOMAIN = "0193a1f4-0000-7000-8000-0000000000d4";

/** A power supply in a switch that is a member of a stack. */
const supply = {
  parent: { hid: SWITCH, name: "site2-sw-access-01", serial_number: "FCW0000X001" },
  groups: [],
};
const member = {
  parent: null,
  groups: [{ group_hid: STACK, name: "site2-sw-stack1", type: "stack" }],
};

describe("contactSearch", () => {
  it("asks for nothing when nothing is typed", () => {
    expect(contactSearch("")).toBeNull();
    expect(contactSearch("   ")).toBeNull();
  });

  it("looks for a word in the name and in the email address", () => {
    expect(contactSearch("marchetti")).toEqual({
      or: [
        { field: "name", op: "contains", value: "marchetti" },
        { field: "email", op: "contains", value: "marchetti" },
      ],
    });
  });

  it("wants every word found, in either", () => {
    const found = contactSearch(" Lee  example.net ");
    expect(found && "and" in found ? found.and : []).toHaveLength(2);
  });
});

describe("contactLabel", () => {
  it("names a contact with its email address beside it, when it has one", () => {
    expect(contactLabel({ name: "Lee Marchetti", email: "lee.marchetti@example.net" })).toBe(
      "Lee Marchetti (lee.marchetti@example.net)",
    );
    expect(contactLabel({ name: "Network Operations", email: null })).toBe("Network Operations");
  });
});

describe("where the operator of an item came from", () => {
  it("is nowhere else for an operator of the item's own, and for none", () => {
    expect(itemOperatorSource({ source: "own", source_hid: SWITCH }, member)).toBeNull();
    expect(itemOperatorSource({ source: "none", source_hid: null }, member)).toBeNull();
  });

  it("names the stack a switch has it from, and links to it", () => {
    expect(itemOperatorSource({ source: "device_group", source_hid: STACK }, member)).toEqual({
      text: "the stack site2-sw-stack1",
      path: `/groups/${STACK}`,
    });
  });

  it("links a group that the item is no member of itself without naming it", () => {
    // The operator of a controller domain reaches the members of a cluster nested in it.
    expect(itemOperatorSource({ source: "device_group", source_hid: DOMAIN }, member)).toEqual({
      text: "a group that its group is in",
      path: `/groups/${DOMAIN}`,
    });
    // A power supply has it from the stack of its switch: it is no member itself.
    expect(itemOperatorSource({ source: "device_group", source_hid: STACK }, supply)).toEqual({
      text: "the group of the item it is in",
      path: `/groups/${STACK}`,
    });
  });

  it("names the item a minor item has it from, or says that it is one further up", () => {
    expect(itemOperatorSource({ source: "parent_item", source_hid: SWITCH }, supply)).toEqual({
      text: "the item it is in, site2-sw-access-01",
      path: `/items/${SWITCH}`,
    });
    expect(itemOperatorSource({ source: "parent_item", source_hid: STACK }, supply)).toEqual({
      text: "an item above it",
      path: `/items/${STACK}`,
    });
  });

  it("says it as the hint of a cell of the grid, and nothing for an own one", () => {
    const inherited = { source: "device_group" as const, source_hid: STACK, value: LEE };
    expect(operatorHint(inherited, member)).toBe("Inherited from the stack site2-sw-stack1");
    expect(operatorHint({ source: "own", source_hid: SWITCH, value: LEE }, member)).toBe("");
    expect(operatorHint({ source: "none", source_hid: null, value: null }, member)).toBe("");
  });
});

describe("where the operator of a group came from", () => {
  const cluster = { parent: { hid: DOMAIN, name: "site2-wlan", type: "controller_domain" } };

  it("names the group it is nested in", () => {
    expect(groupOperatorSource({ source: "device_group", source_hid: DOMAIN }, cluster)).toEqual({
      text: "the controller domain site2-wlan, which it is in",
      path: `/groups/${DOMAIN}`,
    });
  });

  it("links a group further up without naming it, and is nowhere else for its own", () => {
    expect(groupOperatorSource({ source: "device_group", source_hid: STACK }, cluster)).toEqual({
      text: "a group above the one it is in",
      path: `/groups/${STACK}`,
    });
    expect(groupOperatorSource({ source: "own", source_hid: DOMAIN }, cluster)).toBeNull();
    expect(groupOperatorSource({ source: "none", source_hid: null }, cluster)).toBeNull();
  });
});

describe("what nobody is assigned to", () => {
  it("is found by having no operator in force, in the grid as it shows major items", () => {
    expect(UNASSIGNED).toBe("effective.operator_hid:empty:true");
    expect(unassignedPath()).toBe(`/items?filter=${encodeURIComponent(UNASSIGNED)}`);
  });

  it("is counted as the components of the blank row of a summary by operator", () => {
    const rows = [
      { key: LEE, component_count: 4 },
      { key: null, component_count: 7 },
    ];
    expect(unassignedComponents(rows)).toBe(7);
    // No blank row: everything has an operator.
    expect(unassignedComponents([{ key: LEE, component_count: 4 }])).toBe(0);
    expect(unassignedComponents([])).toBe(0);
    expect(unassignedComponents(undefined)).toBe(0);
  });
});

describe("what a contact is the operator of", () => {
  it("is listed in the grid of items by the operator in force, minor items among them", () => {
    expect(operatedItemsPath(LEE)).toBe(
      `/items?filter=${encodeURIComponent(`effective.operator_hid:eq:${LEE}`)}&minor=1`,
    );
  });

  it("is listed in the grid of groups by the group's own operator", () => {
    expect(operatedGroupsPath(LEE)).toBe(
      `/groups?filter=${encodeURIComponent(`operator_hid:eq:${LEE}`)}`,
    );
  });
});
