// The grid of items, of a part of the item list: the items a report counted, or the
// items of one vendor. It is the item list with a filter the page gives, so it is
// sorted, filtered and paged by the server as the item grid is, and copied and exported
// like it: what the file holds is what the grid shows.

import { type ReactNode, useMemo } from "react";
import { api, type Schemas } from "../api";
import { queryBody } from "../lib/gridQuery";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { DataGrid, type GridAction, type GridWithin } from "./grid/DataGrid";
import { itemColumns, itemIsDimmed } from "./grid/itemColumns";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

interface ItemsGridProps {
  /** The name the reader's layout of this grid is remembered under. */
  id: string;
  /** The part of the item list the grid is of. */
  within: GridWithin;
  /** Columns of the item grid to show from the start here, though it hides them. */
  shown?: readonly string[];
  /** Change it to read the rows again. */
  reloadKey?: number;
  actions?: ReadonlyArray<GridAction<Item>>;
  children?: ReactNode;
}

/** The item grid, of the items a page names. */
export function ItemsGrid({
  id,
  within,
  shown = [],
  reloadKey,
  actions,
  children,
}: ItemsGridProps) {
  const choices = useChoices();
  const rules = useRules();
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  const wanted = shown.join(" ");
  const columns = useMemo(() => {
    const show = new Set(wanted.split(" "));
    return itemColumns(choices.data, states).map((column) =>
      show.has(column.id) ? { ...column, hide: false } : column,
    );
  }, [choices.data, states, wanted]);
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
          entity="items"
          columns={columns}
          within={within}
          {...(reloadKey === undefined ? {} : { reloadKey })}
          {...(actions ? { actions } : {})}
          load={(request, signal) =>
            api.request("post", "/api/v1/items/query", { body: queryBody(request), signal })
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
