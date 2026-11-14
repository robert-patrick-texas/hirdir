import { describe, expect, it } from "vitest";
import {
  assignmentPath,
  contactLabel,
  contactSearch,
  markOf,
  markTitle,
  OPEN,
  type OperatorInForce,
  operatedGroupsPath,
  operatedItemsPath,
  operatorHint,
  operatorOptionLabel,
  operatorPath,
  operatorSearch,
  operatorSource,
  safeColour,
  UNASSIGNED,
  unassignedComponents,
} from "./operators";

const OP2 = "0193a1f4-0000-7000-8000-0000000000d1";
const LEE = "0193a1f4-0000-7000-8000-0000000000d2";
const STACK = "0193a1f4-0000-7000-8000-0000000000d3";
const SITE = "0193a1f4-0000-7000-8000-0000000000d4";

/** The label Op2, with Lee Marchetti behind it, as a record names it. */
const ref = {
  hid: OP2,
  label: "Op2",
  colour: "#1f6feb",
  contact_hid: LEE,
  contact: "Lee Marchetti",
  is_open: false,
  record_status: "active" as const,
};

function inForce(more: Partial<OperatorInForce> = {}): OperatorInForce {
  return {
    value: OP2,
    label: "Op2",
    colour: "#1f6feb",
    contact_hid: LEE,
    contact: "Lee Marchetti",
    is_open: false,
    source: "own",
    source_hid: null,
    source_label: null,
    ...more,
  };
}

describe("searching", () => {
  it("finds a contact by a word of its name or of its email address", () => {
    expect(contactSearch("")).toBeNull();
    expect(contactSearch("marchetti")).toEqual({
      or: [
        { field: "name", op: "contains", value: "marchetti" },
        { field: "email", op: "contains", value: "marchetti" },
      ],
    });
    const two = contactSearch(" Lee  example.net ");
    expect(two && "and" in two ? two.and : []).toHaveLength(2);
    expect(contactLabel({ name: "Lee Marchetti", email: "lee.marchetti@example.net" })).toBe(
      "Lee Marchetti (lee.marchetti@example.net)",
    );
    expect(contactLabel({ name: "Network Operations", email: null })).toBe("Network Operations");
  });

  it("finds an operator by its label, or by the name of the person behind it", () => {
    expect(operatorSearch("   ")).toBeNull();
    expect(operatorSearch("op2")).toEqual({
      or: [
        { field: "label", op: "contains", value: "op2" },
        { field: "contact.name", op: "contains", value: "op2" },
      ],
    });
    const two = operatorSearch("lee marchetti");
    expect(two && "and" in two ? two.and : []).toHaveLength(2);
  });

  it("offers an operator by its label, with the person behind it, or that it is open", () => {
    expect(operatorOptionLabel(ref)).toBe("Op2 · Lee Marchetti");
    expect(operatorOptionLabel({ ...ref, contact: null, is_open: true })).toBe("Op2 · open");
    // As its own record names it, the person is a contact and not a name.
    expect(
      operatorOptionLabel({ ...ref, contact: { name: "Lee Marchetti", email: null } as never }),
    ).toBe("Op2 · Lee Marchetti");
  });
});

describe("the mark of an operator", () => {
  it("is the label, its colour, the person behind it and whether it is open", () => {
    expect(markOf(ref)).toEqual({
      hid: OP2,
      label: "Op2",
      colour: "#1f6feb",
      person: "Lee Marchetti",
      open: false,
      released: false,
    });
  });

  it("is read off an operator in force too, and is none for an item nobody is assigned to", () => {
    expect(markOf(inForce())?.hid).toBe(OP2);
    expect(markOf(inForce({ value: null, label: null, source: "none" }))).toBeNull();
    expect(markOf(null)).toBeNull();
  });

  it("uses a colour only as the server stores one", () => {
    expect(safeColour("#1F6FEB")).toBe("#1F6FEB");
    expect(safeColour("red")).toBeNull();
    expect(safeColour("#fff")).toBeNull();
    expect(safeColour("#1f6feb; background: url(x)")).toBeNull();
    expect(safeColour(null)).toBeNull();
    expect(markOf({ ...ref, colour: "tomato" })?.colour).toBeNull();
  });

  it("says who is behind the label, that it is open, or that it is released", () => {
    expect(markTitle({ person: "Lee Marchetti", open: false, released: false })).toBe(
      "Lee Marchetti",
    );
    expect(markTitle({ person: "", open: true, released: false })).toBe(
      "Open: nobody is behind this label",
    );
    // Open also when the person behind it is retired.
    expect(markTitle({ person: "Lee Marchetti", open: true, released: false })).toBe(
      "Open: Lee Marchetti, who was behind this label, is retired",
    );
    expect(markTitle({ person: "Lee Marchetti", open: false, released: true })).toContain(
      "Released",
    );
    expect(markOf({ ...ref, record_status: "retired" })?.released).toBe(true);
  });

  it("leads to the page of the operator", () => {
    expect(operatorPath(OP2)).toBe(`/operators/${OP2}`);
  });
});

