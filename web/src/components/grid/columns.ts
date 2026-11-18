// A column as a page describes it, and the same column as AG Grid takes it.

import type { ColDef, ICellRendererParams, IFilterOptionDef } from "ag-grid-community";
import { type Effective, isInherited, sourceHint } from "../../lib/effective";
import type { Kind } from "../../lib/filter";
import type { QueryColumn } from "../../lib/gridQuery";
import type { ColumnDefault, GridLayout } from "../../lib/gridStore";
import { healthTone } from "../../lib/health";
import type { Option } from "../../lib/patch";
import type { ValueLink } from "../../lib/valueLinks";
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
  /**
   * The column of an export that holds this one, or the columns when it shows several.
   * Left out, the ID. Null when none does.
   */
  column?: string | readonly string[] | null;
  /** The text of a cell. */
  value: (row: T) => string | null | undefined;
  /** For a field that inherits: its value in force, to style it and to name its source. */
  effective?: (row: T) => Effective | null | undefined;
  /**
   * For a value that the row has from elsewhere and that comes with no such block, as a
   * coverage has the dates of its contract: true shows the cell in the lighter style of
   * an inherited value. Where it came from is then said by `hint`.
   */
  inherited?: (row: T) => boolean;
  /**
   * For a health: the colour of the mark that stands before the text of the cell, by the
   * name of the health. The text stays, so the colour is never all there is.
   */
  mark?: (row: T) => string | null | undefined;
  /**
   * What more there is to say of a cell, such as the reasons of a health: shown on hover,
   * and beneath the grid when the cell has the focus.
   */
  hint?: (row: T) => string | null | undefined;
  /** Show the cell as the link to its record. */
  link?: boolean;
  /**
   * Show the cell as a link to another record than the row's own, by its path in the
   * app: the item that took the place of the one the row is about.
   */
  linkTo?: (row: T) => string | null | undefined;
  /**
   * For a label that has a colour and a page of its own, as an operator has: the colour
   * of the dot before the text, the page the text leads to, and a word to say after it,
   * such as "open". The text stays, so the colour is never all there is.
   */
  chip?: (row: T) => { colour: string | null; path: string; note?: string } | null | undefined;
  /**
   * 0.9.7: the records the value of the cell names, each a link to its page in the style
   * of the text around it (P-232). Several are parted by commas, as the text of the cell
   * parts them; one with no page stays text. What is copied and exported is unchanged.
   */
  links?: (row: T) => readonly ValueLink[] | null | undefined;
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

/**
 * The page a cell leads to, where it is a link to another record than the row's own: the
 * first of its links. Enter on the cell opens it, as Enter on the name opens the row.
 */
export function cellPath<T>(column: GridColumn<T>, row: T): string | null {
  if (column.links) {
    return column.links(row)?.find((one) => one.text !== "" && one.path)?.path ?? null;
  }
  if (column.linkTo) return column.value(row) ? (column.linkTo(row) ?? null) : null;
  if (column.chip) return column.value(row) ? (column.chip(row)?.path ?? null) : null;
  return null;
}

