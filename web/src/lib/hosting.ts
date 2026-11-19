// 0.9.8: a thing that runs on another (P-226, P-246, P-249, P-250). A virtual machine on
// a hypervisor, a virtual context in a switch and a long-lived container are items of
// their own that name what they run on: an item, or a stack or a cluster. The server
// holds the rules and says what each record runs on, what was seen, and what is to be
// looked at; this only turns that into words and links, and the one field of a form that
// names an item or a group into the two fields the server takes.

import type { Schemas } from "../api/client";
import { all, any, type FilterNode, itemsPath } from "./filter";
import { formatTime, itemName } from "./format";
import { groupTypeLabel } from "./groups";
import { type FieldSpec, type FormValues, localMoment, type Option } from "./patch";

export type HostRef = Schemas["HostRef"];
export type ReviewReason = Schemas["ReviewReason"];
export type HostedItem = Schemas["HostedItem"];

/** The kinds of model whose items run on a host. */
export const HOSTED_KINDS: readonly string[] = ["virtual_machine", "virtual_context", "container"];

/** The kinds of model whose items may be a host; an item with no model may be one too. */
export const HOSTING_KINDS: readonly string[] = ["hardware", "virtual_machine"];

/** The types of group that may be a host: the two that are one device. */
export const HOSTING_GROUPS: readonly string[] = ["stack", "cluster"];

/** The states in which an item is out of the team's hands, and hosts nothing. */
const LEFT: readonly string[] = ["Released", "Archived"];

/** Whether an item of a model of this kind runs on a host. */
export function runsOnHost(kind: string | null | undefined): boolean {
  return typeof kind === "string" && HOSTED_KINDS.includes(kind);
}

/** Whether an item of a model of this kind may be a host. No model may. */
export function mayHost(kind: string | null | undefined): boolean {
  return kind === null || kind === undefined || HOSTING_KINDS.includes(kind);
}

/** The page of what an item runs on. */
export function hostPath(host: { item_hid: string | null; group_hid: string | null }): string {
  return host.group_hid
    ? `/groups/${encodeURIComponent(host.group_hid)}`
    : `/items/${encodeURIComponent(host.item_hid ?? "")}`;
}

/** Which record a host is, in a word: "a cluster", "a stack", "an item". */
export function hostWhat(host: { type: string | null }): string {
  if (host.type === "cluster") return "a cluster";
  if (host.type === "stack") return "a stack";
  if (host.type) return `a ${groupTypeLabel(host.type).toLowerCase()}`;
  return "an item";
}

/** What a cell of a list says of a host beyond its name: which record it is, and if gone. */
export function hostHint(host: HostRef): string {
  const what = hostWhat(host);
  const which = `${what.charAt(0).toUpperCase()}${what.slice(1)}${host.pid ? `, ${host.pid}` : ""}`;
  return hostIsGone(host) ? `${which}: retired or out of the team's hands` : which;
}

/** Whether the host named is gone: retired, or an item out of the team's hands. */
export function hostIsGone(host: HostRef): boolean {
  return host.record_status === "retired" || LEFT.includes(host.lifecycle_state ?? "");
}

// --- the field of a form that names an item or a group ---------------------------------

/** The name of the field of a form that holds what an item runs on, an item or a group. */
export const HOST_FIELD = "host_hid";

/** The two fields of the server that one value of the form stands for. */
export const HOST_FIELDS: readonly string[] = ["host_item_hid", "host_group_hid"];

/** What the form holds for what an item runs on: `item:<hid>`, `group:<hid>`, or blank. */
export function hostValue(item: {
  host_item_hid?: string | null;
  host_group_hid?: string | null;
}): string {
  if (item.host_group_hid) return `group:${item.host_group_hid}`;
  if (item.host_item_hid) return `item:${item.host_item_hid}`;
  return "";
}

/** The fields of the server for what the form holds: one set, the other cleared. */
export function hostFields(value: string): {
  host_item_hid: string | null;
  host_group_hid: string | null;
} {
  if (value.startsWith("group:")) return { host_item_hid: null, host_group_hid: value.slice(6) };
  if (value.startsWith("item:")) return { host_item_hid: value.slice(5), host_group_hid: null };
  return { host_item_hid: null, host_group_hid: null };
}

