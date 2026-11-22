// Circuits (P-145 to P-154): telecommunication circuits beside the inventory. A circuit
// shares what the inventory holds: its two sides are locations, its carriers vendors,
// its contacts contact records, its owner an owner, and its devices items and device
// groups. The server works out everything that is in force when a circuit is read: the
// speed written short, the rates in force, the site its cost counts at, what it costs,
// and the contacts it has from its carrier and from the locations of its sides. Nothing
// is worked out here; this only lays it out and turns it into words.

import type { Schemas } from "../api/client";
import type { FilterNode } from "./filter";
import type { FormValue, FormValues, Option } from "./patch";
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

/**
 * The circuits of a group. 0.9.18: of a network, those put into it and those whose Z side
 * names it, each once (P-320 (7)).
 */
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
  "z_group_hid",
  "z_group",
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
  "z_installed_on",
  "z_activated_on",
  "z_disconnected_on",
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
  "effective.z_installed_on",
  "effective.z_activated_on",
  "effective.z_disconnected_on",
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

/** 0.9.18: the network a Z side reaches, as the circuit names it (P-320 (6)). */
export type Network = NonNullable<Circuit["z_group"]>;

/** What a side of a circuit is at, as the circuit has it. */
export interface SideOf {
  side: Side;
  /** Its location, with the location's path, site and region; null where it has none. */
  at: CircuitSide | null;
  /** 0.9.18: the network the Z side reaches, where it names one; the A side names none. */
  network: Network | null;
  note: string | null;
}

export function sideOf(
  circuit: Pick<Circuit, "a_side" | "a_note" | "z_side" | "z_note" | "z_group">,
  side: Side,
): SideOf {
  return side === "a"
    ? { side, at: circuit.a_side, network: null, note: circuit.a_note }
    : { side, at: circuit.z_side, network: circuit.z_group ?? null, note: circuit.z_note };
}

/**
 * A side in a cell of the grid: the name of its location, or of the network it reaches,
 * or its note where it has neither.
 */
export function sideCell(
  at: CircuitSide | null,
  note: string | null,
  network: Network | null = null,
): string {
  if (at) return at.name;
  return network ? network.name : (note ?? "");
}

/**
 * A side on hover: the path of its location and its note, or the network it reaches, or
 * that it has no location.
 */
