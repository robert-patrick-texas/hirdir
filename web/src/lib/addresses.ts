// Addresses and the networks they are under, as words. An address is a fact about an
// item or a device group; the server keeps it in canonical form and decides everything
// about it. This only says what is there.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

/** An address as an item or a group lists it. */
export type AddressRef = Schemas["AddressRef"];
export type Address = Schemas["AddressOut"];
export type AddressRole = Address["role"];
export type NetworkKind = Schemas["NetworkOut"]["kind"];

export const ADDRESS_ROLES: ReadonlyArray<Option & { value: AddressRole }> = [
  { value: "management", label: "Management" },
  { value: "loopback", label: "Loopback" },
  { value: "secondary", label: "Secondary" },
  { value: "virtual", label: "Virtual" },
];

export const NETWORK_KINDS: ReadonlyArray<Option & { value: NetworkKind }> = [
  { value: "network", label: "Network" },
  { value: "vrf", label: "VRF" },
  { value: "other", label: "Other" },
];

export function isAddressRole(value: string): value is AddressRole {
  return ADDRESS_ROLES.some((role) => role.value === value);
}

/** The name of a role for people. One this build does not know is shown as sent. */
export function addressRoleLabel(role: string): string {
  return ADDRESS_ROLES.find((known) => known.value === role)?.label ?? role;
}

/** Only a management address may be a primary one. */
export function mayBePrimary(role: string): boolean {
  return role === "management";
}

/** The two families of address. A record may have a primary management address of each. */
export type Family = AddressRef["family"];
export const FAMILIES: readonly Family[] = [4, 6];

/** A family for people: IPv4, IPv6. */
export function familyLabel(family: number): string {
  return `IPv${family}`;
}

/**
 * The family of an address as it is being typed, before the server has read it: one
 * with a colon in it is IPv6. The server decides; this only says which primary a new
 * address would be.
 */
export function typedFamily(address: string): Family {
  return address.includes(":") ? 6 : 4;
}

/** The primary management address of one family of a record, if it has one. */
export function primaryAddress<T extends { is_primary: boolean; family: number }>(
  addresses: readonly T[] | null | undefined,
  family: Family,
): T | null {
  return (
    (addresses ?? []).find((address) => address.is_primary && address.family === family) ?? null
  );
}

/** The primary management addresses of a record: the IPv4 one, then the IPv6 one. */
export function primaryAddresses<T extends { is_primary: boolean; family: number }>(
  addresses: readonly T[] | null | undefined,
): T[] {
  const primaries: T[] = [];
  for (const family of FAMILIES) {
    const primary = primaryAddress(addresses, family);
    if (primary) primaries.push(primary);
  }
  return primaries;
}

/**
 * The management addresses of a record as one line, for a cell of a grid: the primary of
 * each family, IPv4 first. Blank when it has neither.
 */
export function managementText(
  addresses: ReadonlyArray<{ address: string; is_primary: boolean; family: number }> | null,
): string {
  return primaryAddresses(addresses)
    .map((primary) => primary.address)
    .join(", ");
}

/** What the Primary cell of an address says: which family it is the primary of, or nothing. */
export function primaryText(address: { is_primary: boolean; family: number }): string {
  return address.is_primary ? `Primary ${familyLabel(address.family)}` : "";
}

/** An address with the network it is under: `192.0.2.10 (Red)`. */
export function addressText(address: { address: string; network: string | null }): string {
  return address.network ? `${address.address} (${address.network})` : address.address;
}

/** Every address of a record, as one line of text, in the order the server lists them. */
export function addressList(addresses: readonly AddressRef[] | null | undefined): string {
  return (addresses ?? []).map(addressText).join(", ");
}

/** The networks a record's addresses are under, each once, in the order first met. */
export function networkLabels(addresses: readonly AddressRef[] | null | undefined): string[] {
  const labels: string[] = [];
  for (const address of addresses ?? []) {
    if (address.network && !labels.includes(address.network)) labels.push(address.network);
  }
  return labels;
}

/** What to call the address space an address is in: its network, or that it has none. */
export function networkText(label: string | null | undefined): string {
  return label || "No network";
}

/** One holder of an address, as the duplicates report names it. */
export type Holder = Schemas["AddressHolder"];

/** The page of an item or a group that holds an address, as a path of the app. */
export function holderPath(holder: {
  item_hid: string | null;
  group_hid: string | null;
}): string | null {
  if (holder.item_hid) return `/items/${encodeURIComponent(holder.item_hid)}`;
  if (holder.group_hid) return `/groups/${encodeURIComponent(holder.group_hid)}`;
  return null;
}

/** Whether a holder is an item or a device group, for people. */
export function holderKind(holder: { item_hid: string | null; group_hid: string | null }): string {
  if (holder.item_hid) return "Item";
  return holder.group_hid ? "Group" : "";
}

/**
 * The body of a new address, from what a form holds. A blank network is the unlabelled
 * address space, and is not sent. The address goes as it was typed: the server reads
 * every common notation and stores the canonical form.
 */
export function newAddress(
  holder: { item_hid: string } | { group_hid: string },
  form: { address: string; network_hid: string; role: string; is_primary: boolean },
): Schemas["AddressCreate"] {
  const role = isAddressRole(form.role) ? form.role : "management";
  return {
    ...holder,
    address: form.address.trim(),
    role,
    ...(form.network_hid ? { network_hid: form.network_hid } : {}),
    // Only a management address may be primary: the mark is not sent with another role.
    // The server files it under its own family, and takes the mark off the one of that
    // family that had it.
    ...(form.is_primary && mayBePrimary(role) ? { is_primary: true } : {}),
  };
}
