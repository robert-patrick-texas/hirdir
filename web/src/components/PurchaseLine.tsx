// The line of a purchase request an item arrived on. Receiving a line sets it on each
// item it makes; it may also be set by hand, for an item that was entered before its
// request was, and the item then counts as received on that line.

import { useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { any } from "../lib/filter";
import { itemName } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction } from "../lib/hooks";
import { PICK_LIMIT } from "../lib/pick";
import { fieldErrors } from "../lib/problems";
import { arrivedPath, lineModel, requestPath } from "../lib/purchases";
import { type Found, PickField, type PickFieldProps } from "./PickField";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

/** The first few purchase lines that match what was typed: by request, or by model. */
async function findLines(typed: string, signal: AbortSignal): Promise<Found | null> {
  const value = typed.trim().slice(0, 200);
  if (value === "") return null;
  // A line is typed as it is named, RITM0012345/2: the request is what is searched for.
  const [reference = "", number = ""] = value.split("/");
  const page = await api.request("get", "/api/v1/purchase-lines", {
    query: queryParams({
      filter: /^\d+$/.test(number.trim())
        ? {
            and: [
              { field: "request.reference", op: "contains", value: reference.trim() },
              { field: "line", op: "eq", value: Number.parseInt(number.trim(), 10) },
            ],
          }
        : any(
            { field: "request.reference", op: "contains", value: reference.trim() || value },
            { field: "catalog.pid", op: "contains", value },
          ),
      sort: ["request.reference", "line"],
      limit: PICK_LIMIT,
      offset: 0,
      include_archived: false,
      include_drafts: false,
    }),
    signal,
  });
  return {
    options: page.items.map((line) => ({
      value: line.hid,
      label: `${line.name} · ${lineModel(line)} · ${line.pending_quantity} of ${line.quantity} still to come`,
    })),
    total: page.total,
  };
}

/** A field that holds a line of a purchase request, found by its request or its model. */
export function PurchaseLineField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["line", "lines"]}
      how="To choose one, type the reference of its request, as in RITM0012345 or RITM0012345/2, or a part of the PID."
      find={findLines}
    />
  );
}

interface ItemPurchaseLineProps {
  item: Item;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The purchase line an item arrived on, and the form that names another, or none. */
export function ItemPurchaseLine({ item, mayEdit, onChanged, onReload }: ItemPurchaseLineProps) {
  const [editing, setEditing] = useState(false);
  const [chosen, setChosen] = useState(item.purchase_line_hid ?? "");
  const action = useAction();
  const refused = fieldErrors(action.error, ["purchase_line_hid"]).shown;
  const line = item.purchase_line;
  const name = itemName(item);

  async function save() {
    const to = chosen === "" ? null : chosen;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, purchase_line_hid: to },
      }),
    );
    if (!result.ok) return;
    const now = result.value.purchase_line;
    onChanged(
      now
        ? `${name} counts as received on ${now.name}.`
        : `${name} names no purchase line any more.`,
    );
  }

  return (
    <section aria-labelledby="purchase-line">
      <h2 id="purchase-line">Purchase</h2>
      <dl className="facts">
        <dt>Arrived on</dt>
        <dd data-testid="item-purchase-line">
          {line ? (
            <>
              <Link to={requestPath(line.request_hid)}>{line.name}</Link>
              <span className="muted">
                {" "}
                · line {line.line} of the request {line.reference} ·{" "}
              </span>
              <Link to={arrivedPath(line.hid)}>everything that arrived on it</Link>
            </>
          ) : (
            <span className="muted">No line of a purchase request</span>
          )}
        </dd>
        <dt>Delivered on</dt>
        <dd>{item.delivered_on ?? <span className="muted">—</span>}</dd>
      </dl>
      {mayEdit && !editing && (
        <p className="actions">
          <button type="button" onClick={() => setEditing(true)}>
            {line ? "Name another line" : "Name the line it arrived on"}
          </button>
        </p>
      )}
      {mayEdit && editing && (
        <div className="panel stack" data-testid="set-purchase-line">
          <p className="hint">
            Receiving a line names it on each item it makes. Named here by hand, the item counts as
            received on that line, which must still have room for it.
          </p>
          <Problem error={action.error} shown={["purchase_line_hid"]} onReload={onReload} />
          <div className="fields">
            <PurchaseLineField
              label="Purchase line"
              name="purchase_line_hid"
              value={chosen}
              onChange={setChosen}
              known={line ? [{ value: line.hid, label: line.name }] : []}
              blank="None"
              disabled={action.busy}
              error={refused.purchase_line_hid}
            />
          </div>
          <p className="actions">
            <button
              type="button"
              className="primary"
              disabled={action.busy || chosen === (item.purchase_line_hid ?? "")}
              onClick={save}
            >
              Save
            </button>
            <button
              type="button"
              disabled={action.busy}
              onClick={() => {
                setEditing(false);
                setChosen(item.purchase_line_hid ?? "");
                action.clear();
              }}
            >
              Cancel
            </button>
          </p>
        </div>
      )}
    </section>
  );
}
