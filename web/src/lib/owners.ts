// Owners and their people. An owner outside the operations team is an exception, and
// says why, once, where it is defined: an item and a device group that have it are marked
// and show that reason, and hold none of their own. The server keeps the rules; this
// lays owners out for a form and says of each whether it is outside the team.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type Owner = Schemas["OwnerOut"];
export type OwnerMember = Schemas["OwnerMemberOut"];

/** The heading a form lists the owners outside the team under. */
export const EXTERNAL_GROUP = "Outside the operations team";

type Named = Pick<Owner, "hid" | "label" | "is_external"> & {
  /** Why the owner is an exception, where the record that names it says. */
  exception_reason?: string | null;
};

/**
 * What a form says of an owner outside the team once it is chosen: that whatever has it
 * is marked as an exception, with the owner's reason, and where that reason is changed.
 */
export function externalNote(reason: string | null | undefined): string {
  const why = reason?.trim() ? `Its reason: ${reason.trim().replace(/[.!?]+$/, "")}.` : "";
  return [
    "This owner is outside the operations team, so what has it is marked as an exception.",
    why,
    "The reason is the owner's own, and is changed on the owner's page.",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * One owner as a form offers it: by its label, and under the heading of those outside the
 * team if it is one, with its reason to show once it is chosen.
 */
export function ownerOption(owner: Named): Option {
  return {
    value: owner.hid,
    label: owner.label,
    ...(owner.is_external
      ? { group: EXTERNAL_GROUP, note: externalNote(owner.exception_reason) }
      : {}),
  };
}

/** Owners as a form offers them, by label: those outside the team under a heading of their own. */
export function ownerOptions(owners: readonly Named[]): Option[] {
  return owners.map(ownerOption);
}

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
