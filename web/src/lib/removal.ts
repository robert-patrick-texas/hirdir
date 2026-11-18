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

/** What a record in the way is, as people say it: "contract", "purchase line". */
export function dependentKind(dependent: Pick<Dependent, "record_type">): string {
  return DEPENDENT_WORDS[dependent.record_type] ?? dependent.record_type.replaceAll("_", " ");
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

/** What a Retire of several did, in one sentence: "Retired 3 items. 1 was retired already." */
export function retiredText(kind: RemovalKind, answer: RetiredMany): string {
  const parts = [
    answer.retired.length > 0
      ? `Retired ${countOf(kind, answer.retired.length)}.`
      : `No ${NOUNS[kind][1]} were retired.`,
  ];
  if (answer.already.length > 0) {
    parts.push(`${countOf(kind, answer.already.length)} retired already.`);
  }
  if (answer.refused.length > 0) {
    parts.push(`${countOf(kind, answer.refused.length)} refused, still ticked:`);
  }
  if (answer.missing.length > 0) {
    parts.push(`${countOf(kind, answer.missing.length)} not found, as deleted since.`);
  }
  return parts.join(" ");
}

/** What a Delete did, or with a dry run would do, in one sentence. */
export function deletedText(kind: RemovalKind, answer: DeletedMany): string {
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
      parts.push(`${countOf(kind, answer.refused.length)} refused, still ticked:`);
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
