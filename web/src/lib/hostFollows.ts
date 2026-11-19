// 0.9.8: what follows from a host, as the forms of Retire, Replace and Import say it
// (P-247, P-248, P-249). The server holds every rule: this only says, in words, what it
// answered or is asked.

import { plural } from "./format";

/** The box of Replace (P-247): "The 3 things that run on it go to the new one". */
export function handOverLabel(count: number): string {
  return count === 1
    ? "The 1 thing that runs on it goes to the new one"
    : `The ${count.toLocaleString("en-US")} things that run on it go to the new one`;
}

// How many names are listed beneath the box, at most: "where they are few".
export const FEW = 10;

/** The names beneath the box, where they are few; none where there are more. */
export function fewNames(names: readonly string[]): readonly string[] {
  return names.length <= FEW ? names : [];
}

/**
 * What the answer to Replace adds of what runs on the item that left: where it went, or
 * that it stayed. Nothing where nothing ran on it.
 */
export function handedOverText(count: number, handedOver: boolean, came: string): string {
  if (count === 0) return "";
  if (handedOver) {
    return count === 1
      ? ` The 1 thing that ran on it runs on ${came} now.`
      : ` The ${count.toLocaleString("en-US")} things that ran on it run on ${came} now.`;
  }
  return count === 1
    ? " The 1 thing that runs on it stays on it."
    : ` The ${count.toLocaleString("en-US")} things that run on it stay on it.`;
}

/** What the box says once the item that comes is chosen, where it hosts nothing by its kind. */
export function hostsNothingHint(name: string, kind: string): string {
  return `Unticked: ${name} is of the kind ${kind.replaceAll("_", " ")}, which hosts nothing. Tick it to hand them over all the same; the server says whether it may.`;
}

// --- a tool's report (P-248) -------------------------------------------------------------

/** What the box of a tool's report does, beneath it. */
export const COMPLETE_HINT =
  "Every item registered with the system that the file does not name is marked as not reported, to be looked at. Nothing is retired, moved or unregistered: the next file that names it makes it registered again.";

/** Why a complete import marks nothing, as the job says in `not_reported_held`. */
export type NotReportedHeld = "rejected" | "skipped" | "stale" | null;

const HELD_WORDS: Readonly<Record<string, string>> = {
  rejected: "a row was rejected",
  skipped: "the rows that were rejected were left out",
  stale: "a row was left out, its record having changed since the preview",
};

/**
 * What the preview of a complete report says it would mark, or the applied one marked.
 * `named` says whether the first of them are listed after it: the sentence then ends in
 * a colon, and otherwise in a full stop.
 */
export function notReportedText(
  job: {
    complete: boolean | null;
    status: string;
    not_reported: number;
    not_reported_held?: NotReportedHeld;
    rejected: number;
    system: { name: string } | null;
  },
  named = false,
): string {
  if (!job.complete) return "";
  const system = job.system?.name ?? "the system";
  const count = job.not_reported;
  const held = job.not_reported_held ?? null;
  if (job.status === "previewed") {
    if (held !== null || job.rejected > 0) {
      return `Nothing will be marked as not reported: a row is rejected, and only a file applied whole is everything ${system} reports.`;
    }
    return count === 0
      ? `Every item registered with ${system} is named by the file: none will be marked as not reported.`
      : `${plural(count, "item registered with", "items registered with")} ${system} ${count === 1 ? "is" : "are"} not named by the file, and will be marked as not reported once it is applied whole${named ? ":" : "."}`;
  }
  if (job.status === "applied" || job.status === "stopped") {
    if (held !== null) {
      return `Nothing was marked as not reported: ${HELD_WORDS[held] ?? held}, and only a file applied whole is everything ${system} reports.`;
    }
    if (job.status === "stopped") {
      return "Nothing is marked as not reported until the file is applied whole.";
    }
    return count === 0
      ? `No item was marked as not reported by ${system}.`
      : `${plural(count, "item was", "items were")} marked as not reported by ${system}, each to be looked at.`;
  }
  return "Nothing is marked as not reported until the file is applied whole.";
}

// --- what is to be looked at (P-249) -----------------------------------------------------

/** The filter of the item list for every item with a reason to be looked at. */
export const TO_REVIEW = "review:empty:false";

/** The item list with every item to be looked at, the minor ones among them. */
export function toReviewPath(): string {
  return `/items?${new URLSearchParams({ filter: TO_REVIEW, minor: "1" }).toString()}`;
}

/** The first page's line, as a link and what follows it. */
export function toReviewText(count: number): { link: string; after: string } {
  return {
    link: plural(count, "item is", "items are"),
    after: " to be looked at",
  };
}

/** The reasons an item is to be looked at, in the order the first page says them. */
export const REVIEW_ORDER = ["no_host", "host_gone", "not_reported"] as const;
export type ReviewReasonName = (typeof REVIEW_ORDER)[number];

const REASON_WORDS: Readonly<Record<ReviewReasonName, [one: string, many: string]>> = {
  no_host: ["names no host", "name no host"],
  host_gone: ["has a host that is gone", "have a host that is gone"],
  not_reported: ["is reported no more by a tool", "are reported no more by a tool"],
};

/**
 * 0.9.8, review: the first page says why each is to be looked at by a link of its own for
 * each reason, to the item list filtered by it, so that the list it opens says the reason
 * in its filter without a column of its own. A reason that counts none is left out.
 */
export function reviewReasonParts(
  counts: Readonly<Partial<Record<ReviewReasonName, number>>>,
): { reason: ReviewReasonName; count: number; text: string; path: string }[] {
  return REVIEW_ORDER.flatMap((reason) => {
    const count = counts[reason] ?? 0;
    if (count === 0) return [];
    const [one, many] = REASON_WORDS[reason];
    return [{ reason, count, text: plural(count, one, many), path: reviewPath(reason) }];
  });
}

/** The item list of the items to be looked at for one reason. */
export function reviewPath(reason: ReviewReasonName): string {
  return `/items?${new URLSearchParams({ filter: `review:eq:${reason}`, minor: "1" }).toString()}`;
}
