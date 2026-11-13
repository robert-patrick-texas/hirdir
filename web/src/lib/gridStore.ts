// How each reader left each grid: the order, width and visibility of its columns, its
// sort, and the last filter. Kept in localStorage under a key that names the user, so
// two people who share a browser do not inherit each other's layout. Nothing here is
// sent anywhere.

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const VERSION = 1;

export interface ColumnLayout {
  id: string;
  /** In pixels. Left out, the column has its own width. */
  width?: number;
  hide: boolean;
}

export interface SortLayout {
  id: string;
  descending: boolean;
}

export interface GridLayout {
  /** Every column, in the order shown. */
  columns: ColumnLayout[];
  sort: SortLayout[];
  /** The grid's filter model: a filter per column, by column ID. */
  filter: Record<string, unknown>;
  /** What was last typed in the filter box, in the short form. */
  short: string;
  includeArchived: boolean;
  includeDrafts: boolean;
}

/** A column as the page defines it, before the reader changed anything. */
export interface ColumnDefault {
  id: string;
  width?: number;
  hide?: boolean;
}

export function gridKey(userHid: string, grid: string): string {
  return `hirdir.grid.${userHid}.${grid}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Read a stored layout. Anything malformed is no layout, and the defaults stand. */
export function parseLayout(raw: string | null): GridLayout | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(value) || value.v !== VERSION || !Array.isArray(value.columns)) return null;
  const columns: ColumnLayout[] = [];
  for (const entry of value.columns) {
    if (!isRecord(entry) || typeof entry.id !== "string" || entry.id === "") continue;
    const column: ColumnLayout = { id: entry.id, hide: entry.hide === true };
    if (typeof entry.width === "number" && Number.isFinite(entry.width) && entry.width > 0) {
      column.width = Math.round(entry.width);
    }
    columns.push(column);
  }
  const sort: SortLayout[] = [];
  for (const entry of Array.isArray(value.sort) ? value.sort : []) {
    if (isRecord(entry) && typeof entry.id === "string") {
      sort.push({ id: entry.id, descending: entry.descending === true });
    }
  }
  return {
    columns,
    sort,
    filter: isRecord(value.filter) ? value.filter : {},
    short: typeof value.short === "string" ? value.short : "",
    includeArchived: value.includeArchived === true,
    includeDrafts: value.includeDrafts === true,
  };
}

/**
 * Lay a stored layout over the columns a page defines now.
 *
 * A column the page no longer has is dropped, with its sort and its filter. A column the
 * page has gained since is put where the page puts it: after the column it follows there.
 */
export function mergeLayout(
  defaults: readonly ColumnDefault[],
  stored: GridLayout | null,
): GridLayout {
  const fresh = (column: ColumnDefault): ColumnLayout => ({
    id: column.id,
    hide: column.hide === true,
    ...(column.width === undefined ? {} : { width: column.width }),
  });
  if (!stored) {
    return {
      columns: defaults.map(fresh),
      sort: [],
      filter: {},
      short: "",
      includeArchived: false,
      includeDrafts: false,
    };
  }
  const known = new Map(defaults.map((column) => [column.id, column]));
  const columns = stored.columns.filter(
    (column, place) =>
      known.has(column.id) && stored.columns.findIndex((other) => other.id === column.id) === place,
  );
  defaults.forEach((column, place) => {
    if (columns.some((present) => present.id === column.id)) return;
    const before = defaults[place - 1];
    const after = before ? columns.findIndex((present) => present.id === before.id) : -1;
    columns.splice(after + 1, 0, fresh(column));
  });
  const filter: Record<string, unknown> = {};
  for (const [id, model] of Object.entries(stored.filter)) {
    if (known.has(id)) filter[id] = model;
  }
  return {
    columns,
    sort: stored.sort.filter((entry) => known.has(entry.id)),
    filter,
    short: stored.short,
    includeArchived: stored.includeArchived,
    includeDrafts: stored.includeDrafts,
  };
}

/** The layouts of one user. A browser that refuses storage simply remembers nothing. */
export class GridStore {
  private readonly storage: Store;
  private readonly userHid: string;

  constructor(storage: Store, userHid: string) {
    this.storage = storage;
    this.userHid = userHid;
  }

  load(grid: string): GridLayout | null {
    try {
      return parseLayout(this.storage.getItem(gridKey(this.userHid, grid)));
    } catch {
      return null;
    }
  }

  save(grid: string, layout: GridLayout): void {
    try {
      this.storage.setItem(gridKey(this.userHid, grid), JSON.stringify({ v: VERSION, ...layout }));
    } catch {
      // Storage is full or refused: the layout lasts as long as the page does.
    }
  }

  clear(grid: string): void {
    try {
      this.storage.removeItem(gridKey(this.userHid, grid));
    } catch {
      // Nothing could be stored, so nothing is left behind.
    }
  }
}
