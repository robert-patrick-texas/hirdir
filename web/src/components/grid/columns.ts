// A column as a page describes it, and the same column as AG Grid takes it.

import type { ColDef, ICellRendererParams, IFilterOptionDef } from "ag-grid-community";
import { type Effective, isInherited, sourceHint } from "../../lib/effective";
import type { Kind } from "../../lib/filter";
import type { QueryColumn } from "../../lib/gridQuery";
import type { ColumnDefault, GridLayout } from "../../lib/gridStore";
import type { Option } from "../../lib/patch";
import { ChoiceFilter } from "./choiceFilter";

export interface GridColumn<T> {
  /** The column's ID: the name its layout is remembered under. */
  id: string;
  header: string;
  kind: Kind;
  /** The field the server filters by. Left out, the ID. Null for a column with no filter. */
  field?: string | null;
  /** The field the server sorts by. Left out, the filter's. Null for a column with no sort. */
  sortField?: string | null;
  /** The column of an export that holds this one. Left out, the ID. Null when none does. */
  column?: string | null;
  /** The text of a cell. */
  value: (row: T) => string | null | undefined;
  /** For a field that inherits: its value in force, to style it and to name its source. */
  effective?: (row: T) => Effective | null | undefined;
  /** Show the cell as the link to its record. */
  link?: boolean;
  /**
   * For a choice: the values to offer in the filter. For a boolean: what to call `true`
   * and `false` there, when Yes and No would not say it.
   */
  choices?: readonly Option[];
  width?: number;
  hide?: boolean;
  numeric?: boolean;
  mono?: boolean;
}

export function queryColumns<T>(columns: readonly GridColumn<T>[]): QueryColumn[] {
  return columns.map((column) => {
    const field = column.field === undefined ? column.id : column.field;
    const sortField = column.sortField === undefined ? field : column.sortField;
    return {
      id: column.id,
      field,
      sortField: column.kind === "tags" ? null : sortField,
      kind: column.kind,
    };
  });
}

export function columnDefaults<T>(columns: readonly GridColumn<T>[]): ColumnDefault[] {
  return columns.map((column) => ({
    id: column.id,
    hide: column.hide === true,
    ...(column.width === undefined ? {} : { width: column.width }),
  }));
}

// An option the grid does not have of its own. The grid never runs a filter itself, so
// the option only has to exist, under the name of the server's operator.
function option(displayKey: string, displayName: string, inputs: 1 | 2 = 1): IFilterOptionDef {
  return { displayKey, displayName, predicate: () => true, numberOfInputs: inputs };
}

const BUTTONS = { buttons: ["apply", "reset"], closeOnApply: true } as const;
const BLANKS = ["blank", "notBlank"] as const;
const AMOUNTS = [
  option("eq", "Equals"),
  option("ne", "Does not equal"),
  option("lt", "Less than"),
  option("lte", "Less than or equal to"),
  option("gt", "Greater than"),
  option("gte", "Greater than or equal to"),
  option("between", "Between", 2),
  ...BLANKS,
];

/** The filter of a column, by the kind of field it shows. */
function filterOf<T>(column: GridColumn<T>): Pick<ColDef<T>, "filter" | "filterParams"> {
  const text = (filterOptions: ReadonlyArray<string | IFilterOptionDef>, conditions = 2) => ({
    filter: "agTextColumnFilter",
    filterParams: { ...BUTTONS, filterOptions, maxNumConditions: conditions, trimInput: true },
  });
  switch (column.kind) {
    case "text":
      return text([
        "contains",
        "equals",
        "notEqual",
        "startsWith",
        option("glob", "Matches pattern (* and ?)"),
        option("regex", "Matches regular expression"),
        ...BLANKS,
      ]);
    case "mac":
    case "address":
      return text(["contains", "equals", "notEqual", "startsWith", ...BLANKS]);
    case "number":
    case "integer":
      // A text input, so that an amount is sent as it was typed.
      return text(AMOUNTS);
    case "tags":
      return text([option("has", "Has the tag"), ...BLANKS], 4);
    case "date":
    case "timestamp":
      return {
        filter: "agDateColumnFilter",
        filterParams: {
          ...BUTTONS,
          maxNumConditions: 1,
          filterOptions: [
            "equals",
            "lessThan",
            "lessThanOrEqual",
            "greaterThan",
            "greaterThanOrEqual",
            "inRange",
            ...BLANKS,
          ],
        },
      };
    case "boolean":
      return {
        filter: { component: ChoiceFilter },
        filterParams: {
          ...BUTTONS,
          // Yes and No, unless the column has its own words for true and for false.
          options:
            column.choices ??
            ([
              { value: "true", label: "Yes" },
              { value: "false", label: "No" },
            ] satisfies Option[]),
        },
      };
    default:
      if (column.choices && column.choices.length > 0) {
        return {
          filter: { component: ChoiceFilter },
          filterParams: { ...BUTTONS, options: column.choices },
        };
      }
      return text(["equals", "notEqual", ...BLANKS], 1);
  }
}

