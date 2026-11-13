import { describe, expect, it } from "vitest";
import {
  columnFilter,
  gridFilter,
  gridSort,
  type ListRequest,
  type QueryColumn,
  queryBody,
  queryParams,
  startOfDay,
} from "./gridQuery";

function column(id: string, kind: QueryColumn["kind"], more: Partial<QueryColumn> = {}) {
  return { id, field: id, sortField: id, kind, ...more };
}

const NAME = column("name", "text");
const VALUE = column("effective.est_value", "number");
const LDOS = column("effective.ldos", "date");
const CHANGED = column("updated_at", "timestamp");
const STATE = column("lifecycle_state", "choice");
const ONLINE = column("expected_online", "boolean");
const TAGS = column("tags", "tags", { sortField: null });
const ALIASES = column("aliases", "text", { field: null, sortField: null });
const COLUMNS = [NAME, VALUE, LDOS, CHANGED, STATE, ONLINE, TAGS, ALIASES];

describe("columnFilter: text", () => {
  it("turns the grid's options into the server's operators", () => {
    const of = (type: string) => columnFilter(NAME, { filterType: "text", type, filter: "site2" });
    expect(of("contains")).toEqual({ field: "name", op: "contains", value: "site2" });
    expect(of("equals")).toEqual({ field: "name", op: "eq", value: "site2" });
    expect(of("notEqual")).toEqual({ field: "name", op: "ne", value: "site2" });
    expect(of("startsWith")).toEqual({ field: "name", op: "prefix", value: "site2" });
    expect(of("glob")).toEqual({ field: "name", op: "glob", value: "site2" });
    expect(of("regex")).toEqual({ field: "name", op: "regex", value: "site2" });
  });

  it("turns blank and not blank into empty", () => {
    expect(columnFilter(NAME, { filterType: "text", type: "blank" })).toEqual({
      field: "name",
      op: "empty",
      value: true,
    });
    expect(columnFilter(NAME, { filterType: "text", type: "notBlank" })).toEqual({
      field: "name",
      op: "empty",
      value: false,
    });
  });

  it("asks for nothing when nothing was typed, or the option is not one it knows", () => {
    expect(columnFilter(NAME, { filterType: "text", type: "contains", filter: "  " })).toBeNull();
    expect(columnFilter(NAME, { filterType: "text", type: "contains" })).toBeNull();
    expect(columnFilter(NAME, { filterType: "text", type: "endsWith", filter: "x" })).toBeNull();
    expect(columnFilter(NAME, null)).toBeNull();
    expect(columnFilter(NAME, "site2")).toBeNull();
  });

  it("joins two conditions on one column as the reader chose", () => {
    const conditions = [
      { filterType: "text", type: "startsWith", filter: "site2-" },
      { filterType: "text", type: "regex", filter: "-0[12]$" },
    ];
    expect(columnFilter(NAME, { filterType: "text", operator: "AND", conditions })).toEqual({
      and: [
        { field: "name", op: "prefix", value: "site2-" },
        { field: "name", op: "regex", value: "-0[12]$" },
      ],
    });
    expect(columnFilter(NAME, { filterType: "text", operator: "OR", conditions })).toEqual({
      or: [
        { field: "name", op: "prefix", value: "site2-" },
        { field: "name", op: "regex", value: "-0[12]$" },
      ],
    });
  });

  it("uses the tag operator on a tags column", () => {
    expect(columnFilter(TAGS, { filterType: "text", type: "has", filter: "core" })).toEqual({
      field: "tags",
      op: "has",
      value: "core",
    });
  });

  it("asks for nothing on a column the server cannot filter by", () => {
    expect(columnFilter(ALIASES, { filterType: "text", type: "contains", filter: "x" })).toBeNull();
  });
});

