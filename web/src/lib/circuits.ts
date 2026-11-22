// Circuits (P-145 to P-154): telecommunication circuits beside the inventory. A circuit
// shares what the inventory holds: its two sides are locations, its carriers vendors,
// its contacts contact records, its owner an owner, and its devices items and device
// groups. The server works out everything that is in force when a circuit is read: the
// speed written short, the rates in force, the site its cost counts at, what it costs,
// and the contacts it has from its carrier and from the locations of its sides. Nothing
// is worked out here; this only lays it out and turns it into words.

import type { Schemas } from "../api/client";
import type { FilterNode } from "./filter";
import type { Option } from "./patch";
import { placePath } from "./places";
import { amountText } from "./summary";

export type Circuit = Schemas["CircuitOut"];
export type CircuitSide = Schemas["CircuitSide"];
export type CircuitGroup = Schemas["CircuitGroupOut"];
export type Connection = Schemas["CircuitConnection"];
export type CarrierContacts = Schemas["CarrierContacts"];
export type SiteRoleContacts = Schemas["SiteRoleContacts"];
export type NamedContact = Schemas["NamedContact"];
export type Side = "a" | "z";

/** The editable lists of circuits (P-146, P-148). */
export const CIRCUIT_TYPE_LIST = "circuit_type";
export const CARRIER_ROLE_LIST = "carrier_role";
/** The list the site contacts of a side are named in, as those of a place are. */
export const CONTACT_ROLE_LIST = "contact_role";

export const SIDES: ReadonlyArray<Option & { value: Side }> = [
  { value: "a", label: "A side" },
  { value: "z", label: "Z side" },
];

/** A side as people read it: "A side", "Z side". */
export function sideLabel(side: Side): string {
  return side === "a" ? "A side" : "Z side";
}

export function otherSide(side: Side): Side {
  return side === "a" ? "z" : "a";
}

/** The page of a circuit, of a circuit group, as a path of the app. */
export function circuitPath(hid: string): string {
  return `/circuits/${encodeURIComponent(hid)}`;
}

export function circuitGroupPath(hid: string): string {
  return `/circuit-groups/${encodeURIComponent(hid)}`;
}

export function vendorPath(hid: string): string {
  return `/vendors/${encodeURIComponent(hid)}`;
}

export function ownerPath(hid: string): string {
  return `/owners/${encodeURIComponent(hid)}`;
}

/** The page of the device a circuit connects: an item's, or a device group's. */
export function devicePath(device: { item_hid: string | null; group_hid: string | null }): string {
  return device.item_hid
    ? `/items/${encodeURIComponent(device.item_hid)}`
    : `/groups/${encodeURIComponent(device.group_hid ?? "")}`;
}

/** The circuits with a side at a place, or at or beneath it: a location, a site, a region. */
export function circuitsWithin(placeHid: string): FilterNode {
  return { field: "location", op: "within", value: placeHid };
}

/** The circuits a vendor is a carrier of, as the primary one or another. */
export function circuitsOfCarrier(vendorHid: string): FilterNode {
  return { field: "carriers.vendor_hid", op: "eq", value: vendorHid };
}

/** The circuits of a group. */
export function circuitsInGroup(groupHid: string): FilterNode {
  return { field: "groups.hid", op: "eq", value: groupHid };
}

/** The circuits found by what was typed: a part of the name or of the enterprise ID. */
export function circuitSearch(typed: string): FilterNode | null {
  const value = typed.trim().slice(0, 200);
  if (value === "") return null;
  return {
    or: [
      { field: "name", op: "contains", value },
      { field: "enterprise_circuit_id", op: "contains", value },
      { field: "carriers.circuit_number", op: "contains", value },
    ],
  };
}

/** A circuit as a search offers it, or a list names it: its name, and its enterprise ID. */
export function circuitLabel(circuit: {
  name: string;
  enterprise_circuit_id: string | null;
}): string {
  return circuit.enterprise_circuit_id
    ? `${circuit.name} (${circuit.enterprise_circuit_id})`
    : circuit.name;
}

/**
 * The fields a page of the circuit grid asks for: every field of a circuit but its cost
 * lines, its devices and the contacts, which the grid does not show. Its groups and its
 * other carriers are left out of a list unless they are asked for.
 */
export const GRID_FIELDS: readonly string[] = [
  "name",
  "enterprise_circuit_id",
  "description",
  "notes",
  "circuit_type",
  "port_mbps",
  "down_mbps",
  "up_mbps",
  "speed",
  "a_location_hid",
  "a_note",
  "a_side",
  "z_location_hid",
  "z_note",
  "z_side",
  "cost_side",
  "cost_site_hid",
  "cost_site_path",
  "carrier_hid",
  "carrier",
  "carrier_circuit_number",
  "carriers",
  "billing_account",
  "billing_contract",
  "a_installed_on",
  "a_activated_on",
  "a_disconnected_on",
  "production",
  "support_weight",
  "owner_hid",
  "owner",
  "owner_exception",
  "owner_exception_reason",
  "monthly_cost",
  "annual_cost",
  "in_service",
  "groups",
  "effective.support_weight",
  "effective.down_mbps",
  "effective.up_mbps",
  "tags",
  "record_status",
  "created_at",
  "updated_at",
];

