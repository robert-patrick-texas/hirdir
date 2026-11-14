// Sending a file to be imported.
//
// The file itself is the body of the request, as CSV or as JSON, and what else there is
// to say about it (which records it holds, the mode, its name) goes beside it in the
// URL. The server reads it and judges it; this only says what is being sent.

import type { FileType } from "../api/client";
import type { Option } from "./patch";
import type { Entity } from "./transfer";

/** The kinds of record a file can carry, in the order they are loaded. */
export const ENTITIES: ReadonlyArray<Option & { value: Entity }> = [
  { value: "tags", label: "Tags" },
  { value: "vendors", label: "Vendors" },
  { value: "catalog_entries", label: "Catalog entries" },
  { value: "regions", label: "Regions" },
  { value: "sites", label: "Sites" },
  { value: "locations", label: "Locations" },
  { value: "contacts", label: "Contacts" },
  { value: "contact_assignments", label: "Contacts of places" },
  { value: "owners", label: "Owners" },
  { value: "owner_members", label: "People of owners" },
  { value: "networks", label: "Networks" },
  { value: "items", label: "Items" },
  { value: "device_groups", label: "Device groups" },
  { value: "device_group_members", label: "Members of device groups" },
  { value: "addresses", label: "Addresses" },
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

/**
 * The kind of record a file's name suggests, as `catalog-entries.csv` suggests catalog
 * entries, or blank. It only fills in the form: the reader may choose otherwise.
 */
export function guessEntity(fileName: string): Entity | "" {
  const name = fileName.toLowerCase().replace(/[^a-z]+/g, "_");
  // The longer names first, so that a name within a name does not win.
  const known = [...ENTITIES].sort((one, other) => other.value.length - one.value.length);
  return known.find((entity) => name.includes(entity.value))?.value ?? "";
}

// The longest file name the server takes.
const LONGEST_NAME = 255;

/** What goes beside the file in the URL of `POST /imports/preview`. A blank is left out. */
export function previewQuery(
  entity: Entity | "",
  mode: Mode | "",
  fileName: string,
): { entity?: Entity; mode?: Mode; file_name?: string } {
  const name = fileName.trim().slice(-LONGEST_NAME);
  return {
    ...(entity === "" ? {} : { entity }),
    ...(mode === "" ? {} : { mode }),
    ...(name === "" ? {} : { file_name: name }),
  };
}

/** What is the same about a file whenever the same file is sent again. */
export function fileIdentity(
  file: { name: string; size: number; lastModified: number },
  entity: string,
  mode: string,
): string {
  return ["preview", file.name, file.size, file.lastModified, entity, mode].join("\u0000");
}
