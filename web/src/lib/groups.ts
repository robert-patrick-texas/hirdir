// Device groups as words, and what a form of members sends. The types of group and the
// roles of each are fixed by the data model. The server checks every change, and its
// refusal is what counts: what is here only offers what the rules allow and says early
// what they will say.
//
// The master of a stack is two facts. The role `master` of a membership marks the master
// that is intended, the member given the priority: it is optional, and a stack has at
// most one. The master that is seen is recorded on the stack, with the moment, and may
// be another member. No rule depends on either, and neither stops a member leaving.

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
  // The role marks the master that is meant. The one that is seen is kept on the stack.
  master: "Intended master",
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

/** A membership in a few words, as an item's page lists it: "Intended master, position 1". */
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
 * What the rules will say of the members about to be added to a stack, before they are
 * sent: nothing when they would stand. A stack needs no master, may be one switch alone,
 * and may have no member at all. The one thing refused is two intended masters named in
 * one request: `adding` is the roles of the members of that request.
 */
export function stackProblem(type: string, adding: readonly string[]): string {
  if (type !== "stack") return "";
  const masters = adding.filter((role) => role === MASTER).length;
  if (masters > 1) {
    return "A stack has at most one intended master: more than one of these members is named as it.";
  }
  return "";
}

/**
 * True when a member about to be added as the intended master would take the mark from
 * the current member that has it. That is no fault: the form says so, and nothing more.
 */
export function takesTheMark(
  type: string,
  current: readonly string[],
  adding: readonly string[],
): boolean {
  return type === "stack" && current.includes(MASTER) && adding.includes(MASTER);
}

export type ManagedAs = NonNullable<DeviceGroup["managed_as"]>;

/**
 * How a cluster is managed, which is what it is on the network and so how many managed
 * nodes it counts as. The component count and the support weight do not depend on it.
 */
export const MANAGED_AS: ReadonlyArray<
  Option & { value: ManagedAs; nodes: string; explained: string }
> = [
  {
    value: "one",
    label: "One managed node",
    nodes: "One managed node",
    explained:
      "The cluster is one device on the network, and its members do not appear by themselves: a pair of wireless LAN controllers in HA, with one address to manage.",
  },
  {
    value: "members",
    label: "One for each member",
    nodes: "One managed node for each member",
    explained:
      "Every member is managed at its own address, and virtual addresses are shared between them: a pair of firewalls in HA.",
  },
  {
    value: "members_and_cluster",
    label: "Its members and a node of its own",
    nodes: "One managed node for each member, and one more for the cluster itself",
    explained:
      "Every member is managed, and the cluster answers as a virtual node as well: one more managed node than it has members.",
  },
];

/** How a cluster is managed, in a few words, for a cell or a fact. Blank for a group that is no cluster. */
export function managedAsText(managedAs: string | null | undefined): string {
  if (!managedAs) return "";
  return MANAGED_AS.find((known) => known.value === managedAs)?.nodes ?? managedAs;
}

/** Which master the serial number of a stack is read from, in words. Blank when from neither. */
export function serialSourceText(source: string | null | undefined): string {
  if (source === "observed") return "read from the master that is seen";
  if (source === "intended") return "read from the intended master";
  return "";
}