/**
 * The body a form of an item sends, with the one field of what it runs on put as the
 * server takes it. A body that does not name it is sent as it is. On a new item only the
 * one that is given is sent.
 */
export function sentHost<T>(body: T, creating = false): T {
  const fields = body as Record<string, unknown>;
  if (!(HOST_FIELD in fields)) return body;
  const { [HOST_FIELD]: value, ...rest } = fields;
  const host = hostFields(typeof value === "string" ? value : "");
  if (!creating) return { ...rest, ...host } as T;
  return {
    ...rest,
    ...(host.host_item_hid ? { host_item_hid: host.host_item_hid } : {}),
    ...(host.host_group_hid ? { host_group_hid: host.host_group_hid } : {}),
  } as T;
}

/** An item offered as a host: its name, its PID, and that it is an item. */
export function hostItemOption(item: {
  hid: string;
  name?: string | null;
  hostname?: string | null;
  serial_number?: string | null;
  asset_tag?: string | null;
  catalog?: { pid: string } | null;
}): Option {
  const pid = item.catalog?.pid ? ` · ${item.catalog.pid}` : "";
  return { value: `item:${item.hid}`, label: `${itemName(item)}${pid} · an item` };
}

/** A stack or a cluster offered as a host: its name, and which of the two it is. */
export function hostGroupOption(group: { hid: string; name: string; type: string }): Option {
  return { value: `group:${group.hid}`, label: `${group.name} · ${hostWhat(group)}` };
}

// The hosts a search has offered in this page, by what a form holds of each: a bulk edit
// names a stack or a cluster by its name, as a file does.
const seenHosts = new Map<string, string>();

/** Note the hosts a search offered, each by what the form holds and its name. */
export function sawHosts(hosts: ReadonlyArray<{ value: string; name: string }>): void {
  for (const host of hosts) seenHosts.set(host.value, host.name);
}

/** The name of a host a search offered, by what the form holds of it. */
export function hostSeen(value: string): string | undefined {
  return seenHosts.get(value);
}

/**
 * What a bulk edit sets for a host the form holds (P-250), as the columns of a file name
 * it: `host`, the item, by its HID, or `host_group`, a stack or a cluster, by its name.
 * Null where a group's name is not known.
 */
export function bulkHost(
  value: string,
  groupName: string | undefined,
): Record<string, string> | null {
  const host = hostFields(value);
  if (host.host_item_hid) return { host: host.host_item_hid };
  if (host.host_group_hid && groupName) return { host_group: groupName };
  return null;
}

/** What a form says the host is, before a search: the one the item names. */
export function hostOption(host: HostRef | null): Option[] {
  if (!host) return [];
  const value = host.group_hid ? `group:${host.group_hid}` : `item:${host.item_hid ?? ""}`;
  const pid = host.pid ? ` · ${host.pid}` : "";
  return [{ value, label: `${host.name}${pid} · ${hostWhat(host)}` }];
}

/**
 * The items a search offers as a host, by what was typed: of a kind that may host, or of
 * no model. Retired items are left out by the list; one out of the team's hands is
 * refused by the server, naming the field.
 */
export function hostItemSearch(text: FilterNode | null): FilterNode | null {
  if (text === null) return null;
  return all(
    text,
    any(
      { field: "catalog.kind", op: "in", value: [...HOSTING_KINDS] },
      { field: "catalog_entry_hid", op: "empty", value: true },
    ),
  );
}

/** The item list of what names a record as its host, to tick and change together. */
export function hostedListPath(of: "item" | "group", hid: string): string {
  return itemsPath(`${of === "item" ? "host_item_hid" : "host_group_hid"}:eq:${hid}`);
}

/**
 * What runs on a record, as its list shows it: each once, after its host as the server
 * sent it, with how deep it stands, 1 for what runs on the record itself.
 */