export interface ColumnContext<T> {
  /** The address of a row's own page, as a link's `href`. */
  href: (row: T) => string | null;
  /** Go to a row's own page without loading the app again. */
  open: (row: T) => void;
}

function linkRenderer<T>(context: ColumnContext<T>) {
  return (params: ICellRendererParams<T, string>): HTMLElement => {
    const { data } = params;
    const href = data ? context.href(data) : null;
    if (!data || href === null) {
      const plain = document.createElement("span");
      plain.textContent = params.value ?? "";
      return plain;
    }
    const link = document.createElement("a");
    link.href = href;
    // Reached with the arrow keys and opened with Enter, as every cell of the row is.
    link.tabIndex = -1;
    // Text from the inventory is put in as text, never as HTML.
    link.textContent = params.value || "(no name)";
    link.addEventListener("click", (event) => {
      const plainClick =
        event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
      if (!plainClick) return;
      event.preventDefault();
      context.open(data);
    });
    return link;
  };
}

/** The grid's column definitions: the page's columns, laid out as the reader left them. */
export function columnDefs<T>(
  columns: readonly GridColumn<T>[],
  layout: GridLayout,
  context: ColumnContext<T>,
): ColDef<T>[] {
  const sortable = new Map(queryColumns(columns).map((column) => [column.id, column]));
  const defs: ColDef<T>[] = [];
  for (const entry of layout.columns) {
    const column = columns.find((candidate) => candidate.id === entry.id);
    if (!column) continue;
    const query = sortable.get(column.id);
    const sortPlace = layout.sort.findIndex((sorted) => sorted.id === column.id);
    const sorted = layout.sort[sortPlace];
    const { effective } = column;
    const classes = [column.numeric ? "ag-right-aligned-cell" : "", column.mono ? "mono" : ""];
    const width = entry.width ?? column.width;
    defs.push({
      colId: column.id,
      headerName: column.header,
      valueGetter: (params) => (params.data ? (column.value(params.data) ?? "") : ""),
      sortable: query?.sortField !== null && query?.sortField !== undefined,
      ...(query?.field === null || query?.field === undefined
        ? { filter: false }
        : filterOf(column)),
      initialHide: entry.hide,
      ...(width === undefined ? {} : { initialWidth: width }),
      ...(sorted && sortPlace >= 0
        ? { initialSort: sorted.descending ? "desc" : "asc", initialSortIndex: sortPlace }
        : {}),
      cellClass: classes.filter(Boolean),
      ...(column.numeric ? { headerClass: "ag-right-aligned-header" } : {}),
      ...(effective
        ? {
            // An inherited value is shown lighter, and says where it came from on hover.
            cellClassRules: {
              "cell-inherited": (params) =>
                Boolean(params.data) && isInherited(effective(params.data as T)),
            },
            tooltipValueGetter: (params) =>
              params.data ? sourceHint(effective(params.data)) || null : null,
          }
        : {}),
      ...(column.link ? { cellRenderer: linkRenderer(context) } : {}),
    });
  }
  return defs;
}
