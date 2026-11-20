// Saving a file the server sends: an export of a grid, of a whole table, or of everything.
//
// The file is fetched like everything else, with the bearer token, and saved from memory:
// there is no cookie for a plain link to the file to be allowed by. It is saved under the
// name the server gave it, which is the product's and the moment's (P-168), or, where the
// answer named none, under a name the page makes alike.

import { useCallback, useState } from "react";
import type { ApiError, Download } from "../api/client";
import { saveFile } from "../components/grid/save";
import { toApiError } from "./hooks";

/**
 * Have the browser save a file the server is sending, under the name it gives, or
 * `fallback` where it gives none. Returns the name it was saved under.
 */
export async function saveDownload(
  fetched: Promise<Download>,
  fallback: string,
  save: (blob: Blob, name: string) => void = saveFile,
): Promise<string> {
  const file = await fetched;
  const name = file.fileName ?? fallback;
  save(file.blob, name);
  return name;
}

/** What became of the last press of one export. */
export type Saved = { working: true } | { name: string } | { error: ApiError };

/** What the page says of an export, by what was pressed: under way, saved, or refused. */
export function savedText(saved: Saved | undefined): string {
  if (!saved) return "";
  if ("working" in saved) return "Exporting…";
  if ("name" in saved) return `Exported to ${saved.name}.`;
  return "";
}

/**
 * What became of the export of `keys` pressed last, with its key: what one place on the
 * page says of the buttons beside it. `saved` holds the one pressed last at its end.
 */
export function latestOf(
  saved: ReadonlyMap<string, Saved>,
  keys: readonly string[],
): { key: string; saved: Saved } | null {
  let latest: { key: string; saved: Saved } | null = null;
  for (const [key, state] of saved) {
    if (keys.includes(key)) latest = { key, saved: state };
  }
  return latest;
}

export interface Saving {
  /** What became of each export pressed, by its key, the one pressed last at the end. */
  saved: ReadonlyMap<string, Saved>;
  /**
   * Fetch a file and save it, under a key that says which button asked for it. A
   * refusal, as a busy server's, is kept under that key, and the same button may be
   * pressed again.
   */
  save: (key: string, fetch: () => Promise<Download>, fallback: string) => Promise<void>;
}

/** Exports pressed on one page, each said beside its own button. */
export function useSaving(): Saving {
  const [saved, setSaved] = useState<ReadonlyMap<string, Saved>>(new Map());
  const save = useCallback(
    async (key: string, fetch: () => Promise<Download>, fallback: string) => {
      const put = (state: Saved, last: boolean) =>
        setSaved((was) => {
          const next = new Map(was);
          // A press moves its key to the end; what comes of it later stays where it is.
          if (last) next.delete(key);
          next.set(key, state);
          return next;
        });
      put({ working: true }, true);
      try {
        put({ name: await saveDownload(fetch(), fallback) }, false);
      } catch (thrown) {
        put({ error: toApiError(thrown) }, false);
      }
    },
    [],
  );
  return { saved, save };
}
