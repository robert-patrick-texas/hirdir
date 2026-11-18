// The grid of items, of a part of the item list: the items a report counted, or the
// items of one vendor. It is the item list with a filter the page gives, so it is
// sorted, filtered and paged by the server as the item grid is, and copied and exported
// like it: what the file holds is what the grid shows.

import { type ReactNode, useMemo } from "react";
import { api, type Schemas } from "../api";
import { ITEM_MAC_FIELD, ITEM_QUICK_FIELDS } from "../lib/filter";
import { type ListRequest, queryBody } from "../lib/gridQuery";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { broughtForward } from "./grid/columns";
import { DataGrid, type GridAction, type GridWithin, type Page } from "./grid/DataGrid";
import { itemColumns, itemIsDimmed } from "./grid/itemColumns";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

// The example of the short form under the filter box, as the item list has it.
const ITEMS_SHORT_FILTER = "lifecycle_state:in:Test,Prod hostname:prefix:site2-";

interface ItemsGridProps {
  /** The name the reader's layout of this grid is remembered under. */
  id: string;
  /** The part of the item list the grid is of. */
  within: GridWithin;
  /**
   * Columns of the item grid that are what this grid is about: they are shown from the
   * start, though the item grid hides them, and stand right after the name, in this order.
   */
  shown?: readonly string[];
  /** Change it to read the rows again. */
  reloadKey?: number;
  actions?: ReadonlyArray<GridAction<Item>>;
  /**
   * Read the rows from another route than the item list, where the page has no filter
   * to give for them, as a report asked with a filter that is as large as one may be.
   * The grid is then sorted and paged by that route, its columns do not filter, and it
   * is neither copied nor exported: no filter says which rows those would be.
   */
  read?: (request: ListRequest, signal: AbortSignal) => Promise<Page<Item>>;
  /**
   * 0.9.6: the filter box of the item list, with its plain words, which narrows within
   * the part the grid is of (P-211). Not with `read`, whose rows no filter names.
   */
  filterBox?: boolean;
  children?: ReactNode;
}

/** The item grid, of the items a page names. */
export function ItemsGrid({
  id,
  within,
  shown = [],
  reloadKey,
  actions,
  read,
  filterBox = false,
  children,
}: ItemsGridProps) {
  const choices = useChoices();
  const rules = useRules();
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  const wanted = shown.join(" ");
  const sorted = read !== undefined;
  const columns = useMemo(() => {
    const made = broughtForward(itemColumns(choices.data, states), wanted.split(" "));
    if (!sorted) return made;
    // Sorted by the field it has, and filtered by none.
    return made.map((column) => {
      const field = column.field === undefined ? column.id : column.field;
      return {
        ...column,
        field: null,
        sortField: column.sortField === undefined ? field : column.sortField,
      };
    });
  }, [choices.data, states, wanted, sorted]);
  const ready = !choices.loading && !rules.loading;

  return (
    <>
      <Problem error={choices.error ?? rules.error} />
      {!ready && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {ready && (
        <DataGrid<Item>
          id={id}
          noun={["item", "items"]}
          {...(read ? {} : { entity: "items" as const })}
          columns={columns}
          within={within}
          {...(reloadKey === undefined ? {} : { reloadKey })}
          {...(actions ? { actions } : {})}
          load={
            read ??
            ((request, signal) =>
              api.request("post", "/api/v1/items/query", { body: queryBody(request), signal }))
          }
          rowId={(item) => item.hid}
          rowLink={(item) => `/items/${encodeURIComponent(item.hid)}`}
          dimmed={itemIsDimmed}
          {...(filterBox && !read
            ? {
                shortFilter: ITEMS_SHORT_FILTER,
                quickFields: ITEM_QUICK_FIELDS,
                quickMac: ITEM_MAC_FIELD,
              }
            : {})}
        >
          {children}
        </DataGrid>
      )}
    </>
  );
}
