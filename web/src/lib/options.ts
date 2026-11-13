// The lists a form offers. Some are fixed by the data model; the rest are the editable
// lists of `GET /choices`, of which only the active values are offered.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

type Choice = Schemas["ChoiceOut"];

export const CATALOG_KINDS: readonly Option[] = [
  { value: "hardware", label: "Hardware" },
  { value: "virtual_machine", label: "Virtual machine" },
  { value: "software", label: "Software" },
  { value: "service", label: "Service" },
];

export const RECORD_STATUSES: readonly Option[] = [
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "retired", label: "Retired" },
];

/** The statuses a change may set. Retiring is an action of its own. */
export const SETTABLE_STATUSES: readonly Option[] = RECORD_STATUSES.filter(
  (status) => status.value !== "retired",
);

export const REVIEW_STATUSES: readonly Option[] = [
  { value: "reviewed", label: "Reviewed" },
  { value: "unreviewed", label: "Unreviewed" },
];

/** The editable lists, as the data model names them. */
export const CHOICE_LISTS: readonly Option[] = [
  { value: "catalog_type", label: "Catalog type" },
  { value: "catalog_function", label: "Catalog function" },
  { value: "state_reason", label: "State reason" },
  { value: "contact_role", label: "Contact role" },
  { value: "location_kind", label: "Location kind" },
  { value: "replacement_reason", label: "Replacement reason" },
  { value: "capacity_category", label: "Capacity category" },
];

/**
 * The values of one list to offer in a form: the active ones, in the list's order. The
 * value a record already holds is offered too, even when it is no longer active, so
 * that saving the form does not change it by accident.
 */
export function choiceOptions(
  choices: readonly Choice[] | undefined,
  list: string,
  current: string | null = null,
): Option[] {
  const options = (choices ?? [])
    .filter((choice) => choice.list === list && (choice.active || choice.value === current))
    .map((choice) => ({
      value: choice.value,
      label: choice.active ? choice.label : `${choice.label} (inactive)`,
    }));
  if (current && !options.some((option) => option.value === current)) {
    options.push({ value: current, label: current });
  }
  return options;
}

/** Every value of one list, active or not, for a filter: old records still hold them. */
export function choiceFilterOptions(
  choices: readonly Choice[] | undefined,
  list: string,
): Option[] {
  return (choices ?? [])
    .filter((choice) => choice.list === list)
    .map((choice) => ({ value: choice.value, label: choice.label }));
}

/** The label of a value of a list, or the value itself when the list does not know it. */
export function choiceLabel(
  choices: readonly Choice[] | undefined,
  list: string,
  value: string | null | undefined,
): string {
  if (!value) return "";
  const found = (choices ?? []).find((choice) => choice.list === list && choice.value === value);
  return found ? found.label : value;
}

/** The label of a value of a fixed list. */
export function optionLabel(options: readonly Option[], value: string | null | undefined): string {
  if (!value) return "";
  return options.find((option) => option.value === value)?.label ?? value;
}
