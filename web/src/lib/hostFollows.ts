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

/** What the preview of a complete report says it would mark, or the applied one marked. */
export function notReportedText(job: {
  complete: boolean | null;
  status: string;
  not_reported: number;
  rejected: number;
  system: { name: string } | null;
}): string {
  if (!job.complete) return "";
  const system = job.system?.name ?? "the system";
  const count = job.not_reported;
  if (job.status === "previewed") {
    if (job.rejected > 0) {
      return `Nothing will be marked as not reported: a row is rejected, and only a file applied whole is everything ${system} reports.`;
    }
    return count === 0
      ? `Every item registered with ${system} is named by the file: none will be marked as not reported.`
      : `${plural(count, "item registered with", "items registered with")} ${system} ${count === 1 ? "is" : "are"} not named by the file, and will be marked as not reported once it is applied whole:`;
  }
  if (job.status === "applied") {
    return count === 0
      ? `No item was marked as not reported by ${system}.`
      : `${plural(count, "item was", "items were")} marked as not reported by ${system}, each to be looked at.`;
  }
  return `Nothing is marked as not reported until the file is applied whole.`;
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
    after: ` to be looked at: no host named, a host gone, or a tool that reports ${count === 1 ? "it" : "them"} no more. ${count === 1 ? "Its" : "Each"} page says why, and the way to put it right.`,
  };
}
