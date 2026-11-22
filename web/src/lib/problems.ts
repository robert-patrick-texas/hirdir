// What a refused change means for the form that sent it.
//
// The server answers a refusal with an RFC 9457 problem document. Three of them matter
// to a form: the record changed under the reader (409 "Stale version"), the change
// collides with another record (409 "Conflict"), and one or more fields are not
// acceptable (422, with the fields named in `errors`).

import type { ApiError, ExistingRecord } from "../api/client";
import { kindPath } from "./preview";

export type Refusal =
  /** Someone else changed the record. Nothing was saved, and nothing is sent again. */
  | "stale"
  /** The change collides with another record, such as a serial number already in use. */
  | "conflict"
  /** One or more fields are not acceptable. */
  | "invalid"
  /** The reader's role does not allow it. */
  | "forbidden"
  /** The record is not there. */
  | "missing"
  /** The server could not be reached. */
  | "unreachable"
  | "other";

export function refusalOf(error: ApiError): Refusal {
  if (error.stale) return "stale";
  switch (error.status) {
    case 409:
      return "conflict";
    case 422:
      return "invalid";
    case 403:
      return "forbidden";
    case 404:
      return "missing";
    case 0:
      return "unreachable";
    default:
      return "other";
  }
}

export interface FieldErrors {
  /** Messages for the fields the form shows, by the name the form knows them by. */
  shown: Record<string, string>;
  /** Messages about anything the form has no input for, to be listed above it. */
  rest: Array<[field: string, message: string]>;
}

/**
 * Sort a refusal's field messages into those the form can show beside an input and the
 * rest. The server names a field as the request does (`est_value`), an entry of a list
 * by its place (`tags.0`), and a query parameter with its origin (`query.limit`): each is
 * matched to the form's field of that name.
 */
export function fieldErrors(error: ApiError | null, known: readonly string[]): FieldErrors {
  const shown: Record<string, string> = {};
  const rest: FieldErrors["rest"] = [];
  if (!error) return { shown, rest };
  for (const [field, message] of Object.entries(error.fields)) {
    const parts = field.split(".");
    const name = known.includes(field)
      ? field
      : parts.find((part) => known.includes(part) && part !== "query");
    if (name === undefined) {
      rest.push([field, message]);
    } else {
      shown[name] = shown[name] === undefined ? message : `${shown[name]}; ${message}`;
    }
  }
  return { shown, rest };
}

/**
 * A sentence as it is shown: a capital first letter and a full stop. 0.9.17: a sentence
 * that begins with a username or a label begins as that is written (review 5): one of
 * `names`, the records the refusal names, or a first word written as only a name is,
 * with a hyphen, a dot, an underscore or a digit in it, as `agent-sync`.
 */
export function sentence(text: string, names: readonly string[] = []): string {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  const first = trimmed.split(/[\s,:;]/, 1)[0] ?? "";
  const named = names.some(
    (name) =>
      name !== "" && trimmed.startsWith(name) && /^($|[\s,:;.])/.test(trimmed.slice(name.length)),
  );
  const asWritten = named || /[-_.\d]/.test(first.replace(/\.$/, ""));
  const capital = asWritten ? trimmed : trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}

/**
 * What is wrong with a field that is not shown beside an input: the field as the page
 * calls it, then the message; or the message alone, as a sentence, for a field the page
 * names as blank. A field the page has no word for is named as the server names it.
 */
export function fieldLine(
  field: string,
  message: string,
  labels: Readonly<Record<string, string>> = {},
): string {
  const label = labels[field];
  if (label === "") return sentence(message);
  return `${label ?? field}: ${message}`;
}

/** Each kind of record a refusal may name, as a person calls it (P-207). */
const KIND_WORDS: Readonly<Record<string, string>> = {
  item: "item",
  catalog_entry: "catalog entry",
  vendor: "vendor",
  owner: "owner",
  device_group: "device group",
  operator: "operator",
  contact: "contact",
  circuit: "circuit",
  circuit_group: "circuit group",
  agreement: "agreement",
  contract: "contract",
  purchase_request: "purchase request",
  external_system: "external system",
  capacity_line: "capacity line",
  region: "region",
  site: "site",
  location: "location",
  user: "user",
  user_group: "user group",
  tag: "tag",
  choice: "value",
  network: "network",
  reference_file: "reference",
};

/** A kind of record as a person calls it: "catalog entry"; one with no word, as it is named. */
export function kindWord(recordType: string): string {
  return KIND_WORDS[recordType] ?? recordType.replaceAll("_", " ");
}

/**
 * What is said before the record a duplicate is refused for: "The item that has it:".
 * A kind the page has no word for is a record.
 */
export function existingLead(existing: Pick<ExistingRecord, "record_type">): string {
  return `The ${KIND_WORDS[existing.record_type] ?? "record"} that has it:`;
}

/**
 * The page of the record a duplicate is refused for, where its kind has one. A user and
 * a user group are refused only to an Admin, who alone may change them, so their pages
 * are offered: the server holds the role.
 */
export function existingPath(existing: Pick<ExistingRecord, "record_type" | "hid">): string | null {
  return kindPath(existing.record_type, existing.hid, true);
}
