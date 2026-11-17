import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { BulkEdit } from "../components/BulkEdit";
import { CoverItems } from "../components/Coverage";
import { DataGrid, type GridAction } from "../components/grid/DataGrid";
import { itemColumns, itemIsDimmed, MAJOR_ITEMS } from "../components/grid/itemColumns";
import { NewItem } from "../components/NewItem";
import { Notice, Problem } from "../components/Problem";
import { ITEM_QUICK_FIELDS } from "../lib/filter";
import { queryBody } from "../lib/gridQuery";
import { useTitle } from "../lib/hooks";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useRules } from "../lib/lists";
import { allows } from "../lib/roles";
import type { Chosen, GridView } from "../lib/transfer";

type Item = Schemas["ItemOut"];

/** The rows something is to be done with, as they were chosen when its form was opened. */
interface Rows {
  rows: Chosen;
  view: GridView;
  turn: number;
}

/**
 * Items: the main grid, the filter box, and the form for a new item. The grid leaves
 * minor items out until Include minor items is turned on. The rows selected are edited
 * in bulk, or put under a contract, in one request.
 */
export function Items() {
  useTitle("Items");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  // A link to particular items asks for the minor items among them too.
  const withMinor = params.get("minor") === "1";
  // A link to items that a list leaves out, as a report's of archived ones, asks for them.
  const withArchived = params.get("archived") === "1";
  const withDrafts = params.get("drafts") === "1";
  const [adding, setAdding] = useState(false);
  const [bulk, setBulk] = useState<Rows | null>(null);
  const [cover, setCover] = useState<Rows | null>(null);
  const [turns, setTurns] = useState(0);
  const [reloads, setReloads] = useState(0);
  const [done, setDone] = useState("");
  const mayChange = allows(user.role, "inventory");
  const choices = useChoices();
  const rules = useRules();
  const ready = !choices.loading && !rules.loading;
  const states = useMemo(() => stateNames(rules.data ?? []), [rules.data]);
  const columns = useMemo(() => itemColumns(choices.data, states), [choices.data, states]);
  const actions: GridAction<Item>[] = [
    {
      label: "Cover with a contract",
      run: (rows, view) => {
        setAdding(false);
        setBulk(null);
        setDone("");
        setCover({ rows, view, turn: turns });
        setTurns((turn) => turn + 1);
      },
    },
  ];

  return (
    <>
      <h1>Items</h1>
      <Problem error={choices.error ?? rules.error} />
      <Notice text={done} />
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
      {cover && (
        <CoverItems
          key={cover.turn}
          rows={cover.rows}
          view={cover.view}
          onCovered={(text) => {
            setCover(null);
            setDone(text);
            setReloads((count) => count + 1);
          }}
          onClose={() => setCover(null)}
        />
      )}
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <DataGrid<Item>
          key={`${startFilter ?? ""} ${withMinor} ${withArchived} ${withDrafts}`}
          id="items"
          noun={["item", "items"]}
          entity="items"
          reloadKey={reloads}
          {...(mayChange
            ? {
                onBulkEdit: (rows: Chosen, view: GridView) => {
                  setAdding(false);
                  setCover(null);
                  setBulk({ rows, view, turn: turns });
                  setTurns((turn) => turn + 1);
                },
                actions,
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
          quickFields={ITEM_QUICK_FIELDS}
          startFilter={startFilter}
          startSwitches={
            withArchived || withDrafts
              ? {
                  ...(withArchived ? { archived: true } : {}),
                  ...(withDrafts ? { drafts: true } : {}),
                }
              : null
          }
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
