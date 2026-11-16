// 0.8.0: the support weight of a place, and a default and a minimum of each kind
// (P-139, P-141, P-155). Nothing is resolved here: the server answers the weight in force
// of a site, an item and a circuit with where it came from, and the weight it was raised
// from where a minimum raised it. This turns that into words.

import type { Schemas } from "../api/client";

export type EffectiveWeight = Schemas["EffectiveWeight"];

/** What a default and a minimum of support weight are of: a major item, a site, a circuit. */
export type WeightKind = "item" | "site" | "circuit";

/** What each kind is called, after "a". */
const NOUN: Readonly<Record<WeightKind, string>> = {
  item: "major item",
  site: "site",
  circuit: "circuit",
};

/** The setting that gives the default weight of a kind. */
export function defaultKey(kind: WeightKind): string {
  return `default_${kind}_weight`;
}

/** The setting that gives the least weight of a kind. */
export function minimumKey(kind: WeightKind): string {
  return `minimum_${kind}_weight`;
}

/** The six settings of a default and a minimum, in the order the pages list them. */
export const WEIGHT_SETTINGS = [
  "default_item_weight",
  "minimum_item_weight",
  "default_site_weight",
  "minimum_site_weight",
  "default_circuit_weight",
  "minimum_circuit_weight",
] as const;
export type WeightSetting = (typeof WEIGHT_SETTINGS)[number];

export function isWeightSetting(key: string): key is WeightSetting {
  return (WEIGHT_SETTINGS as readonly string[]).includes(key);
}

/** A weight setting as people read it: "Default weight of a site". */
export function weightSettingLabel(key: WeightSetting): string {
  const [which = "", kind = ""] = key.split("_");
  const noun = NOUN[kind as WeightKind] ?? kind;
  return `${which === "default" ? "Default" : "Minimum"} weight of a ${noun}`;
}

/** True for a weight in force that is not the record's own: the default, its model's. */
export function weightInherited(weight: EffectiveWeight | null | undefined): boolean {
  return Boolean(weight) && weight?.source !== "own" && weight?.source !== "none";
}

/**
 * Where a weight in force came from, in words: set here, its model's, the default of its
 * kind, which names the setting, or nothing at all.
 */
export function weightSource(weight: EffectiveWeight | null | undefined, kind: WeightKind): string {
  if (!weight || weight.source === "none") return "Not set";
  if (weight.source === "own") return "Set here";
  if (weight.source === "catalog") return "From the catalog entry";
  if (weight.source === "setting") return `The default of a ${NOUN[kind]}, ${defaultKey(kind)}`;
  return `From the ${weight.source}`;
}

/**
 * That a weight was raised to the minimum of its kind, with the weight it had before:
 * blank where it was not raised.
 */
export function raisedText(weight: EffectiveWeight | null | undefined, kind: WeightKind): string {
  const from = weight?.raised_from;
  if (from === null || from === undefined || from === "") return "";
  return `Raised to the minimum, ${minimumKey(kind)}, from ${from}`;
}

/**
 * What to say under the input of a site's own weight: what a blank counts at, or that
 * the weight is set here. `weight` is the site's weight in force, as the server read it,
 * and nothing for a site that is not made yet.
 */
export function siteWeightHint(
  own: string | null | undefined,
  weight: EffectiveWeight | null | undefined,
): string {
  const set = own !== null && own !== undefined && own !== "";
  const minimum = `A weight below ${minimumKey("site")} is raised to it.`;
  if (set || !weight) {
    return `${set ? "Set here. " : ""}Blank counts at ${defaultKey("site")} where an Admin has set one. ${minimum}`;
  }
  if (weight.source === "setting" && weight.value !== null) {
    const before = weight.raised_from ?? weight.value;
    return `Blank counts at ${defaultKey("site")}, ${before}. ${minimum}`;
  }
  return `Blank counts for nothing while ${defaultKey("site")} is blank. ${minimum}`;
}