export function sideHint(
  at: CircuitSide | null,
  note: string | null,
  network: Network | null = null,
): string {
  if (at) return note ? `${at.path} · ${note}` : at.path;
  if (network)
    return note
      ? `The carrier network ${network.name} · ${note}`
      : `The carrier network ${network.name}`;
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

// --- the dates of each side (P-317, P-320) ----------------------------------------------

/** A date of a side, by its name after the letter of the side: `a_activated_on`. */
export type SideDate = "installed_on" | "activated_on" | "disconnected_on";

/** The three dates of a side, in order, as a page and a form name them. */
export const SIDE_DATES: ReadonlyArray<{ name: SideDate; label: string; hint?: string }> = [
  { name: "installed_on", label: "Installed on" },
  { name: "activated_on", label: "Activated on", hint: "The carrier bills it from this day." },
  { name: "disconnected_on", label: "Disconnected on", hint: "The last day it was in service." },
];

/** What a circuit holds of the dates of its sides, its own and those in force. */
export type CircuitDates = Pick<
  Circuit,
  | "a_installed_on"
  | "a_activated_on"
  | "a_disconnected_on"
  | "z_installed_on"
  | "z_activated_on"
  | "z_disconnected_on"
> & {
  effective: Pick<Circuit["effective"], "z_installed_on" | "z_activated_on" | "z_disconnected_on">;
};

/** A date of a side in force, with where it came from: `own`, `a_side` or `none`. */
export interface DateInForce {
  value: string | null;
  source: string;
}

/**
 * A date of a side in force (P-320 (2)): the A side's is its own; the Z side's is its
 * own, or, where it is blank, the A side's, never copied, as the server answers it in
 * `effective`.
 */
export function dateInForce(circuit: CircuitDates, side: Side, name: SideDate): DateInForce {
  if (side === "a") {
    const value = circuit[`a_${name}`] ?? null;
    return { value, source: value === null ? "none" : "own" };
  }
  const held = circuit.effective[`z_${name}`];
  return { value: typeof held.value === "string" ? held.value : null, source: held.source };
}

/**
 * What a blank date of the Z side of a form is read as, said beneath it: the A side's
 * date, as the form holds it now (P-320 (2)).
 */
export function zDateHint(typedZ: string, typedA: string): string | undefined {
  if (typedZ.trim() !== "") return undefined;
  const a = typedA.trim();
  return a === ""
    ? "Blank: the A side's is read in its place, and it has none."
    : `Blank: the A side's, ${a}, is read in its place.`;
}

/**
 * Why a circuit costs nothing today, though its lines have their amounts: it is not in
 * service. One activated later than today is not yet in service; one disconnected, or
 * retired with no day it was disconnected, no longer is. A draft, an ordered circuit, is
 * read as a view of drafts reads it: in service, at what it will cost. Blank for a
 * circuit in service. `day` is today, as the application's time zone has it. 0.9.18: the
 * dates are those of the side `cost_side` names, the Z side's in force where it is `z`,
 * whether or not that side is a location (P-320 (4)).
 */
export function notInServiceText(
  circuit: CircuitDates & Pick<Circuit, "in_service" | "record_status" | "cost_side">,
  day: string,
): string {
  if (circuit.in_service) return "";
  const then =
    "Its lines keep their amounts, and its monthly and annual cost are 0.00 while it is not in service.";
  const side: Side = circuit.cost_side === "z" ? "z" : "a";
  const activated = dateInForce(circuit, side, "activated_on").value;
  const disconnected = dateInForce(circuit, side, "disconnected_on").value;
  const it = side === "z" ? "its Z side" : "it";
  const It = side === "z" ? "Its Z side" : "It";
  if (activated && activated > day) {
    return `It is not in service until ${it} is activated on ${activated}. ${then}`;
  }
  if (disconnected && disconnected < day) {
    return `${It} was disconnected on ${disconnected}. ${then}`;
  }
  if (circuit.record_status === "retired") {
    return `It was retired with no day ${it} was disconnected: taken out, it is in service on no day. ${then}`;
  }
  return `It is not in service today. ${then}`;
}

/**
 * What a retired circuit's page says of it (P-320 (4)): in service until the side its
 * cost counts at was disconnected, or, with no such day, on no day.
 */
export function retiredText(circuit: CircuitDates & Pick<Circuit, "cost_side">): string {
  const side: Side = circuit.cost_side === "z" ? "z" : "a";
  const disconnected = dateInForce(circuit, side, "disconnected_on").value;
  if (side === "a") {
    return disconnected
      ? `This circuit is retired. It was in service until ${disconnected}, and counts for that time in what circuits cost.`
      : "This circuit is retired, with no day it was disconnected: it was taken out, and is in service on no day.";
  }
  return disconnected
    ? `This circuit is retired. It was in service until ${disconnected}, when its Z side, whose dates decide, was disconnected, and counts for that time in what circuits cost.`
    : "This circuit is retired, with no day its Z side, whose dates decide, was disconnected: it was taken out, and is in service on no day.";
}

// --- the network a Z side reaches (P-319, P-320) ----------------------------------------

/** The two kinds of a circuit group, as a page offers them (P-320 (5)). */
export const GROUP_KINDS: ReadonlyArray<Option & { value: "network" | "collection" }> = [
  { value: "network", label: "Network" },
  { value: "collection", label: "Collection" },
];

/** The kind of a group in words: Network, Collection. */
export function groupKindLabel(kind: string): string {
  return GROUP_KINDS.find((one) => one.value === kind)?.label ?? kind;
}

/** The circuit groups of the kind Network: the only ones a Z side may name. */
export function networksOnly(): FilterNode {
  return { field: "kind", op: "eq", value: "network" };
}

/** Whether a circuit is in a group by its Z side, which names the group as its network. */
export function byZSide(circuit: Pick<Circuit, "z_group_hid">, groupHid: string): boolean {
  return circuit.z_group_hid === groupHid;
}

/**
 * What the take-out of circuits from a group says it did (review of 0.9.18): how many left
 * it, and which stay because their Z side names it, which nothing here changes.
 */
export function takenOutText(group: string, taken: number, stay: readonly string[]): string {
  const said =
    taken === 0
      ? `No circuit was taken out of ${group}.`
      : `${taken} ${taken === 1 ? "circuit" : "circuits"} ${taken === 1 ? "was" : "were"} taken out of ${group}.`;
  if (stay.length === 0) return said;
  const named = stay.length <= 3 ? stay.join(", ") : `${stay.length} circuits`;
  const verb = stay.length === 1 ? "stays" : "stay";
  const their = stay.length === 1 ? "its" : "their";
  return `${said} ${named} ${verb} in it by ${their} Z side: a circuit leaves a carrier network by a change of its Z side.`;
}

/** The networks a vendor is the carrier of. */
export function networksOfCarrier(vendorHid: string): FilterNode {
  return { and: [networksOnly(), { field: "carrier_hid", op: "eq", value: vendorHid }] };
}

/**
 * A carrier network as a form offers it for a Z side: by its name, a draft said to be one,
 * under the name of its carrier, so that a long name with its carrier is not cut short in
 * the box (review of 0.9.18).
 */
export function networkOption(group: {
  hid: string;
  name: string;
  record_status?: string;
  carrier?: { name: string } | null;
}): Option {
  return {
    value: group.hid,
    label: group.record_status === "draft" ? `${group.name} (draft)` : group.name,
    ...(group.carrier ? { group: group.carrier.name } : {}),
  };
}

/**
 * 0.9.18: the fills of a choice of a Z side that excludes another, its location or its
 * carrier network (P-320 (6)): choosing one lets go of the other, which is kept aside in
 * the form and comes back when the choice is undone, so that looking through a list
 * leaves the record as it was and sends nothing of it (review of 0.9.18, finding 1).
 */
export function letsGoOf(other: string): (value: FormValue, before: FormValues) => FormValues {
  const aside = `${other}:let-go`;
  return (value, before) => {
    const held = before[other];
    const kept = before[aside];
    if (value !== "") {
      return typeof held === "string" && held !== "" ? { [other]: "", [aside]: held } : {};
    }
    return typeof kept === "string" && kept !== "" ? { [other]: kept, [aside]: "" } : {};
  };
}

/**
 * Whether a circuit is in service on a day by the dates of one side (P-320 (4)): active or
 * a draft, on a day not before that side's activation and not after its disconnection, a
 * blank being open; retired, only until a disconnection that side has. The Z side's are
 * those in force.
 */
export function inServiceBy(
  circuit: CircuitDates & Pick<Circuit, "record_status">,
  side: Side,
  day: string,
): boolean {
  const activated = dateInForce(circuit, side, "activated_on").value;
  const disconnected = dateInForce(circuit, side, "disconnected_on").value;
  if (circuit.record_status === "retired" && disconnected === null) return false;
  return (activated === null || activated <= day) && (disconnected === null || disconnected >= day);
}

/** Whether the two sides differ in the dates that decide service: the activation, the disconnection. */
export function deciderDatesDiffer(circuit: CircuitDates): boolean {
  return (["activated_on", "disconnected_on"] as const).some(
    (name) => dateInForce(circuit, "a", name).value !== dateInForce(circuit, "z", name).value,
  );
}

/**
 * What switching `cost_side` does to whether the circuit is in service (P-320 (4)): blank
 * where both sides' dates are the same; otherwise that the other side's dates then decide,
 * and whether that changes today's answer.
 */
export function switchServiceText(
  circuit: CircuitDates & Pick<Circuit, "record_status" | "cost_side" | "in_service">,
  day: string,
): string {
  if (!deciderDatesDiffer(circuit)) return "";
  const other: Side = circuit.cost_side === "z" ? "a" : "z";
  const then = inServiceBy(circuit, other, day);
  const whose = `The ${sideLabel(other)}'s dates then decide whether it is in service, and the months its cost counts`;
  if (then === circuit.in_service) {
    return `${whose}: it is ${then ? "" : "not "}in service today either way.`;
  }
  return then
    ? `${whose}: it would be in service today, which it is not now.`
    : `${whose}: it would not be in service today, which it is now, and would cost nothing today.`;
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
