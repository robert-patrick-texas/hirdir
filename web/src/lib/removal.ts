// 0.9.7: several items or device groups retired at once by the Inventory role, and those
// that were a mistake deleted by an Admin (P-227, P-228, P-236). What the pages say of a
// request and of its answer; the server holds every rule.

import type { Schemas } from "../api";
import { plural } from "./format";
import { kindPath } from "./preview";

export type RetiredMany = Schemas["RetiredMany"];
export type DeletedMany = Schemas["DeletedMany"];
export type Dependent = Schemas["Dependent"];

/** The two kinds of record that are retired several at once and deleted. */
export type RemovalKind = "item" | "device_group";

const NOUNS: Readonly<Record<RemovalKind, [one: string, many: string]>> = {
  item: ["item", "items"],
  device_group: ["group", "groups"],
};

/** "3 items", "1 group". */
export function countOf(kind: RemovalKind, count: number): string {
  const [one, many] = NOUNS[kind];
  return plural(count, one, many);
}

/** The page of a record of the kind, as a path of the app. */
export function removalPath(kind: RemovalKind, hid: string): string {
  return kindPath(kind, hid) ?? "";
}

/** The page of a record that stands in the way of a deletion, where its kind has one. */
export function dependentPath(dependent: Pick<Dependent, "record_type" | "hid">): string | null {
  return kindPath(dependent.record_type, dependent.hid);
}

/**
 * What a record in the way is, as people say it: "contract", "purchase line". 0.9.8: an
 * item in the way runs on the record where `runsOn` says so, as every item does that
 * stands in the way of a group (P-247), and is otherwise installed in it.
 */
export function dependentKind(dependent: Pick<Dependent, "record_type">, runsOn = false): string {
  if (dependent.record_type === "item" && runsOn) return "item that runs on it";
  return DEPENDENT_WORDS[dependent.record_type] ?? dependent.record_type.replaceAll("_", " ");
}

/**
 * 0.9.8: of the items that stand in the way of deleting an item, those that run on it,
 * by their HIDs, from what each of them names as its host (P-247). The answer names an
 * item installed in it and one that runs on it alike.
 */
export function runningOn(
  refused: readonly {
    hid: string;
    depends_on: readonly Pick<Dependent, "record_type" | "hid">[];
  }[],
  hosts: readonly { hid: string; host_item_hid?: string | null }[],
): Set<string> {
  const hostOf = new Map(hosts.map((one) => [one.hid, one.host_item_hid ?? null]));
  const found = new Set<string>();
  for (const one of refused) {
    for (const dependent of one.depends_on) {
      if (dependent.record_type === "item" && hostOf.get(dependent.hid) === one.hid) {
        found.add(dependent.hid);
      }
    }
  }
  return found;
}

/** The HIDs of the items that stand in the way of a deletion, each once. */
export function itemsInTheWay(
  refused: readonly { depends_on: readonly Pick<Dependent, "record_type" | "hid">[] }[],
): string[] {
  const found = new Set<string>();
  for (const one of refused) {
    for (const dependent of one.depends_on) {
      if (dependent.record_type === "item") found.add(dependent.hid);
    }
  }
  return [...found];
}

const DEPENDENT_WORDS: Readonly<Record<string, string>> = {
  contract: "contract",
  purchase_line: "purchase line",
  item: "item installed in it",
  item_replacement: "replacement",
  circuit: "circuit",
  reference_file: "reference",
  device_group: "group nested in it",
};

/** The HIDs of an answer that stay ticked: those refused. */
export function stayTicked(answer: { refused: readonly { hid: string }[] }): string[] {
  return answer.refused.map((one) => one.hid);
}

/** What is said before those refused: on a list they stay ticked, on a page nothing is. */
function refusedLead(kind: RemovalKind, count: number, ticked: boolean): string {
  return `${countOf(kind, count)} refused${ticked ? ", still ticked" : ""}:`;
}

/**
 * What a Retire of several did, in one sentence: "Retired 3 items. 1 was retired already."
 * `ticked` is false where nothing was ticked, as on a record's page.
 */
export function retiredText(kind: RemovalKind, answer: RetiredMany, ticked = true): string {
  const parts = [
    answer.retired.length > 0
      ? `Retired ${countOf(kind, answer.retired.length)}.`
      : `No ${NOUNS[kind][1]} were retired.`,
  ];
  if (answer.already.length > 0) {
    parts.push(`${countOf(kind, answer.already.length)} retired already.`);
  }
  if (answer.refused.length > 0) {
    parts.push(refusedLead(kind, answer.refused.length, ticked));
  }
  if (answer.missing.length > 0) {
    parts.push(`${countOf(kind, answer.missing.length)} not found, as deleted since.`);
  }
  // 0.9.8: what ran on them went with them, and is counted apart (P-247).
  const hosted = answer.hosted.length;
  if (hosted > 0) {
    parts.splice(1, 0, `${withThemText(hosted, answer.retired.length, "past")}`);
  }
  return parts.join(" ");
}

/**
 * 0.9.8: what goes, or went, with those named because it runs on one of them (P-247):
 * "With them, 3 items that ran on them were retired." `named` is how many were named
 * and retired, which says "it" or "them".
 */
export function withThemText(hosted: number, named: number, when: "past" | "ahead"): string {
  const them = named === 1 ? "it" : "them";
  if (when === "past") {
    return `With ${them}, ${plural(hosted, "item that ran", "items that ran")} on ${them} ${hosted === 1 ? "was" : "were"} retired.`;
  }
  return `With ${them}, ${plural(hosted, "item that runs", "items that run")} on ${them} will be retired: what runs on it goes with its host.`;
}

