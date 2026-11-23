// A stored preview, of an import or of a bulk edit, as a page shows it.
//
// The server works out what every row would do and keeps it, and applies it in the
// background when asked. Nothing is decided here: this turns the job and its rows into
// words, says how far a preview or an apply has got, and asks for the rows a page at a
// time.

import type { Schemas } from "../api/client";
import { plural } from "./format";
import { optionLabel } from "./options";
import type { Option } from "./patch";
import { REGISTRATION_STATUSES } from "./systems";

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
  // 0.9.8: a row of a file read from a system makes the item's registration with it, or
  // brings it back, which is said by its status (P-248).
  if (change.field === "registration") {
    const status = (value: unknown) =>
      typeof value === "string" && value !== ""
        ? optionLabel(REGISTRATION_STATUSES, value)
        : "not registered";
    return `registration with the system: ${status(change.old)} → ${status(change.new)}`;
  }
  const said = `${change.field}: ${valueText(change.old)} → ${valueText(change.new)}`;
  // 0.9.17: a row that makes its record retired says so plainly, before the change (P-311).
  if (change.field === "record_status" && change.new === "retired" && !change.old) {
    return `made retired, as the file says: ${said}`;
  }
  // 0.9.18: a value a format writes again is said beside the file's, so that what an
  // import would tidy is seen before it is applied (P-322 (5)).
  if (change.as_in_file !== undefined && change.as_in_file !== null) {
    return `${said} (in the file: ${valueText(change.as_in_file)})`;
  }
  return said;
}

/** Why a row is rejected, as "field: message", or the message alone when it names no field. */
export function reasonText(reason: Schemas["RowReason"]): string {
  return reason.field ? `${reason.field}: ${reason.message}` : reason.message;
}

/** The counts of a preview in a sentence: "2 to create, 1 to update, 5 unchanged, 0 rejected". */
export function countsText(job: Job): string {
  return [
    `${job.created} to create`,
    `${job.updated} to update`,
    `${job.unchanged} unchanged`,
    `${job.rejected} rejected`,
  ].join(", ");
}

const STATUS_LABELS: Readonly<Record<Job["status"], string>> = {
  previewing: "Being previewed",
  previewed: "Previewed, not applied",
  queued: "Waiting to be applied",
  applying: "Being applied",
  applied: "Applied",
  stopped: "Stopped partway, to be resumed",
  failed: "Failed: nothing was applied",
};

export function statusLabel(job: Job): string {
  // 0.9.19: a preview that failed in the background was never whole, and is sent again (P-325).
  if (previewFailed(job)) return "Preview failed";
  if (job.status === "applied") {
    const without: string[] = [];
    if (job.skip_rejected && job.rejected > 0) without.push("the rejected rows");
    if (job.stale > 0) without.push("the rows changed since the preview");
    if (without.length > 0) return `Applied, without ${without.join(" and ")}`;
  }
  return STATUS_LABELS[job.status] ?? job.status;
}

// --- the preview, in the background (P-325) -----------------------------------------
//
// 0.9.19: a file of more than a hundred rows, and a bulk edit of more than a hundred
// items, is answered at once with its job, `previewing`, and no rows. The background
// work previews it and says how far it has got, `rows_previewed` of `row_count`; the job
// is then `previewed`, as a preview answered at once is, or `failed`, with why in
// `failure`, and nothing of its rows kept. Until it is previewed, its rows are not
// listed and it is not applied: the server answers both with a 409.

export function isPreviewing(job: Pick<Job, "status">): boolean {
  return job.status === "previewing";
}

/** Whether a page reads a job again every moment: its preview or its apply is under way. */
export function isUnderWay(job: Pick<Job, "status">): boolean {
  return isPreviewing(job) || isWorking(job);
}

type Counted = Pick<
  Job,
  "status" | "row_count" | "rows_previewed" | "created" | "updated" | "unchanged" | "rejected"
>;