export function queryColumns<T>(columns: readonly GridColumn<T>[]): QueryColumn[] {
  return columns.map((column) => {
    const field = column.field === undefined ? column.id : column.field;
    const sortField = column.sortField === undefined ? field : column.sortField;
    return {
      id: column.id,
      field,
      sortField,
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

/**
 * The columns of a list for a grid that is about some of them: those are shown, also
 * where the list hides them, and stand right after the first column, in the order they
 * are named, so that they are in view. A name the list does not have is passed over.
 */
export function broughtForward<T>(
  columns: readonly GridColumn<T>[],
  ids: readonly string[],
): GridColumn<T>[] {
  const [first, ...rest] = columns;
  if (!first) return [];
  const forward: GridColumn<T>[] = [];
  const moved = new Set<string>();
  for (const id of ids) {
    const found = rest.find((column) => column.id === id);
    if (!found || moved.has(id)) continue;
    moved.add(id);
    forward.push({ ...found, hide: false });
  }
  return [first, ...forward, ...rest.filter((column) => !moved.has(column.id))];
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
  /** A path of the app as a link's `href`. */
  hrefOf: (path: string) => string;
  /** Go to a path of the app without loading the app again, from the row of the cell. */
  go: (path: string, row?: T) => void;
}

/**
 * A link in a cell. It is reached with the arrow keys and opened with Enter, as every
 * cell of the row is, so it takes no place in the order of Tab. A plain press opens its
 * page within the app; a press with a key held, or with another button, is the
 * browser's, as a new tab. No press on it selects the row (P-232).
 */
function cellLink(href: string, follow: () => void): HTMLAnchorElement {
  const link = document.createElement("a");
  link.href = href;
  link.tabIndex = -1;
  link.addEventListener("click", (event) => {
    event.stopPropagation();
    const plainClick =
      event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
    if (!plainClick) return;
    event.preventDefault();
    follow();
  });
  // A press with the middle button opens a tab, and selects nothing either.
  link.addEventListener("auxclick", (event) => event.stopPropagation());
  return link;
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
    const link = cellLink(href, () => context.open(data));
    // Text from the inventory is put in as text, never as HTML.
    link.textContent = params.value || "(no name)";
    return link;
  };
}

/**
 * A value that names another record than the row's own, as a link to its page in the
 * style of the text around it (P-232).
 */
function valueLink<T>(text: string, path: string, context: ColumnContext<T>, row: T | undefined) {
  const link = cellLink(context.hrefOf(path), () => context.go(path, row));
  link.className = "value-link";
  // Text from the inventory is put in as text, never as HTML.
  link.textContent = text;
  return link;
}

/** A cell that is a link to the page a row names for it, which is not the row's own. */
function pathRenderer<T>(path: (row: T) => string | null | undefined, context: ColumnContext<T>) {
  return (params: ICellRendererParams<T, string>): HTMLElement => {
    const to = params.data ? path(params.data) : null;
    const text = params.value ?? "";
    if (!to || text === "") {
      const plain = document.createElement("span");
      plain.textContent = text;
      return plain;
    }
    return valueLink(text, to, context, params.data);
  };
}

/** A cell of the values that name records, each a link to its page, parted by commas. */
function linksRenderer<T>(
  links: (row: T) => readonly ValueLink[] | null | undefined,
  context: ColumnContext<T>,
) {
  return (params: ICellRendererParams<T, string>): HTMLElement => {
    const cell = document.createElement("span");
    const named = (params.data ? links(params.data) : null)?.filter((one) => one.text !== "");
    if (!named?.some((one) => one.path)) {
      cell.textContent = params.value ?? "";
      return cell;
    }
    named.forEach((one, index) => {
      if (index > 0) cell.append(", ");
      cell.append(one.path ? valueLink(one.text, one.path, context, params.data) : one.text);
    });
    return cell;
  };
}

/**
 * A cell with a mark in the colour of its health before its text. The mark is decoration
 * and hidden from a screen reader: the word beside it says the same.
 */
function markRenderer<T>(mark: (row: T) => string | null | undefined) {
  return (params: ICellRendererParams<T, string>): HTMLElement => {
    const cell = document.createElement("span");
    const text = params.value ?? "";
    if (!params.data || text === "") return cell;
    cell.className = `health health-${healthTone(mark(params.data))}`;
    const dot = document.createElement("span");
    dot.className = "health-dot";
    dot.setAttribute("aria-hidden", "true");
    cell.append(dot, text);
    return cell;
  };
}

/**
 * A cell that shows a label with a dot in its colour before it, as a link to the page of
 * what the label names. The dot is decoration: the label says the same in words.
 */
function chipRenderer<T>(chip: NonNullable<GridColumn<T>["chip"]>, context: ColumnContext<T>) {
  return (params: ICellRendererParams<T, string>): HTMLElement => {
    const cell = document.createElement("span");
    const text = params.value ?? "";
    const about = params.data ? chip(params.data) : null;
    if (text === "" || !about) {
      cell.textContent = text;
      return cell;
    }
    cell.className = "operator-mark";
    const link = cellLink(context.hrefOf(about.path), () => context.go(about.path, params.data));
    link.className = "value-link";
    const dot = document.createElement("span");
    dot.className = "swatch operator-dot";
    dot.setAttribute("aria-hidden", "true");
    if (about.colour) dot.style.backgroundColor = about.colour;
    // Text from the inventory is put in as text, never as HTML.
    link.append(dot, text);
    cell.append(link);
    if (about.note) {
      const note = document.createElement("span");
      note.className = "badge badge-plain mark";
      note.textContent = about.note;
      cell.append(" ", note);
    }
    return cell;
  };
}

/**
 * What more a cell has to say: its own hint, or for an inherited value where it came
 * from. Blank when there is nothing.
 */
export function cellHint<T>(column: GridColumn<T>, row: T): string {
  const own = column.hint?.(row);
  if (own) return own;
  return column.effective ? sourceHint(column.effective(row)) : "";
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
    const { effective, inherited } = column;
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
      ...(effective || inherited
        ? {
            // An inherited value is shown lighter, and says where it came from on hover.
            cellClassRules: {
              "cell-inherited": (params) =>
                params.data !== undefined &&
                (effective
                  ? isInherited(effective(params.data))
                  : inherited?.(params.data) === true),
            },
          }
        : {}),
      ...(effective || column.hint
        ? {
            tooltipValueGetter: (params) =>
              params.data ? cellHint(column, params.data) || null : null,
          }
        : {}),
      ...(column.link ? { cellRenderer: linkRenderer(context) } : {}),
      ...(column.linkTo ? { cellRenderer: pathRenderer(column.linkTo, context) } : {}),
      ...(column.links ? { cellRenderer: linksRenderer(column.links, context) } : {}),
      ...(column.mark ? { cellRenderer: markRenderer(column.mark) } : {}),
      ...(column.chip ? { cellRenderer: chipRenderer(column.chip, context) } : {}),
    });
  }
  return defs;
}
