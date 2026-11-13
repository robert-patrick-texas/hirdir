// The one grid, used on every list page.
//
// AG Grid Community shows the rows; the server sorts, filters and pages them. The grid
// asks for a block of rows at a time, with its sort and its column filters, and this
// component turns that into the server's filter grammar. The reader's column layout and
// last filter are remembered in localStorage.
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
import type { ApiError } from "../../api/client";
import { useAuth } from "../../auth";
import { routerBasename } from "../../lib/base";
import { all, parseShort } from "../../lib/filter";
import { plural } from "../../lib/format";
import { gridFilter, gridSort, type ListRequest } from "../../lib/gridQuery";
import { type GridLayout, GridStore, mergeLayout } from "../../lib/gridStore";
import { toApiError } from "../../lib/hooks";
import { browserStorage } from "../../lib/session";
import { CheckField, TextField } from "../Field";
import { Problem } from "../Problem";
import { columnDefaults, columnDefs, type GridColumn, queryColumns } from "./columns";

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
  /** Change it to read the list again, as after a record was created. */
  reloadKey?: number;
  /** More to put in the toolbar, such as the button for a new record. */
  children?: ReactNode;
}

interface View {
  short: string;
  includeArchived: boolean;
  includeDrafts: boolean;
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
  const [grid, setGrid] = useState<GridApi<T> | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(
    () => new Set(start.columns.filter((column) => column.hide).map((column) => column.id)),
  );
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [turn, setTurn] = useState(0);

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
  const remember = useEffectEvent((api: GridApi<T>) => {
    if (api.isDestroyed()) return;
    const state = api.getColumnState();
    setHidden(new Set(state.filter((column) => column.hide).map((column) => column.colId)));
    saveLayout(api, { short, includeArchived, includeDrafts });
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
      onSelectionChanged: (event) => setSelected(event.api.getSelectedNodes().length),
      onSortChanged: (event) => remember(event.api),
      onFilterChanged: (event) => {
        event.api.deselectAll();
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
  const wanted = useMemo(
    () => ({ shortNode, includeArchived, includeDrafts, reloadKey, turn }),
    [shortNode, includeArchived, includeDrafts, reloadKey, turn],
  );
  useEffect(() => {
    if (!grid) return;
    const controller = new AbortController();
    grid.deselectAll();
    grid.setGridOption("datasource", {
      getRows: (params) => {
        const request: ListRequest = {
          filter: all(wanted.shortNode, gridFilter(query, params.filterModel)),
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
    if (grid) saveLayout(grid, { short: text.trim(), includeArchived, includeDrafts });
  }

  function submitShort(event: FormEvent) {
    event.preventDefault();
    showShort(draft);
  }

  function setSwitch(which: "includeArchived" | "includeDrafts", on: boolean) {
    if (which === "includeArchived") setIncludeArchived(on);
    else setIncludeDrafts(on);
    if (grid) saveLayout(grid, { short, includeArchived, includeDrafts, [which]: on });
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
    saveLayout(grid, { short: "", includeArchived: false, includeDrafts: false });
  }

  const count =
    total === null ? "" : total === 0 ? `No ${noun[1]}` : plural(total, noun[0], noun[1]);

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

      <p className="grid-status" role="status">
        <span data-testid="grid-total">{count}</span>
        {selected > 0 && <span data-testid="grid-selected"> · {selected} selected</span>}
      </p>
      <div ref={host} className="grid-host ag-theme-quartz" data-testid={`grid-${id}`} />
      <p className="hint">
        Click a heading to sort, and hold Shift to sort by a further column. Click a row to select
        it, with Shift for a range and Ctrl for several. A double click opens the row. With the
        keyboard: Enter on a heading sorts, Ctrl+Enter opens its filter, Space selects a row and
        Enter opens it.
      </p>
    </div>
  );
}
