// The walk of each value, as the server answers it, turned into boxes (P-176). The
// answers here have the shape of `GET /items/{hid}/resolution`; every name is invented.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ResolutionWalks } from "../components/ResolutionWalks";
import {
  deciding,
  fieldLabel,
  ordinal,
  overridden,
  type Resolution,
  type ResolutionField,
  type ResolutionStep,
  stepKind,
  stepPath,
  stepTitle,
  valueText,
  walkBoxes,
} from "./resolution";

const OPTIC = "0193a1f4-0000-7000-8000-00000000e001";
const SWITCH = "0193a1f4-0000-7000-8000-00000000e002";
const POOL = "0193a1f4-0000-7000-8000-00000000d001";
const SPARE = "0193a1f4-0000-7000-8000-00000000d002";
const STACK = "0193a1f4-0000-7000-8000-00000000d003";
const SITE = "0193a1f4-0000-7000-8000-00000000c001";

function step(more: Partial<ResolutionStep> & Pick<ResolutionStep, "level">): ResolutionStep {
  return {
    hid: null,
    name: null,
    label: null,
    value: null,
    type: null,
    rank: null,
    via_hid: null,
    via_name: null,
    outcome: "nothing",
    ...more,
  };
}

// An optic in a switch: its own custom groups come before the switch (P-175), so the
// group optics-pool decides, and the switch's own operator and its stack's are passed over.
const operator: ResolutionField = {
  field: "operator_hid",
  value: "0193a1f4-0000-7000-8000-00000000f003",
  label: "RA",
  source: "device_group",
  source_hid: POOL,
  overrides: null,
  overrides_label: null,
  steps: [
    step({ level: "own", hid: OPTIC, name: "SFP-1" }),
    step({ level: "device_group", hid: SPARE, name: "aaa-pool", type: "custom", rank: 1 }),
    step({
      level: "device_group",
      hid: POOL,
      name: "optics-pool",
      type: "custom",
      rank: 2,
      value: "0193a1f4-0000-7000-8000-00000000f003",
      label: "RA",
      outcome: "decides",
    }),
    step({
      level: "parent_item",
      hid: SWITCH,
      name: "sw-01",
      value: "0193a1f4-0000-7000-8000-00000000f001",
      label: "LM",
      outcome: "passed_over",
    }),
    step({
      level: "device_group",
      hid: STACK,
      name: "site2-sw",
      type: "stack",
      rank: 1,
      value: "0193a1f4-0000-7000-8000-00000000f002",
      label: "PR",
      outcome: "passed_over",
    }),
    step({
      level: "site",
      hid: SITE,
      name: "Americas > Central > Site-2",
      value: "0193a1f4-0000-7000-8000-00000000f004",
      label: "DW",
      outcome: "retired",
    }),
  ],
};

// A location of its own, which overrides the stack's.
const location: ResolutionField = {
  field: "location_hid",
  value: "0193a1f4-0000-7000-8000-00000000c010",
  label: "Americas > Central > Site-2 > Room 102",
  source: "own",
  source_hid: SWITCH,
  overrides: "0193a1f4-0000-7000-8000-00000000c011",
  overrides_label: "Americas > Central > Site-2 > Room 104",
  steps: [
    step({
      level: "own",
      hid: SWITCH,
      name: "sw-01",
      value: "0193a1f4-0000-7000-8000-00000000c010",
      label: "Americas > Central > Site-2 > Room 102",
      outcome: "decides",
    }),
    step({
      level: "device_group",
      hid: STACK,
      name: "site2-sw",
      type: "stack",
      rank: 1,
      value: "0193a1f4-0000-7000-8000-00000000c011",
      label: "Americas > Central > Site-2 > Room 104",
      via_hid: POOL,
      via_name: "campus-stacks",
      outcome: "passed_over",
    }),
  ],
};

// The support weight of a major item: its model's is below the minimum, which raises it.
// The value is found on the catalog entry, which decides, and the minimum raises it: the
// source stays where the value was found.
const weight: ResolutionField = {
  field: "support_weight",
  value: "1.00",
  label: null,
  source: "catalog",
  source_hid: "c-1",
  overrides: null,
  overrides_label: null,
  steps: [
    step({ level: "own", hid: SWITCH, name: "sw-01" }),
    step({
      level: "catalog",
      hid: "c-1",
      name: "Example Networks EN-4800",
      value: "0.50",
      outcome: "decides",
    }),
    step({ level: "setting", name: "default_item_weight", value: "1.00", outcome: "passed_over" }),
    step({ level: "setting", name: "minimum_item_weight", value: "1.00", outcome: "raises" }),
  ],
};

const renewal: ResolutionField = {
  field: "do_not_renew",
  value: false,
  label: null,
  source: "catalog",
  source_hid: "c-1",
  overrides: null,
  overrides_label: null,
  steps: [
    step({ level: "own", hid: SWITCH, name: "sw-01" }),
    step({
      level: "catalog",
      hid: "c-1",
      name: "Example Networks EN-4800",
      value: false,
      outcome: "decides",
    }),
  ],
};

