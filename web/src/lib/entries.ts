// 0.9.6: what the search of a catalog entry field offers (P-200).

import type { Schemas } from "../api/client";
import type { Option } from "./patch";
import { entryLabel } from "./pick";

type FoundEntry = Pick<
  Schemas["CatalogEntryOut"],
  "hid" | "pid" | "model_name" | "vendor" | "record_status"
>;

/**
 * What a search offers of the entries it found: each but those excluded, as the entry
 * itself for its successor, which the server refuses (P-200), and how many match.
 */
export function offeredEntries(
  page: { items: readonly FoundEntry[]; total: number },
  exclude: readonly string[],
): { options: Array<Option & { draft: boolean }>; total: number } {
  const offered = page.items.filter((entry) => !exclude.includes(entry.hid));
  return {
    options: offered.map((entry) => ({
      value: entry.hid,
      label: entryLabel(entry),
      draft: entry.record_status === "draft",
    })),
    total: page.total - (page.items.length - offered.length),
  };
}
