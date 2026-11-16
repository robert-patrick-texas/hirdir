// 0.8.0: what a Try of the capacity report sends, and what an Admin saves of it (P-156).
// Every name and number here is invented.

import { describe, expect, it } from "vitest";
import {
  type AddedLine,
  FIGURE_KEYS,
  figureLabel,
  figuresOf,
  type StaffLineTry,
  settingsToSave,
  staffFields,
  staffLinesOf,
  type Tried,
  triedText,
  tryRequest,
} from "./capacityTry";

const ENGINEER = "0193a1f4-0000-7000-8000-00000000c001";
const JUNIOR = "0193a1f4-0000-7000-8000-00000000c002";

const settings = [
  { key: "stack_discount_pct", value: 50 },
  { key: "currency", value: "USD" },
  { key: "weight_per_resource_unit", value: 300 },
  { key: "default_item_weight", value: null },
  { key: "minimum_item_weight", value: null },
  { key: "default_site_weight", value: 2.5 },
  { key: "minimum_site_weight", value: null },
  { key: "default_circuit_weight", value: null },
  { key: "minimum_circuit_weight", value: 1 },
];

function lines(): StaffLineTry[] {
  return staffLinesOf([
    {
      hid: ENGINEER,
      name: "Network engineer",
      quantity: "3",
      units_each: "1",
      record_status: "active",
      in_date: true,
    },
    {
      hid: JUNIOR,
      name: "Junior network engineer",
      quantity: "2",
      units_each: "0.6",
      record_status: "draft",
      in_date: true,
    },
    {
      hid: "0193a1f4-0000-7000-8000-00000000c003",
      name: "Former position",
      quantity: "1",
      units_each: "1",
      record_status: "retired",
      in_date: true,
    },
  ]);
}

describe("the figures of a Try", () => {
  it("are eight, the six weights first, each named", () => {
    expect(FIGURE_KEYS).toHaveLength(8);
    expect(figureLabel("weight_per_resource_unit")).toBe("Support weight one engineer carries");
    expect(figureLabel("default_site_weight")).toBe("Default weight of a site");
  });

  it("start from the settings in force, a blank weight blank", () => {
    const figures = figuresOf(settings);
    expect(figures.weight_per_resource_unit).toBe("300");
    expect(figures.stack_discount_pct).toBe("50");
    expect(figures.default_site_weight).toBe("2.5");
    expect(figures.minimum_circuit_weight).toBe("1");
    expect(figures.default_item_weight).toBe("");
  });
});

describe("the staff lines of a Try", () => {
  it("are those that are there and not retired, as they stand", () => {
    const listed = lines();
    expect(listed.map((line) => [line.name, line.standing])).toEqual([
      ["Network engineer", "active"],
      ["Junior network engineer", "draft"],
    ]);
    expect(listed[0]?.triedQuantity).toBe("3");
  });
});

describe("the request of a Try", () => {
  const inForce = figuresOf(settings);

  it("sends nothing that is as it is in force", () => {
    expect(tryRequest(inForce, inForce, lines(), []).body).toEqual({});
  });

  it("sends each figure changed, a blank as null, which tries it at its default", () => {
    const figures = {
      ...inForce,
      default_item_weight: " 1 ",
      default_site_weight: "",
      weight_per_resource_unit: "250",
    };
    expect(tryRequest(figures, inForce, lines(), []).body).toEqual({
      default_item_weight: "1",
      default_site_weight: null,
      weight_per_resource_unit: "250",
    });
  });

  it("sends a staff line changed with what was changed alone, and one left out by its HID", () => {
    const tried = lines().map((line) =>
      line.hid === ENGINEER
        ? { ...line, triedQuantity: "4" }
        : { ...line, triedUnitsEach: "0.8", leaveOut: true },
    );
    const request = tryRequest(inForce, inForce, tried, []);
    expect(request.body).toEqual({
      staff: { change: [{ hid: ENGINEER, quantity: "4" }], leave_out: [JUNIOR] },
    });
    expect(request.changed).toEqual([ENGINEER]);
  });

  it("sends the rows added that hold anything, a quantity left blank left out", () => {
    const added: AddedLine[] = [
      { id: 1, name: "Network engineer, new", quantity: "2", unitsEach: "1" },
      { id: 2, name: "", quantity: "", unitsEach: "" },
      { id: 3, name: "Contractor", quantity: "", unitsEach: "0.5" },
    ];
    const request = tryRequest(inForce, inForce, lines(), added);
    expect(request.body.staff?.add).toEqual([
      { name: "Network engineer, new", quantity: "2", units_each: "1" },
      { name: "Contractor", units_each: "0.5" },
    ]);
    // The server names an added line by its place in the request: the third row is the second.
    expect(staffFields(request).add.get(3)).toBe(1);
    expect(staffFields(request).add.get(2)).toBeUndefined();
  });
});

describe("the settings an Admin saves of a Try", () => {
  const tried: Tried = {
    default_item_weight: "1",
    minimum_item_weight: null,
    default_site_weight: null,
    minimum_site_weight: null,
    default_circuit_weight: null,
    minimum_circuit_weight: "1",
    weight_per_resource_unit: "250",
    stack_discount_pct: "50",
    staff: { add: [], change: [], leave_out: [] },
    changed: ["default_item_weight", "default_site_weight", "weight_per_resource_unit"],
  };

  it("are those the answer says changed, each at the value tried, a blank as null", () => {
    expect(settingsToSave(tried)).toEqual([
      { key: "default_item_weight", value: "1" },
      { key: "default_site_weight", value: null },
      { key: "weight_per_resource_unit", value: "250" },
    ]);
  });

  it("say a blank weight is blank", () => {
    expect(triedText("default_site_weight", null)).toBe("blank");
    expect(triedText("default_item_weight", "1")).toBe("1");
  });
});
