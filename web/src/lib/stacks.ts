// 0.9.6: working a stack (P-220, P-222). A stack is known by its name, and its members,
// which have no name of their own, by the stack they are in and their position in it.

import type { ExistingRecord } from "../api/client";
import { any, type FilterNode, isCondition } from "./filter";
import { existingPath } from "./problems";

// The most device groups the line above the items names.
export const MOST_NAMED = 3;

/**
 * The words a filter of the item list looks for in the names of the groups: the values
 * of its conditions `group.name` `contains` or `eq`, as the plain words of the list send
 * them, each once, in the order they stand.
 */
export function groupWords(filter: FilterNode | null | undefined): string[] {
  const found: string[] = [];
  const walk = (node: FilterNode) => {
    if (isCondition(node)) {
      if (
        node.field === "group.name" &&
        (node.op === "contains" || node.op === "eq") &&
        typeof node.value === "string" &&
        node.value.trim() !== "" &&
        !found.includes(node.value.trim())
      ) {
        found.push(node.value.trim());
      }
      return;
    }
    for (const part of "and" in node ? node.and : node.or) walk(part);
  };
  if (filter) walk(filter);
  return found;
}

/** Whether two lists of words are the same words in the same order. */
export function sameWords(one: readonly string[], other: readonly string[]): boolean {
  return one.length === other.length && one.every((word, index) => word === other[index]);
}

/** The device groups those words name: a group whose name or host name is one of them. */
export function namedBy(words: readonly string[]): FilterNode | null {
  return any(
    ...words.flatMap((value) => [
      { field: "name", op: "eq" as const, value },
      { field: "hostname", op: "eq" as const, value },
    ]),
  );
}

/** A group a member is in, as an item names it. */
export interface Membership {
  group_hid: string;
  name: string;
  type: string;
  position: number | null;
}

/** The stack an item is a current member of: one at most. */
export function stackOf<T extends { type: string }>(groups: readonly T[]): T | undefined {
  return groups.find((group) => group.type === "stack");
}

/** A member as the item list names it: its stack and its position, "cw07-idf03-acc1 #2". */
export function memberText(groups: readonly Membership[]): string {
  const stack = stackOf(groups);
  if (!stack) return "";
  return stack.position === null ? stack.name : `${stack.name} #${stack.position}`;
}

// --- The forms of a stack's page (P-217 to P-219) -----------------------------------

/**
 * The position to offer a member about to be added (P-219): the stack's `next_position`,
 * the lowest that no current member holds, or else 1, passing over those that the other
 * members of the same request are given, so that a replacement takes the place of the one
 * that left.
 */
export function offeredPosition(
  next: number | null | undefined,
  used: ReadonlyArray<number | null | undefined>,
): number {
  const held = new Set(used.filter((one): one is number => typeof one === "number"));
  let position = next ?? 1;
  while (held.has(position)) position += 1;
  return position;
}

/** The fields of a member added that a refusal names, as `members.0.position`. */
export const MEMBER_FIELDS = ["position", "drop_identity", "disposition", "expected_online"];

/** What the server refused of the members sent, by the HID of each item, to say by its row. */
export interface RefusedRows {
  errors: Record<string, string>;
  /** The member that holds a position refused, as a link (P-219). */
  holders: Record<string, { to: string; label: string }>;
}

/**
 * The refusals of the members of one request, by row: each field the server named, as
 * `members.1.position`, put beside the item sent at that place in the list; and, for a
 * position another member holds, that member as the refusal's `existing` names it.
 */
export function refusedRows(
  sent: ReadonlyArray<{ item_hid: string }>,
  refused: Readonly<Record<string, string>>,
  existing: Pick<ExistingRecord, "record_type" | "hid" | "label"> | null,
): RefusedRows {
  const errors: Record<string, string> = {};
  const holders: Record<string, { to: string; label: string }> = {};
  sent.forEach((member, index) => {
    const said = MEMBER_FIELDS.map((field) => refused[`members.${index}.${field}`]).filter(
      (message): message is string => Boolean(message),
    );
    if (said.length > 0) errors[member.item_hid] = said.join(" ");
    const to = existing ? existingPath(existing) : null;
    if (refused[`members.${index}.position`] && existing && to) {
      holders[member.item_hid] = { to, label: existing.label };
    }
  });
  return { errors, holders };
}

