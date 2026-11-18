// The one grid, used on every list page.
//
// AG Grid Community shows the rows; the server sorts, filters and pages them. The grid
// asks for a block of rows at a time, with its sort and its column filters, and this
// component turns that into the server's filter grammar. The reader's column layout,
// last filter and switches are remembered in localStorage.
//
// 0.9.6: a list keeps its place (P-203). Where the grid was scrolled to, and the row
// that was opened from it, are kept for the tab in session storage, by the grid's `id`.
// Coming back to the list, by Back or by a link, under the same filter, sort and
// switches, shows the same rows with the row opened marked; a new filter or sort
// begins at the top. A link that brings a filter of its own shows it from the top,
// unless it is the browser's Back that comes to it.
//
// Rows are selected whole: one, a range, several, or all that the filter keeps. "All"
// is never a list of rows: it is shown as a count and sent to the server as the filter.
// 0.9.7: rows are ticked (P-233). A box to each row at the left, and one in the heading
// for every row on show; pressing a row selects it as before, and each button that acts
// on the rows chosen says how many.
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
  EventApiModule,
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
import { NavigationType, useNavigate, useNavigationType } from "react-router";
import { api } from "../../api";
import type { ApiError } from "../../api/client";
import { useAuth } from "../../auth";
import { routerBasename } from "../../lib/base";
import { ClipboardRefused, copyText } from "../../lib/clipboard";
import { all, type FilterNode, fieldsText, parseFilter, type QuickFields } from "../../lib/filter";
import { plural } from "../../lib/format";
import { type GridPlace, GridPlaces, placeFor, tabStorage, viewText } from "../../lib/gridPlace";
import { gridFilter, gridSort, type ListRequest, sortModelOf } from "../../lib/gridQuery";
import { type GridLayout, GridStore, mergeLayout, withoutFilters } from "../../lib/gridStore";
import { toApiError } from "../../lib/hooks";
import { useSite } from "../../lib/product";
import { withCount } from "../../lib/selection";
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
  namesPlaces,
} from "../../lib/transfer";
import { CheckField, TextField } from "../Field";
import { Notice, Problem } from "../Problem";
import {
  cellHint,
  cellPath,
  columnDefaults,
  columnDefs,
  type GridColumn,
  queryColumns,
} from "./columns";
import { saveFile } from "./save";
import { TickHeader, type TickHeaderParams } from "./tickHeader";

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
  // For the box in the heading to hear of the rows read and ticked (P-233).
  EventApiModule,
]);

// How many rows the grid asks the server for at a time.
const BLOCK = 100;

/**
 * The part of a grid whose rows scroll. Rows the grid has not read yet cannot be gone to
 * by their index: the grid is scrolled to where it was, and reads the rows there (P-203).
 */
