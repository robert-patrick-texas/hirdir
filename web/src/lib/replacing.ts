// 0.9.8: the form of Replace (P-242, P-243). What the item that comes is known by, as the
// box of a member that joins a stack reads it; the server holds every rule.

import { type Joining, knownByHostAlone } from "./stacks";

/** A value of the form, as text with its spaces taken off; blank where it is none. */
function typed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * What a new item made in the form of Replace is known by: its name, asset tag, serial
 * number with its catalog entry, and host name, as typed. The box of a stack reads it to
 * say what the stack takes, and whether the item would be known by its host name alone.
 */
export function newItemJoining(values: Readonly<Record<string, unknown>>): Joining {
  const joining: Joining = {};
  for (const field of ["name", "asset_tag", "serial_number", "catalog_entry_hid", "hostname"]) {
    const value = typed(values[field]);
    if (value) (joining as Record<string, string>)[field] = value;
  }
  return joining;
}

/**
 * Whether Replace waits: in a stack, where the item that comes takes the stack's name and
 * place and is known by its host name alone, which the stack would take, the server
 * refuses it. The box says so beneath it, and the button waits until the box is unticked
 * or the item is given something else to be known by.
 */
export function replaceWaits(
  inStack: boolean,
  coming: { drop?: boolean; joining?: Joining } | null,
): boolean {
  return inStack && coming?.drop === true && knownByHostAlone(coming.joining ?? {});
}