/**
 * Whether a job holds what each of its rows would do, so that its counts and its rows
 * are shown: every job but one still being previewed, and one whose preview failed
 * before it was whole. Every row of a whole preview has an outcome, so its counts add up
 * to its rows; a failed job of a release before 0.7.0 was previewed whole, and one that
 * failed in the background kept none of them.
 */
export function hasPreview(job: Counted): boolean {
  if (isPreviewing(job)) return false;
  if (job.status !== "failed") return true;
  const counted = job.created + job.updated + job.unchanged + job.rejected;
  return job.rows_previewed >= job.row_count && counted >= job.row_count;
}

/**
 * A preview that failed in the background: it was never whole, is never applied, and is
 * sent again.
 */
export function previewFailed(job: Counted): boolean {
  return job.status === "failed" && !hasPreview(job);
}

/** How far a preview has got: "Previewing 3,200 of 10,000 rows". */
export function previewingText(
  job: Pick<Job, "rows_previewed" | "row_count">,
  noun: [one: string, many: string] = ["row", "rows"],
): string {
  return `Previewing ${job.rows_previewed.toLocaleString("en-US")} of ${plural(job.row_count, noun[0], noun[1])}`;
}

/**
 * What a preview that was followed in the background found, said once it has come:
 * "Previewed: 9,990 to create, 0 to update, 0 unchanged, 10 rejected". A bulk edit
 * creates nothing, and does not say it would (P-204).
 */
export function previewedText(
  job: Pick<Job, "source" | "created" | "updated" | "unchanged" | "rejected">,
): string {
  const counts: Array<[count: number, what: string]> = [
    [job.created, "to create"],
    [job.updated, "to update"],
    [job.unchanged, "unchanged"],
    [job.rejected, "rejected"],
  ];
  const said = (job.source === "bulk" ? counts.slice(1) : counts).map(
    ([count, what]) => `${count.toLocaleString("en-US")} ${what}`,
  );
  return `Previewed: ${said.join(", ")}`;
}

/**
 * What came to an end between two readings of a job: its preview, which was under way
 * and is no longer, previewed or failed; its apply, likewise, applied or stopped; or
 * nothing. A job read for the first time has ended nothing that this page saw.
 */
export function whatEnded(
  before: Job["status"] | undefined,
  after: Job["status"],
): "preview" | "apply" | null {
  if (before === undefined) return null;
  if (before === "previewing" && after !== "previewing") return "preview";
  if (WORKING.includes(before) && !WORKING.includes(after)) return "apply";
  return null;
}

// --- the apply, in the background -----------------------------------------------------
//
// An apply answers at once, and the server works the rows in batches beside the
// requests. The job says how far it has got, `rows_done` of `row_count`, and once every
// row is worked how many were applied and how many were left out as changed since the
// preview. What was worked and is neither was refused.

/** The states of a job whose apply is under way: it is read again until it is in another. */
export const WORKING: readonly Job["status"][] = ["queued", "applying"];

export function isWorking(job: Pick<Job, "status">): boolean {
  return WORKING.includes(job.status);
}

/**
 * Whether the apply of a job has been asked for, so that the job says what it did: not
 * while it is being previewed or waits to be applied, and not when it failed.
 */
export function applyBegun(job: Pick<Job, "status">): boolean {
  return job.status !== "previewing" && job.status !== "previewed" && job.status !== "failed";
}

/** The rows the apply refused: of those it worked, the ones neither applied nor stale. */
export function refusedAtApply(job: Pick<Job, "rows_done" | "applied" | "stale">): number {
  return Math.max(0, job.rows_done - job.applied - job.stale);
}

/** How far an apply has got: "120 of 300 rows worked". */
export function progressText(
  job: Pick<Job, "rows_done" | "row_count">,
  noun: [one: string, many: string] = ["row", "rows"],
): string {
  const of = job.row_count === 1 ? noun[0] : noun[1];
  return `${job.rows_done} of ${job.row_count} ${of} worked`;
}

/**
 * What an apply did, in a sentence: "3 rows applied, 1 left out as changed since the
 * preview, none refused".
 */