describe("columnFilter: amounts", () => {
  it("sends an amount as the text that was typed", () => {
    const filter = columnFilter(VALUE, { filterType: "text", type: "gte", filter: "18000.50" });
    expect(filter).toEqual({ field: "effective.est_value", op: "gte", value: "18000.50" });
    // Text all the way: 0.1 + 0.2 is not what was typed, and neither is 1e21.
    expect(
      columnFilter(VALUE, { filterType: "text", type: "eq", filter: "1000000000000000000000.10" }),
    ).toEqual({ field: "effective.est_value", op: "eq", value: "1000000000000000000000.10" });
  });

  it("does not take a JavaScript number for one", () => {
    expect(
      columnFilter(VALUE, { filterType: "number", type: "equals", filter: 18000.5 }),
    ).toBeNull();
  });

  it("sends between as two values, and nothing until both are there", () => {
    expect(
      columnFilter(VALUE, {
        filterType: "text",
        type: "between",
        filter: "15000",
        filterTo: "18000",
      }),
    ).toEqual({ field: "effective.est_value", op: "between", value: ["15000", "18000"] });
    expect(
      columnFilter(VALUE, { filterType: "text", type: "between", filter: "15000", filterTo: "" }),
    ).toBeNull();
  });
});

describe("columnFilter: dates", () => {
  const dated = (type: string, dateFrom: string | null, dateTo: string | null = null) => ({
    filterType: "date",
    type,
    dateFrom,
    dateTo,
  });

  it("compares a date with the day alone", () => {
    expect(columnFilter(LDOS, dated("lessThan", "2029-01-01 00:00:00"))).toEqual({
      field: "effective.ldos",
      op: "lt",
      value: "2029-01-01",
    });
    expect(columnFilter(LDOS, dated("equals", "2034-04-30 00:00:00"))).toEqual({
      field: "effective.ldos",
      op: "eq",
      value: "2034-04-30",
    });
    expect(columnFilter(LDOS, dated("greaterThanOrEqual", "2030-06-01"))).toEqual({
      field: "effective.ldos",
      op: "gte",
      value: "2030-06-01",
    });
  });

  it("sends a range as between, both days included", () => {
    expect(
      columnFilter(LDOS, dated("inRange", "2030-01-01 00:00:00", "2030-12-31 00:00:00")),
    ).toEqual({ field: "effective.ldos", op: "between", value: ["2030-01-01", "2030-12-31"] });
    expect(columnFilter(LDOS, dated("inRange", "2030-01-01 00:00:00"))).toBeNull();
  });

  it("asks for nothing without a day, and handles blank", () => {
    expect(columnFilter(LDOS, dated("lessThan", null))).toBeNull();
    expect(columnFilter(LDOS, dated("lessThan", "soon"))).toBeNull();
    expect(columnFilter(LDOS, dated("blank", null))).toEqual({
      field: "effective.ldos",
      op: "empty",
      value: true,
    });
  });

  it("compares a moment with the reader's own days", () => {
    const start = startOfDay("2026-03-01");
    const next = startOfDay("2026-03-01", 1);
    expect(start).toBe(new Date(2026, 2, 1).toISOString());
    expect(next).toBe(new Date(2026, 2, 2).toISOString());
    expect(columnFilter(CHANGED, dated("equals", "2026-03-01 00:00:00"))).toEqual({
      and: [
        { field: "updated_at", op: "gte", value: start },
        { field: "updated_at", op: "lt", value: next },
      ],
    });
    expect(columnFilter(CHANGED, dated("lessThan", "2026-03-01 00:00:00"))).toEqual({
      field: "updated_at",
      op: "lt",
      value: start,
    });
    expect(columnFilter(CHANGED, dated("greaterThan", "2026-03-01 00:00:00"))).toEqual({
      field: "updated_at",
      op: "gte",
      value: next,
    });
    expect(columnFilter(CHANGED, dated("inRange", "2026-03-01", "2026-03-31"))).toEqual({
      and: [
        { field: "updated_at", op: "gte", value: start },
        { field: "updated_at", op: "lt", value: startOfDay("2026-03-31", 1) },
      ],
    });
  });
});

