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

function isNode(value: unknown, depth = 0): value is FilterNode {
  if (typeof value !== "object" || value === null || Array.isArray(value) || depth > 8) {
    return false;
  }
  const node = value as Record<string, unknown>;
  for (const joined of ["and", "or"] as const) {
    if (joined in node) {
      const parts = node[joined];
      return Array.isArray(parts) && parts.every((part) => isNode(part, depth + 1));
    }
  }
  return (
    typeof node.field === "string" &&
    typeof node.op === "string" &&
    (OPERATORS as readonly string[]).includes(node.op)
  );
}

/** The filter a report gives, as a tree: null for none, and for what is no filter. */
export function viewFilter(filter: unknown): FilterNode | null {
  return isNode(filter) ? filter : null;
}

/**
 * Read a filter as a link or the filter box holds it: the short form, or a filter tree
 * written as JSON, which is how a report hands on a filter that the short form cannot
 * say, one with an OR in it. The server remains the judge of the fields and the values.
 */
export function parseFilter(text: string): ShortResult {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) return parseShort(trimmed);
  let value: unknown;
  try {
    value = JSON.parse(trimmed);
  } catch {
    return { ok: false, error: "A filter that begins with { is a filter tree, written as JSON." };
  }
  if (!isNode(value)) {
    return {
      ok: false,
      error:
        'A filter tree is a condition, {"field": "…", "op": "…", "value": "…"}, or {"and": […]} or {"or": […]} of them.',
    };
  }
  return { ok: true, filter: value };
}

/** A tree of ANDs within ANDs as one AND: what the short form can then write. */
function flat(node: FilterNode): FilterNode {
  if (!("and" in node)) return node;
  return all(...node.and.map(flat)) ?? node;
}

/**
 * A filter as text for a link or for the filter box: the short form where it can be
 * written so and reads back as the same conditions, which is easier to read and to
 * change, and otherwise the tree as JSON.
 */
export function filterText(node: FilterNode | null): string {
  if (node === null) return "";
  const plain = flat(node);
  const short = formatShort(plain);
  if (short !== null) {
    const back = parseShort(short);
    if (back.ok && back.filter !== null && asText(back.filter) === asText(plain)) return short;
  }
  return JSON.stringify(node);
}

/** A filter with every value as the short form would hold it, to compare two of them. */
function asText(node: FilterNode): string {
  const parts = isCondition(node) ? [node] : "and" in node ? node.and : [];
  return JSON.stringify(
    parts
      .filter(isCondition)
      .map((part) => [
        part.field,
        part.op,
        Array.isArray(part.value) ? part.value.map(String) : String(part.value ?? ""),
      ]),
  );
}

/** What a report says of a list of items: the filter of the item list, and its switches. */
export interface ItemsView {
  filter?: unknown;
  include_archived?: boolean;
  include_drafts?: boolean;
}

/**
 * The grid of items on the items a report counted, as a path of the app: the filter the
 * report gives for them, with the switches as it says they must be sent. The minor items
 * among them are asked for too: the filter says itself where only major items count.
 */
export function itemsViewPath(view: ItemsView): string {
  const query = new URLSearchParams({ filter: filterText(viewFilter(view.filter)), minor: "1" });
  if (view.include_archived) query.set("archived", "1");
  if (view.include_drafts) query.set("drafts", "1");
  return `/items?${query.toString()}`;
}
