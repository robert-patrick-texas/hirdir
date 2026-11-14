// The grid of items, of a part of the item list: the items a report counted, or the
// items of one vendor. It is the item list with a filter the page gives, so it is
// sorted, filtered and paged by the server as the item grid is, and copied and exported
// like it: what the file holds is what the grid shows.

import { type ReactNode, useMemo } from "react";
import { api, type Schemas } from "../api";
import { type ListRequest, queryBody } from "../lib/gridQuery";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { broughtForward, type GridColumn } from "./grid/columns";
import { DataGrid, type GridAction, type GridWithin, type Page } from "./grid/DataGrid";
import { itemColumns, itemIsDimmed } from "./grid/itemColumns";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

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
  /**
   * Columns that only this grid has, beside those of the item grid: what the page says
   * of each of its items that the item grid has no column for. One that is to stand
   * after the name is named in `shown` too. The list is the same one at every render.
   */
  extra?: ReadonlyArray<GridColumn<Item>>;
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
  children?: ReactNode;
}

/** The item grid, of the items a page names. */
export function ItemsGrid({
  id,
  within,
  shown = [],
  extra,
  reloadKey,
  actions,
  read,
  children,
}: ItemsGridProps) {
  const choices = useChoices();
  const rules = useRules();
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  const wanted = shown.join(" ");
  const sorted = read !== undefined;
  const columns = useMemo(() => {
    const made = broughtForward(
      [...itemColumns(choices.data, states), ...(extra ?? [])],
      wanted.split(" "),
    );
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
  }, [choices.data, states, wanted, sorted, extra]);
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
        >
          {children}
        </DataGrid>
      )}
    </>
  );
}
