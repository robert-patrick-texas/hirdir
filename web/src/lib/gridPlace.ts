// 0.9.6: a list keeps its place (P-203). A grid that a person leaves for a record and
// comes back to, by the browser's Back or by a link back to the list, shows the rows it
// was on, scrolled to where it was, with the row that was opened marked. The place is
// kept for the tab, in the browser's session storage, and never in a cookie; a browser
// that refuses the storage still shows the list, from its top. The place is kept with
// what the grid showed, its filter, its sort and its switches: under another, the list
// begins at its top.

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Where a grid was left. */
export interface GridPlace {
  /** What the grid showed: its filter, sort and switches, as `viewText` writes them. */
  view: string;
  /** How far the rows of the grid were scrolled, in pixels. */
  top: number;
  /** How far the page itself was scrolled, in pixels. */
  windowY: number;
  /** The row that was opened, by what the grid knows it by, and where it stood. */
  opened: { id: string; index: number } | null;
}

/** What a grid shows, as one text: two views are the same when their texts are. */
export function viewText(view: unknown): string {
  return JSON.stringify(view, (_key, value: unknown) =>
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(
          Object.entries(value as Record<string, unknown>).sort(([one], [other]) =>
            one.localeCompare(other),
          ),
        )
      : value,
  );
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/** Read a place that was kept. Anything malformed is no place. */
export function parsePlace(raw: string | null): GridPlace | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const { view, top, windowY, opened } = value as Record<string, unknown>;
  if (typeof view !== "string" || count(top) === null || count(windowY) === null) return null;
  let row: GridPlace["opened"] = null;
  if (typeof opened === "object" && opened !== null) {
    const { id, index } = opened as Record<string, unknown>;
    if (typeof id === "string" && count(index) !== null) row = { id, index: index as number };
  }
  return { view, top: top as number, windowY: windowY as number, opened: row };
}

/** The tab's session storage, or nothing when the browser refuses it. */
export function tabStorage(): Store | null {
  try {
    const storage = window.sessionStorage;
    storage.getItem("hirdir.probe");
    return storage;
  } catch {
    return null;
  }
}

/** The places of a person's grids, for this tab. */
export class GridPlaces {
  private readonly storage: Store | null;
  private readonly user: string;

  constructor(storage: Store | null, user: string) {
    this.storage = storage;
    this.user = user;
  }

  private key(grid: string): string {
    return `hirdir.place.${this.user}.${grid}`;
  }

  load(grid: string): GridPlace | null {
    try {
      return parsePlace(this.storage?.getItem(this.key(grid)) ?? null);
    } catch {
      return null;
    }
  }

  save(grid: string, place: GridPlace): void {
    try {
      this.storage?.setItem(this.key(grid), JSON.stringify(place));
    } catch {
      // A full or refused storage keeps no place: the list begins at its top next time.
    }
  }

  clear(grid: string): void {
    try {
      this.storage?.removeItem(this.key(grid));
    } catch {
      // Nothing was kept, or nothing can be.
    }
  }
}

/**
 * The place to go back to, when the grid shows what it showed when it was left: the
 * place kept, or nothing.
 */
export function placeFor(kept: GridPlace | null, view: string): GridPlace | null {
  return kept !== null && kept.view === view ? kept : null;
}