export function hostedRows(
  hosted: readonly HostedItem[],
): Array<{ item: HostedItem["item"]; depth: number }> {
  const seen = new Set<string>();
  const rows: Array<{ item: HostedItem["item"]; depth: number }> = [];
  for (const one of hosted) {
    if (seen.has(one.item.hid)) continue;
    seen.add(one.item.hid);
    rows.push({ item: one.item, depth: Math.max(1, one.depth) });
  }
  return rows;
}

// --- what is to be looked at ------------------------------------------------------------

/** The reasons an item is to be looked at, as the filter of the list offers them. */
export const REVIEW_REASONS: readonly Option[] = [
  { value: "no_host", label: "Names no host" },
  { value: "host_gone", label: "Its host is gone" },
  { value: "not_reported", label: "Not reported" },
];

/** One reason in words, with what it is about. */
export function reviewText(reason: ReviewReason): string {
  const word = REVIEW_REASONS.find((one) => one.value === reason.reason)?.label ?? reason.reason;
  return reason.about ? `${word}: ${reason.about.label}` : word;
}

/** Every reason of a record in words, parted by semicolons. Blank for none. */
export function reviewsText(review: readonly ReviewReason[]): string {
  return review.map(reviewText).join("; ");
}

// --- what was seen --------------------------------------------------------------------

/** The moment a host was seen, as the page says it. */
export function seenAt(at: string | null | undefined): string {
  return at ? formatTime(at) : "";
}

// --- the fields of an item's form -------------------------------------------------------

/** What the fields of what an item runs on need of the form they stand in. */
export interface HostFormFacts {
  /** The kind of the model the form holds now, by its HID. */
  kindOf: (entryHid: string) => string | null | undefined;
  /** What the item runs on now, and what it was seen on, as the form names them first. */
  host?: HostRef | null;
  observed?: { hid: string; label: string } | null;
  /** The item itself, which is never its own host. */
  self?: string;
}

/**
 * The fields of what an item runs on, asked for while the model chosen is of a kind that
 * runs on a host (P-250): Host, an item or a stack or a cluster; what it was seen on, an
 * item; and when, filled with now as that item is chosen.
 */
export function hostSpecs(facts: HostFormFacts): FieldSpec[] {
  const hosted = (values: FormValues) => {
    const entry = values.catalog_entry_hid;
    return typeof entry === "string" && entry !== "" && runsOnHost(facts.kindOf(entry));
  };
  const exclude = facts.self ? [facts.self] : [];
  return [
    {
      name: HOST_FIELD,
      label: "Host",
      kind: "host",
      blank: "No host named: it is marked to be looked at",
      options: hostOption(facts.host ?? null),
      exclude,
      aliases: HOST_FIELDS,
      hint: "What it runs on: a server, a switch, a virtual machine, or a stack or a cluster. Its location, owner and operator come from there unless it has its own.",
      when: hosted,
      clearedWhenNotAsked: true,
    },
    {
      name: "observed_host_hid",
      label: "Seen on",
      kind: "item",
      blank: "Not seen on any",
      options: facts.observed ? [{ value: facts.observed.hid, label: facts.observed.label }] : [],
      exclude,
      hint: "The item it was seen to run on, which may differ from its host.",
      when: hosted,
      // A model of a kind that runs on no host takes what was seen with the host.
      clearedWhenNotAsked: true,
      fills: (value) => ({ host_observed_at: value === "" ? "" : localMoment(new Date()) }),
    },
    {
      name: "host_observed_at",
      label: "Seen at",
      kind: "moment",
      hint: "When it was seen there: now, as the item is chosen.",
      when: (values) => hosted(values) && values.observed_host_hid !== "",
      clearedWhenNotAsked: true,
    },
  ];
}

/**
 * What the form says beneath the model of an item that names a host or was seen on one,
 * while the model chosen is of a kind that runs on none: that saving clears both. Blank
 * otherwise.
 */
export function hostClearedHint(facts: HostFormFacts, values: FormValues): string | undefined {
  if (!facts.host && !facts.observed) return undefined;
  const entry = values.catalog_entry_hid;
  const kind = typeof entry === "string" && entry !== "" ? facts.kindOf(entry) : null;
  if (runsOnHost(kind)) return undefined;
  return "A model of this kind runs on no host: saving clears what the item runs on and what it was seen on.";
}
