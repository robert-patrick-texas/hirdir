// From what the grid knows (a filter per column, a sort by one or more columns) to what
// the server takes: one filter tree in its grammar, and a list of field names to sort by.
//
// The grid never filters or sorts a row itself. Its filter models are read here as plain
// data, so this file needs nothing from the grid and can be tested without a browser.

import { all, any, type Condition, type FilterNode, type Kind, type Operator } from "./filter";

/** What the translation needs to know of a column. */
export interface QueryColumn {
  /** The column's ID in the grid. */
  id: string;
  /** The field the server filters by, or null for a column that cannot be filtered. */
  field: string | null;
  /** The field the server sorts by, or null for a column that cannot be sorted. */
  sortField: string | null;
  kind: Kind;
}

/** One condition of the grid's own text and date filters. */
interface SimpleModel {
  filterType?: unknown;
  type?: unknown;
  filter?: unknown;
  filterTo?: unknown;
  dateFrom?: unknown;
  dateTo?: unknown;
}

/** The model of the choice filter: the values ticked, and whether blanks are wanted too. */
export interface ChoiceModel {
  filterType: "choice";
  values: string[];
  blank: boolean;
}

// The names the grid's own filter options go by, and the server's operators.
const OPERATOR_OF: Readonly<Record<string, Operator>> = {
  equals: "eq",
  notEqual: "ne",
  contains: "contains",
  startsWith: "prefix",
  lessThan: "lt",
  lessThanOrEqual: "lte",
  greaterThan: "gt",
  greaterThanOrEqual: "gte",
  inRange: "between",
  // The options this UI adds are named as the server names them.
  eq: "eq",
  ne: "ne",
  prefix: "prefix",
  glob: "glob",
  regex: "regex",
  lt: "lt",
  lte: "lte",
  gt: "gt",
  gte: "gte",
  between: "between",
  has: "has",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * What was typed, as text. Every filter input of this UI is a text input, so that an
 * amount reaches the server digit for digit and never by way of a JavaScript number.
 */
function typed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The day of a date filter's value, `2029-01-01 00:00:00` or `2029-01-01`. */
function day(value: unknown): string {
  const text = typed(value);
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : "";
}

/** The moment a day starts in the reader's own time zone, as the server reads moments. */
export function startOfDay(date: string, plusDays = 0): string {
  const [year = 0, month = 1, dayOfMonth = 1] = date.split("-").map(Number);
  return new Date(year, month - 1, dayOfMonth + plusDays).toISOString();
}

function moments(field: string, type: string, from: string, to: string): FilterNode | null {
  // A timestamp is compared with the reader's own days, as the times on the page are shown.
  const within = (first: string, last: string): FilterNode => ({
    and: [
      { field, op: "gte", value: startOfDay(first) },
      { field, op: "lt", value: startOfDay(last, 1) },
    ],
  });
  if (from === "") return null;
  switch (OPERATOR_OF[type]) {
    case "eq":
      return within(from, from);
    case "ne":
      return {
        or: [
          { field, op: "lt", value: startOfDay(from) },
          { field, op: "gte", value: startOfDay(from, 1) },
          { field, op: "empty", value: true },
        ],
      };
    case "lt":
      return { field, op: "lt", value: startOfDay(from) };
    case "lte":
      return { field, op: "lt", value: startOfDay(from, 1) };
    case "gt":
      return { field, op: "gte", value: startOfDay(from, 1) };
    case "gte":
      return { field, op: "gte", value: startOfDay(from) };
    case "between":
      return to === "" ? null : within(from, to);
    default:
      return null;
  }
}

function simple(column: QueryColumn, field: string, model: SimpleModel): FilterNode | null {
  const type = typeof model.type === "string" ? model.type : "";
  if (type === "blank") return { field, op: "empty", value: true };
  if (type === "notBlank") return { field, op: "empty", value: false };
  const dated = model.filterType === "date";
  const from = dated ? day(model.dateFrom) : typed(model.filter);
  const to = dated ? day(model.dateTo) : typed(model.filterTo);
  if (column.kind === "timestamp") return moments(field, type, from, to);
  const op = OPERATOR_OF[type];
  if (op === undefined || from === "") return null;
  if (op === "between") return to === "" ? null : { field, op, value: [from, to] };
  return { field, op, value: from };
}

function choice(
  column: QueryColumn,
  field: string,
  model: Record<string, unknown>,
): FilterNode | null {
  const values = Array.isArray(model.values)
    ? model.values.filter((value): value is string => typeof value === "string")
    : [];
  const blank: Condition | null = model.blank === true ? { field, op: "empty", value: true } : null;
  let chosen: FilterNode | null = null;
  if (column.kind === "boolean") {
    // A boolean has no `in`: each value ticked is a condition of its own.
    chosen = any(
      ...values
        .filter((value) => value === "true" || value === "false")
        .map((value): Condition => ({ field, op: "eq", value: value === "true" })),
    );
  } else if (values.length === 1) {
    chosen = { field, op: "eq", value: values[0] ?? "" };
  } else if (values.length > 1) {
    chosen = { field, op: "in", value: values };
  }
  return any(chosen, blank);
}

/** The filter one column's model asks for, or null when it asks for nothing. */
export function columnFilter(column: QueryColumn, model: unknown): FilterNode | null {
  const { field } = column;
  if (field === null || !isRecord(model)) return null;
  if (model.filterType === "choice") return choice(column, field, model);
  if (Array.isArray(model.conditions)) {
    // Two or more conditions on one column, joined as the reader chose.
    const parts = model.conditions.map((part) => columnFilter(column, part));
    return model.operator === "OR" ? any(...parts) : all(...parts);
  }
  return simple(column, field, model);
}

/** The filter the whole grid asks for: every column's, joined by AND. */
export function gridFilter(columns: readonly QueryColumn[], model: unknown): FilterNode | null {
  if (!isRecord(model)) return null;
  return all(...columns.map((column) => columnFilter(column, model[column.id])));
}

/** The sort the grid asks for, as the server takes it: `["site", "-effective.ldos"]`. */
export function gridSort(columns: readonly QueryColumn[], model: unknown): string[] {
  const sort: string[] = [];
  if (!Array.isArray(model)) return sort;
  for (const entry of model) {
    if (!isRecord(entry)) continue;
    const column = columns.find((candidate) => candidate.id === entry.colId);
    if (!column || column.sortField === null) continue;
    if (entry.sort !== "asc" && entry.sort !== "desc") continue;
    const name = `${entry.sort === "desc" ? "-" : ""}${column.sortField}`;
    if (!sort.some((present) => present.replace(/^-/, "") === column.sortField)) sort.push(name);
  }
  return sort;
}

/** One page of a list, as every list route takes it. */
export interface ListRequest {
  filter: FilterNode | null;
  sort: string[];
  limit: number;
  offset: number;
  include_archived: boolean;
  include_drafts: boolean;
}

/** A list request as the body of a `POST …/query`. */
export function queryBody(request: ListRequest): {
  filter: Record<string, unknown> | null;
  sort: string[];
  limit: number;
  offset: number;
  include_archived: boolean;
  include_drafts: boolean;
} {
  return { ...request, filter: request.filter as Record<string, unknown> | null };
}

/** A list request as the query of a `GET`, for the lists that take no body. */
export function queryParams(request: ListRequest): {
  filter?: string;
  sort?: string[];
  limit: number;
  offset: number;
  include_archived?: boolean;
  include_drafts?: boolean;
} {
  return {
    ...(request.filter ? { filter: JSON.stringify(request.filter) } : {}),
    ...(request.sort.length > 0 ? { sort: request.sort } : {}),
    limit: request.limit,
    offset: request.offset,
    ...(request.include_archived ? { include_archived: true } : {}),
    ...(request.include_drafts ? { include_drafts: true } : {}),
  };
}
