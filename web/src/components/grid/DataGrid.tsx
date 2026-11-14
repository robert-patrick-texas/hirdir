// The one grid, used on every list page.
//
// AG Grid Community shows the rows; the server sorts, filters and pages them. The grid
// asks for a block of rows at a time, with its sort and its column filters, and this
// component turns that into the server's filter grammar. The reader's column layout,
// last filter and switches are remembered in localStorage.
//
// Rows are selected whole: one, a range, several, or all that the filter keeps. "All"
// is never a list of rows: it is shown as a count and sent to the server as the filter.
// Copy and Export are one export of the rows chosen, with the grid's sort and columns:
// to the clipboard as tab-separated text, or to a file.
//
// Content security policy: the grid is run with `theme: "legacy"`, which makes it use
// the stylesheets bundled below and inject no <style> element of its own, so the policy
// needs no style allowance. No string expression is given to the grid anywhere, so it
// never compiles code and needs no script allowance either. See vite.config.ts for the
// font and pictures those stylesheets embed.

import {
  CellStyleModule,
  ColumnApiModule,
  type ColumnState,
  CustomFilterModule,
  createGrid,
  DateFilterModule,
  type GridApi,
  GridStateModule,
  InfiniteRowModelModule,
  ModuleRegistry,
  RowApiModule,
  RowSelectionModule,
  RowStyleModule,
  TextFilterModule,
  TooltipModule,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router";
import { api } from "../../api";
import type { ApiError } from "../../api/client";
import { useAuth } from "../../auth";
import { routerBasename } from "../../lib/base";
import { ClipboardRefused, copyText } from "../../lib/clipboard";
import { all, type FilterNode, parseShort } from "../../lib/filter";
import { plural } from "../../lib/format";
import { gridFilter, gridSort, type ListRequest, sortModelOf } from "../../lib/gridQuery";
import { type GridLayout, GridStore, mergeLayout } from "../../lib/gridStore";
import { toApiError } from "../../lib/hooks";
import { browserStorage } from "../../lib/session";
import {
  type Chosen,
  csvToClipboard,
  type Entity,
  exportColumns,
  exportName,
  exportRequest,
  type FileFormat,
  type GridView,
} from "../../lib/transfer";
import { CheckField, TextField } from "../Field";
import { Notice, Problem } from "../Problem";
import { cellHint, columnDefaults, columnDefs, type GridColumn, queryColumns } from "./columns";
import { saveFile } from "./save";

ModuleRegistry.registerModules([
  InfiniteRowModelModule,
  TextFilterModule,
  DateFilterModule,
  CustomFilterModule,
  RowSelectionModule,
  RowStyleModule,
  CellStyleModule,
  TooltipModule,
  ColumnApiModule,
  GridStateModule,
  // To read the row of the cell that has the focus.
  RowApiModule,
]);

// How many rows the grid asks the server for at a time.
const BLOCK = 100;

export interface Page<T> {
  items: T[];
  total: number;
}

export interface DataGridProps<T> {
  /** The name the reader's layout of this grid is remembered under. */
  id: string;
  /** What a row is, one and many: "item", "items". */
  noun: [one: string, many: string];
  /** The columns. Read when the grid is made: keep the same array between renders. */
  columns: readonly GridColumn<T>[];
  /** Read one page of the list from the server. */
  load: (request: ListRequest, signal: AbortSignal) => Promise<Page<T>>;
  rowId: (row: T) => string;
  /** The page of a row, as a path of the app: `/items/<hid>`. */
  rowLink?: (row: T) => string;
  /** Rows to show greyed: drafts, and retired and archived records. */
  dimmed?: (row: T) => boolean;
  /** Offer a box for the short filter form, with this example of it under the box. */
  shortFilter?: string;
  /** A short filter to start with, as from a link, instead of the one remembered. */
  startFilter?: string | null;
  /** Offer the switches for records a list leaves out by default. */
  switches?: { archived?: string; drafts?: string };
  /**
   * Rows the grid leaves out until a switch is turned on, as the item grid leaves out
   * minor items: the label of the switch, and the filter that leaves them out. While the
   * switch is off that filter is part of every filter sent, so what is copied, exported
   * or edited in bulk is what the grid shows. `start` turns the switch on for this visit,
   * as a link to particular rows does, without changing what is remembered.
   */
  minor?: { label: string; without: FilterNode; start?: boolean };
  /** Change it to read the list again, as after a record was created. */
  reloadKey?: number;
  /** The kind of record the rows are, as an export names it. With it, Copy and Export are offered. */
  entity?: Entity;
  /** Open the form that changes many rows at once. With it, Bulk edit is offered. */
  onBulkEdit?: (rows: Chosen, view: GridView) => void;
  /** More to put in the toolbar, such as the button for a new record. */
  children?: ReactNode;
}

interface View {
  short: string;
  includeArchived: boolean;
  includeDrafts: boolean;
  includeMinor: boolean;
}

function layoutOf(
  state: readonly ColumnState[],
  filter: Record<string, unknown>,
  view: View,
): GridLayout {
  const sorted = state
    .filter((column) => column.sort === "asc" || column.sort === "desc")
    .sort((one, other) => (one.sortIndex ?? 0) - (other.sortIndex ?? 0));
  return {
    columns: state.map((column) => ({
      id: column.colId,
      hide: column.hide === true,
      ...(typeof column.width === "number" ? { width: column.width } : {}),
    })),
    sort: sorted.map((column) => ({ id: column.colId, descending: column.sort === "desc" })),
    filter,
    ...view,
  };
}

export function DataGrid<T>(props: DataGridProps<T>) {
  const { id, noun, columns, shortFilter, switches, reloadKey = 0, children } = props;
  const { entity, onBulkEdit, minor } = props;
  const { user } = useAuth();
  const navigate = useNavigate();
  const host = useRef<HTMLDivElement>(null);
  const store = useMemo(() => new GridStore(browserStorage(), user.hid), [user.hid]);
  const defaults = useMemo(() => columnDefaults(columns), [columns]);
  const query = useMemo(() => queryColumns(columns), [columns]);

  // What the reader left behind, unless a link brought a filter of its own: then that
  // filter is the only one, and the column filters remembered are not put back.
  const [fromLink] = useState(() => (props.startFilter ?? null) !== null);
  const [start] = useState(() => {
    const layout = mergeLayout(defaults, store.load(id));
    return fromLink ? { ...layout, short: props.startFilter ?? "", filter: {} } : layout;
  });
  const [draft, setDraft] = useState(start.short);
  const [short, setShort] = useState(start.short);
  const [shortError, setShortError] = useState("");
  const [includeArchived, setIncludeArchived] = useState(start.includeArchived);
  const [includeDrafts, setIncludeDrafts] = useState(start.includeDrafts);
  const [includeMinor, setIncludeMinor] = useState(start.includeMinor || minor?.start === true);
  // What is remembered of that switch is the reader's own choice, not what a link turned on.
  const minorChosen = useRef(start.includeMinor);
  // What the cell that has the focus has to say: the reasons of a health, a value's source.
  const [note, setNote] = useState("");
  const [grid, setGrid] = useState<GridApi<T> | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(
    () => new Set(start.columns.filter((column) => column.hide).map((column) => column.id)),
  );
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState(0);
  // Every row the filter keeps is chosen, whether the grid has read it or not.
  const [allMatching, setAllMatching] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [turn, setTurn] = useState(0);
  // Copy and Export: which is under way, how it went, and text the clipboard refused.
  const [working, setWorking] = useState<"" | "copy" | FileFormat>("");
  const [done, setDone] = useState("");
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const refusedBox = useRef<HTMLTextAreaElement>(null);

  // Text the clipboard refused is shown selected, ready to be copied by hand.
  useEffect(() => {
    if (refused === null) return;
    refusedBox.current?.focus();
    refusedBox.current?.select();
  }, [refused]);

  /** Remember the layout as the grid has it now, with the filter box and the switches. */
  function saveLayout(api: GridApi<T>, view: View) {
    if (api.isDestroyed()) return;
    store.save(id, layoutOf(api.getColumnState(), api.getFilterModel(), view));
  }

  const read = useEffectEvent(props.load);
  const idOf = useEffectEvent(props.rowId);
  const isDimmed = useEffectEvent((row: T) => props.dimmed?.(row) === true);
  const linkOf = useEffectEvent((row: T) => props.rowLink?.(row) ?? null);
  const open = useEffectEvent((row: T) => {
    const path = linkOf(row);
    if (path !== null) navigate(path);
  });
  const go = useEffectEvent((path: string) => navigate(path));
  const remember = useEffectEvent((api: GridApi<T>) => {
    if (api.isDestroyed()) return;
    const state = api.getColumnState();
    setHidden(new Set(state.filter((column) => column.hide).map((column) => column.colId)));
    saveLayout(api, { short, includeArchived, includeDrafts, includeMinor: minorChosen.current });
  });

  // Make the grid. It is made again only if the page gives it other columns.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const layout = mergeLayout(defaults, store.load(id));
    const base = routerBasename(document.baseURI);
    const api = createGrid<T>(element, {
      theme: "legacy",
      rowModelType: "infinite",
      cacheBlockSize: BLOCK,
      maxBlocksInCache: 20,
      enableFilterHandlers: true,
      columnDefs: columnDefs(columns, layout, {
        href: (row) => {
          const path = linkOf(row);
          return path === null ? null : base + path.replace(/^\/+/, "");
        },
        open,
        hrefOf: (path) => base + path.replace(/^\/+/, ""),
        go,
      }),
      defaultColDef: { resizable: true, sortable: true, minWidth: 60 },
      initialState: { filter: { filterModel: fromLink ? {} : layout.filter } },
      getRowId: (params) => idOf(params.data),
      rowSelection: {
        mode: "multiRow",
        checkboxes: false,
        headerCheckbox: false,
        enableClickSelection: true,
      },
      rowClassRules: { "row-dim": (params) => params.data !== undefined && isDimmed(params.data) },
      suppressDragLeaveHidesColumns: true,
      tooltipShowDelay: 300,
      onSelectionChanged: (event) => {
        const count = event.api.getSelectedNodes().length;
        setSelected(count);
        // Choosing particular rows takes the place of "all that match".
        if (count > 0) setAllMatching(false);
      },
      onSortChanged: (event) => remember(event.api),
      onFilterChanged: (event) => {
        // Another filter keeps other rows: what was chosen under the last one is let go.
        event.api.deselectAll();
        setAllMatching(false);
        remember(event.api);
      },
      onColumnVisible: (event) => remember(event.api),
      onColumnMoved: (event) => {
        if (event.finished) remember(event.api);
      },
      onColumnResized: (event) => {
        if (event.finished) remember(event.api);
      },
      onRowDoubleClicked: (event) => {
        if (event.data) open(event.data);
      },
      onCellKeyDown: (event) => {
        const key = event.event instanceof KeyboardEvent ? event.event.key : "";
        if (key === "Enter" && event.data) open(event.data);
      },
      // What a cell shows on hover it also says when it has the focus, beneath the grid,
      // for whoever moves through the grid with the keyboard.
      onCellFocused: (event) => {
        const colId = typeof event.column === "string" ? event.column : event.column?.getColId();
        const column = columns.find((candidate) => candidate.id === colId);
        const row =
          event.rowIndex === null || event.rowPinned
            ? undefined
            : event.api.getDisplayedRowAtIndex(event.rowIndex)?.data;
        const hint = column && row !== undefined ? cellHint(column, row) : "";
        setNote(column && hint ? `${column.header}: ${hint}` : "");
      },
    });
    setGrid(api);
    return () => {
      setGrid(null);
      api.destroy();
    };
  }, [columns, defaults, store, id, fromLink]);

  // Give the grid its source of rows, and a new one whenever what is asked for changes.
  // A new source empties the grid's cache, so every row on show is read again.
  const parsed = useMemo(() => parseShort(short), [short]);
  const shortNode = parsed.ok ? parsed.filter : null;
  // The filter of the switch that is off. Read when the grid is made, as the columns are.
  const [without] = useState(() => minor?.without ?? null);
  const leftOut = includeMinor ? null : without;
  const wanted = useMemo(
    () => ({ shortNode, leftOut, includeArchived, includeDrafts, reloadKey, turn }),
    [shortNode, leftOut, includeArchived, includeDrafts, reloadKey, turn],
  );
  useEffect(() => {
    if (!grid) return;
    const controller = new AbortController();
    grid.deselectAll();
    setAllMatching(false);
    grid.setGridOption("datasource", {
      getRows: (params) => {
        const request: ListRequest = {
          filter: all(wanted.shortNode, gridFilter(query, params.filterModel), wanted.leftOut),
          sort: gridSort(query, params.sortModel),
          limit: params.endRow - params.startRow,
          offset: params.startRow,
          include_archived: wanted.includeArchived,
          include_drafts: wanted.includeDrafts,
        };
        read(request, controller.signal).then(
          (page) => {
            if (controller.signal.aborted) return;
            setError(null);
            setTotal(page.total);
            params.successCallback(page.items, page.total);
          },
          (thrown: unknown) => {
            if (controller.signal.aborted) return;
            setError(toApiError(thrown));
            setTotal(null);
            params.failCallback();
          },
        );
      },
    });
    return () => controller.abort();
  }, [grid, query, wanted]);

  function showShort(text: string) {
    const result = parseShort(text);
    if (!result.ok) {
      setShortError(result.error);
      return;
    }
    setShortError("");
    setShort(text.trim());
    setDraft(text.trim());
    if (grid) {
      saveLayout(grid, {
        short: text.trim(),
        includeArchived,
        includeDrafts,
        includeMinor: minorChosen.current,
      });
    }
  }

  function submitShort(event: FormEvent) {
    event.preventDefault();
    showShort(draft);
  }

  function setSwitch(which: "includeArchived" | "includeDrafts" | "includeMinor", on: boolean) {
    if (which === "includeArchived") setIncludeArchived(on);
    else if (which === "includeDrafts") setIncludeDrafts(on);
    else {
      setIncludeMinor(on);
      minorChosen.current = on;
    }
    if (!grid) return;
    saveLayout(grid, {
      short,
      includeArchived,
      includeDrafts,
      includeMinor: minorChosen.current,
      [which]: on,
    });
  }

  function showColumn(column: string, on: boolean) {
    // The box follows the click at once; the grid tells of the change a moment later.
    setHidden((was) => {
      const next = new Set(was);
      if (on) next.delete(column);
      else next.add(column);
      return next;
    });
    grid?.setColumnsVisible([column], on);
  }

  function resetLayout() {
    store.clear(id);
    setShortError("");
    setShort("");
    setDraft("");
    setIncludeArchived(false);
    setIncludeDrafts(false);
    setIncludeMinor(false);
    minorChosen.current = false;
    if (!grid) return;
    const first = mergeLayout(defaults, null);
    grid.applyColumnState({
      state: first.columns.map((column) => ({
        colId: column.id,
        hide: column.hide,
        width: column.width ?? null,
        sort: null,
        sortIndex: null,
      })),
      applyOrder: true,
    });
    grid.setFilterModel(null);
    // The grid told of its changes while the box and the switches were still as they
    // were: remember them as they are now.
    saveLayout(grid, {
      short: "",
      includeArchived: false,
      includeDrafts: false,
      includeMinor: false,
    });
  }

  /** What the grid shows now, as the server takes it: the filter, the sort, the switches. */
  function viewOf(api: GridApi<T>): GridView {
    const own = all(shortNode, gridFilter(query, api.getFilterModel()));
    return {
      // The rows a switch leaves out are left out of what is copied, exported and edited too.
      filter: all(own, leftOut),
      sort: gridSort(query, sortModelOf(api.getColumnState())),
      include_archived: includeArchived,
      include_drafts: includeDrafts,
      unfiltered: own === null,
    };
  }

  /** The rows chosen: all that match, as a count, or the ones selected, by HID. */
  function chosenOf(api: GridApi<T>): Chosen | null {
    if (allMatching) return total ? { kind: "all", count: total } : null;
    const hids: string[] = [];
    for (const node of api.getSelectedNodes()) {
      if (node.data !== undefined) hids.push(props.rowId(node.data));
    }
    return hids.length > 0 ? { kind: "rows", hids } : null;
  }

  function selectAllMatching() {
    grid?.deselectAll();
    setAllMatching(true);
  }

  function clearSelection() {
    grid?.deselectAll();
    setAllMatching(false);
  }

  function began(what: "copy" | FileFormat) {
    setWorking(what);
    setDone("");
    setFailure(null);
    setRefused(null);
  }

  /**
   * Put the chosen rows on the clipboard, as tab-separated text with a header row. The
   * text is the CSV export of those rows, so it holds what an exported file holds.
   */
  async function copy() {
    const chosen = grid && entity ? chosenOf(grid) : null;
    if (!grid || !entity || !chosen) return;
    const body = exportRequest(
      entity,
      "csv",
      viewOf(grid),
      exportColumns(columns, grid.getColumnState()),
      chosen,
    );
    began("copy");
    let count = 0;
    const text = api
      .download("/api/v1/exports", { body })
      .then((file) => file.blob.text())
      .then((csv) => {
        const made = csvToClipboard(csv);
        count = made.count;
        return made.text;
      });
    try {
      await copyText(text);
      setDone(`Copied ${plural(count, noun[0], noun[1])} to the clipboard, with a header row.`);
    } catch (thrown) {
      if (thrown instanceof ClipboardRefused) {
        setRefused(thrown.text);
      } else setFailure(toApiError(thrown));
    } finally {
      setWorking("");
    }
  }

  /** Save the chosen rows as a file, or every row the filter keeps when none is chosen. */
  async function exportAs(format: FileFormat) {
    if (!grid || !entity) return;
    const chosen = chosenOf(grid) ?? { kind: "all", count: total ?? 0 };
    const body = exportRequest(
      entity,
      format,
      viewOf(grid),
      exportColumns(columns, grid.getColumnState()),
      chosen,
    );
    began(format);
    try {
      // Fetched like everything else, with the bearer token, and saved from memory:
      // there is no cookie for a plain link to the file to be allowed by.
      const file = await api.download("/api/v1/exports", { body });
      const name = file.fileName ?? exportName(entity, format);
      saveFile(file.blob, name);
      setDone(`Exported to ${name}.`);
    } catch (thrown) {
      setFailure(toApiError(thrown));
    } finally {
      setWorking("");
    }
  }

  const count =
    total === null ? "" : total === 0 ? `No ${noun[1]}` : plural(total, noun[0], noun[1]);
  const some = allMatching || selected > 0;
  const busy = working !== "";

  return (
    <div className="grid-page">
      <div className="grid-tools">
        {shortFilter !== undefined && (
          <form onSubmit={submitShort} className="inline grid-filter">
            <TextField
              label="Filter"
              name="filter"
              type="search"
              value={draft}
              onChange={setDraft}
              autoComplete="off"
              hint={`field:op:value, as in ${shortFilter}`}
              error={shortError || undefined}
            />
            <button type="submit">Apply</button>
            <button type="button" onClick={() => showShort("")} disabled={!short && !draft}>
              Clear
            </button>
          </form>
        )}
        <div className="grid-switches">
          {switches?.archived && (
            <CheckField
              label={switches.archived}
              name="include_archived"
              checked={includeArchived}
              onChange={(on) => setSwitch("includeArchived", on)}
            />
          )}
          {switches?.drafts && (
            <CheckField
              label={switches.drafts}
              name="include_drafts"
              checked={includeDrafts}
              onChange={(on) => setSwitch("includeDrafts", on)}
            />
          )}
          {minor && (
            <CheckField
              label={minor.label}
              name="include_minor"
              checked={includeMinor}
              onChange={(on) => setSwitch("includeMinor", on)}
            />
          )}
          <details className="grid-columns">
            <summary>Columns</summary>
            <div className="grid-columns-menu">
              <fieldset>
                <legend className="visually-hidden">Columns to show</legend>
                {columns.map((column) => (
                  <CheckField
                    key={column.id}
                    label={column.header}
                    name={`show-${column.id}`}
                    checked={!hidden.has(column.id)}
                    disabled={!grid}
                    onChange={(on) => showColumn(column.id, on)}
                  />
                ))}
              </fieldset>
              <button type="button" onClick={resetLayout}>
                Reset layout and filters
              </button>
            </div>
          </details>
        </div>
        {children && <div className="grid-actions">{children}</div>}
      </div>

      <Problem error={error} />
      {error && !error.aborted && (
        <p className="grid-retry">
          <button type="button" onClick={() => setTurn((was) => was + 1)}>
            Try again
          </button>
        </p>
      )}

      <Problem error={failure} />
      <Notice text={done} />
      {refused !== null && (
        <section className="panel" aria-labelledby={`grid-${id}-refused`}>
          <h2 id={`grid-${id}-refused`}>Copy by hand</h2>
          <p>
            The browser did not let this page write to the clipboard. The rows are selected below:
            copy them with Ctrl+C.
          </p>
          <textarea
            ref={refusedBox}
            className="mono grid-copy-text"
            aria-labelledby={`grid-${id}-refused`}
            readOnly
            rows={6}
            value={refused}
            onFocus={(event) => event.target.select()}
          />
          <p className="actions">
            <button type="button" onClick={() => setRefused(null)}>
              Done
            </button>
          </p>
        </section>
      )}

      <div className="grid-selection">
        <p className="grid-status" role="status">
          <span data-testid="grid-total">{count}</span>
          {allMatching && total !== null && (
            <span data-testid="grid-selected">
              {" "}
              · all {plural(total, noun[0], noun[1])} that match the filter selected
            </span>
          )}
          {!allMatching && selected > 0 && (
            <span data-testid="grid-selected"> · {selected} selected</span>
          )}
        </p>
        <fieldset className="grid-selected-actions" disabled={!grid}>
          <legend className="visually-hidden">The selected rows</legend>
          {!allMatching && (
            <button type="button" onClick={selectAllMatching} disabled={!total}>
              Select all that match
            </button>
          )}
          {some && (
            <button type="button" onClick={clearSelection}>
              Clear selection
            </button>
          )}
          {entity && (
            <>
              <button type="button" onClick={copy} disabled={!some || busy}>
                Copy
              </button>
              <button type="button" onClick={() => exportAs("csv")} disabled={!total || busy}>
                Export CSV
              </button>
              <button type="button" onClick={() => exportAs("json")} disabled={!total || busy}>
                Export JSON
              </button>
            </>
          )}
          {onBulkEdit && (
            <button
              type="button"
              disabled={!some || busy}
              onClick={() => {
                const chosen = grid ? chosenOf(grid) : null;
                if (grid && chosen) onBulkEdit(chosen, viewOf(grid));
              }}
            >
              Bulk edit
            </button>
          )}
          {busy && (
            <span role="status" className="muted loading-late">
              Working…
            </span>
          )}
        </fieldset>
      </div>
      <div
        ref={host}
        className={`grid-host ag-theme-quartz${allMatching ? " grid-all" : ""}`}
        data-testid={`grid-${id}`}
      />
      <p className="grid-cell-note" role="status" data-testid="grid-cell-note">
        {note}
      </p>
      <p className="hint">
        Click a heading to sort, and hold Shift to sort by a further column. Click a row to select
        it, with Shift for a range and Ctrl for several. A double click opens the row. With the
        keyboard: Enter on a heading sorts, Ctrl+Enter opens its filter, Space selects a row and
        Enter opens it.
        {entity &&
          " Copy and Export take the selected rows, with the columns on show and hid first. With no row selected, Export takes every row that matches."}
        {minor &&
          ` Until ${minor.label} is on, minor items are left out of the grid, and so of what is copied, exported and edited in bulk.`}
      </p>
    </div>
  );
}