/**
 * The switches a link to the circuit grid asks for: `archived=1` and `drafts=1`, as a
 * link to the item grid has them, or `include_archived` and `include_drafts`, as the
 * list itself names them, `true` or `1`. A row of the report of what circuits cost asks
 * for retired circuits so: one that was disconnected ran for part of the year.
 */
export function switchesOf(params: URLSearchParams): { archived: boolean; drafts: boolean } {
  const on = (...names: string[]) =>
    names.some((name) => ["1", "true"].includes((params.get(name) ?? "").trim().toLowerCase()));
  return {
    archived: on("archived", "include_archived"),
    drafts: on("drafts", "include_drafts"),
  };
}

// --- the two sides ---------------------------------------------------------------------

/** What a side of a circuit is at, as the circuit has it. */
export interface SideOf {
  side: Side;
  /** Its location, with the location's path, site and region; null where it has none. */
  at: CircuitSide | null;
  note: string | null;
}

export function sideOf(
  circuit: Pick<Circuit, "a_side" | "a_note" | "z_side" | "z_note">,
  side: Side,
): SideOf {
  return side === "a"
    ? { side, at: circuit.a_side, note: circuit.a_note }
    : { side, at: circuit.z_side, note: circuit.z_note };
}

/** A side in a cell of the grid: the name of its location, or its note where it has none. */
export function sideCell(at: CircuitSide | null, note: string | null): string {
  return at ? at.name : (note ?? "");
}

/** A side on hover: the path of its location and its note, or that it has no location. */
export function sideHint(at: CircuitSide | null, note: string | null): string {
  if (at) return note ? `${at.path} · ${note}` : at.path;
  return note ? `No location: ${note}` : "";
}

/**
 * The side whose site the cost and the support weight of a circuit count at: the one
 * `cost_side` names, or the other where that one has no location (P-150).
 */
export function countingSide(circuit: Pick<Circuit, "cost_side" | "a_side" | "z_side">): Side {
  const named = circuit.cost_side;
  const at = named === "a" ? circuit.a_side : circuit.z_side;
  return at === null ? otherSide(named) : named;
}

/** What the place of a site contact's source is, as a page links to it. */
export function contactSourcePath(entry: Pick<SiteRoleContacts, "source" | "source_hid">): string {
  return entry.source === "own" ? "" : placePath(entry.source, entry.source_hid);
}

/**
 * Where the site contacts of one role of a side came from, in words: the circuit names
 * them itself, or the location of the side resolves them from itself, a location above
 * it, its site or its region, as the contacts of a place resolve (P-149).
 */
export function siteSourceText(
  entry: Pick<SiteRoleContacts, "source" | "source_hid">,
  at: CircuitSide | null,
): string {
  switch (entry.source) {
    case "own":
      return "Named here";
    case "location":
      return at && entry.source_hid === at.location_hid
        ? `From its location, ${at.path}`
        : "From a location it is in";
    case "site":
      return at && entry.source_hid === at.site_hid
        ? `From its site, ${at.site_path}`
        : "From its site";
    case "region":
      return at && entry.source_hid === at.region_hid
        ? "From the region of its site"
        : "From a region above its site";
    default:
      return entry.source;
  }
}

// --- the carrier's contacts -----------------------------------------------------------

export type CarrierRole = "account_manager" | "support_contact";

/** The two roles of a carrier's contacts, in the order they are shown (P-149). */
export const CARRIER_CONTACT_ROLES: ReadonlyArray<{
  value: CarrierRole;
  label: string;
  one: string;
}> = [
  { value: "account_manager", label: "Account team", one: "account manager" },
  { value: "support_contact", label: "Support desk", one: "support contact" },
];

export function carrierRoleOne(role: string): string {
  return CARRIER_CONTACT_ROLES.find((one) => one.value === role)?.one ?? role;
}

/** Where the carrier's contacts of a role came from, in a few words. */
export function carrierSourceText(list: CarrierContacts, carrier: string | null): string {
  const count = list.value.length;
  if (list.source === "none" || count === 0) {
    return carrier ? `nobody is named, here or on ${carrier}` : "nobody is named";
  }
  const who = count === 1 ? "1 contact" : `${count} contacts`;
  if (list.source === "vendor") return `${who} from the carrier, ${carrier ?? "its carrier"}`;
  return `${who} named here, in place of the carrier's`;
}

// --- figures ----------------------------------------------------------------------------

/** Money as the server sends it, with two places and its thousands marked. */
export function moneyText(amount: string | null | undefined): string {
  return amountText(amount);
}

