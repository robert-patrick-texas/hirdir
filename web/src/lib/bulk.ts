// Bulk edit: one change to many items.
//
// The form says which rows (the ones selected, by HID, or every row the filter keeps, by
// the filter) and what to change. A field is named as a column of an import. A field
// that is not on the form is left alone; one that is on it is set, or cleared with null.
// The server works out what that does to each row and stores it as a preview.

import type { Schemas } from "../api/client";
import { type FieldSpec, type FormValue, read } from "./patch";
import type { Chosen, GridView } from "./transfer";

export type BulkUpdate = Schemas["BulkUpdate"];

/** The fields that tell one item from another. They are not set in bulk. */
export const NOT_IN_BULK: readonly string[] = [
  "serial_number",
  "asset_tag",
  "mac_address",
  "name",
  "hostname",
  "fqdn",
];

/** The line of the form that names a catalog entry. It sets two columns: vendor and PID. */
export const CATALOG_ENTRY = "catalog_entry";
export const LIFECYCLE_STATE = "lifecycle_state";
/** The line that names an owner. An owner outside the team has a reason beside it. */
export const OWNER = "owner";

/** A field a bulk edit may change. */
export interface BulkField extends FieldSpec {
  /** Whether the field may be cleared, so that it is blank or inherits again. */
  clearable?: boolean;
}

/** One field on the form: what it is to be set to, or that it is to be cleared. */
export interface BulkLine {
  name: string;
  clear: boolean;
  value: FormValue;
}

export interface BulkDraft {
  lines: readonly BulkLine[];
  /** Why the items move, when the lifecycle state is among the lines. */
  reason: string;
  /** Why the items are with an owner outside the team, when such an owner is set. */
  ownerReason?: string;
  addTags: readonly string[];
  removeTags: readonly string[];
}

/** A catalog entry as a file names it: its vendor, here by HID, and its PID. */
export interface EntryRef {
  vendor: string;
  pid: string;
}

type Rows = Pick<
  BulkUpdate,
  "filter" | "hids" | "all_rows" | "include_archived" | "include_drafts"
>;

/**
 * The rows of a bulk edit as the server takes them. Particular rows are named by their
 * HIDs. All that match are named by the filter, with the switches of the list, and with
 * no filter at all the request has to say that every item is meant.
 */
export function bulkRows(chosen: Chosen, view: GridView): Rows {
  if (chosen.kind === "rows") return { hids: [...chosen.hids] };
  const switches = {
    include_archived: view.include_archived,
    include_drafts: view.include_drafts,
  };
  if (view.filter === null) return { all_rows: true, ...switches };
  return { filter: view.filter as unknown as Record<string, unknown>, ...switches };
}

export interface BuiltBulk {
  body: BulkUpdate;
  /** What is wrong with a line, by its name, found before anything was sent. */
  errors: Record<string, string>;
  /** True when the form changes nothing yet. */
  empty: boolean;
}

/** The body of `POST /items/bulk-update` for the rows chosen and the change on the form. */
export function buildBulk(
  fields: readonly BulkField[],
  draft: BulkDraft,
  rows: Rows,
  entries: Readonly<Record<string, EntryRef>> = {},
  external: ReadonlySet<string> = new Set(),
): BuiltBulk {
  const set: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const line of draft.lines) {
    const field = fields.find((candidate) => candidate.name === line.name);
    if (!field || NOT_IN_BULK.includes(line.name)) {
      errors[line.name] = "This field is not set in bulk.";
      continue;
    }
    if (line.clear) {
      if (field.clearable) set[field.name] = null;
      else errors[field.name] = "This field cannot be cleared.";
      continue;
    }
    const result = read(field, line.value);
    if ("error" in result) {
      errors[field.name] = result.error;
    } else if (result.value === null) {
      errors[field.name] = field.clearable
        ? "Give a value, or choose to clear the field."
        : "Give a value.";
    } else if (field.name === CATALOG_ENTRY) {
      const entry = entries[String(result.value)];
      if (entry) {
        set.vendor = entry.vendor;
        set.pid = entry.pid;
      } else errors[field.name] = "Choose a catalog entry.";
    } else {
      set[field.name] = result.value;
    }
  }
  // A reason is taken with a move to another state, and with nothing else.
  const reason = draft.reason.trim();
  if (reason !== "" && typeof set[LIFECYCLE_STATE] === "string") set.state_reason = reason;
  // The reason for an exception goes beside an owner outside the team, and with nothing
  // else. Left blank it is left out: an item that has one already keeps it, and the
  // server rejects the rows that have none.
  const ownerReason = (draft.ownerReason ?? "").trim();
  const owner = set[OWNER];
  if (ownerReason !== "" && typeof owner === "string" && external.has(owner)) {
    set.owner_exception_reason = ownerReason;
  }

  const addTags = [...new Set(draft.addTags)];
  const removeTags = [...new Set(draft.removeTags)];
  const both = removeTags.filter((label) => addTags.includes(label));
  if (both.length > 0) {
    errors.remove_tags = `Also among the tags to add: ${both.join(", ")}.`;
  }
  const body: BulkUpdate = {
    ...rows,
    ...(Object.keys(set).length > 0 ? { set } : {}),
    ...(addTags.length > 0 ? { add_tags: addTags } : {}),
    ...(removeTags.length > 0 ? { remove_tags: removeTags } : {}),
  };
  const empty = draft.lines.length === 0 && addTags.length === 0 && removeTags.length === 0;
  return { body, errors, empty };
}

/** What is the same about a bulk edit whenever the same one is sent again. */
export function bulkIdentity(body: BulkUpdate): string {
  return `bulk ${JSON.stringify(body)}`;
}