describe("where an operator in force came from", () => {
  it("is nowhere else for one of the record's own, and for none", () => {
    expect(operatorSource(inForce())).toBeNull();
    expect(operatorSource(inForce({ source: "none", value: null }))).toBeNull();
  });

  it("names the group or the item by what the server calls it, and links to it", () => {
    expect(
      operatorSource(
        inForce({ source: "device_group", source_hid: STACK, source_label: "site2-sw-stack1" }),
      ),
    ).toEqual({ text: "the group site2-sw-stack1", path: `/groups/${STACK}` });
    expect(
      operatorSource(
        inForce({ source: "parent_item", source_hid: STACK, source_label: "site2-sw-access-01" }),
      ),
    ).toEqual({ text: "the item site2-sw-access-01", path: `/items/${STACK}` });
  });

  it("names a place by its level and its path, and links to its page", () => {
    const path = "Americas > Central > Site-2";
    expect(
      operatorSource(inForce({ source: "site", source_hid: SITE, source_label: path })),
    ).toEqual({ text: `the site ${path}`, path: `/geography/site/${SITE}` });
    expect(
      operatorSource(inForce({ source: "region", source_hid: SITE, source_label: "Americas" })),
    ).toEqual({ text: "the region Americas", path: `/geography/region/${SITE}` });
    expect(
      operatorSource(
        inForce({ source: "location", source_hid: SITE, source_label: `${path} > Room 102` }),
      )?.path,
    ).toBe(`/geography/location/${SITE}`);
  });

  it("still links when no name came with it", () => {
    expect(
      operatorSource(inForce({ source: "device_group", source_hid: STACK, source_label: null })),
    ).toEqual({ text: "the group", path: `/groups/${STACK}` });
  });

  it("says the person and the source as the hint of a cell of the grid", () => {
    expect(operatorHint(inForce())).toBe("Lee Marchetti");
    expect(
      operatorHint(
        inForce({ source: "site", source_hid: SITE, source_label: "Americas > Site-2" }),
      ),
    ).toBe("Lee Marchetti · Inherited from the site Americas > Site-2");
    expect(operatorHint(inForce({ contact: null, contact_hid: null, is_open: true }))).toBe(
      "Open: nobody is behind this label",
    );
    expect(operatorHint(inForce({ value: null, label: null, source: "none" }))).toBe("");
  });
});

describe("what nobody is assigned to, and what is under an open label", () => {
  it("is found by a filter of the item list, in the grid as it shows major items", () => {
    expect(UNASSIGNED).toBe("effective.operator_hid:empty:true");
    expect(OPEN).toBe("operator.is_open:eq:true");
    expect(assignmentPath(UNASSIGNED)).toBe(`/items?filter=${encodeURIComponent(UNASSIGNED)}`);
    expect(assignmentPath(OPEN)).toBe(`/items?filter=${encodeURIComponent(OPEN)}`);
  });

  it("is counted as the components of the blank row of a summary by operator", () => {
    const rows = [
      { key: OP2, component_count: 4 },
      { key: null, component_count: 7 },
    ];
    expect(unassignedComponents(rows)).toBe(7);
    // No blank row: everything has an operator.
    expect(unassignedComponents([{ key: OP2, component_count: 4 }])).toBe(0);
    expect(unassignedComponents([])).toBe(0);
    expect(unassignedComponents(undefined)).toBe(0);
  });
});

describe("what an operator is on", () => {
  it("is listed in the grid of items by the operator in force, minor items among them", () => {
    expect(operatedItemsPath(OP2)).toBe(
      `/items?filter=${encodeURIComponent(`effective.operator_hid:eq:${OP2}`)}&minor=1`,
    );
  });

  it("is listed in the grid of groups by the group's own operator", () => {
    expect(operatedGroupsPath(OP2)).toBe(
      `/groups?filter=${encodeURIComponent(`operator_hid:eq:${OP2}`)}`,
    );
  });
});