function scrolledRows(host: HTMLElement | null): HTMLElement | null {
  return host?.querySelector<HTMLElement>(".ag-grid-viewport, .ag-body-viewport") ?? null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

/**
 * What a grid is of, when it is of a part of a list: the items a report counted, the
 * items of a vendor, the coverage of one contract. The filter is part of every filter
 * the grid sends, so what is copied, exported or acted on is what the grid shows; the
 * sort is the order until a header is pressed; and the switches are on whatever the
 * reader's own are, as for a list of covered items that are archived.
 */
export interface GridWithin {
  filter?: FilterNode | null;
  sort?: readonly string[];
  includeArchived?: boolean;
  includeDrafts?: boolean;
}

/** Something a page does with the rows chosen in a grid, offered as a button. */
export interface GridAction<T> {
  label: string;
  /**
   * It takes particular rows, with what the grid read of each, and is not offered for
   * "all that match", of which the grid has read only a part.
   */
  rowsOnly?: boolean;
  /**
   * 0.9.7: what is said, with the button not to be pressed, where more rows are ticked
   * than it takes, as Retire and Delete take 1,000 at most; null where it takes them.
   */
  tooMany?: (ticked: number) => string | null;
  /** `rows` holds what the grid read of the rows chosen: none of them for "all that match". */
  run: (chosen: Chosen, view: GridView, rows: T[]) => void;
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
  /**
   * 0.9.5: the fields a row is known by (P-187). Plain words in the box, with no
   * condition, find the rows where each word is held by one of them.
   */
  quickFields?: readonly string[];
  /** The field of MAC addresses a word that can be one is looked for in too, as an item's. */
  quickMac?: string;
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
  /**
   * 0.9.7: rows to tick again once the list is read again, by their ids, as those that a
   * Retire or a Delete of the rows ticked refused (P-228): once, when the list is read
   * for the `reloadKey` given with them, and not again for another filter.
   */
  tickAfter?: { reload: number; ids: readonly string[] };
  /** The kind of record the rows are, as an export names it. With it, Copy and Export are offered. */
  entity?: Entity;
  /** Open the form that changes many rows at once. With it, Bulk edit is offered. */
  onBulkEdit?: (rows: Chosen, view: GridView) => void;
  /** What else the page does with the rows chosen, each as a button beside Bulk edit. */
  actions?: ReadonlyArray<GridAction<T>>;
  /** The part of the list the grid is of. It may change while the grid is on show. */
  within?: GridWithin;
  /**
   * The switches as a link asks for them, for this visit, instead of the ones
   * remembered: a link to archived items turns Include archived on.
   */
  startSwitches?: { archived?: boolean; drafts?: boolean } | null;
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
  // What words in the box are looked for in, and the example its help gives.
  const quickText = (props.quickFields ?? []).join(" ");
  const { quickMac } = props;
  const quick = useMemo<QuickFields | undefined>(
    () =>
      quickText === ""
        ? undefined
        : {
            fields: quickText.split(" "),
            example: shortFilter ?? "",
            ...(quickMac === undefined ? {} : { mac: quickMac }),
          },
    [quickText, shortFilter, quickMac],
  );
  const { entity, onBulkEdit, minor, actions = [] } = props;
  // The part of the list the grid is of, the same object until what it says changes.
  const withinText = JSON.stringify(props.within ?? {});
  const within = useMemo(() => JSON.parse(withinText) as GridWithin, [withinText]);
  // A grid of one record's part of a list, under the same id on every record's page,
  // remembers no filter: one typed on one record's page is not in force on another's.
  const ofRecord = Boolean(within.filter);
  const { user } = useAuth();
  const { productName } = useSite();
  const navigate = useNavigate();
  const host = useRef<HTMLDivElement>(null);
  const store = useMemo(() => new GridStore(browserStorage(), user.hid), [user.hid]);
  const places = useMemo(() => new GridPlaces(tabStorage(), user.hid), [user.hid]);
  const how = useNavigationType();
  const defaults = useMemo(() => columnDefaults(columns), [columns]);
  const query = useMemo(() => queryColumns(columns), [columns]);

  // What the reader left behind, unless a link brought a filter of its own: then that
  // filter is the only one, and the column filters remembered are not put back.
  const [fromLink] = useState(() => (props.startFilter ?? null) !== null);
  const [start] = useState(() => {
    const merged = mergeLayout(defaults, store.load(id));
    const layout = ofRecord ? withoutFilters(merged) : merged;
    const asked = props.startSwitches;
    const switched = {
      ...layout,
      ...(asked?.archived === undefined ? {} : { includeArchived: asked.archived }),
      ...(asked?.drafts === undefined ? {} : { includeDrafts: asked.drafts }),
    };
    return fromLink ? { ...switched, short: props.startFilter ?? "", filter: {} } : switched;
  });
  // Where the list was left, to go back to (P-203): not when a link brought a filter of
  // its own, unless the browser's Back came to it.
  const kept = useRef<GridPlace | null | undefined>(undefined);
  if (kept.current === undefined) {
    kept.current = fromLink && how !== NavigationType.Pop ? null : places.load(id);
  }
  // The place being gone back to until the rows it is at have been read, the row that
  // was opened and is marked, and what the grid showed when the place was taken.
  const restoring = useRef<GridPlace | null>(null);
  const opened = useRef<{ id: string; index: number } | null>(null);
  // The row opened, until the grid has it and it is drawn marked.
  const marking = useRef<string | null>(null);
  const shownView = useRef<string | null>(null);
  const [draft, setDraft] = useState(start.short);
  const [short, setShort] = useState(start.short);
  // What is wrong with the text in force, from the start: a link or a remembered filter
  // the grid cannot read is said at once, not when Apply is next pressed (P-187).
  const [shortError, setShortError] = useState(() => {
    const read = parseFilter(start.short, quick);
    return read.ok ? "" : read.error;
  });
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
  // The same, as the box in the heading reads it while the grid takes a block of rows.
  const listTotal = useRef<number | null>(null);
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
  // 0.9.7: Copy and Export write each place by its codes, while this is ticked (P-235).
  const [placeCodes, setPlaceCodes] = useState(false);
  const byCode = placeCodes && entity !== undefined && namesPlaces(entity);
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
    const layout = layoutOf(api.getColumnState(), api.getFilterModel(), view);
    store.save(id, ofRecord ? withoutFilters(layout) : layout);
  }

  const read = useEffectEvent(props.load);
  const idOf = useEffectEvent(props.rowId);
  const isDimmed = useEffectEvent((row: T) => props.dimmed?.(row) === true);
  // The reload whose rows to tick were ticked already.
  const tickedFor = useRef<number | null>(null);
  const tickAfter = useEffectEvent((reload: number): readonly string[] => {
    const asked = props.tickAfter;
    if (!asked || asked.reload !== reload || tickedFor.current === reload) return [];
    tickedFor.current = reload;
    return asked.ids;
  });
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

  /** What the grid shows, as the place of the list is kept with it (P-203). */
  const viewNow = useEffectEvent((api: GridApi<T>) =>
    viewText({
      short,
      filter: api.getFilterModel(),
      sort: sortModelOf(api.getColumnState()),
      includeArchived,
      includeDrafts,
      includeMinor,
      within: withinText,
    }),
  );
  /** Keep where the list is now, and the row opened from it, for the tab. */
  const keepPlace = useEffectEvent((api: GridApi<T>) => {
    if (api.isDestroyed() || restoring.current !== null) return;
    places.save(id, {
      view: viewNow(api),
      top: Math.max(0, Math.round(scrolledRows(host.current)?.scrollTop ?? 0)),
      windowY: Math.max(0, Math.round(window.scrollY)),
      opened: opened.current,
    });
  });
  /** A row is being left for: it is the row opened, kept with the place. */
  const leaving = useEffectEvent((api: GridApi<T>, row: T) => {
    if (api.isDestroyed()) return;
    const rowId = idOf(row);
    const index = api.getRowNode(rowId)?.rowIndex;
    opened.current = typeof index === "number" ? { id: rowId, index } : null;
    restoring.current = null;
    keepPlace(api);
  });
  /**
   * Whether the grid now shows something else than it did: then it begins at its top,
   * no row is marked, and the place kept is let go.
   */
  const viewChanged = useEffectEvent((api: GridApi<T>): boolean => {
    const now = viewNow(api);
    if (shownView.current === now) return false;
    shownView.current = now;
    restoring.current = null;
    places.clear(id);
    if (opened.current !== null) {
      opened.current = null;
      api.redrawRows();
    }
    return true;
  });

  // Make the grid. It is made again only if the page gives it other columns.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const merged = mergeLayout(defaults, store.load(id));
    const layout = ofRecord ? withoutFilters(merged) : merged;
    const base = routerBasename(document.baseURI);
    let made: GridApi<T> | null = null;
    const toTop = () => {
      const rows = scrolledRows(element);
      if (rows) rows.scrollTop = 0;
    };
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
        open: (row) => {
          if (made) leaving(made, row);
          open(row);
        },
        hrefOf: (path) => base + path.replace(/^\/+/, ""),
        go: (path, row) => {
          if (made && row !== undefined) leaving(made, row);
          go(path);
        },
      }),
      defaultColDef: { resizable: true, sortable: true, minWidth: 60 },
      initialState: { filter: { filterModel: fromLink ? {} : layout.filter } },
      getRowId: (params) => idOf(params.data),
      rowSelection: {
        mode: "multiRow",
        checkboxes: true,
        // The grid's own box in the heading is for rows it holds whole: this one is drawn
        // by TickHeader, for the rows on show (P-233).
        headerCheckbox: false,
        enableClickSelection: true,
        // A press on a row ticks it or unticks it, and unticks nothing else; Shift still
        // takes the rows between. A press on a link follows it and ticks nothing (0.9.7).
        enableSelectionWithoutKeys: true,
      },
      selectionColumnDef: {
        headerComponent: TickHeader,
        // How many rows the list holds, for the box to know when every one is read.
        headerComponentParams: { total: () => listTotal.current } satisfies TickHeaderParams,
        headerName: "Ticked",
        lockPosition: "left",
        suppressMovable: true,
        suppressHeaderMenuButton: true,
        sortable: false,
        resizable: false,
        width: 44,
        minWidth: 44,
        maxWidth: 44,
      },
      rowClassRules: {
        "row-dim": (params) => params.data !== undefined && isDimmed(params.data),
        // The row that was opened, on coming back to the list (P-203).
        "row-opened": (params) =>
          params.data !== undefined && opened.current?.id === idOf(params.data),
      },
      suppressDragLeaveHidesColumns: true,
      tooltipShowDelay: 300,
      onSelectionChanged: (event) => {
        const count = event.api.getSelectedNodes().length;
        setSelected(count);
        // Choosing particular rows takes the place of "all that match".
        if (count > 0) setAllMatching(false);
      },
      onSortChanged: (event) => {
        if (viewChanged(event.api)) toTop();
        remember(event.api);
      },
      onBodyScrollEnd: (event) => keepPlace(event.api),
      onFilterChanged: (event) => {
        if (viewChanged(event.api)) toTop();
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
        if (!event.data) return;
        leaving(event.api, event.data);
        open(event.data);
      },
      onCellKeyDown: (event) => {
        const key = event.event instanceof KeyboardEvent ? event.event.key : "";
        if (key !== "Enter" || !event.data) return;
        leaving(event.api, event.data);
        // 0.9.7: on a cell whose value names another record, its page (P-232).
        const colId = "column" in event ? event.column.getColId() : null;
        const column = columns.find((one) => one.id === colId);
        const path = column ? cellPath(column, event.data) : null;
        if (path) go(path);
        else open(event.data);
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
    made = api;
    // Back where the list was left, if it shows what it showed then (P-203).
    shownView.current = viewNow(api);
    const back = placeFor(kept.current ?? null, shownView.current);
    restoring.current = back;
    opened.current = back?.opened ?? null;
    setGrid(api);
    return () => {
      setGrid(null);
      api.destroy();
    };
  }, [columns, defaults, store, id, fromLink, ofRecord]);

  // Give the grid its source of rows, and a new one whenever what is asked for changes.
  // A new source empties the grid's cache, so every row on show is read again.
  const parsed = useMemo(() => parseFilter(short, quick), [short, quick]);
  const shortNode = parsed.ok ? parsed.filter : null;
  // While the text in force cannot be read, no row is asked for: not every row under
  // text that was not understood, for a count, a selection or an export to act on.
  const readable = parsed.ok;
  // The filter of the switch that is off. Read when the grid is made, as the columns are.
  const [without] = useState(() => minor?.without ?? null);
  const leftOut = includeMinor ? null : without;
  const wanted = useMemo(
    () => ({
      readable,
      shortNode,
      leftOut,
      includeArchived,
      includeDrafts,
      reloadKey,
      turn,
      within,
    }),
    [readable, shortNode, leftOut, includeArchived, includeDrafts, reloadKey, turn, within],
  );
  useEffect(() => {
    if (!grid) return;
    const controller = new AbortController();
    // The reads under way, each with what tells the grid it ended. The grid reads two
    // blocks at a time at most, and waits for one to end before it reads another: a read
    // that is let go, as when words are typed while the whole list is still being read on
    // a busy server, is ended at once, or the grid would wait for it for ever (P-187).
    const pending = new Set<() => void>();
    grid.deselectAll();
    setAllMatching(false);
    // The rows to tick again as they come, as those a Retire refused (P-228).
    const toTick = new Set(tickAfter(wanted.reloadKey));
    // Another filter or switch: the list begins at its top (P-203).
    const fromTop = viewChanged(grid);
    grid.setGridOption("datasource", {
      getRows: (params) => {
        if (!wanted.readable) {
          setError(null);
          setTotal(0);
          listTotal.current = 0;
          params.successCallback([], 0);
          return;
        }
        const letGo = () => params.failCallback();
        pending.add(letGo);
        const sorted = gridSort(query, params.sortModel);
        const request: ListRequest = {
          filter: all(
            wanted.within.filter,
            wanted.shortNode,
            gridFilter(query, params.filterModel),
            wanted.leftOut,
          ),
          // Until a header is pressed, the order the page gives the part it shows.
          sort: sorted.length > 0 ? sorted : [...(wanted.within.sort ?? [])],
          limit: params.endRow - params.startRow,
          offset: params.startRow,
          include_archived: wanted.includeArchived || wanted.within.includeArchived === true,
          include_drafts: wanted.includeDrafts || wanted.within.includeDrafts === true,
        };
        read(request, controller.signal).then(
          (page) => {
            if (controller.signal.aborted) return;
            pending.delete(letGo);
            setError(null);
            setTotal(page.total);
            listTotal.current = page.total;
            params.successCallback(page.items, page.total);
            if (toTick.size > 0) {
              const nodes = [];
              for (const row of page.items) {
                const rowId = idOf(row);
                const node = toTick.has(rowId) ? grid.getRowNode(rowId) : undefined;
                if (node) nodes.push(node);
                toTick.delete(rowId);
              }
              if (nodes.length > 0) grid.setNodesSelected({ nodes, newValue: true });
            }
            if (params.startRow === 0) arrived(grid, fromTop);
            else if (marking.current !== null) requestAnimationFrame(() => markOpened(grid));
          },
          (thrown: unknown) => {
            if (controller.signal.aborted) return;
            pending.delete(letGo);
            setError(toApiError(thrown));
            setTotal(null);
            params.failCallback();
          },
        );
      },
    });
    return () => {
      controller.abort();
      for (const end of pending) end();
      pending.clear();
    };
  }, [grid, query, wanted]);

  /**
   * The first rows of what is asked for have come: the grid goes back to where the list was
   * left, or to its top for a new filter, once the grid has drawn them.
   */
  const arrived = useEffectEvent((api: GridApi<T>, fromTop: boolean) => {
    const place = restoring.current;
    if (!place && !fromTop) return;
    requestAnimationFrame(() => {
      if (api.isDestroyed()) return;
      const rows = scrolledRows(host.current);
      if (!place) {
        if (rows) rows.scrollTop = 0;
        return;
      }
      if (restoring.current !== place) return;
      if (rows) rows.scrollTop = place.top;
      window.scrollTo(0, place.windowY);
      restoring.current = null;
      if (place.opened) {
        setNote("Back where the list was left.");
        marking.current = place.opened.id;
        markOpened(api);
      }
    });
  });

  /**
   * The row opened last, once the grid has it: drawn again with its mark, and only then
   * said to be marked. Its rows may come after the first, as the grid reads them.
   */
  const markOpened = useEffectEvent((api: GridApi<T>) => {
    const rowId = marking.current;
    if (rowId === null || api.isDestroyed()) return;
    if (opened.current?.id !== rowId) {
      marking.current = null;
      return;
    }
    const node = api.getRowNode(rowId);
    if (!node || node.data === undefined) return;
    marking.current = null;
    api.redrawRows({ rowNodes: [node] });
    setNote("Back where the list was left. The row opened last is marked.");
  });

  function showShort(text: string) {
    const result = parseFilter(text, quick);
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
    const sorted = gridSort(query, sortModelOf(api.getColumnState()));
    return {
      // The rows a switch leaves out are left out of what is copied, exported and edited
      // too, and so is everything outside the part of the list the grid is of.
      filter: all(within.filter, own, leftOut),
      sort: sorted.length > 0 ? sorted : [...(within.sort ?? [])],
      include_archived: includeArchived || within.includeArchived === true,
      include_drafts: includeDrafts || within.includeDrafts === true,
      unfiltered: own === null && !within.filter,
    };
  }

  /** What the grid read of the rows that are selected. */
  function rowsOf(api: GridApi<T>): T[] {
    const rows: T[] = [];
    for (const node of api.getSelectedNodes()) {
      if (node.data !== undefined) rows.push(node.data);
    }
    return rows;
  }

  /** The rows chosen: all that match, as a count, or the ones selected, by HID. */
  function chosenOf(api: GridApi<T>): Chosen | null {
    if (!readable) return null;
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
    const chosen = grid && entity && readable ? chosenOf(grid) : null;
    if (!grid || !entity || !chosen) return;
    const body = exportRequest(
      entity,
      "csv",
      viewOf(grid),
      exportColumns(columns, grid.getColumnState()),
      chosen,
      byCode,
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
    if (!grid || !entity || !readable) return;
    const chosen = chosenOf(grid) ?? { kind: "all", count: total ?? 0 };
    const body = exportRequest(
      entity,
      format,
      viewOf(grid),
      exportColumns(columns, grid.getColumnState()),
      chosen,
      byCode,
    );
    began(format);
    try {
      // Fetched like everything else, with the bearer token, and saved from memory:
      // there is no cookie for a plain link to the file to be allowed by.
      const file = await api.download("/api/v1/exports", { body });
      const name = file.fileName ?? exportName(entity, format, productName);
      saveFile(file.blob, name);
      setDone(`Exported to ${name}.`);
    } catch (thrown) {
      setFailure(toApiError(thrown));
    } finally {
      setWorking("");
    }
  }

  const count = !readable
    ? `No ${noun[1]} are shown: the filter in force cannot be read`
    : total === null
      ? ""
      : total === 0
        ? `No ${noun[1]}`
        : plural(total, noun[0], noun[1]);
  const some = allMatching || selected > 0;
  const busy = working !== "";
  // How many rows each button acts on, as it says (P-233).
  const chosenCount = { ticked: selected, allMatching, total };
  // What the buttons that take fewer rows than are ticked say of it, each once.
  const tooMany = allMatching
    ? []
    : [
        ...new Set(
          actions
            .map((action) => action.tooMany?.(selected) ?? null)
            .filter((text): text is string => text !== null),
        ),
      ];

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
              hint={
                quick
                  ? `Words find ${noun[1]} by their ${fieldsText(quick.fields)}. Or field:op:value, as in ${shortFilter}. A filter tree as JSON is taken too.`
                  : `field:op:value, as in ${shortFilter}. A filter tree as JSON is taken too.`
              }
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
                {withCount("Copy", chosenCount)}
              </button>
              <button type="button" onClick={() => exportAs("csv")} disabled={!total || busy}>
                {withCount("Export CSV", chosenCount)}
              </button>
              <button type="button" onClick={() => exportAs("json")} disabled={!total || busy}>
                {withCount("Export JSON", chosenCount)}
              </button>
              {namesPlaces(entity) && (
                <CheckField
                  label="Places by code"
                  name="place_codes"
                  checked={placeCodes}
                  onChange={setPlaceCodes}
                  disabled={busy}
                />
              )}
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
              {withCount("Bulk edit", chosenCount)}
            </button>
          )}
          {actions.map((action) => (
            <button
              type="button"
              key={action.label}
              disabled={
                !some ||
                busy ||
                (action.rowsOnly === true && allMatching) ||
                (!allMatching && (action.tooMany?.(selected) ?? null) !== null)
              }
              title={
                action.rowsOnly && allMatching
                  ? "Select the rows themselves: this takes particular rows."
                  : undefined
              }
              onClick={() => {
                const chosen = grid ? chosenOf(grid) : null;
                if (grid && chosen) action.run(chosen, viewOf(grid), rowsOf(grid));
              }}
            >
              {withCount(action.label, chosenCount, action.rowsOnly === true)}
            </button>
          ))}
          {busy && (
            <span role="status" className="muted loading-late">
              Working…
            </span>
          )}
          {tooMany.map((text) => (
            <p key={text} className="hint grid-too-many" data-testid="grid-too-many">
              {text}
            </p>
          ))}
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
        Click a heading to sort, and hold Shift to sort by a further column. Click a row, or the box
        at its left, to tick it or untick it: the other rows stay as they are. Shift with a click
        ticks the rows between. A click on a link follows it and ticks nothing. The box in the
        heading ticks the rows read so far, and clears them. A double click opens the row. With the
        keyboard: Enter on a heading sorts, Ctrl+Enter opens its filter, Space selects a row and
        Enter opens it.
        {entity &&
          " Copy and Export take the selected rows, with the columns on show and hid first. With no row selected, Export takes every row that matches."}
        {entity &&
          namesPlaces(entity) &&
          " With Places by code they write each place the short way, by the codes of its site and its own, as S2 > R102, which loads back to the same place."}
        {minor &&
          ` Until ${minor.label} is on, minor items are left out of the grid, and so of what is copied, exported and edited in bulk.`}
      </p>
    </div>
  );
}
