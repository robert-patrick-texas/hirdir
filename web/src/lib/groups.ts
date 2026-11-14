// Device groups as words, and what a form of members sends. The types of group and the
// roles of each are fixed by the data model. The server checks every group as a whole,
// a stack for its one master, and its refusal is what counts: what
// is here only offers what the rules allow and says early what they will say.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type DeviceGroup = Schemas["DeviceGroupOut"];
export type GroupType = DeviceGroup["type"];
export type Member = Schemas["MemberOut"];
export type MemberAdd = Schemas["MemberAdd"];

export const GROUP_TYPES: ReadonlyArray<Option & { value: GroupType }> = [
  { value: "stack", label: "Stack" },
  { value: "cluster", label: "Cluster" },
  { value: "controller_domain", label: "Controller domain" },
  { value: "custom", label: "Custom" },
];

/** The roles a member may have in each type of group. The first is the one taken when none is named. */
const ROLES: Readonly<Record<GroupType, readonly string[]>> = {
  stack: ["member", "master"],
  cluster: ["member", "active", "standby"],
  controller_domain: ["endpoint", "controller"],
  custom: ["member"],
};

const ROLE_LABELS: Readonly<Record<string, string>> = {
  master: "Master",
  member: "Member",
  active: "Active",
  standby: "Standby",
  controller: "Controller",
  endpoint: "Endpoint",
};

export const MASTER = "master";
// The largest position the server takes.
const LAST_POSITION = 10000;

export function isGroupType(value: string): value is GroupType {
  return GROUP_TYPES.some((type) => type.value === value);
}

/** The name of a type of group for people. One this build does not know is shown as sent. */
export function groupTypeLabel(type: string): string {
  return GROUP_TYPES.find((known) => known.value === type)?.label ?? type;
}

/** The roles a member of a group of this type may have, the usual one first. */
export function rolesOf(type: string): readonly string[] {
  return isGroupType(type) ? ROLES[type] : ["member"];
}

/** The role a member has when none is named. */
export function defaultRole(type: string): string {
  return rolesOf(type)[0] ?? "member";
}

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

export function roleOptions(type: string): Option[] {
  return rolesOf(type).map((role) => ({ value: role, label: roleLabel(role) }));
}

/** A membership in a few words, as an item's page lists it: "Master, position 1". */
export function membershipText(member: { role: string; position: number | null }): string {
  const role = roleLabel(member.role);
  return member.position === null ? role : `${role}, position ${member.position}`;
}

/** True when a current member has another owner in force than the group's own (P-67). */
export function ownerDisputed(group: { members_disagree: readonly string[] }): boolean {
  return group.members_disagree.includes("owner_hid");
}

/** The position to offer the next member: one past the highest there is, from 1. */
export function nextPosition(positions: ReadonlyArray<number | null | undefined>): number {
  let highest = 0;
  for (const position of positions) {
    if (typeof position === "number" && position > highest) highest = position;
  }
  return highest + 1;
}

/** An item chosen to become a member, with the role and position typed for it. */
export interface PendingMember {
  item_hid: string;
  /** What to call the item while it waits in the form. */
  name: string;
  role: string;
  /** As typed. Blank is no position. */
  position: string;
}

export interface MembersBuilt {
  members: MemberAdd[];
  /** What is wrong with a row, by the HID of its item, found before anything was sent. */
  errors: Record<string, string>;
}

/**
 * The members of one request: every item chosen, each with its role and position, and
 * the day they join when one was given. They are sent together, so that the group is
 * checked once they are all in.
 */
export function buildMembers(
  type: string,
  pending: readonly PendingMember[],
  joinedOn = "",
): MembersBuilt {
  const members: MemberAdd[] = [];
  const errors: Record<string, string> = {};
  const allowed = rolesOf(type);
  for (const row of pending) {
    const position = row.position.trim();
    if (position !== "" && (!/^\d{1,5}$/.test(position) || Number(position) > LAST_POSITION)) {
      errors[row.item_hid] = `A whole number from 0 to ${LAST_POSITION}, or blank.`;
      continue;
    }
    if (!allowed.includes(row.role)) {
      errors[row.item_hid] = `One of ${allowed.map(roleLabel).join(", ")}.`;
      continue;
    }
    members.push({
      item_hid: row.item_hid,
      role: row.role,
      ...(position === "" ? {} : { position: Number(position) }),
      ...(joinedOn === "" ? {} : { joined_on: joinedOn }),
    });
  }
  return { members, errors };
}

/**
 * What the rules will say of a stack with these members, before it is sent: nothing
 * when it would stand. A stack with no member at all is a shell and stands. From its
 * first member on, an active stack has exactly one master, which may be its only member;
 * a draft may have no master yet, and never two masters.
 */
export function stackProblem(type: string, recordStatus: string, roles: readonly string[]): string {
  if (type !== "stack" || roles.length === 0) return "";
  const masters = roles.filter((role) => role === MASTER).length;
  if (masters > 1) return "A stack has exactly one master: this one would have more.";
  if (recordStatus === "draft") return "";
  if (masters === 0) return "A stack has exactly one master: choose which member it is.";
  return "";
}
