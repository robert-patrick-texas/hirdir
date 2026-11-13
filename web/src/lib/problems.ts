// What a refused change means for the form that sent it.
//
// The server answers a refusal with an RFC 9457 problem document. Three of them matter
// to a form: the record changed under the reader (409 "Stale version"), the change
// collides with another record (409 "Conflict"), and one or more fields are not
// acceptable (422, with the fields named in `errors`).

import type { ApiError } from "../api/client";

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