describe("columnFilter: choices", () => {
  const chosen = (values: string[], blank = false) => ({ filterType: "choice", values, blank });

  it("is eq for one value and in for several", () => {
    expect(columnFilter(STATE, chosen(["Prod"]))).toEqual({
      field: "lifecycle_state",
      op: "eq",
      value: "Prod",
    });
    expect(columnFilter(STATE, chosen(["Test", "Prod"]))).toEqual({
      field: "lifecycle_state",
      op: "in",
      value: ["Test", "Prod"],
    });
  });

  it("adds the blanks with OR when they are wanted too", () => {
    expect(columnFilter(STATE, chosen(["Prod"], true))).toEqual({
      or: [
        { field: "lifecycle_state", op: "eq", value: "Prod" },
        { field: "lifecycle_state", op: "empty", value: true },
      ],
    });
    expect(columnFilter(STATE, chosen([], true))).toEqual({
      field: "lifecycle_state",
      op: "empty",
      value: true,
    });
    expect(columnFilter(STATE, chosen([]))).toBeNull();
  });

  it("compares a boolean with true or false, never with in", () => {
    expect(columnFilter(ONLINE, chosen(["true"]))).toEqual({
      field: "expected_online",
      op: "eq",
      value: true,
    });
    expect(columnFilter(ONLINE, chosen(["true", "false"]))).toEqual({
      or: [
        { field: "expected_online", op: "eq", value: true },
        { field: "expected_online", op: "eq", value: false },
      ],
    });
    expect(columnFilter(ONLINE, chosen(["maybe"]))).toBeNull();
  });
});

describe("gridFilter", () => {
  it("joins the filters of every column with AND", () => {
    const model = {
      name: { filterType: "text", type: "contains", filter: "site2" },
      lifecycle_state: { filterType: "choice", values: ["Test", "Prod"], blank: false },
      "effective.ldos": { filterType: "date", type: "lessThan", dateFrom: "2029-01-01 00:00:00" },
    };
    expect(gridFilter(COLUMNS, model)).toEqual({
      and: [
        { field: "name", op: "contains", value: "site2" },
        { field: "effective.ldos", op: "lt", value: "2029-01-01" },
        { field: "lifecycle_state", op: "in", value: ["Test", "Prod"] },
      ],
    });
  });

  it("is the one condition itself when one column filters, and nothing when none does", () => {
    expect(gridFilter(COLUMNS, { name: { filterType: "text", type: "blank" } })).toEqual({
      field: "name",
      op: "empty",
      value: true,
    });
    expect(gridFilter(COLUMNS, {})).toBeNull();
    expect(gridFilter(COLUMNS, null)).toBeNull();
  });

  it("ignores a model for a column the page no longer has", () => {
    expect(gridFilter(COLUMNS, { gone: { filterType: "text", type: "blank" } })).toBeNull();
  });
});

describe("gridSort", () => {
  it("writes the sort as field names, with a minus for descending, in the order chosen", () => {
    expect(
      gridSort(COLUMNS, [
        { colId: "effective.ldos", sort: "desc" },
        { colId: "name", sort: "asc" },
      ]),
    ).toEqual(["-effective.ldos", "name"]);
  });

  it("sorts by the field the server knows the column by", () => {
    const owner = column("owner", "text", { field: "owner.label", sortField: "owner.label" });
    expect(gridSort([owner], [{ colId: "owner", sort: "asc" }])).toEqual(["owner.label"]);
  });

  it("leaves out a column that cannot be sorted, an unknown one, and a repeat", () => {
    expect(
      gridSort(COLUMNS, [
        { colId: "tags", sort: "asc" },
        { colId: "gone", sort: "asc" },
        { colId: "name", sort: null },
        { colId: "name", sort: "desc" },
        { colId: "name", sort: "asc" },
      ]),
    ).toEqual(["-name"]);
    expect(gridSort(COLUMNS, undefined)).toEqual([]);
  });
});

describe("the request", () => {
  const request: ListRequest = {
    filter: { field: "name", op: "prefix", value: "site2-" },
    sort: ["catalog.vendor", "-serial_number"],
    limit: 100,
    offset: 200,
    include_archived: true,
    include_drafts: false,
  };

  it("goes whole into the body of a query", () => {
    expect(queryBody(request)).toEqual(request);
    expect(queryBody({ ...request, filter: null }).filter).toBeNull();
  });

  it("goes into a URL with the filter as JSON, and without what is not asked for", () => {
    expect(queryParams(request)).toEqual({
      filter: '{"field":"name","op":"prefix","value":"site2-"}',
      sort: ["catalog.vendor", "-serial_number"],
      limit: 100,
      offset: 200,
      include_archived: true,
    });
    expect(queryParams({ ...request, filter: null, sort: [], include_archived: false })).toEqual({
      limit: 100,
      offset: 200,
    });
  });
});
