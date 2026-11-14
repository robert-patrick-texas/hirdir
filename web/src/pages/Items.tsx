import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { BulkEdit } from "../components/BulkEdit";
import { DataGrid } from "../components/grid/DataGrid";
import { itemColumns, itemIsDimmed, MAJOR_ITEMS } from "../components/grid/itemColumns";
import { NewItem } from "../components/NewItem";
import { Problem } from "../components/Problem";
import { queryBody } from "../lib/gridQuery";
import { useTitle } from "../lib/hooks";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { allows } from "../lib/roles";
import type { Chosen, GridView } from "../lib/transfer";

type Item = Schemas["ItemOut"];

/**
 * Items: the main grid, the filter box, and the form for a new item. The grid leaves
 * minor items out until Include minor items is turned on.
 */
export function Items() {
  useTitle("Items");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  // A link to particular items asks for the minor items among them too.
  const withMinor = params.get("minor") === "1";
  const [adding, setAdding] = useState(false);
  // The rows a bulk edit is for, as they were chosen when its form was opened.
  const [bulk, setBulk] = useState<{ rows: Chosen; view: GridView; turn: number } | null>(null);
  const [bulkTurn, setBulkTurn] = useState(0);
  const [reloads, setReloads] = useState(0);
  const mayChange = allows(user.role, "inventory");
  const choices = useChoices();
  const rules = useRules();
  const ready = !choices.loading && !rules.loading;
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  const columns = useMemo(() => itemColumns(choices.data, states), [choices.data, states]);

  return (
    <>
      <h1>Items</h1>
      <Problem error={choices.error ?? rules.error} />
      {adding && (
        <NewItem
          states={states}
          onCancel={() => setAdding(false)}
          onCreated={(item) => navigate(`/items/${encodeURIComponent(item.hid)}`)}
        />
      )}
      {bulk && (
        <BulkEdit
          key={bulk.turn}
          rows={bulk.rows}
          view={bulk.view}
          states={states}
          choices={choices.data}
          onApplied={() => setReloads((count) => count + 1)}
          onClose={() => setBulk(null)}
        />
      )}
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <DataGrid<Item>
          key={`${startFilter ?? ""} ${withMinor}`}
          id="items"
          noun={["item", "items"]}
          entity="items"
          reloadKey={reloads}
          {...(mayChange
            ? {
                onBulkEdit: (rows: Chosen, view: GridView) => {
                  setAdding(false);
                  setBulk({ rows, view, turn: bulkTurn });
                  setBulkTurn((turn) => turn + 1);
                },
              }
            : {})}
          columns={columns}
          load={(request, signal) =>
            api.request("post", "/api/v1/items/query", { body: queryBody(request), signal })
          }
          rowId={(item) => item.hid}
          rowLink={(item) => `/items/${encodeURIComponent(item.hid)}`}
          dimmed={itemIsDimmed}
          shortFilter="lifecycle_state:in:Test,Prod hostname:prefix:site2-"
          startFilter={startFilter}
          switches={{ archived: "Include archived", drafts: "Include drafts" }}
          minor={{ label: "Include minor items", without: MAJOR_ITEMS, start: withMinor }}
        >
          {mayChange && !adding && (
            <button type="button" className="primary" onClick={() => setAdding(true)}>
              New item
            </button>
          )}
        </DataGrid>
      )}
    </>
  );
}
