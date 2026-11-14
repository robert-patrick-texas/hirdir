import { describe, expect, it } from "vitest";
import { mergeLayout } from "../../lib/gridStore";
import { columnDefaults, columnDefs, type GridColumn, queryColumns } from "./columns";

interface Row {
  name: string;
  value: string | null;
}

const COLUMNS: GridColumn<Row>[] = [
  { id: "name", header: "Name", kind: "text", value: (row) => row.name, link: true, width: 220 },
  {
    id: "effective.est_value",
    header: "Estimated value",
    kind: "number",
    value: (row) => row.value,
    effective: (row) => ({
      value: row.value,
      source: row.value ? "catalog" : "none",
      source_hid: null,
    }),
    numeric: true,
  },
  { id: "ldos", header: "LDoS", kind: "date", field: "effective.ldos", value: () => null },
  {
    id: "state",
    header: "State",
    kind: "choice",
    field: "lifecycle_state",
    value: () => null,
    choices: [{ value: "Prod", label: "Prod" }],
  },
  { id: "kind", header: "Kind", kind: "choice", value: () => null, hide: true },
  { id: "online", header: "Online", kind: "boolean", field: "expected_online", value: () => null },
  { id: "tags", header: "Tags", kind: "tags", value: () => null },
  { id: "aliases", header: "Also known as", kind: "text", field: null, value: () => null },
  {
    id: "is_major",
    header: "Major or minor",
    kind: "boolean",
    value: () => null,
    choices: [
      { value: "true", label: "Major" },
      { value: "false", label: "Minor" },
    ],
  },
  { id: "address", header: "Addresses", kind: "address", sortField: null, value: () => null },
];

const CONTEXT = { href: () => "/items/x", open: () => {} };

function defs(layout = mergeLayout(columnDefaults(COLUMNS), null)) {
  return columnDefs(COLUMNS, layout, CONTEXT);
}

function def(id: string) {
  const found = defs().find((candidate) => candidate.colId === id);
  if (!found) throw new Error(`no column ${id}`);
  return found;
}

function optionKeys(id: string): string[] {
  const options = (
    def(id).filterParams as { filterOptions: Array<string | { displayKey: string }> }
  ).filterOptions;
  return options.map((option) => (typeof option === "string" ? option : option.displayKey));
}

describe("queryColumns", () => {
  it("filters and sorts by the column's ID unless the page names another field", () => {
    const columns = queryColumns(COLUMNS);
    expect(columns.find((column) => column.id === "name")).toEqual({
      id: "name",
      field: "name",
      sortField: "name",
      kind: "text",
    });
    expect(columns.find((column) => column.id === "state")).toMatchObject({
      field: "lifecycle_state",
      sortField: "lifecycle_state",
    });
  });

  it("never sorts by tags, and neither filters nor sorts where the page says the server cannot", () => {
    const columns = queryColumns(COLUMNS);
    expect(columns.find((column) => column.id === "tags")).toMatchObject({
      field: "tags",
      sortField: null,
    });
    expect(columns.find((column) => column.id === "aliases")).toMatchObject({
      field: null,
      sortField: null,
    });
  });
});

