// 0.9.17: a contact may have the name of another, and is saved with a warning (P-315).
//
// The server counts, in `same_name`, how many other contacts that are not retired have
// a contact's name, compared as a file matches a contact by its name. Nothing is
// refused for it: the page says so, and that a file then tells them apart by the email
// or the HID, with a link to the contacts of that name.

import { parseShort } from "./filter";
import { contactsAddress } from "./onboarding";

/** Whose name it is: a contact's, on its page, or the person's own, on the Profile. */
export type Whose = "contact" | "own";

/**
 * The filter of the list of contacts that have a name, as the box of the list shows it:
 * the short form, `name:eq:Kim Lee`, or, for a name the short form cannot hold whole,
 * the filter as a tree.
 */
export function nameFilter(name: string): string {
  const short = `name:eq:${name}`;
  const read = parseShort(short);
  const condition = read.ok ? read.filter : null;
  if (
    condition !== null &&
    "field" in condition &&
    condition.field === "name" &&
    condition.value === name.trim()
  ) {
    return short;
  }
  return JSON.stringify({ field: "name", op: "eq", value: name });
}

/** The address of the list of the contacts that have a name, those not retired. */
export function namedAddress(name: string): string {
  return contactsAddress(nameFilter(name));
}

/**
 * What is said of a name that other contacts have, or null where none has it:
 * "Another contact is named Kim Lee: a file tells them apart by the email or the HID.",
 * and on the Profile "… a file tells you apart by your email or your HID."
 */
export function sameNameWords(name: string, others: number, whose: Whose): string | null {
  if (others <= 0) return null;
  const who = others === 1 ? "Another contact is" : `${others} other contacts are`;
  const apart =
    whose === "own"
      ? "a file tells you apart by your email or your HID"
      : "a file tells them apart by the email or the HID";
  return `${who} named ${name}: ${apart}.`;
}
