// Why a record has each value it has from elsewhere: the walk of each, as the server
// answers it from `GET /items/{hid}/resolution` and `GET /device-groups/{hid}/resolution`
// (P-176). Each step is a record the walk looks at, in its order, and what that holds; the
// server says which step decides, which is passed over, and which holds nothing. This
// only turns the answer into the boxes and the words of the page: nothing is decided here.

import type { Schemas } from "../api/client";
import type { WalkBox } from "../components/BoxWalk";
import { groupTypeLabel } from "./groups";
import { placePath } from "./places";
import { isWeightSetting, weightSettingLabel } from "./weights";

export type Resolution = Schemas["Resolution"];
export type ResolutionField = Schemas["ResolutionField"];
export type ResolutionStep = Schemas["ResolutionStep"];

/** Each value a record may have from elsewhere, as people read it. */
const FIELD_LABELS: Readonly<Record<string, string>> = {
  location_hid: "Location",
  planned_location_hid: "Planned location",
  operator_hid: "Operator",
  owner_hid: "Owner",
  est_value: "Estimated value",
  support_weight: "Support weight",
  annual_support_cost: "Annual support cost",
  end_of_sale: "End of sale",
  end_of_sw_support: "End of software support",
  end_of_hw_support: "End of hardware support",
  ldos: "Last day of support (LDoS)",
  do_not_renew: "Not to be renewed",
};

/** What a field of the walk is called; one this build does not know is shown as sent. */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

/**
 * A value of the walk as people read it: what the server calls it, a path or a label,
 * else the value itself, a truth value as Yes or No. Null where there is none.
 */
export function valueText(value: string | boolean | null, label: string | null): string | null {
  if (value === null) return null;
  if (label) return label;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value;
}

/** 1st, 2nd, 3rd, 4th, 11th, 21st. */
export function ordinal(place: number): string {
  const tens = place % 100;
  if (tens >= 11 && tens <= 13) return `${place}th`;
  const suffix = ["th", "st", "nd", "rd"][place % 10] ?? "th";
  return `${place}${suffix}`;
}

/**
 * What kind of record a step looks at, small above its name. A group of an item's walk
 * says its type and its rank among the groups of the record it is a group of; a group of
 * a group's walk is one it is nested in.
 */
export function stepKind(step: ResolutionStep): string {
  switch (step.level) {
    case "own":
      return "Its own";
    case "device_group": {
      const type = step.type ? groupTypeLabel(step.type).toLowerCase() : "group";
      return step.rank === null
        ? `Group it is in · ${type}`
        : `Group · ${type} · ranked ${ordinal(step.rank)}`;
    }
    case "parent_item":
      return "Item it is in";
    case "catalog":
      return "Catalog entry";
    case "setting":
      return "Setting";
    case "location":
      return "Location";
    case "site":
      return "Site";
    case "region":
      return "Region";
  }
}

/** The page of the record a step looks at, where it has one and is not the page itself. */
export function stepPath(step: ResolutionStep): string | null {
  if (step.hid === null) return null;
  const hid = encodeURIComponent(step.hid);
  switch (step.level) {
    case "device_group":
      return `/groups/${hid}`;
    case "parent_item":
      return `/items/${hid}`;
    case "catalog":
      return `/catalog/${hid}`;
    case "location":
    case "site":
    case "region":
      return placePath(step.level, step.hid);
    default:
      return null;
  }
}

/** What a step's record is called: a setting by its words, the rest by name or path. */
export function stepTitle(step: ResolutionStep): string {
  const name = step.name ?? step.hid ?? "";
  if (step.level === "setting" && isWeightSetting(name)) return weightSettingLabel(name);
  return name || "(no name)";
}

/** The walk of one value as the boxes of the page, in its order. */
export function walkBoxes(field: ResolutionField): WalkBox[] {
  return field.steps.map((step, place) => ({
    key: `${place}-${step.level}-${step.hid ?? step.name ?? ""}`,
    kind: stepKind(step),
    title: stepTitle(step),
    href: stepPath(step),
    value: valueText(step.value, step.label),
    via:
      step.via_hid && step.via_name
        ? { text: step.via_name, href: `/groups/${encodeURIComponent(step.via_hid)}` }
        : null,
    state: step.outcome,
  }));
}

/**
 * What a value of the record's own replaces: the first value passed over after it, and
 * the step that holds it. Null where the value in force is not its own or replaces none.
 */
export function overridden(
  field: ResolutionField,
): { text: string; from: ResolutionStep | null } | null {
  const text = valueText(field.overrides, field.overrides_label);
  if (text === null) return null;
  const from = field.steps.find((step) => step.outcome === "passed_over") ?? null;
  return { text, from };
}

/** The step that decides, if one does: the record the value in force comes from. */
export function deciding(field: ResolutionField): ResolutionStep | null {
  return field.steps.find((step) => step.outcome === "decides") ?? null;
}
