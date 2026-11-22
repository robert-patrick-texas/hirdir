// 0.9.13: every table a file is taken for, exported whole (P-286, P-287).
//
// The Import page lists them all, in the order their files are loaded, each with how many
// records it holds; Geography has its three, and Choices, since 0.9.18, the lists of
// countries and states, which are loaded first and are never empty in an inventory, which
// starts with them (P-321). Each is exported as an import reads it, by
// `POST /exports` with `whole`: the server's word for the whole table as the zip of every
// table holds it, so that the file is corrected and loaded back, and changes nothing where
// it is loaded back as it is. The page holds no copy of what that is.

import type { Schemas } from "../api/client";
import { ENTITIES } from "./imports";
import { namedFile } from "./product";
import { countText } from "./summary";
import type { Entity, FileFormat } from "./transfer";

/** One table as `GET /exports/tables` gives it. */
export type ExportTable = Schemas["ExportTable"];

/** One table as a list of them shows it. */
export interface TableRow {
  entity: Entity;
  label: string;
  /** How many records it holds; null until the server has said. */
  count: number | null;
}

/**
 * The tables to show, in the order their files are loaded: as the server lists them, or,
 * until it has, as this build knows them, so that each can be exported from the start.
 * Only those of `only`, where it is given.
 */
export function tableRows(
  tables: readonly ExportTable[] | undefined,
  only?: readonly Entity[],
): TableRow[] {
  const rows: TableRow[] = tables
    ? tables.map(({ entity, label, count }) => ({ entity, label, count }))
    : ENTITIES.map(({ value, label }) => ({ entity: value, label, count: null }));
  return only ? rows.filter((row) => only.includes(row.entity)) : rows;
}

/** Whether a table is known to hold nothing, so that its CSV is the template of its import. */
export function holdsNothing(row: TableRow): boolean {
  return row.count === 0;
}

/** How many records a table holds, in words for its row. */
export function countWords(count: number | null): string {
  if (count === null) return "…";
  return count === 0 ? "None" : countText(count);
}

/** What is said above the list: how many tables, and how many records they hold. */
export function tablesText(rows: readonly TableRow[]): string {
  const tables = `${rows.length} ${rows.length === 1 ? "table" : "tables"}`;
  if (rows.some((row) => row.count === null)) return tables;
  const empty = rows.filter(holdsNothing).length;
  if (empty === 0) return tables;
  if (empty < rows.length) return `${tables}, ${countText(empty)} holding nothing yet`;
  return `${tables}, ${rows.length === 1 ? "" : "all "}holding nothing yet`;
}

/**
 * The name of the button that exports a table, as a screen reader says it. It is the same
 * whatever the table holds, on the Import page and on Geography, which does not count:
 * the words above the list say that the CSV of a table that holds nothing is its
 * template (review X4).
 */
export function exportLabel(row: TableRow, format: FileFormat): string {
  return `Export ${row.label} as ${format.toUpperCase()}`;
}

/** A name for the zip of every table, where the server's answer named none (P-168). */
export function everythingName(format: FileFormat, productName: string): string {
  return namedFile(productName, `all-${format}.zip`);
}
