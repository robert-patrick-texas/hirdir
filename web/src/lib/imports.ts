// Sending a file to be imported.
//
// The file itself is the body of the request, as CSV or as JSON, and what else there is
// to say about it (which records it holds, the mode, its name) goes beside it in the
// URL. The server reads it and judges it; this only says what is being sent.

import type { FileType } from "../api/client";
import type { Option } from "./patch";
import { DEFAULT_NAME, fileStem } from "./product";
import type { Entity } from "./transfer";

/** The kinds of record a file can carry, in the order they are loaded. */
export const ENTITIES: ReadonlyArray<Option & { value: Entity }> = [
  // 0.9.18: the lists an address takes its country and its state from come first, before
  // the places whose addresses take them; a row of them is an Admin's to apply (P-321).
  { value: "countries", label: "Countries" },
  { value: "states", label: "States" },
  { value: "tags", label: "Tags" },
  { value: "vendors", label: "Vendors" },
  { value: "catalog_entries", label: "Catalog entries" },
  { value: "contacts", label: "Contacts" },
  // 0.8.0: the account team and the support desk of a vendor follow the contacts (P-153).
  { value: "vendor_contacts", label: "Contacts of vendors" },
  { value: "operators", label: "Operators" },
  { value: "regions", label: "Regions" },
  { value: "sites", label: "Sites" },
  { value: "locations", label: "Locations" },
  { value: "contact_assignments", label: "Contacts of places" },
  { value: "owners", label: "Owners" },
  { value: "owner_members", label: "People of owners" },
  { value: "networks", label: "Networks" },
  { value: "external_systems", label: "External systems" },
  { value: "agreements", label: "Support agreements" },
  { value: "contracts", label: "Contracts" },
  { value: "contract_contacts", label: "Contacts of agreements and contracts" },
  { value: "purchase_requests", label: "Purchase requests" },
  { value: "purchase_lines", label: "Lines of purchase requests" },
  { value: "items", label: "Items" },
  { value: "device_groups", label: "Device groups" },
  { value: "device_group_members", label: "Members of device groups" },
  { value: "item_replacements", label: "Replacements of items" },
  { value: "addresses", label: "Addresses" },
  { value: "contract_coverage", label: "Coverage of items under contracts" },
  { value: "registrations", label: "Registrations with external systems" },
  { value: "capacity_lines", label: "Capacity lines" },
  // 0.8.0: the circuits come last, their groups first and their devices after the items
  // and the device groups they name (P-153).
  { value: "circuit_groups", label: "Circuit groups" },
  { value: "circuits", label: "Circuits" },
  { value: "circuit_carriers", label: "Carriers of circuits" },
  { value: "circuit_costs", label: "Cost lines of circuits" },
  { value: "circuit_contacts", label: "Contacts of circuits" },
  { value: "circuit_devices", label: "Devices of circuits" },
];

export function isEntity(value: string): value is Entity {
  return ENTITIES.some((entity) => entity.value === value);
}

/** The name of a kind of record for people. One this build does not know is shown as sent. */
export function entityLabel(entity: string): string {
  return ENTITIES.find((known) => known.value === entity)?.label ?? entity;
}

export type Mode = "create" | "upsert";

export const MODES: ReadonlyArray<Option & { value: Mode }> = [
  { value: "upsert", label: "Create and update" },
  { value: "create", label: "Create only" },
];

export function modeLabel(mode: string): string {
  if (mode === "update") return "Update only";
  return MODES.find((known) => known.value === mode)?.label ?? mode;
}

/**
 * The format of a file: by the end of its name, and failing that by the type the
 * browser gives it. Null for a file that is neither CSV nor JSON.
 */
export function fileType(file: { name: string; type: string }): FileType | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".csv")) return "text/csv";
  if (name.endsWith(".json")) return "application/json";
  const type = file.type.split(";")[0]?.trim().toLowerCase();
  if (type === "text/csv" || type === "application/json") return type;
  return null;
}

/** A name in lower case, each run of anything but a letter one `_`. */
function words(text: string): string {
  return text.toLowerCase().replace(/[^a-z]+/g, "_");
}

/**
 * The kind of record a file's name suggests, as `catalog-entries.csv` suggests catalog
 * entries, or blank. A name may hold more than one, as `items-operators-team.csv` does:
 * the one that stands first in the name is meant, and of two that start at the same
 * place the longer. It only fills in the form: the reader may choose otherwise.
 *
 * 0.9.2: an export is named after the product (P-168), `Example-Inventory-vendors-….csv`, and the
 * product's name may hold the name of a kind of record itself, as `Sites Tool` does. So
 * the name of the product in force, or hirdir, at the start of the file's name is passed
 * over where a kind of record follows it.
 */
export function guessEntity(fileName: string, productName: string = DEFAULT_NAME): Entity | "" {
  const name = words(fileName).replace(/^_+/, "");
  for (const stem of [fileStem(productName), DEFAULT_NAME]) {
    const lead = words(stem).replace(/^_+|_+$/g, "");
    if (lead === "" || !name.startsWith(`${lead}_`)) continue;
    const after = firstEntity(name.slice(lead.length + 1));
    if (after !== "") return after;
  }
  return firstEntity(name);
}

/** The kind of record that stands first in a name, and the longer of two at one place. */
function firstEntity(name: string): Entity | "" {
  let best: { entity: Entity; at: number } | null = null;
  for (const { value } of ENTITIES) {
    const at = name.indexOf(value);
    if (at < 0) continue;
    const better =
      best === null || at < best.at || (at === best.at && value.length > best.entity.length);
    if (better) best = { entity: value, at };
  }
  return best?.entity ?? "";
}

// The longest file name the server takes.
const LONGEST_NAME = 255;

/**
 * 0.9.8: what a file of items says of the tool it was read from (P-248): the external
 * system, by its HID, and whether the file is everything it reports. Blank, it was read
 * from none.
 */
export interface ReadFrom {
  system: string;
  complete: boolean;
}

export const FROM_NONE: ReadFrom = { system: "", complete: false };

/** Whether a file of these records may be read from a system: only a file of items. */
export function readsFromSystem(entity: Entity | ""): boolean {
  return entity === "items" || entity === "";
}

/** What goes beside the file in the URL of `POST /imports/preview`. A blank is left out. */
export function previewQuery(
  entity: Entity | "",
  mode: Mode | "",
  fileName: string,
  from: ReadFrom = FROM_NONE,
): { entity?: Entity; mode?: Mode; file_name?: string; system?: string; complete?: boolean } {
  const name = fileName.trim().slice(-LONGEST_NAME);
  // A system is sent with a file of items alone, and `complete` with a system alone.
  const system = readsFromSystem(entity) ? from.system : "";
  return {
    ...(entity === "" ? {} : { entity }),
    ...(mode === "" ? {} : { mode }),
    ...(name === "" ? {} : { file_name: name }),
    ...(system === "" ? {} : { system }),
    ...(system !== "" && from.complete ? { complete: true } : {}),
  };
}

/** What is the same about a file whenever the same file is sent again. */
export function fileIdentity(
  file: { name: string; size: number; lastModified: number },
  entity: string,
  mode: string,
  from: ReadFrom = FROM_NONE,
): string {
  return [
    "preview",
    file.name,
    file.size,
    file.lastModified,
    entity,
    mode,
    from.system,
    from.complete ? "complete" : "",
  ].join("\u0000");
}
