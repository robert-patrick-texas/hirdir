// External systems and the registrations of items and of device groups with them. A
// registration is on the record it was made for: that of a stack is on the stack. One
// that ends is given the status `removed`, and is never deleted.

import type { Schemas } from "../api/client";
import { filterText } from "./filter";
import { itemName } from "./format";
import type { Option } from "./patch";

export type ExternalSystem = Schemas["ExternalSystemOut"];
export type Registration = Schemas["RegistrationOut"];
export type RegistrationRef = Schemas["RegistrationRef"];
type Choice = Schemas["ChoiceOut"];

/**
 * 0.9.3: the kinds of external system are the editable list `system_kind` of Admin ›
 * Choices, which a site names, renames, adds to and retires (P-170). A form offers its
 * active values with their labels, and a system that holds a value no longer offered
 * keeps it and shows its label.
 */
export const SYSTEM_KIND_LIST = "system_kind";

/** The kind a system made with none is given, while the list offers it. */
export const KIND_LEFT_OUT = "other";

/**
 * What the form of a new system starts with: the kind that a system with none is given,
 * while the list offers it, and otherwise no kind, which the server refuses, saying so
 * of the field.
 */
export function startingKind(choices: readonly Choice[] | undefined): string {
  const offered = (choices ?? []).some(
    (choice) => choice.list === SYSTEM_KIND_LIST && choice.value === KIND_LEFT_OUT && choice.active,
  );
  return offered ? KIND_LEFT_OUT : "";
}

/** What the form of a new system says of a kind left out, by the label of `other`. */
export function leftOutHint(choices: readonly Choice[] | undefined): string {
  const other = (choices ?? []).find(
    (choice) => choice.list === SYSTEM_KIND_LIST && choice.value === KIND_LEFT_OUT,
  );
  return other?.active
    ? `Left out, it is ${other.label}.`
    : "A kind is needed: the list does not offer other, which a system made with none is given.";
}

export const REGISTRATION_STATUSES: readonly Option[] = [
  { value: "registered", label: "Registered" },
  { value: "pending", label: "Pending" },
  { value: "removed", label: "Removed" },
];

export const REMOVED = "removed";

export function systemPath(hid: string): string {
  return `/systems/${encodeURIComponent(hid)}`;
}

/** The record a registration is of: an item or a device group. */
export type Holder = { item_hid: string } | { group_hid: string };

/** The filter of the list of registrations for those of one record. */
export function holderFilter(holder: Holder): string {
  return "item_hid" in holder
    ? `item_hid:eq:${holder.item_hid}`
    : `group_hid:eq:${holder.group_hid}`;
}

/** What a registration is of, by the name it is shown by, with the page of that record. */
export function registeredRecord(
  registration: Pick<Registration, "item" | "item_hid" | "group" | "group_hid">,
): { name: string; path: string; kind: "Item" | "Device group" } | null {
  if (registration.group && registration.group_hid) {
    return {
      name: registration.group.name,
      path: `/groups/${encodeURIComponent(registration.group_hid)}`,
      kind: "Device group",
    };
  }
  if (registration.item && registration.item_hid) {
    return {
      name: itemName(registration.item),
      path: `/items/${encodeURIComponent(registration.item_hid)}`,
      kind: "Item",
    };
  }
  return null;
}

/** What a stack or a cluster an item is a member of is registered with: read only. */
export type GroupRegistration = Schemas["GroupRegistrationRef"];

/**
 * The names of the systems that know a record, each once, as a cell of a grid shows
 * them: those it is registered with itself, and for an item those a stack or a cluster
 * it is a member of is registered with, which is what the filter of the item list finds
 * it by. A registration that is removed does not count.
 */
export function registeredWith(
  registrations: readonly Pick<RegistrationRef, "status" | "system">[],
  throughGroups: readonly Pick<GroupRegistration, "status" | "system">[] = [],
): string {
  const names: string[] = [];
  for (const one of [...registrations, ...throughGroups]) {
    if (one.status !== REMOVED && !names.includes(one.system.name)) names.push(one.system.name);
  }
  return names.join(", ");
}

/** The items, or the device groups, registered with a system, in their grid. */
export function registeredPath(list: "items" | "groups", systemName: string): string {
  const filter = filterText({ field: "registration.system", op: "eq", value: systemName });
  return `/${list}?filter=${encodeURIComponent(filter)}${list === "items" ? "&minor=1" : ""}`;
}

/**
 * The systems a record can still be registered with: those that are active and that it
 * has no registration with. One that was removed is registered again on its own row,
 * since it is the same record.
 */
export function unregistered(
  systems: readonly Pick<ExternalSystem, "hid" | "name" | "record_status">[],
  registrations: readonly { system_hid: string }[],
): Option[] {
  const taken = new Set(registrations.map((one) => one.system_hid));
  return systems
    .filter((system) => system.record_status !== "retired" && !taken.has(system.hid))
    .map((system) => ({ value: system.hid, label: system.name }));
}