/** What of a switch the form needs to say what joining a stack removes, and what it is. */
export interface Joining {
  hostname?: string | null;
  fqdn?: string | null;
  addresses?: ReadonlyArray<{ address: string }>;
  /** Its own location, not the one in force. */
  location?: { path: string } | null;
  lifecycle_state?: string | null;
  disposition?: string | null;
}

/** Words joined as a list is said: "a, b and c". */
export function listed(words: readonly string[]): string {
  if (words.length <= 1) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words.at(-1)}`;
}

/**
 * Exactly what joining a stack with its name and place will remove from this switch
 * (P-217): its host name, its FQDN, each of its addresses and its own location, as the
 * switch has them. None, for a switch that has none of them.
 */
export function dropsOf(item: Joining): string[] {
  return [
    ...(item.hostname ? [`the host name ${item.hostname}`] : []),
    ...(item.fqdn ? [`the FQDN ${item.fqdn}`] : []),
    ...(item.addresses ?? []).map((one) => `the address ${one.address}`),
    ...(item.location ? [`its own location ${item.location.path}`] : []),
  ];
}

/** The line under the box: what is about to go, before it goes. */
export function dropsText(name: string, item: Joining): string {
  const drops = dropsOf(item);
  if (drops.length === 0) {
    return `${name} has no host name, FQDN, address or location of its own: nothing is removed.`;
  }
  return `Removed from ${name}: ${listed(drops)}. The stack's are in force for it.`;
}

/** The disposition and intent a member of a stack is offered with, as the form holds them. */
export interface JoinStanding {
  /** A disposition, or blank to leave it as it is. */
  disposition: string;
  /** "true", "false", or blank to leave it as it is. */
  online: string;
}

/**
 * What a switch that joins a stack is offered (P-217): a spare is offered Production and
 * expected online, where the rule of its state allows them; anything else is left as it
 * is. `allowed` is the dispositions the rule of its state allows, and `intents` the
 * intents it allows with Production.
 */
export function joinStanding(
  item: Joining,
  allowed: readonly string[],
  intents: readonly boolean[],
): JoinStanding {
  if (item.disposition !== "Spare" || !allowed.includes("Production")) {
    return { disposition: "", online: "" };
  }
  return { disposition: "Production", online: intents.includes(true) ? "true" : "" };
}

/**
 * What the answer to an add says was done to one member (P-217): where it joined, and for
 * one that took the stack's name and place, what was removed and what it is now.
 */
export function joinedText(
  group: string,
  name: string,
  position: number | null,
  sent: { drop_identity?: boolean; disposition?: string | null; expected_online?: boolean | null },
  has: Joining | undefined,
): string {
  const where = position === null ? "" : ` as member ${position}`;
  const said = [`${name} was added to ${group}${where}.`];
  if (sent.drop_identity) {
    const drops = dropsOf(has ?? {});
    said.push(
      drops.length > 0
        ? `It takes the stack's name and place: ${listed(drops)} removed.`
        : "It takes the stack's name and place.",
    );
  }
  const now = [
    ...(sent.disposition ? [sent.disposition] : []),
    ...(sent.expected_online === true ? ["expected online"] : []),
    ...(sent.expected_online === false ? ["not expected online"] : []),
  ];
  if (now.length > 0) said.push(`It is ${listed(now)} now.`);
  return said.join(" ");
}

/** An intent of a form, as it is sent: blank is left out. */
export function onlineValue(online: string): boolean | undefined {
  if (online === "true") return true;
  if (online === "false") return false;
  return undefined;
}

// What becomes of a member that leaves a stack (P-218).
export const LEAVING = ["pool", "returned", "excess", "nothing"] as const;
export type Leaving = (typeof LEAVING)[number];

export const LEAVING_LABELS: Readonly<Record<Leaving, string>> = {
  pool: "To the spare pool",
  returned: "To be returned to the manufacturer",
  excess: "Excess",
  nothing: "Nothing now",
};