/** A speed in Mbps as the server sends it, without the places that say nothing: `1,000`. */
export function mbpsText(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
  return amountText(trimmed);
}

/** A rate in force as words: its own, or the full rate of the port. */
export function rateText(rate: Schemas["EffectiveValue"]): string {
  const value = typeof rate.value === "string" ? rate.value : null;
  if (value === null) return "";
  const mbps = `${mbpsText(value)} Mbps`;
  return rate.source === "port" ? `${mbps}, the full rate of the port` : mbps;
}

type Weight = Schemas["EffectiveWeight"];

/** Where a support weight in force came from, and what it was raised from (P-155). */
export function weightHint(weight: Weight): string {
  const from =
    weight.source === "own"
      ? "Its own"
      : weight.source === "setting"
        ? "The default of circuits, default_circuit_weight"
        : weight.source === "none"
          ? ""
          : `From ${weight.source}`;
  const raised =
    weight.raised_from !== null && weight.raised_from !== undefined
      ? `raised from ${weight.raised_from} to the minimum of circuits, minimum_circuit_weight`
      : "";
  return [from, raised].filter(Boolean).join(", ");
}

// --- the devices of a circuit -----------------------------------------------------------

/** A device chosen to be connected, not yet sent. */
export interface PendingDevice {
  kind: "item" | "group";
  hid: string;
  name: string;
  side: Side;
}

/** The body that connects the devices chosen, all together, each on its side. */
export function devicesBody(pending: readonly PendingDevice[]): Schemas["CircuitDevicesAdd"] {
  return {
    devices: pending.map((device) =>
      device.kind === "item"
        ? { item_hid: device.hid, side: device.side }
        : { group_hid: device.hid, side: device.side },
    ),
  };
}

/** The HIDs of the items and device groups a circuit is connected to already. */
export function connectedHids(devices: readonly Schemas["CircuitDeviceOut"][]): string[] {
  return devices.map((device) => device.item_hid ?? device.group_hid ?? "").filter(Boolean);
}

// --- cost lines -------------------------------------------------------------------------

/**
 * A monthly cost as typed: a number with at most two places, below zero for a credit.
 * Blank is no amount; anything else is refused before it is sent.
 */
export function readMoney(typed: string): { value: string | null } | { error: string } {
  const text = typed.trim();
  if (text === "") return { value: null };
  if (!/^-?\d{1,13}(\.\d{1,2})?$/.test(text)) {
    return {
      error: "An amount, with at most two digits after the point; below zero for a credit.",
    };
  }
  return { value: text };
}

/**
 * Why a circuit costs nothing today, though its lines have their amounts: it is not in
 * service. One activated later than today is not yet in service; one disconnected, or
 * retired with no day it was disconnected, no longer is. A draft, an ordered circuit, is
 * read as a view of drafts reads it: in service, at what it will cost. Blank for a
 * circuit in service. `day` is today, as the application's time zone has it.
 */
export function notInServiceText(
  circuit: Pick<Circuit, "in_service" | "record_status" | "a_activated_on" | "a_disconnected_on">,
  day: string,
): string {
  if (circuit.in_service) return "";
  const then =
    "Its lines keep their amounts, and its monthly and annual cost are 0.00 while it is not in service.";
  if (circuit.a_activated_on && circuit.a_activated_on > day) {
    return `It is not in service until it is activated on ${circuit.a_activated_on}. ${then}`;
  }
  if (circuit.a_disconnected_on && circuit.a_disconnected_on < day) {
    return `It was disconnected on ${circuit.a_disconnected_on}. ${then}`;
  }
  if (circuit.record_status === "retired") {
    return `It was retired with no day it was disconnected: taken out, it is in service on no day. ${then}`;
  }
  return `It is not in service today. ${then}`;
}

/** The carrier a cost line names, in words: blank is the circuit's primary carrier. */
export function lineCarrier(
  line: Pick<Schemas["CircuitCostOut"], "vendor" | "vendor_hid">,
  primary: string | null,
): string {
  if (line.vendor_hid) return line.vendor ?? line.vendor_hid;
  return primary ? `${primary} (the primary carrier)` : "The primary carrier";
}

// --- in a list of circuits --------------------------------------------------------------

/** A circuit a list shows greyed: a draft, or one retired. */
export function circuitIsDimmed(circuit: { record_status: string }): boolean {
  return circuit.record_status !== "active";
}

/**
 * The sides of a circuit that are at a place or within it, by the path of that place:
 * a side whose location is the place, or whose path runs through it.
 */
export function sidesWithin(
  circuit: Pick<Circuit, "a_side" | "z_side">,
  placePathText: string,
): Side[] {
  const within = (at: CircuitSide | null) =>
    at !== null && (at.path === placePathText || at.path.startsWith(`${placePathText} > `));
  return (["a", "z"] as const).filter((side) =>
    within(side === "a" ? circuit.a_side : circuit.z_side),
  );
}
