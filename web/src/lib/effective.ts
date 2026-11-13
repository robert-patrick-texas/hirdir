// Values in force. A field that inherits comes back from the server as the record's own
// value plus an `effective` block: the value in force and where it came from. Nothing is
// worked out here; this only turns that block into words.

import type { Schemas } from "../api/client";

export type Effective = Schemas["EffectiveValue"];
export type Source = Effective["source"];

const FROM: Readonly<Record<Source, string>> = {
  own: "",
  catalog: "the catalog entry",
  parent_item: "the parent item",
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

/** The value in force as text. Blank when there is none. */
export function effectiveText(effective: Effective | null | undefined): string {
  return effective?.value ?? "";
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
  return `Blank inherits ${inherited.value} from ${FROM[inherited.source] || inherited.source}.`;
}
