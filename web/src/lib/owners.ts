// Owners and their people. An owner outside the operations team is an exception, and an
// item that is given to one says why. The server keeps the rules; this lays owners out
// for a form and says which of them are outside the team.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type Owner = Schemas["OwnerOut"];
export type OwnerMember = Schemas["OwnerMemberOut"];

/** The heading a form lists the owners outside the team under. */
export const EXTERNAL_GROUP = "Outside the operations team";

/** Owners as a form offers them, by label: those outside the team under a heading of their own. */
export function ownerOptions(
  owners: ReadonlyArray<Pick<Owner, "hid" | "label" | "is_external">>,
): Option[] {
  return owners.map((owner) => ({
    value: owner.hid,
    label: owner.label,
    ...(owner.is_external ? { group: EXTERNAL_GROUP } : {}),
  }));
}

/**
 * The owners that are outside the team, by HID: those a form offers as such, and any
 * other that is known to be, such as the owner an item has that is no longer offered.
 */
export function externalOwners(
  options: readonly Option[] | undefined,
  also: ReadonlyArray<string | null | undefined> = [],
): Set<string> {
  const outside = new Set<string>();
  for (const option of options ?? []) {
    if (option.group === EXTERNAL_GROUP) outside.add(option.value);
  }
  for (const hid of also) {
    if (hid) outside.add(hid);
  }
  return outside;
}

/** Why a form asks for a reason when an item is given to an owner outside the team. */
export const EXCEPTION_HINT =
  "Asked because this owner is outside the operations team: an item with such an owner is an exception, and says why it is with them.";

/** The people of an owner as a page lists them: the primary first, then by priority and name. */
export function membersInOrder(members: readonly OwnerMember[]): OwnerMember[] {
  return [...members].sort(
    (one, other) =>
      Number(other.role === "primary") - Number(one.role === "primary") ||
      one.priority - other.priority ||
      one.contact.name.localeCompare(other.contact.name),
  );
}

/** The primary is not removed while others remain: another is made the primary first. */
export function mayRemove(member: OwnerMember, members: readonly OwnerMember[]): boolean {
  return member.role !== "primary" || members.length === 1;
}

export function memberRoleLabel(role: string): string {
  if (role === "primary") return "Primary";
  if (role === "alternate") return "Alternate";
  return role;
}
