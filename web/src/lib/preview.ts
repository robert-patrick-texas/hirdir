// A stored preview, of an import or of a bulk edit, as a page shows it.
//
// The server works out what every row would do and keeps it. Nothing is decided here:
// this turns the job and its rows into words, asks for the rows a page at a time, and
// reads the refusal of an apply that found a record changed since.

import type { ApiError, Schemas } from "../api/client";
import type { Option } from "./patch";

export type Job = Schemas["ImportJobOut"];
export type PreviewRow = Schemas["ImportRowOut"];
export type Preview = Schemas["ImportPreview"];
export type Outcome = PreviewRow["outcome"];

export const OUTCOMES: readonly Outcome[] = ["create", "update", "unchanged", "rejected"];
/** How many rows of a preview a page shows, which is also how many a preview answers with. */
export const ROWS_PAGE = 100;

const COUNT_OF = {
  create: "created",
  update: "updated",
  unchanged: "unchanged",
  rejected: "rejected",
} as const satisfies Record<Outcome, keyof Job>;

const OUTCOME_LABELS: Readonly<Record<Outcome, string>> = {
  create: "Create",
  update: "Update",
  unchanged: "Unchanged",
  rejected: "Rejected",
};

export function isOutcome(value: string): value is Outcome {
  return (OUTCOMES as readonly string[]).includes(value);
}

export function outcomeLabel(outcome: string): string {
  return isOutcome(outcome) ? OUTCOME_LABELS[outcome] : outcome;
}

/** How many rows of a job have an outcome. With no outcome, how many rows it has. */
export function outcomeCount(job: Job, outcome: Outcome | ""): number {
  return outcome === "" ? job.row_count : job[COUNT_OF[outcome]];
}

/** The choices of the filter over a preview's rows, each with its count. */
export function outcomeOptions(job: Job): Option[] {
  return [
    { value: "", label: `All rows (${job.row_count})` },
    ...OUTCOMES.map((outcome) => ({
      value: outcome,
      label: `${OUTCOME_LABELS[outcome]} (${outcomeCount(job, outcome)})`,
    })),
  ];
}

/** The query of `GET /imports/{hid}/rows` for one page of rows. */
export function rowsQuery(
  outcome: Outcome | "",
  offset: number,
): { outcome?: Outcome; limit: number; offset: number } {
  return {
    ...(outcome === "" ? {} : { outcome }),
    limit: ROWS_PAGE,
    offset: Math.max(0, Math.floor(offset)),
  };
}

export interface RowsPage {
  items: PreviewRow[];
  total: number;
}

/**
 * The page of rows that a preview's own answer already holds, or null when the page
 * wanted has to be asked for. The answer holds the first rows of all outcomes; it is
 * used only when it is a whole page, so that the next page starts where this one ends.
 */
export function firstPage(
  preview: Preview | null | undefined,
  outcome: Outcome | "",
  offset: number,
): RowsPage | null {
  if (!preview || outcome !== "" || offset !== 0) return null;
  const whole = Math.min(ROWS_PAGE, preview.job.row_count);
  if (preview.rows.length !== whole) return null;
  return { items: preview.rows, total: preview.job.row_count };
}

/** One value of a row, as a file would write it. Blank is said in words. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(blank)";
  if (Array.isArray(value)) return value.length === 0 ? "(blank)" : value.map(String).join("; ");
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** One change of a row, as "field: old → new". */
export function changeText(change: Schemas["RowChange"]): string {
  return `${change.field}: ${valueText(change.old)} → ${valueText(change.new)}`;
}

/** Why a row is rejected, as "field: message", or the message alone when it names no field. */
export function reasonText(reason: Schemas["RowReason"]): string {
  return reason.field ? `${reason.field}: ${reason.message}` : reason.message;
}

/** The counts of a job in a sentence: "2 to create, 1 to update, 5 unchanged, 0 rejected". */
export function countsText(job: Job): string {
  const done = job.status === "applied";
  return [
    `${job.created} ${done ? "created" : "to create"}`,
    `${job.updated} ${done ? "updated" : "to update"}`,
    `${job.unchanged} unchanged`,
    `${job.rejected} rejected`,
  ].join(", ");
}

const STATUS_LABELS: Readonly<Record<Job["status"], string>> = {
  previewed: "Previewed, not applied",
  applied: "Applied",
  failed: "Failed: nothing was applied",
};

export function statusLabel(job: Job): string {
  if (job.status === "applied" && job.skip_rejected && job.rejected > 0) {
    return "Applied, without the rejected rows";
  }
  return STATUS_LABELS[job.status] ?? job.status;
}

const TITLE_OUT_OF_DATE = "Preview out of date";

/** An apply that was refused because a record changed after the preview was made. */
export function isOutOfDate(error: ApiError | null | undefined): boolean {
  return Boolean(error) && error?.status === 409 && error.title === TITLE_OUT_OF_DATE;
}

export interface StaleRow {
  /** The row's number in the file, from 1. */
  row: number;
  message: string;
}

/**
 * The rows that stood in the way of an apply, in the order of the file. The server names
 * each as the field `rows.N` of its refusal.
 */
export function staleRows(error: ApiError | null | undefined): StaleRow[] {
  if (!error || !isOutOfDate(error)) return [];
  const rows: StaleRow[] = [];
  for (const [field, message] of Object.entries(error.fields)) {
    const match = /^rows\.(\d+)$/.exec(field);
    if (match) rows.push({ row: Number(match[1]), message });
  }
  return rows.sort((one, other) => one.row - other.row);
}

const PAGE_OF: Readonly<Record<string, string>> = {
  items: "/items/",
  catalog_entries: "/catalog/",
  vendors: "/vendors/",
  owners: "/owners/",
};

/** The page of the record a row names, as a path of the app, where its kind has one. */
export function recordPath(entity: string, hid: string | null | undefined): string | null {
  const page = PAGE_OF[entity];
  return page !== undefined && hid ? `${page}${encodeURIComponent(hid)}` : null;
}
