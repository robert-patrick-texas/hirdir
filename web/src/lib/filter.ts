// The server's filter grammar, as the web UI writes it.
//
// A filter is a tree: a leaf is a condition on one field, a branch joins its parts with
// AND or with OR. The short form, `field:op:value` conditions separated by spaces, is
// read here exactly as the server reads it, so that what is typed in the filter box can
// be joined with the grid's column filters and sent as one tree. The server remains the
// judge of which fields a list allows and which operators a field takes.

export const OPERATORS = [
  "eq",
  "ne",
  "in",
  "empty",
  "contains",
  "prefix",
  "glob",
  "regex",
  "lt",
  "lte",
  "gt",
  "gte",
  "between",
  "has",
  "within",
] as const;
export type Operator = (typeof OPERATORS)[number];

export type Scalar = string | number | boolean;

export interface Condition {
  field: string;
  op: Operator;
  value?: Scalar | Scalar[];
}
export type FilterNode = Condition | { and: FilterNode[] } | { or: FilterNode[] };

/** The kinds of field a list can be filtered by. */
export type Kind =
  | "text"
  | "choice"
  | "reference"
  | "mac"
  | "address"
  | "number"
  | "integer"
  | "date"
  | "timestamp"
  | "boolean"
  | "tags";

const COMPARING = ["eq", "ne", "in", "empty"] as const;
const ORDERING = ["lt", "lte", "gt", "gte", "between"] as const;
const MATCHING = ["contains", "prefix", "glob", "regex"] as const;

/** The operators each kind of field takes, as the server has them. */
export const KINDS: Readonly<Record<Kind, readonly Operator[]>> = {
  text: [...COMPARING, ...MATCHING],
  choice: COMPARING,
  reference: COMPARING,
  mac: [...COMPARING, "contains", "prefix"],
  address: [...COMPARING, "contains", "prefix"],
  number: [...COMPARING, ...ORDERING],
  integer: [...COMPARING, ...ORDERING],
  date: [...COMPARING, ...ORDERING],
  timestamp: [...COMPARING, ...ORDERING],
  boolean: ["eq", "ne", "empty"],
  tags: ["has", "empty"],
};

export function isCondition(node: FilterNode): node is Condition {
  return "field" in node;
}

/**
 * Join filters with AND. Nothing at all is no filter, one part is itself, and a part
 * that is already an AND is taken apart, so the tree stays as shallow as it can be.
 */
export function all(...parts: ReadonlyArray<FilterNode | null | undefined>): FilterNode | null {
  const flat: FilterNode[] = [];
  for (const part of parts) {
    if (!part) continue;
    if ("and" in part) flat.push(...part.and);
    else flat.push(part);
  }
  if (flat.length === 0) return null;
  const [only] = flat;
  return flat.length === 1 && only ? only : { and: flat };
}

/** Join filters with OR. */
export function any(...parts: ReadonlyArray<FilterNode | null | undefined>): FilterNode | null {
  const flat = parts.filter((part): part is FilterNode => Boolean(part));
  if (flat.length === 0) return null;
  const [only] = flat;
  return flat.length === 1 && only ? only : { or: flat };
}

const SHORT = new RegExp(`(?:^|\\s+)([A-Za-z_][A-Za-z0-9_.]*):(${OPERATORS.join("|")}):`, "gi");
// What looks like the start of a condition, whatever stands where the operator should.
const LIKE_A_CONDITION = /(?:^|\s)([A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_]+):/;

export const SHORT_FORM_HELP =
  "The short form is field:op:value, with a space between conditions, as in " +
  "lifecycle_state:in:Test,Prod hostname:prefix:site2-";

export type ShortResult = { ok: true; filter: FilterNode | null } | { ok: false; error: string };

/**
 * Read the short form: `field:op:value` conditions joined by AND.
 *
 * A value runs to the start of the next condition, so it may hold spaces. The values of
 * `in` and `between` are separated by commas. A value that itself holds something shaped
 * like a condition is refused, as the server refuses it: it is far more likely a
 * mistyped operator than a value. Blank text is no filter.
 */
export function parseShort(text: string): ShortResult {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, filter: null };
  const starts = [...trimmed.matchAll(SHORT)];
  const [first] = starts;
  if (first?.index !== 0) return { ok: false, error: SHORT_FORM_HELP };
  const conditions: Condition[] = [];
  for (const [place, match] of starts.entries()) {
    const next = starts[place + 1];
    const end = next ? next.index : trimmed.length;
    const value = trimmed.slice(match.index + match[0].length, end).trim();
    const op = (match[2] ?? "").toLowerCase() as Operator;
    const stray = LIKE_A_CONDITION.exec(value);
    if (stray) {
      return {
        ok: false,
        error: `'${stray[1]}:' is not a condition: the operators are ${OPERATORS.join(", ")}.`,
      };
    }
    conditions.push({
      field: match[1] ?? "",
      op,
      value: op === "in" || op === "between" ? value.split(",").map((part) => part.trim()) : value,
    });
  }
  return { ok: true, filter: all(...conditions) };
}

/**
 * The grid of items with a filter in the short form, as a path of the app. A link names
 * particular items, a model's or an owner's or the ones in a chassis, so it asks for the
 * minor items among them too, which the grid otherwise leaves out.
 */
export function itemsPath(short: string): string {
  return `/items?filter=${encodeURIComponent(short)}&minor=1`;
}

function shortValue(value: Condition["value"]): string {
  if (Array.isArray(value)) return value.map(String).join(",");
  return value === undefined ? "" : String(value);
}

/**
 * Write a filter in the short form, or null when it cannot be: the short form has no
 * OR and no nesting.
 */
export function formatShort(node: FilterNode | null): string | null {
  if (node === null) return "";
  const parts = isCondition(node) ? [node] : "and" in node ? node.and : null;
  if (parts === null) return null;
  const written: string[] = [];
  for (const part of parts) {
    if (!isCondition(part)) return null;
    written.push(`${part.field}:${part.op}:${shortValue(part.value)}`);
  }
  return written.join(" ");
}