/** The fields of what becomes of the item, as the form holds them: blank is left as it is. */
export interface LeavingValues {
  hostname: string;
  fqdn: string;
  location_hid: string;
  lifecycle_state: string;
  state_reason: string;
  disposition: string;
  online: string;
}

/** What the lifecycle rules and the published choices allow, for the presets to keep to. */
export interface LeavingRules {
  /** The states the item may move to from its own. */
  next: readonly string[];
  /** The dispositions allowed in a state, for the item as it is. */
  dispositions: (state: string) => readonly string[];
  /** The reasons for a state that the server publishes. */
  reasons: readonly string[];
}

const PENDING_REMOVAL = "Pending-Removal";

/**
 * The fields a choice fills, which the person may change (P-218). The web offers; the
 * server decides: a state is filled only where the rules let the item move to it, a
 * reason and a disposition only where they are published and allowed.
 *
 * - To the spare pool: a new host name and FQDN and a place, typed by the person;
 *   disposition Spare, not expected online; the state as it is.
 * - To be returned to the manufacturer: Pending-Removal for the reason rma, not
 *   expected online, the disposition as it is.
 * - Excess: Pending-Removal for the reason retired, disposition Excess, not expected online.
 */
export function leavingPreset(
  choice: Leaving,
  state: string | null | undefined,
  rules: LeavingRules,
): LeavingValues | null {
  if (choice === "nothing") return null;
  const blank: LeavingValues = {
    hostname: "",
    fqdn: "",
    location_hid: "",
    lifecycle_state: "",
    state_reason: "",
    disposition: "",
    online: "false",
  };
  const reason = (wanted: string) => (rules.reasons.includes(wanted) ? wanted : "");
  if (choice === "pool") {
    const allowed = rules.dispositions(state ?? "");
    return { ...blank, disposition: allowed.includes("Spare") ? "Spare" : "" };
  }
  const moves = rules.next.includes(PENDING_REMOVAL);
  const to = moves ? PENDING_REMOVAL : "";
  if (choice === "returned") {
    return { ...blank, lifecycle_state: to, state_reason: moves ? reason("rma") : "" };
  }
  const allowed = rules.dispositions(to || (state ?? ""));
  return {
    ...blank,
    lifecycle_state: to,
    state_reason: moves ? reason("retired") : "",
    disposition: allowed.includes("Excess") ? "Excess" : "",
  };
}

/** What is sent as `item` with the end. */
export interface LeavingBody {
  hostname?: string;
  fqdn?: string;
  location_hid?: string;
  lifecycle_state?: string;
  state_reason?: string;
  disposition?: string;
  expected_online?: boolean;
}

/** What is sent as `item` with the end: the fields filled, those left blank left out. */
export function leavingBody(values: LeavingValues): LeavingBody {
  const online = onlineValue(values.online);
  const hostname = values.hostname.trim();
  const fqdn = values.fqdn.trim();
  return {
    ...(hostname ? { hostname } : {}),
    ...(fqdn ? { fqdn } : {}),
    ...(values.location_hid ? { location_hid: values.location_hid } : {}),
    ...(values.lifecycle_state ? { lifecycle_state: values.lifecycle_state } : {}),
    // A reason goes with a move, and with nothing else.
    ...(values.lifecycle_state && values.state_reason ? { state_reason: values.state_reason } : {}),
    ...(values.disposition ? { disposition: values.disposition } : {}),
    ...(online === undefined ? {} : { expected_online: online }),
  };
}

/** What the answer says the end did to the item: "moved to Pending-Removal and given ...". */
export function leavingText(body: LeavingBody): string {
  return listed([
    ...(body.hostname ? [`named ${body.hostname}`] : []),
    ...(body.location_hid ? ["given its place"] : []),
    ...(body.lifecycle_state ? [`moved to ${body.lifecycle_state}`] : []),
    ...(body.disposition ? [`given the disposition ${body.disposition}`] : []),
    ...(body.expected_online === true ? ["expected online"] : []),
    ...(body.expected_online === false ? ["not expected online"] : []),
  ]);
}
