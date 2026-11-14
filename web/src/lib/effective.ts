// Values in force. A field that inherits comes back from the server as the record's own
// value plus an `effective` block: the value in force and where it came from. Nothing is
// worked out here; this only turns that block into words.

import type { Schemas } from "../api/client";

export type Effective = Schemas["EffectiveValue"];
export type Source = Effective["source"];
/** A record in force: the value is its HID, and `label` is what people call it. */
export type EffectiveRecord = Schemas["EffectiveReference"];

const FROM: Readonly<Record<Source, string>> = {
  own: "",
  catalog: "the catalog entry",
  parent_item: "the item it is in",
  device_group: "the group it is in",
  location: "the location",
  site: "the site",
  region: "the region",
  setting: "the global setting",
  none: "",
};

/** True for a value that came from somewhere else than the record itself. */
export function isInherited(effective: Effective | null | undefined): boolean {
  return Boolean(effective) && effective?.source !== "own" && effective?.source !== "none";
}

/**
 * The value in force as text. Blank when there is none. A decimal and a date are shown
 * as the server sent them, and a truth value, such as the intent, as Yes or No.
 */
export function effectiveText(effective: Effective | null | undefined): string {
  const value = effective?.value ?? null;
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value;
}

/**
 * A record in force as text: what people call it, and its HID only when the server sent
 * no name for it. Blank when there is none.
 */
export function effectiveLabel(effective: EffectiveRecord | null | undefined): string {
  if (!effective || effective.value === null) return "";
  return effective.label || String(effective.value);
}

/** Where a value in force came from, as a short label for a table. */
export function sourceLabel(effective: Effective | null | undefined): string {
  if (!effective || effective.source === "none") return "Not set";
  if (effective.source === "own") return "Set here";
  return `From ${FROM[effective.source] || effective.source}`;
}

/** Where a value in force came from, as a sentence for a tooltip. Blank for an own value. */
export function sourceHint(effective: Effective | null | undefined): string {
  if (!isInherited(effective) || !effective) return "";
  return `Inherited from ${FROM[effective.source] || effective.source}`;
}

/**
 * What to say under the input of a field that inherits: what a blank will show, or what
 * clearing the override will bring back.
 */
export function inheritHint(
  own: string | null | undefined,
  inherited: Effective | null | undefined,
): string {
  const overridden = own !== null && own !== undefined && own !== "";
  if (overridden) return "Set here. Clear it to inherit again.";
  if (!inherited || inherited.source === "none" || inherited.value === null) {
    return "Blank, and nothing to inherit.";
  }
  const from = FROM[inherited.source] || inherited.source;
  return `Blank inherits ${effectiveText(inherited)} from ${from}.`;
}
