// What a record has from the record above it. A location and a planned location flow
// down each hierarchy: a minor item with none of its own has that of the item it is in,
// a member that of its group, a group that of the group it is nested in. The server
// resolves it when the record is read and says where it came from. Nothing is worked out
// here: this only turns that answer into words and into links.

import type { Schemas } from "../api/client";
import { itemsPath } from "./filter";
import { operatorSource } from "./operators";

/** A location in force, or a planned one: the value is its HID, the label its path. */
export type PlaceInForce = Schemas["EffectiveLocation"];

/** Which of the two: where a record is, or where it is going. */
export type PlaceKind = "location" | "planned";

/** The record a value came from, in words and as the address of its page. */
export interface SourceRecord {
  text: string;
  path: string;
}

/** A value in force with where it came from: a location, a plan, an owner. */
interface Sourced {
  value: unknown;
  source: string;
  source_hid: string | null;
}

/** A record that a value may have come from, as the page knows it: by its name. */
export interface Named {
  hid: string;
  name: string | null;
}

/** True for a value that the record has from the record above it. */
export function isFromAbove(effective: Sourced | null | undefined): boolean {
  return (
    Boolean(effective) &&
    effective?.value !== null &&
    effective?.source !== "own" &&
    effective?.source !== "none"
  );
}

/**
 * The item or the group a location in force came from, by the name the server sends
 * with it. Null for a location of the record's own, and for none.
 */
export function placeSource(effective: PlaceInForce | null | undefined): SourceRecord | null {
  if (!effective || !isFromAbove(effective)) return null;
  return operatorSource(effective);
}

/**
 * What more there is to say of a location in force than its name: its whole path, and
 * the item or the group it came from when it is not the record's own. Blank for none.
 */
export function locationHint(effective: PlaceInForce | null | undefined): string {
  if (!effective || effective.value === null) return "";
  const from = placeSource(effective);
  const inherited = isFromAbove(effective) ? `Inherited${from ? ` from ${from.text}` : ""}` : "";
  return [effective.label ?? "", inherited].filter(Boolean).join(" · ");
}

/**
 * The item or the group an owner in force came from. The server sends no name with an
 * owner: the record is named from what the page knows, the item it is in and the groups
 * it is a member of, and is linked by its HID all the same when it is none of those.
 * Null for an owner of the record's own, and for none.
 */
export function ownerSource(
  effective: Sourced | null | undefined,
  known: readonly Named[],
): SourceRecord | null {
  if (!effective || !isFromAbove(effective) || !effective.source_hid) return null;
  const hid = effective.source_hid;
  const name = known.find((one) => one.hid === hid)?.name;
  if (effective.source === "parent_item") {
    return {
      text: name ? `the item ${name}` : "the item it is in",
      path: `/items/${encodeURIComponent(hid)}`,
    };
  }
  if (effective.source === "device_group") {
    return {
      text: name ? `the group ${name}` : "the group it is in",
      path: `/groups/${encodeURIComponent(hid)}`,
    };
  }
  return null;
}

/** The records above an item that the item itself names: its parent, and its groups. */
export function knownAbove(item: {
  parent: Named | null;
  groups: ReadonlyArray<{ group_hid: string; name: string }>;
}): Named[] {
  return [
    ...(item.parent ? [{ hid: item.parent.hid, name: item.parent.name }] : []),
    ...item.groups.map((member) => ({ hid: member.group_hid, name: member.name })),
  ];
}

/** What the hint of a cell says of a value from above: blank for none. */
export function inheritedHint(from: SourceRecord | null): string {
  return from ? `Inherited from ${from.text}` : "";
}

/** What stands above an item, in words: blank for an item with nothing above it. */
export function aboveItem(item: {
  parent_item_hid: string | null;
  groups: readonly unknown[];
}): string {
  if (item.parent_item_hid) return "the item it is in";
  return item.groups.length > 0 ? "its group" : "";
}

/** What stands above a device group, in words: blank for one that is nested in none. */
export function aboveGroup(group: { parent_group_hid: string | null }): string {
  return group.parent_group_hid ? "the group it is in" : "";
}

const NOUN: Readonly<Record<PlaceKind, string>> = {
  location: "location",
  planned: "planned location",
};

/**
 * What a form says beneath the location, the planned location or the owner of a record
 * that has something above it. With a value of its own: that it is an override, and how to have
 * the one from above again. With none, and none from above: that there is none. Where
 * the record has one from above the form shows it above the field, and nothing is added
 * here. Blank where nothing is to be said.
 */
export function descentHint(
  kind: PlaceKind | "owner",
  what: "item" | "group",
  own: string | null | undefined,
  effective: Sourced | null | undefined,
  above: string,
): string {
  if (above === "") return "";
  if (own) {
    const set = `Set here, as the ${what}'s own: an override.`;
    if (kind === "owner") {
      return `${set} Choose the blank and save, and the ${what} has the owner of ${above} again.`;
    }
    return kind === "location"
      ? `${set} Clear it and save, and the ${what} is where ${above} is again.`
      : `${set} Clear it and save, and the ${what} has the plan of ${above} again.`;
  }
  if (isFromAbove(effective)) return "";
  return `None of its own, and none from ${above}.`;
}

/** The words for what a note or a line is about: "location", "planned location". */
export function placeNoun(kind: PlaceKind): string {
  return NOUN[kind];
}

const OWN_FIELD: Readonly<Record<PlaceKind, string>> = {
  location: "location_hid",
  planned: "planned_location_hid",
};

/**
 * The filter that keeps the current members of a group that have a location, or a plan,
 * of their own: an override of what the group has.
 */
export function membersWithOwn(groupHid: string, kind: PlaceKind): string {
  return `group.hid:eq:${groupHid} ${OWN_FIELD[kind]}:empty:false`;
}

/** The grid of those members. */
export function membersWithOwnPath(groupHid: string, kind: PlaceKind): string {
  return itemsPath(membersWithOwn(groupHid, kind));
}

/**
 * How many members of a group have a location, or a plan, of their own, as a sentence
 * with the number first. The number is what is linked: `before`, `linked`, `after`.
 */
export function membersWithOwnText(
  count: number,
  kind: PlaceKind,
): { linked: string; after: string } {
  if (count === 0) {
    return {
      linked: "",
      after:
        kind === "location"
          ? "none of its members has a location of its own"
          : "none of its members has a plan of its own",
    };
  }
  const thing = kind === "location" ? "a location" : "a plan";
  return {
    linked: `${count} of its members`,
    after:
      count === 1
        ? `has ${thing} of its own, as an override`
        : `have ${thing} of their own, as an override`,
  };
}
