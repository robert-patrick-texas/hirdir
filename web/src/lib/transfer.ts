// Taking rows out of a grid: to the clipboard and to a file.
//
// Both are the same export. The grid says which rows (the ones selected, by HID, or
// every row its filter keeps, by the filter and never by a list), in which order and
// with which columns, and the server writes them. The clipboard is that very file with
// tabs between the cells, so the clipboard, an exported file and the command line hold
// the same rows and the same columns, each with `hid` first.

import type { Schemas } from "../api/client";
import type { FilterNode } from "./filter";

export type ExportRequest = Schemas["ExportRequest"];
/** The kinds of record a file can carry. */
export type Entity = ExportRequest["entity"];
export type FileFormat = "csv" | "json";

/** What a grid is showing: the filter, the sort and the switches of its list. */
export interface GridView {
  filter: FilterNode | null;
  sort: string[];
  include_archived: boolean;
  include_drafts: boolean;
}

/**
 * The rows something is to be done with: particular rows, each by its HID, or every row
 * the filter keeps. "All" is a count for the reader and a filter for the server.
 */
export type Chosen = { kind: "rows"; hids: string[] } | { kind: "all"; count: number };

export function chosenCount(chosen: Chosen): number {
  return chosen.kind === "rows" ? chosen.hids.length : chosen.count;
}

/** What the export needs to know of a grid's column. */
export interface ExportColumn {
  /** The column's ID in the grid. */
  id: string;
  /** The column of an export that holds it. Left out, the ID. Null when no export has it. */
  column?: string | null;
}

/** A column of the grid as the grid reports it: where it stands and whether it is hidden. */
export interface ShownColumn {
  colId: string;
  hide?: boolean | null | undefined;
}

/**
 * The columns to export: the ones on show, in the order they are shown, by the names an
 * export knows them by. `hid` is always the first, shown or not.
 */
export function exportColumns(
  columns: readonly ExportColumn[],
  state: readonly ShownColumn[],
): string[] {
  const names = ["hid"];
  for (const entry of state) {
    if (entry.hide === true) continue;
    const column = columns.find((candidate) => candidate.id === entry.colId);
    if (!column) continue;
    const name = column.column === undefined ? column.id : column.column;
    if (name !== null && !names.includes(name)) names.push(name);
  }
  return names;
}

/**
 * The body of `POST /exports` for what a grid shows. Particular rows are named by their
 * HIDs alone, so that what was selected is what comes, also when a row has changed
 * since and the filter would no longer keep it. All that match are named by the filter.
 */
export function exportRequest(
  entity: Entity,
  format: FileFormat,
  view: GridView,
  columns: readonly string[],
  chosen: Chosen,
): ExportRequest {
  return {
    entity,
    format,
    columns: [...columns],
    sort: [...view.sort],
    ...(chosen.kind === "rows"
      ? { hids: [...chosen.hids] }
      : {
          ...(view.filter ? { filter: view.filter as unknown as Record<string, unknown> } : {}),
          include_archived: view.include_archived,
          include_drafts: view.include_drafts,
        }),
  };
}

/** A name for an exported file, when the server's answer did not name it. */
export function exportName(entity: Entity, format: FileFormat): string {
  return `hirdir-${entity}.${format}`;
}

/**
 * Read CSV text into rows of cells, as RFC 4180 has it: a cell in double quotes may
 * hold commas, line breaks and doubled quotes. A final line break ends the last row
 * and starts no new one.
 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  // Whether the row being read has anything in it yet, even an empty quoted cell.
  let begun = false;
  const source = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  for (let at = 0; at < source.length; at += 1) {
    const char = source[at];
    if (quoted) {
      if (char !== '"') cell += char;
      else if (source[at + 1] === '"') {
        cell += '"';
        at += 1;
      } else quoted = false;
    } else if (char === '"') {
      quoted = true;
      begun = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
      begun = true;
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && source[at + 1] === "\n") at += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      begun = false;
    } else {
      cell += char;
      begun = true;
    }
  }
  if (begun || cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

/**
 * Rows of cells as text for the clipboard: a tab between cells and a line break between
 * rows, the first row being the header. Tab-separated text has no way to quote, so a
 * tab or a line break inside a cell becomes a space.
 */
export function clipboardText(rows: ReadonlyArray<readonly string[]>): string {
  return rows
    .map((row) => row.map((cell) => cell.replace(/\r\n|[\t\r\n]/g, " ")).join("\t"))
    .join("\n");
}

/** An exported CSV file as text for the clipboard, and how many records it holds. */
export function csvToClipboard(csv: string): { text: string; count: number } {
  const rows = parseCsv(csv);
  return { text: clipboardText(rows), count: Math.max(0, rows.length - 1) };
}