describe("columnDefs", () => {
  it("offers a text column the server's own ways of matching text", () => {
    expect(def("name").filter).toBe("agTextColumnFilter");
    expect(optionKeys("name")).toEqual([
      "contains",
      "equals",
      "notEqual",
      "startsWith",
      "glob",
      "regex",
      "blank",
      "notBlank",
    ]);
  });

  it("takes an amount through a text input, so that it is never a JavaScript number", () => {
    expect(def("effective.est_value").filter).toBe("agTextColumnFilter");
    expect(optionKeys("effective.est_value")).toEqual([
      "eq",
      "ne",
      "lt",
      "lte",
      "gt",
      "gte",
      "between",
      "blank",
      "notBlank",
    ]);
  });

  it("gives a date the date filter, and tags the one operator they have", () => {
    expect(def("ldos").filter).toBe("agDateColumnFilter");
    expect(optionKeys("tags")).toEqual(["has", "blank", "notBlank"]);
  });

  it("gives a choice its list to tick from, and plain equality when it has no list", () => {
    expect(typeof (def("state").filter as { component: unknown }).component).toBe("function");
    expect((def("state").filterParams as { options: unknown }).options).toEqual([
      { value: "Prod", label: "Prod" },
    ]);
    expect((def("online").filterParams as { options: unknown[] }).options).toHaveLength(2);
    expect(def("kind").filter).toBe("agTextColumnFilter");
    expect(optionKeys("kind")).toEqual(["equals", "notEqual", "blank", "notBlank"]);
  });

  it("calls true and false by the column's own words, when it has them", () => {
    expect((def("is_major").filterParams as { options: unknown }).options).toEqual([
      { value: "true", label: "Major" },
      { value: "false", label: "Minor" },
    ]);
    expect((def("online").filterParams as { options: unknown }).options).toEqual([
      { value: "true", label: "Yes" },
      { value: "false", label: "No" },
    ]);
  });

  it("matches an address whole or in part, and never by a pattern", () => {
    expect(def("address").filter).toBe("agTextColumnFilter");
    expect(optionKeys("address")).toEqual([
      "contains",
      "equals",
      "notEqual",
      "startsWith",
      "blank",
      "notBlank",
    ]);
    // An item may have several: the server filters by them and does not sort by them.
    expect(def("address").sortable).toBe(false);
  });

  it("has every filter applied with a button, never on each key", () => {
    for (const column of defs()) {
      if (column.filter === false) continue;
      expect((column.filterParams as { buttons: string[] }).buttons, column.colId).toEqual([
        "apply",
        "reset",
      ]);
    }
  });

  it("offers no filter and no sort where the server has none", () => {
    expect(def("aliases").filter).toBe(false);
    expect(def("aliases").sortable).toBe(false);
    expect(def("tags").sortable).toBe(false);
    expect(def("name").sortable).toBe(true);
  });

  it("gives the grid no string to compile: every getter and rule is a function", () => {
    for (const column of defs()) {
      expect(typeof column.valueGetter, column.colId).toBe("function");
      for (const rule of Object.values(column.cellClassRules ?? {})) {
        expect(typeof rule).toBe("function");
      }
    }
  });

  it("marks an inherited value, and names its source on hover", () => {
    const column = def("effective.est_value");
    const rule = column.cellClassRules?.["cell-inherited"];
    const tooltip = column.tooltipValueGetter;
    if (typeof rule !== "function" || typeof tooltip !== "function") {
      throw new Error("the column has no rule or no tooltip");
    }
    type RuleParams = Parameters<typeof rule>[0];
    type TipParams = Parameters<typeof tooltip>[0];
    const inherited = { data: { name: "a", value: "18000.00" } };
    const blank = { data: { name: "b", value: null } };
    expect(rule(inherited as RuleParams)).toBe(true);
    expect(rule(blank as RuleParams)).toBe(false);
    expect(rule({ data: undefined } as RuleParams)).toBe(false);
    expect(tooltip(inherited as TipParams)).toBe("Inherited from the catalog entry");
    expect(tooltip(blank as TipParams)).toBeNull();
  });

  it("lays the columns out as the reader left them", () => {
    const layout = mergeLayout(columnDefaults(COLUMNS), {
      columns: [
        { id: "tags", hide: false, width: 90 },
        { id: "name", hide: true },
      ],
      sort: [
        { id: "ldos", descending: true },
        { id: "name", descending: false },
      ],
      filter: {},
      short: "",
      includeArchived: false,
      includeDrafts: false,
    });
    const laid = defs(layout);
    // The two columns the reader placed keep their order; the rest follow where the page has them.
    expect(laid.map((column) => column.colId)).toEqual([
      "tags",
      "aliases",
      "is_major",
      "address",
      "name",
      "effective.est_value",
      "ldos",
      "state",
      "kind",
      "online",
    ]);
    expect(laid[0]).toMatchObject({ initialWidth: 90, initialHide: false });
    expect(laid[4]).toMatchObject({ initialHide: true, initialSort: "asc", initialSortIndex: 1 });
    expect(laid.find((column) => column.colId === "ldos")).toMatchObject({
      initialSort: "desc",
      initialSortIndex: 0,
    });
    expect(laid.find((column) => column.colId === "kind")).toMatchObject({ initialHide: true });
  });
});
