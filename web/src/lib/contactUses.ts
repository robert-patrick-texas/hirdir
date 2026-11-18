// Where a contact is named (P-205), as the page of a contact lists it: by kind, each record
// a link to its page with the role the contact has there, from `GET /contacts/{hid}/uses`.
// The server says what names a contact, and counts it as the list of contacts does: here
// it is only put into words.

import type { Schemas } from "../api/client";
import { carrierRoleOne } from "./circuits";
import { type Mark, safeColour } from "./operators";
import { choiceLabel } from "./options";
import { memberRoleLabel } from "./owners";
import { CONTACT_ROLE_LIST, levelLabel } from "./places";
import { kindPath } from "./preview";
import { sentence } from "./problems";

export type ContactUses = Schemas["ContactUses"];
export type NamedRecord = Schemas["NamedRecord"];
export type NamedRecords = Schemas["NamedRecords"];
type Choice = Schemas["ChoiceOut"];

/** The kinds of record that name a contact, in the order the page lists them. */
export const USES_KINDS = [
  { kind: "places", heading: "Places it is a contact of" },
  { kind: "owners", heading: "Owners it is one of the people of" },
  { kind: "operators", heading: "Operators it stands behind" },
  { kind: "agreements", heading: "Agreements that name it" },
  { kind: "contracts", heading: "Contracts that name it" },
  { kind: "vendors", heading: "Vendors that name it" },
  { kind: "circuits", heading: "Circuits that name it" },
] as const;

export type UsesKind = (typeof USES_KINDS)[number]["kind"];

/** The page of a record that names a contact. Every kind of them has one. */
export function namedPath(record: Pick<NamedRecord, "record_type" | "hid">): string | null {
  return kindPath(record.record_type, record.hid);
}

/**
 * The role a contact has in a record, as people call it: of the list of contact roles
 * for a place and for a side of a circuit, the place in the people of an owner, and the
 * role named for an agreement, a contract, a carrier and a circuit's carrier. An operator
 * has none: the contact is the person behind it.
 */
export function namedRole(
  record: Pick<NamedRecord, "record_type" | "role" | "side">,
  choices?: readonly Choice[],
): string {
  const { role } = record;
  if (!role) return "";
  switch (record.record_type) {
    case "region":
    case "site":
    case "location":
      return choiceLabel(choices, CONTACT_ROLE_LIST, role);
    case "owner":
      return memberRoleLabel(role);
    case "circuit":
      return record.side
        ? `${choiceLabel(choices, CONTACT_ROLE_LIST, role)}, ${record.side.toUpperCase()} side`
        : sentence(carrierRoleOne(role)).replace(/\.$/, "");
    default:
      return sentence(carrierRoleOne(role)).replace(/\.$/, "");
  }
}

/** What a place is, beside its path: a region, a site or a location. Blank for the rest. */
export function namedLevel(record: Pick<NamedRecord, "record_type">): string {
  const { record_type: kind } = record;
  return kind === "region" || kind === "site" || kind === "location" ? levelLabel(kind) : "";
}

/**
 * What is said beneath a kind that names a contact more often than the page lists: how
 * many are shown of how many. Null where every one is shown.
 */
export function namedMore(named: Pick<NamedRecords, "total" | "records">): string | null {
  const shown = named.records.length;
  if (named.total <= shown) return null;
  return `The first ${shown.toLocaleString("en-US")} of ${named.total.toLocaleString("en-US")}, by name, are listed.`;
}

/** The mark of an operator that a contact stands behind, which the contact is the person of. */
export function namedMark(
  record: Pick<NamedRecord, "hid" | "label" | "colour" | "record_status">,
  contact: { name: string; record_status: string },
): Mark {
  return {
    hid: record.hid,
    label: record.label,
    colour: safeColour(record.colour),
    person: contact.name,
    // Nobody is behind a label whose person is retired.
    open: contact.record_status === "retired",
    released: record.record_status === "retired",
  };
}
