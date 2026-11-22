// 0.9.8: what the audit trail on show knows of the records its events name (P-240).

/** The action of the event in which an Admin deleted a record. */
const DELETE = "delete";

interface Named {
  action: string;
  record_type: string;
  record_hid?: string | null;
}

function recordKey(kind: string, hid: string): string {
  return `${kind} ${hid}`;
}

/**
 * The records that the events held say were deleted: those of an event of the action
 * `delete`, by kind and HID. Every event of such a record names a record that is not
 * there, however early it is. A record deleted in an event not held is not known here.
 */
export function deletedRecords(events: readonly Named[]): ReadonlySet<string> {
  const gone = new Set<string>();
  for (const event of events) {
    if (event.action === DELETE && event.record_hid) {
      gone.add(recordKey(event.record_type, event.record_hid));
    }
  }
  return gone;
}

/** True where the events held say that the record an event names was deleted. */
export function isDeleted(gone: ReadonlySet<string>, event: Named): boolean {
  return (
    Boolean(event.record_hid) && gone.has(recordKey(event.record_type, event.record_hid ?? ""))
  );
}

/**
 * 0.9.14: an account as the list of who acted offers it (P-296): its username, a
 * retired one marked, since what it did is still in the trail. 0.9.17: an agent marked
 * with the person answerable for it, `agent-reconcile (agent, for sam)` (P-316).
 */
export function actorLabel(user: {
  username: string;
  record_status?: string | null;
  kind?: string;
  answerable?: { username: string } | null;
}): string {
  const marks: string[] = [];
  if (user.kind === "agent") {
    marks.push(user.answerable ? `agent, for ${user.answerable.username}` : "agent");
  }
  if (user.record_status === "retired") marks.push("retired");
  return marks.length > 0 ? `${user.username} (${marks.join(", ")})` : user.username;
}

/** Who acted, as an event answers it (P-316 (6)). */
export interface Acted {
  actor_hid: string | null;
  actor_name: string | null;
  actor_kind?: string | null;
  for_hid?: string | null;
  for_name?: string | null;
}

/**
 * Who made a change, as a history writes it (P-316 (6)): the username, and of an agent
 * the person it was answerable to then, `agent-reconcile for sam`; null for the system.
 */
export function actorWords(event: Acted): string | null {
  if (!event.actor_name) return null;
  if (event.actor_kind === "agent" && event.for_name) {
    return `${event.actor_name} for ${event.for_name}`;
  }
  return event.actor_name;
}

/** The kind of account that acted, as the trail is narrowed to it. */
export type ActorKind = "person" | "service" | "agent";

/** The kinds of account the Audit page narrows the trail to, by who acted (P-316). */
export const ACTOR_KINDS: ReadonlyArray<{ value: ActorKind | ""; label: string }> = [
  { value: "", label: "Any" },
  { value: "person", label: "People" },
  { value: "service", label: "Service accounts" },
  { value: "agent", label: "Agents" },
];

/** The kind of account an address narrows the trail to, or blank for any. */
export function actorKindOf(given: string | null | undefined): ActorKind | "" {
  return ACTOR_KINDS.find((one) => one.value !== "" && one.value === given)?.value ?? "";
}