export function appliedText(
  job: Pick<Job, "rows_done" | "applied" | "stale">,
  noun: [one: string, many: string] = ["row", "rows"],
): string {
  const refused = refusedAtApply(job);
  return [
    `${job.applied} ${job.applied === 1 ? noun[0] : noun[1]} applied`,
    `${job.stale === 0 ? "none" : job.stale} left out as changed since the preview`,
    `${refused === 0 ? "none" : refused} refused`,
  ].join(", ");
}

/** What a stopped job had done when it stopped: "50 of 300 rows had been worked". */
export function stoppedText(
  job: Pick<Job, "rows_done" | "row_count">,
  noun: [one: string, many: string] = ["row", "rows"],
): string {
  return `${job.rows_done} of ${job.row_count} ${job.row_count === 1 ? noun[0] : noun[1]} had been worked`;
}

export type AppliedOutcome = NonNullable<PreviewRow["applied_outcome"]>;

const APPLIED_LABELS: Readonly<Record<AppliedOutcome, string>> = {
  create: "Created",
  update: "Updated",
  unchanged: "Unchanged",
  stale: "Changed since the preview",
  rejected: "Refused",
};

/** What the apply did with a row, for people. Blank until it is worked. */
export function appliedLabel(outcome: PreviewRow["applied_outcome"]): string {
  return outcome ? (APPLIED_LABELS[outcome] ?? outcome) : "";
}

/** The rows an apply left out: those changed since the preview, and those it refused. */
export type LeftOut = "stale" | "rejected";

/** The query of `GET /imports/{hid}/rows` for one page of the rows an apply left out. */
export function leftOutQuery(
  outcome: LeftOut,
  offset: number,
): { applied_outcome: LeftOut; limit: number; offset: number } {
  return { applied_outcome: outcome, limit: ROWS_PAGE, offset: Math.max(0, Math.floor(offset)) };
}

/** How many rows an apply left out of one kind, as the job counts them. */
export function leftOutCount(job: Job, outcome: LeftOut): number {
  return outcome === "stale" ? job.stale : refusedAtApply(job);
}

/**
 * The page of each kind of record that has one, by the kind the audit trail names it by
 * (P-186). A kind with no page of its own, a tag, an address or a member of a group, is
 * not here.
 */
const PAGE_OF_KIND: Readonly<Record<string, string>> = {
  item: "/items/",
  catalog_entry: "/catalog/",
  vendor: "/vendors/",
  owner: "/owners/",
  device_group: "/groups/",
  operator: "/operators/",
  contact: "/contacts/",
  circuit: "/circuits/",
  circuit_group: "/circuit-groups/",
  agreement: "/agreements/",
  contract: "/contracts/",
  purchase_request: "/purchases/",
  external_system: "/systems/",
  capacity_line: "/capacity/",
  import_job: "/import/",
  region: "/geography/region/",
  site: "/geography/site/",
  location: "/geography/location/",
  user: "/admin/users/",
  user_group: "/admin/groups/",
};

/** The kinds whose page only an Admin may open. */
const ADMIN_KINDS: ReadonlySet<string> = new Set(["user", "user_group"]);

/** The kind of record of each entity an import or a bulk edit names. */
const KIND_OF_ENTITY: Readonly<Record<string, string>> = {
  items: "item",
  catalog_entries: "catalog_entry",
  vendors: "vendor",
  owners: "owner",
  device_groups: "device_group",
};

/**
 * The page of a record, by the kind the audit trail names it by, as a path of the app,
 * where its kind has one. A page that only an Admin may open is a page only for an Admin.
 */
export function kindPath(
  kind: string,
  hid: string | null | undefined,
  admin = false,
): string | null {
  const page = PAGE_OF_KIND[kind];
  if (page === undefined || !hid || (ADMIN_KINDS.has(kind) && !admin)) return null;
  return `${page}${encodeURIComponent(hid)}`;
}

/** The page of the record a row names, as a path of the app, where its kind has one. */
export function recordPath(entity: string, hid: string | null | undefined): string | null {
  const kind = KIND_OF_ENTITY[entity];
  return kind === undefined ? null : kindPath(kind, hid);
}