/**
 * 0.9.8: the question of a Retire of the rows ticked, once the server's dry run has said
 * what it would do (P-247): how many of those ticked are retired, and what goes with them.
 */
export function retireWillText(kind: RemovalKind, answer: RetiredMany, ticked: number): string {
  const count = answer.retired.length;
  const parts = [
    count === ticked
      ? `${countOf(kind, count)} will be retired.`
      : count > 0
        ? `${count.toLocaleString("en-US")} of the ${countOf(kind, ticked)} ticked will be retired.`
        : `None of the ${countOf(kind, ticked)} ticked can be retired.`,
  ];
  if (answer.already.length > 0) {
    parts.push(`${countOf(kind, answer.already.length)} retired already.`);
  }
  if (answer.refused.length > 0) {
    parts.push(`${countOf(kind, answer.refused.length)} refused:`);
  }
  if (answer.missing.length > 0) {
    parts.push(`${countOf(kind, answer.missing.length)} not found, as deleted since.`);
  }
  return parts.join(" ");
}

/** "What runs on it:", or "The 3 that run on it:", before a list of them. */
export function runOnItLead(count: number): string {
  return count === 1 ? "What runs on it:" : `The ${count.toLocaleString("en-US")} that run on it:`;
}

/**
 * 0.9.8: what the page of an item says before its Retire where something runs on it
 * (P-247): how many go with it, which the list beneath names.
 */
export function goesWithItText(count: number, deeper: boolean): string {
  if (count === 1) return "1 item runs on it, and is retired with it, as its own page retires it:";
  const where = deeper ? "on it, or on what runs on it," : "on it,";
  return `${count.toLocaleString("en-US")} items run ${where} and are retired with it, each as its own page retires it:`;
}

/** 0.9.8: what the page of an item says once it is retired, with what went with it. */
export function itemRetiredText(hosted: number): string {
  if (hosted === 0) return "The item was retired.";
  return `The item was retired, and with it ${plural(hosted, "item that ran", "items that ran")} on it.`;
}

/**
 * What a Delete did, or with a dry run would do, in one sentence. `ticked` is false where
 * nothing was ticked, as on a record's page.
 */
export function deletedText(kind: RemovalKind, answer: DeletedMany, ticked = true): string {
  const parts: string[] = [];
  const count = answer.deleted.length;
  if (answer.dry_run) {
    parts.push(
      count > 0
        ? `${countOf(kind, count)} will be deleted.`
        : `No ${NOUNS[kind][1]} can be deleted.`,
    );
    if (answer.refused.length > 0) {
      parts.push(
        `${countOf(kind, answer.refused.length)} refused, while what depends on each is there:`,
      );
    }
  } else {
    parts.push(
      count > 0 ? `Deleted ${countOf(kind, count)}.` : `No ${NOUNS[kind][1]} were deleted.`,
    );
    if (answer.refused.length > 0) {
      parts.push(refusedLead(kind, answer.refused.length, ticked));
    }
  }
  if (answer.missing.length > 0) {
    parts.push(`${countOf(kind, answer.missing.length)} not found, as deleted since.`);
  }
  return parts.join(" ");
}

/** The question before a Retire of the rows ticked. */
export function retireQuestion(kind: RemovalKind, count: number): string {
  return `Retire ${countOf(kind, count)}?`;
}

/** How many records one request retires or deletes, at most, as the server takes them. */
export const MOST_AT_ONCE = 1000;

/**
 * What is said before any request where more rows are ticked than one request takes: the
 * web does not split a request, so Retire and Delete wait until some are unticked.
 */
export function tooManyText(ticked: number): string | null {
  if (ticked <= MOST_AT_ONCE) return null;
  return `Retire and Delete take at most ${MOST_AT_ONCE.toLocaleString("en-US")} rows at a time, and ${ticked.toLocaleString("en-US")} are ticked: untick some first.`;
}

/** A reason is typed for a deletion: blank, or spaces alone, is none. */
export function reasonGiven(reason: string): boolean {
  return reason.trim() !== "";
}

// --- the records an import made (P-234) ------------------------------------------------

export type CreatedRecord = Schemas["CreatedRecord"];
export type MadeForARow = Schemas["MadeForARow"];

/** The kind of record an import of an entity makes that is retired and deleted at once. */
export function removalKindOf(entity: string): RemovalKind | null {
  if (entity === "items") return "item";
  if (entity === "device_groups") return "device_group";
  return null;
}

const STATE_LABELS: Readonly<Record<CreatedRecord["state"], string>> = {
  active: "Active",
  draft: "Draft",
  retired: "Retired",
  deleted: "Deleted",
};

/** What a record an import made is now, as people read it. */
export function stateLabel(state: CreatedRecord["state"]): string {
  return STATE_LABELS[state] ?? state;
}

/** Whether a row of what an import made is ticked: one of the kind, and still there. */
export function tickable(
  record: Pick<CreatedRecord, "record_type" | "state">,
  kind: RemovalKind | null,
): boolean {
  return kind !== null && record.record_type === kind && record.state !== "deleted";
}

/** The page of a record an import made, or null where it is deleted or has none. */
export function createdPath(
  record: Pick<CreatedRecord, "record_type" | "record_hid" | "state">,
): string | null {
  return record.state === "deleted" ? null : kindPath(record.record_type, record.record_hid);
}
