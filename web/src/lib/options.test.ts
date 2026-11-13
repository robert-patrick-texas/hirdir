import { describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import {
  choiceFilterOptions,
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
} from "./options";

function choice(list: string, value: string, label: string, active = true): Schemas["ChoiceOut"] {
  return {
    hid: `hid-${list}-${value}`,
    list,
    value,
    label,
    sort: 0,
    active,
    row_version: 1,
    created_at: "2026-03-01T12:00:00Z",
    updated_at: "2026-03-01T12:00:00Z",
  };
}

const CHOICES = [
  choice("catalog_type", "switch", "Switch"),
  choice("catalog_type", "hub", "Hub", false),
  choice("catalog_type", "router", "Router"),
  choice("state_reason", "rma", "RMA"),
];

describe("choiceOptions", () => {
  it("offers the active values of one list, in the order given", () => {
    expect(choiceOptions(CHOICES, "catalog_type")).toEqual([
      { value: "switch", label: "Switch" },
      { value: "router", label: "Router" },
    ]);
  });

  it("offers the value a record holds even when it is no longer active", () => {
    expect(choiceOptions(CHOICES, "catalog_type", "hub")).toEqual([
      { value: "switch", label: "Switch" },
      { value: "hub", label: "Hub (inactive)" },
      { value: "router", label: "Router" },
    ]);
  });

  it("offers a value the list does not know at all, so that a save does not change it", () => {
    expect(choiceOptions(CHOICES, "state_reason", "moved")).toEqual([
      { value: "rma", label: "RMA" },
      { value: "moved", label: "moved" },
    ]);
    expect(choiceOptions(undefined, "state_reason")).toEqual([]);
  });
});

describe("labels", () => {
  it("offers every value to a filter, active or not", () => {
    expect(choiceFilterOptions(CHOICES, "catalog_type").map((option) => option.value)).toEqual([
      "switch",
      "hub",
      "router",
    ]);
  });

  it("shows the label of a value, or the value when the list does not know it", () => {
    expect(choiceLabel(CHOICES, "state_reason", "rma")).toBe("RMA");
    expect(choiceLabel(CHOICES, "state_reason", "moved")).toBe("moved");
    expect(choiceLabel(CHOICES, "state_reason", null)).toBe("");
    expect(optionLabel(RECORD_STATUSES, "retired")).toBe("Retired");
    expect(optionLabel(RECORD_STATUSES, "held")).toBe("held");
    expect(optionLabel(RECORD_STATUSES, undefined)).toBe("");
  });
});