describe("the walk of a value, as boxes", () => {
  it("has a box for each step in the order of the walk, each with what the server says it is", () => {
    const boxes = walkBoxes(operator);
    expect(boxes.map((box) => box.title)).toEqual([
      "SFP-1",
      "aaa-pool",
      "optics-pool",
      "sw-01",
      "site2-sw",
      "Americas > Central > Site-2",
    ]);
    expect(boxes.map((box) => box.state)).toEqual([
      "nothing",
      "nothing",
      "decides",
      "passed_over",
      "passed_over",
      "retired",
    ]);
    expect(new Set(boxes.map((box) => box.key)).size).toBe(boxes.length);
  });

  it("decides by the step the server marks, which is the optic's own group and not the switch", () => {
    expect(deciding(operator)?.name).toBe("optics-pool");
    const boxes = walkBoxes(operator);
    expect(boxes.filter((box) => box.state === "decides").map((box) => box.title)).toEqual([
      "optics-pool",
    ]);
  });

  it("calls each value by its label, and a value with none by itself", () => {
    expect(walkBoxes(operator)[2]?.value).toBe("RA");
    expect(walkBoxes(operator)[0]?.value).toBeNull();
    expect(walkBoxes(weight)[1]?.value).toBe("0.50");
    expect(walkBoxes(renewal)[1]?.value).toBe("No");
    expect(valueText(true, null)).toBe("Yes");
  });

  it("says what kind of record each step looks at, a group with its type and rank", () => {
    expect(walkBoxes(operator).map((box) => box.kind)).toEqual([
      "Its own",
      "Group · custom · ranked 1st",
      "Group · custom · ranked 2nd",
      "Item it is in",
      "Group · stack · ranked 1st",
      "Site",
    ]);
    expect(stepKind(step({ level: "device_group", type: "controller_domain" }))).toBe(
      "Group it is in · controller domain",
    );
    expect(stepKind(step({ level: "catalog" }))).toBe("Catalog entry");
    // 0.9.8: a cluster the item, or its host, runs on is not a group it is in (P-246).
    expect(
      stepKind(step({ level: "device_group", type: "cluster", rank: 1, reached_by: "host" })),
    ).toBe("Cluster it runs on");
    expect(
      stepKind(step({ level: "device_group", type: "cluster", rank: 1, reached_by: "member" })),
    ).toBe("Group · cluster · ranked 1st");
  });

  it("leads each record to its page, and the page itself and a setting to none", () => {
    const boxes = walkBoxes(operator);
    expect(boxes[0]?.href).toBeNull();
    expect(boxes[1]?.href).toBe(`/groups/${SPARE}`);
    expect(boxes[3]?.href).toBe(`/items/${SWITCH}`);
    expect(boxes[5]?.href).toContain(SITE);
    expect(stepPath(step({ level: "catalog", hid: "c-1" }))).toBe("/catalog/c-1");
    expect(stepPath(weight.steps[3] as ResolutionStep)).toBeNull();
  });

  it("names a setting of weight in words", () => {
    expect(stepTitle(weight.steps[2] as ResolutionStep)).toBe("Default weight of a major item");
    expect(stepTitle(weight.steps[3] as ResolutionStep)).toBe("Minimum weight of a major item");
  });

  it("draws the minimum that raises a weight after the step that decides, which keeps the source", () => {
    expect(walkBoxes(weight).map((box) => box.state)).toEqual([
      "nothing",
      "decides",
      "passed_over",
      "raises",
    ]);
    expect(deciding(weight)?.level).toBe("catalog");
    expect(walkBoxes(weight)[3]?.value).toBe("1.00");
  });

  it("names the group a group's value is had from", () => {
    expect(walkBoxes(location)[1]?.via).toEqual({
      text: "campus-stacks",
      href: `/groups/${POOL}`,
    });
  });

  it("says what a value of its own overrides, and where that is from", () => {
    expect(overridden(location)).toEqual({
      text: "Americas > Central > Site-2 > Room 104",
      from: location.steps[1],
    });
    expect(overridden(operator)).toBeNull();
  });
});

describe("the words of the walks", () => {
  it("are ordinals as people say them", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "101st",
      "111th",
    ]);
  });

  it("name each field as the page does", () => {
    expect(fieldLabel("planned_location_hid")).toBe("Planned location");
    expect(fieldLabel("ldos")).toBe("Last day of support (LDoS)");
    expect(fieldLabel("something_new")).toBe("something_new");
  });
});

describe("the walks of a record, on its page", () => {
  const resolution: Resolution = { hid: OPTIC, fields: [location, operator] };
  const markup = renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(ResolutionWalks, { resolution })),
  );
  const fields = markup.split('data-testid="walk-field"').slice(1);

  it("shows each value under a heading of its own with the value in force", () => {
    expect(fields).toHaveLength(2);
    expect(fields[0]).toContain('data-field="location_hid"');
    expect(fields[0]).toContain("Location:");
    expect(fields[1]).toContain('<span class="walk-in-force">RA</span>');
  });

  it("draws the deciding box where the server says, and only there", () => {
    const deciding = (fields[1] ?? "").split('<li class="walk-step"').slice(1);
    const marked = deciding.filter((box) => box.includes("walk-box walk-decides"));
    expect(marked).toHaveLength(1);
    expect(marked[0]).toContain("optics-pool");
  });

  it("says what a value of its own overrides, with a link to where that is from", () => {
    expect(fields[0]).toContain("Overrides</span> Americas &gt; Central &gt; Site-2 &gt; Room 104");
    expect(fields[0]).toMatch(new RegExp(`, from <a href="/groups/${STACK}"[^>]*>site2-sw</a>`));
    expect(fields[1]).not.toContain("walk-overrides");
  });
});
