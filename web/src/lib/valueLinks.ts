// 0.9.7: every value of a list that names another record is a link to its page (P-232).
//
// What the lists of several pages name alike, as links: the page of a record by its
// kind, the contracts of an item and the systems that know a record, each once.

import { kindPath } from "./preview";
import { REMOVED } from "./systems";

/** A value that names a record, and the page of that record. */
export interface ValueLink {
  text: string;
  /** The page of the record, as a path of the app; null where it has none. */
  path: string | null | undefined;
}

/** The page of a record by the kind the audit trail names it by, or null. */
export const page = (kind: string, hid: string | null | undefined): string | null =>
  kindPath(kind, hid);

/** One value that names a record, or none where there is no text. */
export function oneLink(
  text: string | null | undefined,
  path: string | null | undefined,
): ValueLink[] {
  return text ? [{ text, path }] : [];
}

/** The contracts a cell names, each once, as their numbers are listed. */
export function contractLinks(contracts: readonly { hid: string; number: string }[]): ValueLink[] {
  const links: ValueLink[] = [];
  for (const contract of contracts) {
    if (!links.some((one) => one.text === contract.number)) {
      links.push({ text: contract.number, path: page("contract", contract.hid) });
    }
  }
  return links;
}

/** The systems that know a record, each once, as `registeredWith` names them. */
export function systemLinks(
  registrations: readonly { status: string; system: { hid: string; name: string } }[],
): ValueLink[] {
  const links: ValueLink[] = [];
  for (const one of registrations) {
    if (one.status !== REMOVED && !links.some((link) => link.text === one.system.name)) {
      links.push({ text: one.system.name, path: page("external_system", one.system.hid) });
    }
  }
  return links;
}
