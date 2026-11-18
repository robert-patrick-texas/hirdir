import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { CheckField, SelectField, TextAreaField, TextField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { LocationField } from "../components/LocationField";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm, useOpenedIntoView } from "../components/RecordForm";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { effectiveLabel, effectiveText } from "../lib/effective";
import { formatTime, itemName, plural, today } from "../lib/format";
import { queryBody, queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { optionLabel } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import {
  ARRIVED_BY,
  type ArrivedBy,
  arrivedOf,
  arrivedPath,
  asksWhatFollows,
  isArrivedBy,
  lineModel,
  lineWhat,
  MISMATCH_NOTE,
  mismatchedPath,
  modelStays,
  NOT_TRACKED_NOTE,
  notReceivable,
  ON_CORRECTION,
  ON_CORRECTION_NOTE,
  type PurchaseLine,
  type PurchaseRequest,
  REQUEST_STATUSES,
  receiptOf,
  requestPath,
  savedText,
} from "../lib/purchases";
import { allows } from "../lib/roles";
import type { SortFields } from "../lib/sort";
import { useServerSort } from "../lib/useServerSort";
import { broughtPaths, siteOption } from "../lib/within";

const LINES_PAGE = 50;
// The most items of one line the page lists itself: the grid of items holds them all.
const ARRIVED_SHOWN = 100;

function Dash() {
  return <span className="muted">—</span>;
}

/**
 * The sites a line may be going to, by path: the drafts too, marked, since a line may
 * name a site still being built (P-208).
 */
function useLineSites() {
  return useLoad("purchase line sites", async (signal) => {
    const page = await api.request("get", "/api/v1/sites", {
      query: { limit: EVERY, sort: ["name"], include_drafts: true },
      signal,
    });
    return page.items.map(siteOption).sort((one, other) => one.label.localeCompare(other.label));
  });
}

/** The second row of navigation on the pages of purchases. */
function PurchasesNav() {
  return (
    <nav className="sub" aria-label="Purchases">
      <ul>
        <li>
          <NavLink to="/purchases" end>
            Requests
          </NavLink>
        </li>
        <li>
          <NavLink to="/purchases/lines">Lines, and what is still to come</NavLink>
        </li>
      </ul>
    </nav>
  );
}

const REQUEST_COLUMNS: GridColumn<PurchaseRequest>[] = [
  {
    id: "reference",
    header: "Reference",
    kind: "text",
    value: (request) => request.reference,
    link: true,
    width: 200,
  },
  {
    id: "status",
    header: "Status",
    kind: "choice",
    value: (request) => optionLabel(REQUEST_STATUSES, request.status),
    choices: REQUEST_STATUSES,
    width: 130,
  },
  {
    id: "requested_on",
    header: "Requested",
    kind: "date",
    value: (request) => request.requested_on,
    width: 140,
  },
  {
    // How many lines it has: counted by the server, and sorted by that count.
    id: "line_count",
    header: "Lines",
    kind: "integer",
    field: null,
    sortField: "line_count",
    column: null,
    value: (request) => String(request.lines.length),
    hint: (request) =>
      request.lines.map((line) => `${line.quantity} × ${lineModel(line)}`).join("; "),
    numeric: true,
    width: 100,
  },
  {
    // How many items are still to come, on all of its lines.
    id: "pending_quantity",
    header: "Still to come",
    kind: "integer",
    column: null,
    value: (request) => String(request.pending_quantity),
    hint: (request) =>
      `${request.received_quantity} of ${request.quantity} ${request.quantity === 1 ? "item has" : "items have"} arrived`,
    numeric: true,
    // The heading whole (P-210).
    width: 172,
  },
  { id: "notes", header: "Notes", kind: "text", value: (request) => request.notes, width: 320 },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (request) => formatTime(request.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (request) => request.hid,
    mono: true,
    hide: true,
  },
];

const REQUEST_SPECS: FieldSpec[] = [
  {
    name: "reference",
    label: "Reference",
    kind: "text",
    required: true,
    maxLength: 120,
    hint: "The RITM or other request number. It holds no /, which separates it from the number of a line.",
  },
  { name: "requested_on", label: "Requested on", kind: "date" },
  {
    name: "status",
    label: "Status",
    kind: "choice",
    options: REQUEST_STATUSES,
    hint: "What you say of it. One exception: a request that is pending or ordered becomes Received by the delivery that completes its last line. A request that is a draft or cancelled receives nothing.",
  },
  { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
];

/**
 * Purchases: the requests, each with how many lines it has and what is still to come. A
 * request and its lines are not inventory, and are in no count: receiving a line makes
 * the items.
 */
export function Purchases() {
  useTitle("Purchases");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PurchasesNav />
      <h1>Purchases</h1>
      <p>
        A purchase request records what was asked for: a model and how many, on each of its lines. A
        request and its lines are not inventory, and are in no count. Receiving a line says which
        items arrived, and makes them, in the state Delivered. A line of something this inventory
        does not follow, as cable ties or a monitor, has its part number and no model: it is not
        tracked, takes no item, and the request is not kept waiting for it.
      </p>
      {adding && (
        <CreateForm<Schemas["PurchaseRequestCreate"], PurchaseRequest>
          title="New purchase request"
          specs={REQUEST_SPECS}
          start={{ status: "pending" }}
          create={(body) => api.request("post", "/api/v1/purchase-requests", { body })}
          onCreated={(request) => navigate(requestPath(request.hid))}
          onCancel={() => setAdding(false)}
          submitLabel="Create request"
        >
          <p className="hint">Its lines are added on its own page, once it is made.</p>
        </CreateForm>
      )}
      <DataGrid<PurchaseRequest>
        key={startFilter ?? ""}
        id="purchase-requests"
        noun={["request", "requests"]}
        entity="purchase_requests"
        columns={REQUEST_COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/purchase-requests", { query: queryParams(request), signal })
        }
        rowId={(request) => request.hid}
        rowLink={(request) => requestPath(request.hid)}
        dimmed={(request) => request.status === "cancelled" || request.status === "draft"}
        shortFilter="status:in:pending,ordered pending_quantity:gt:0"
        quickFields={["reference"]}
        startFilter={startFilter}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New request
          </button>
        )}
      </DataGrid>
    </>
  );
}

const LINE_COLUMNS: GridColumn<PurchaseLine>[] = [
  {
    id: "request.reference",
    header: "Request",
    kind: "text",
    column: "request",
    value: (line) => line.reference,
    link: true,
    width: 160,
  },
  {
    id: "line",
    header: "Line",
    kind: "integer",
    value: (line) => String(line.line),
    hint: (line) => line.name,
    numeric: true,
    width: 90,
  },
  {
    id: "catalog.vendor",
    header: "Vendor",
    kind: "text",
    column: "vendor",
    value: (line) => line.catalog?.vendor ?? null,
    width: 100,
  },
  {
    id: "catalog.pid",
    header: "PID",
    kind: "text",
    column: "pid",
    value: (line) => line.catalog?.pid ?? null,
    width: 140,
  },
  {
    id: "catalog.model_name",
    header: "Model",
    kind: "text",
    column: null,
    value: (line) => line.catalog?.model_name ?? null,
    hide: true,
  },
  {
    // As the procurement system gave them, beside the model the line is matched to. In
    // the column chooser, so that Destination site and Expected are in view (P-210).
    id: "part_number",
    header: "Part number",
    kind: "text",
    value: (line) => line.part_number,
    mono: true,
    hide: true,
    width: 170,
  },
  {
    id: "description",
    header: "Description",
    kind: "text",
    value: (line) => line.description,
    hide: true,
    width: 240,
  },
  {
    // A line with no model is not tracked: it takes no item and is waited for by nobody.
    id: "tracked",
    header: "Tracked",
    kind: "boolean",
    value: (line) => (line.tracked ? "Yes" : "Not tracked"),
    hint: (line) => (line.tracked ? "" : NOT_TRACKED_NOTE),
    choices: [
      { value: "true", label: "Tracked: the line has a model" },
      { value: "false", label: "Not tracked: no model, and no item" },
    ],
    hide: true,
    width: 120,
  },
  {
    id: "quantity",
    header: "Quantity",
    kind: "integer",
    value: (line) => String(line.quantity),
    numeric: true,
    width: 125,
  },
  {
    id: "received_quantity",
    header: "Received",
    kind: "integer",
    value: (line) => String(line.received_quantity),
    numeric: true,
    width: 125,
  },
  {
    id: "pending_quantity",
    header: "Still to come",
    kind: "integer",
    value: (line) => String(line.pending_quantity),
    numeric: true,
    width: 172,
  },
  {
    // The items on the line that are of another model than the line's, which 0.6.0 let
    // in: zero once they are put right.
    id: "mismatched_items",
    header: "Of another model",
    kind: "integer",
    value: (line) => String(line.mismatched_items),
    hint: (line) =>
      line.mismatched_items > 0
        ? `${plural(line.mismatched_items, "item on it is", "items on it are")} of another model than the line's, which 0.6.0 let in: to be put right`
        : "",
    numeric: true,
    hide: true,
    width: 160,
  },
  {
    id: "site",
    header: "Destination site",
    kind: "text",
    column: "destination_site",
    value: (line) => line.destination_site?.name,
    hint: (line) => line.destination_site?.path,
    width: 200,
  },
  {
    id: "expected_on",
    header: "Expected",
    kind: "date",
    value: (line) => line.expected_on,
    width: 125,
  },
  {
    id: "request.status",
    header: "Status of the request",
    kind: "choice",
    column: null,
    value: (line) => optionLabel(REQUEST_STATUSES, line.request_status),
    choices: REQUEST_STATUSES,
    width: 180,
  },
  { id: "notes", header: "Notes", kind: "text", value: (line) => line.notes, hide: true },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (line) => formatTime(line.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (line) => line.hid,
    mono: true,
    hide: true,
  },
];

/** Purchases → the lines of every request: the planning list of what is still to come. */
export function PurchaseLines() {
  useTitle("Purchase lines");
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  return (
    <>
      <PurchasesNav />
      <h1>Purchase lines</h1>
      <p>
        The lines of every request: what was asked for, what has arrived and what is still to come.
        Filter <span className="mono">Still to come</span> to more than 0, or type{" "}
        <span className="mono">pending_quantity:gt:0</span>, for the list to plan by; the name of a
        site, typed in the filter, finds the lines going to it. A line is received on the page of
        its request. A line with no model is not tracked, and{" "}
        <span className="mono">tracked:eq:false</span> lists those: nothing is to come on them.
      </p>
      <DataGrid<PurchaseLine>
        key={startFilter ?? ""}
        id="purchase-lines"
        noun={["line", "lines"]}
        entity="purchase_lines"
        columns={LINE_COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/purchase-lines", { query: queryParams(request), signal })
        }
        rowId={(line) => line.hid}
        rowLink={(line) => requestPath(line.request_hid)}
        dimmed={(line) => line.request_status === "cancelled" || line.request_status === "draft"}
        shortFilter="pending_quantity:gt:0 tracked:eq:true catalog.vendor:eq:Cisco"
        quickFields={["request.reference", "catalog.pid", "catalog.model_name", "site"]}
        startFilter={startFilter}
      />
    </>
  );
}

/** `GET /purchase-requests/{hid}/lines`: the field of its `sort` behind each column. */
const LINES_SORT: SortFields = {
  line: "line",
  model: "catalog.vendor,catalog.pid",
  part: "part_number",
  quantity: "quantity",
  received: "received_quantity",
  pending: "pending_quantity",
  site: "site",
  expected: "expected_on",
};

/** Purchases → one request: its lines, receiving, and the items that arrived on each line. */
export function PurchaseDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const request = useLoad(`purchase-request ${hid}`, (signal) =>
    api.request("get", "/api/v1/purchase-requests/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const [turn, setTurn] = useState(0);
  const record = request.data;
  useTitle(record ? record.reference : "Purchase request");

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    request.reload();
  }

  return (
    <>
      <PurchasesNav />
      <p className="crumbs">
        <Link to="/purchases">Purchases</Link>
      </p>
      <h1>
        {record ? record.reference : "Purchase request"}
        {record && (
          <span className="badge badge-plain">{optionLabel(REQUEST_STATUSES, record.status)}</span>
        )}
      </h1>
      <Problem error={request.error} />
      <Notice text={done} />
      {request.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="facts" data-testid="request-facts">
            <dt>Reference</dt>
            <dd>{record.reference}</dd>
            <dt>Status</dt>
            <dd data-testid="request-status" data-status={record.status}>
              {optionLabel(REQUEST_STATUSES, record.status)}
              <span className="muted">
                {" "}
                · what a person says of it, and Received by itself once every line that is tracked
                has arrived in full
              </span>
            </dd>
            <dt>Requested on</dt>
            <dd>{record.requested_on ?? <Dash />}</dd>
            <dt>Asked for</dt>
            <dd>
              <span data-testid="request-quantity">{plural(record.quantity, "item")}</span>
              <Untracked request={record} />
            </dd>
            <dt>Received</dt>
            <dd>
              <span data-testid="request-received">{plural(record.received_quantity, "item")}</span>
              <Brought request={record} />
            </dd>
            <dt>Still to come</dt>
            <dd data-testid="request-pending">{plural(record.pending_quantity, "item")}</dd>
            <dt>Notes</dt>
            <dd>{record.notes || <Dash />}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <Mismatched request={record} />
          <Lines request={record} mayEdit={mayEdit} turn={turn} onChanged={changed} />
          {mayEdit && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<PurchaseRequest, Schemas["PurchaseRequestPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={REQUEST_SPECS}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/purchase-requests/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The request was saved.")}
                onReload={request.reload}
              />
            </section>
          )}
        </>
      )}
    </>
  );
}

/**
 * How many lines of a request are not tracked: they are bought with it, and counted in
 * nothing that it asks for or that is still to come. Nothing is said where there are none.
 */
function Untracked({ request }: { request: PurchaseRequest }) {
  const untracked = request.lines.filter((line) => !line.tracked).length;
  if (untracked === 0) return null;
  return (
    <span className="muted" data-testid="request-untracked" data-count={untracked}>
      {" "}
      · on the lines that are tracked; {plural(untracked, "line is", "lines are")} not tracked, and
      counted in none of this
    </span>
  );
}

/**
 * Every item the request brought, in the item list (P-208): the items that arrived on
 * its lines, by the lines received on. A request of more such lines than one address
 * names is given in parts, by its lines.
 */
function Brought({ request }: { request: PurchaseRequest }) {
  const paths = broughtPaths(request.lines);
  const [only] = paths;
  if (!only) return null;
  if (paths.length === 1) {
    return (
      <>
        {" · "}
        <Link to={only.path} data-testid="request-brought">
          Every item it brought
        </Link>
      </>
    );
  }
  return (
    <>
      {" · Every item it brought, "}
      <span data-testid="request-brought">
        {paths.map((part, place) => (
          <span key={part.from}>
            {place > 0 && ", "}
            <Link to={part.path}>
              {part.from === part.to
                ? `on line ${part.from}`
                : `on lines ${part.from} to ${part.to}`}
            </Link>
          </span>
        ))}
      </span>
    </>
  );
}

/**
 * The lines of a request that hold items of another model than the line's, which 0.6.0
 * let in: each with how many, leading to those items in the grid, to be put right.
 * Nothing is said where there are none.
 */
function Mismatched({ request }: { request: PurchaseRequest }) {
  const astray = request.lines.filter((line) => line.mismatched_items > 0);
  if (astray.length === 0) return null;
  const count = astray.reduce((sum, line) => sum + line.mismatched_items, 0);
  return (
    <div className="warning" data-testid="request-mismatched" data-count={count}>
      <p>
        {plural(count, "item")} on the lines of this request {count === 1 ? "is" : "are"} of another
        model than the line&apos;s: 0.6.0 let that in, and an item put on a line now is of the
        line&apos;s model. Each is put right on its own page.
      </p>
      <ul className="plain-list">
        {astray.map((line) => (
          <li key={line.hid} data-line={line.name}>
            <Link to={mismatchedPath(line.hid)}>
              {plural(line.mismatched_items, "item", "items")} on {line.name}
            </Link>
            <span className="muted"> · a line of {lineModel(line)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface LinesProps {
  request: PurchaseRequest;
  mayEdit: boolean;
  /** Changes when the request does, so that the lines are read again. */
  turn: number;
  onChanged: (text: string) => void;
}

type Open = { hid: string; what: "receive" | "change" | "arrived" };

/**
 * The lines of a request, sorted and paged by the server: what was asked for on each,
 * what has arrived and what is still to come. A line is received, changed, and its
 * arrived items listed, from its row. A line is never removed: one that is no longer
 * wanted is lowered to what was received.
 */
function Lines({ request, mayEdit, turn, onChanged }: LinesProps) {
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<Open | null>(null);
  const [adding, setAdding] = useState(false);
  const [mine, setMine] = useState(0);
  const sort = useServerSort<PurchaseLine>({ fields: LINES_SORT, onChange: () => setOffset(0) });
  const lines = sort.held(
    useLoad(`lines ${request.hid} ${offset} ${turn} ${mine} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/purchase-requests/{hid}/lines", {
        path: { hid: request.hid },
        query: { limit: LINES_PAGE, offset, ...sort.query },
        signal,
      }),
    ),
  );
  const rows = lines.data?.items ?? [];
  const holdsAll = lines.data !== undefined && lines.data.total <= rows.length;
  const line = rows.find((row) => row.hid === open?.hid) ?? null;

  function changed(text: string, show: Open | null = null) {
    setAdding(false);
    setOpen(show);
    onChanged(text);
  }

  return (
    <section aria-labelledby="lines">
      <h2 id="lines">Lines</h2>
      <Problem error={lines.error} />
      {lines.loading && !lines.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {lines.data && rows.length === 0 && (
        <p className="muted">{request.reference} has no line yet.</p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="purchase-lines" className="request-lines wrap-heads">
            <caption className="visually-hidden">
              The lines of {request.reference}, by their numbers until a header is clicked
            </caption>
            <thead>
              <tr>
                <SortTh sort={sort.header("line", holdsAll)} column="line">
                  Line
                </SortTh>
                <SortTh sort={sort.header("model", holdsAll)} column="model">
                  Model
                </SortTh>
                <SortTh
                  sort={sort.header("quantity", holdsAll)}
                  column="quantity"
                  className="number"
                >
                  Quantity
                </SortTh>
                <SortTh
                  sort={sort.header("received", holdsAll)}
                  column="received"
                  className="number"
                >
                  Received
                </SortTh>
                <SortTh sort={sort.header("pending", holdsAll)} column="pending" className="number">
                  Still to come
                </SortTh>
                <SortTh sort={sort.header("site", holdsAll)} column="site">
                  Destination site
                </SortTh>
                <SortTh sort={sort.header("expected", holdsAll)} column="expected">
                  Expected
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sort.arrange(rows, holdsAll).map((row) => (
                <tr
                  key={row.hid}
                  data-line={row.name}
                  data-tracked={row.tracked ? "true" : "false"}
                  data-pending={row.pending_quantity}
                  data-received={row.received_quantity}
                >
                  <th scope="row">{row.name}</th>
                  <td className="line-model">
                    {row.catalog_entry_hid === null ? (
                      <span
                        className="badge badge-plain"
                        data-testid="line-not-tracked"
                        title={NOT_TRACKED_NOTE}
                      >
                        Not tracked
                      </span>
                    ) : (
                      <Link to={`/catalog/${encodeURIComponent(row.catalog_entry_hid)}`}>
                        {lineModel(row)}
                      </Link>
                    )}
                    {row.catalog?.model_name && (
                      <span className="muted"> · {row.catalog.model_name}</span>
                    )}
                    {/* As procurement gave it, beneath the model, only where the line has it (P-208). */}
                    {(row.part_number || row.description) && (
                      <div data-testid="line-part-number">
                        <span className="muted">As procurement gave it: </span>
                        {row.part_number && <span className="mono">{row.part_number}</span>}
                        {row.part_number && row.description && " · "}
                        {row.description && <span className="muted">{row.description}</span>}
                      </div>
                    )}
                    {row.notes && <div className="muted">{row.notes}</div>}
                    {row.mismatched_items > 0 && (
                      <div>
                        <Link
                          to={mismatchedPath(row.hid)}
                          className="badge"
                          data-testid="line-mismatched"
                          title={`Of another model than the line's: ${MISMATCH_NOTE}`}
                        >
                          {row.mismatched_items} of another model
                        </Link>
                      </div>
                    )}
                  </td>
                  <td className="number">{row.quantity}</td>
                  <td className="number" data-testid="line-received">
                    {row.tracked ? row.received_quantity : <Dash />}
                  </td>
                  <td className="number" data-testid="line-pending">
                    {row.tracked ? row.pending_quantity : <Dash />}
                  </td>
                  <td title={row.destination_site?.path}>
                    {row.destination_site?.name ?? <Dash />}
                  </td>
                  <td className="nowrap">{row.expected_on ?? <Dash />}</td>
                  <td className="row-actions">
                    {/* A line that is not tracked takes no item: there is nothing to receive. */}
                    {mayEdit && row.tracked && (
                      <button
                        type="button"
                        aria-label={`Receive on ${row.name}`}
                        onClick={() => {
                          setAdding(false);
                          setOpen({ hid: row.hid, what: "receive" });
                        }}
                      >
                        Receive
                      </button>
                    )}
                    <button
                      type="button"
                      aria-label={`What arrived on ${row.name}`}
                      disabled={row.received_quantity === 0}
                      onClick={() => {
                        setAdding(false);
                        setOpen({ hid: row.hid, what: "arrived" });
                      }}
                    >
                      Arrived
                    </button>
                    {mayEdit && (
                      <button
                        type="button"
                        aria-label={`Change ${row.name}`}
                        onClick={() => {
                          setAdding(false);
                          setOpen({ hid: row.hid, what: "change" });
                        }}
                      >
                        Change
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lines.data && lines.data.total > LINES_PAGE && (
        <Pager
          total={lines.data.total}
          limit={LINES_PAGE}
          offset={offset}
          noun="lines"
          onChange={setOffset}
        />
      )}
      {mayEdit && line && open?.what === "receive" && (
        <Receive
          key={`receive ${line.hid} ${line.row_version} ${line.received_quantity}`}
          line={line}
          onReceived={(text) => changed(text, { hid: line.hid, what: "arrived" })}
          onReload={() => setMine((count) => count + 1)}
          onClose={() => setOpen(null)}
        />
      )}
      {mayEdit && line && open?.what === "change" && (
        <ChangeLine
          key={`change ${line.hid} ${line.row_version}`}
          line={line}
          onSaved={(text) => changed(text)}
          onReload={() => setMine((count) => count + 1)}
          onClose={() => setOpen(null)}
        />
      )}
      {line && open?.what === "arrived" && (
        <Arrived
          key={`arrived ${line.hid} ${line.received_quantity}`}
          line={line}
          onClose={() => setOpen(null)}
        />
      )}
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            onClick={() => {
              setOpen(null);
              setAdding(true);
            }}
          >
            Add a line
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <AddLine
          request={request}
          onCancel={() => setAdding(false)}
          onAdded={(made) =>
            changed(`${made.name} was added: ${made.quantity} × ${lineWhat(made)}.`)
          }
          onAddedAnother={(made) => {
            // The form stays open for the next line; the lines are read again.
            setOpen(null);
            onChanged(`${made.name} was added: ${made.quantity} × ${lineWhat(made)}.`);
          }}
        />
      )}
    </section>
  );
}

/** What is said beneath the model of a line, as the line stands. */
function modelHint(line: PurchaseLine | null): string {
  if (line === null) {
    return "The model of the catalog. Left blank, the line is not tracked: it takes no item, is in no count, and the request is not kept waiting for it, as for cable ties or a monitor. It then needs its part number.";
  }
  const stays = modelStays(line);
  if (stays) {
    return `Corrected at any time, a typing error among them. ${stays} Where it is corrected, say beneath it what becomes of the items.`;
  }
  if (line.catalog_entry_hid === null) {
    return "The line is not tracked. Given a model, it is tracked: it takes items, and what is still to come on it is counted.";
  }
  return "Corrected at any time. Nothing has arrived on it, so the model may also be taken off, and the line is then not tracked.";
}

/** The fields of a line that a form sets. */
function lineSpecs(
  entries: FieldSpec["options"],
  sites: FieldSpec["options"],
  line: PurchaseLine | null,
) {
  // A line keeps a model while anything has arrived on it: then there is no blank to choose.
  const keeps = line !== null && modelStays(line) !== "";
  const model: FieldSpec = {
    name: "catalog_entry_hid",
    label: "Model",
    // 0.9.6: searched for, not a list of every model (P-200).
    kind: "entry",
    options: entries ?? [],
    ...(keeps ? { required: true } : { blank: "None: the line is not tracked" }),
    hint: modelHint(line),
  };
  // Asked only where items have arrived on the line and its model is corrected.
  const follows: FieldSpec[] = line
    ? [
        {
          name: "items",
          label: `What becomes of the ${plural(line.received_quantity, "item")} that arrived on it`,
          kind: "choice",
          blank: "Choose one",
          options: ON_CORRECTION,
          hint: ON_CORRECTION_NOTE,
          when: (values) => asksWhatFollows(line, values.catalog_entry_hid),
        },
      ]
    : [];
  const procurement: FieldSpec[] = [
    {
      name: "part_number",
      label: "Part number",
      kind: "text",
      maxLength: 100,
      hint: "As the procurement system gave it. A line with no model needs it.",
    },
    {
      name: "description",
      label: "Description",
      kind: "longtext",
      maxLength: 10000,
      hint: "As the procurement system gave it.",
    },
  ];
  const rest: FieldSpec[] = [
    {
      name: "quantity",
      label: "Quantity",
      kind: "integer",
      required: true,
      hint: line
        ? `At least 1, and never below the ${line.received_quantity} that arrived. A line that is no longer wanted is taken back by lowering it to that.`
        : "How many. At least 1.",
    },
    {
      name: "destination_site_hid",
      label: "Destination site",
      kind: "choice",
      options: sites ?? [],
      blank: "None",
    },
    { name: "expected_on", label: "Expected on", kind: "date" },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
  ];
  return [model, ...follows, ...procurement, ...rest];
}

/** An option for what a line already names, when the list read does not offer it. */
function withOwn(
  options: FieldSpec["options"],
  value: string | null,
  label: string | undefined,
): NonNullable<FieldSpec["options"]> {
  const offered = [...(options ?? [])];
  if (value && !offered.some((option) => option.value === value)) {
    offered.push({ value, label: label ?? value });
  }
  return offered;
}

interface AddLineProps {
  request: PurchaseRequest;
  onCancel: () => void;
  onAdded: (line: PurchaseLine) => void;
  /** A line was added by Add and add another like it, and the form stays open (P-208). */
  onAddedAnother: (line: PurchaseLine) => void;
}

function AddLine({ request, onCancel, onAdded, onAddedAnother }: AddLineProps) {
  const sites = useLineSites();
  const specs = useMemo(() => lineSpecs([], sites.data, null), [sites.data]);
  return (
    <>
      <Problem error={sites.error} />
      <CreateForm<Schemas["PurchaseLineAdd"], PurchaseLine>
        title={`New line of ${request.reference}`}
        specs={specs}
        start={{ quantity: "1" }}
        create={(body) =>
          api.request("post", "/api/v1/purchase-requests/{hid}/lines", {
            path: { hid: request.hid },
            body,
          })
        }
        onCreated={onAdded}
        onCancel={onCancel}
        submitLabel="Add line"
        another={{
          label: "Add and add another like it",
          keep: ["destination_site_hid", "expected_on"],
          focus: "catalog_entry_hid",
          onCreated: onAddedAnother,
        }}
      >
        <p className="hint">
          A model and how many, or the part number with no model for what this inventory does not
          follow. The line takes the next number of the request, and is named by the reference and
          that number, as in {request.reference}/{request.lines.length + 1}.
        </p>
      </CreateForm>
    </>
  );
}

interface LineFormProps {
  line: PurchaseLine;
  onReload: () => void;
  onClose: () => void;
}

function ChangeLine({
  line,
  onSaved,
  onReload,
  onClose,
}: LineFormProps & { onSaved: (text: string) => void }) {
  // What the change did, said once it is taken: the form knows only that it was.
  const said = useRef("");
  const sites = useLineSites();
  const specs = useMemo(
    () =>
      lineSpecs(
        withOwn([], line.catalog_entry_hid, lineModel(line)),
        withOwn(sites.data, line.destination_site_hid, line.destination_site?.path),
        line,
      ),
    [sites.data, line],
  );
  return (
    <section className="panel" aria-labelledby="change-line" data-testid="change-line">
      <h3 id="change-line">Change {line.name}</h3>
      <Problem error={sites.error} />
      <EditForm<PurchaseLine, Schemas["PurchaseLinePatch"]>
        specs={specs}
        record={line}
        save={async (body) => {
          const saved = await api.request("patch", "/api/v1/purchase-lines/{hid}", {
            path: { hid: line.hid },
            body,
          });
          said.current = savedText(line, saved, body);
          return saved;
        }}
        onSaved={() => onSaved(said.current)}
        onReload={onReload}
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}

/**
 * Receive a line: say which items arrived, by the serial number, the asset tag or the
 * name of each, with the day and the location they were put in. The server makes them,
 * in Delivered, of the line's model, each naming the line: all of them, or none.
 */
function Receive({
  line,
  onReceived,
  onReload,
  onClose,
}: LineFormProps & { onReceived: (text: string) => void }) {
  const [by, setBy] = useState<ArrivedBy>("serial_number");
  const [typed, setTyped] = useState("");
  const [count, setCount] = useState("");
  const [day, setDay] = useState(() => today());
  const [location, setLocation] = useState("");
  // 0.9.6: the location is looked for where the line is going, unless the person says
  // otherwise, and is the site's one location where it has only one (P-209).
  const site = line.destination_site;
  const [onlyThere, setOnlyThere] = useState(site !== null);
  const [touched, setTouched] = useState(false);
  const only = useLoad(`receive one location ${site?.hid ?? ""}`, (signal) =>
    site === null ? Promise.resolve(null) : oneLocationOf(site.hid, signal),
  );
  const theOne = only.data ?? null;
  const chosen = location === "" && !touched && theOne ? theOne.value : location;
  const [found, setFound] = useState({ error: "", countError: "" });
  const action = useAction();
  const known = ["delivered_on", "location_hid", "quantity"];
  // Opened by Receive, the form comes into the window with the keyboard in the box of
  // what arrived (P-209, as P-190 for a new form).
  const section = useRef<HTMLElement>(null);
  useOpenedIntoView(section);
  useEffect(() => {
    const form = section.current;
    if (form?.contains(document.activeElement)) {
      form.querySelector<HTMLElement>('[name="arrived"]')?.focus({ preventScroll: true });
    }
  }, []);
  const refused = fieldErrors(action.error, known).shown;
  const stopped = notReceivable(line);
  const read = arrivedOf(typed, by, count, line.pending_quantity);
  // The server names an item it refuses by its place in the request.
  const labels: Record<string, string> = { items: "" };
  for (const [place, item] of read.items.entries()) {
    const name = item[by] ?? "";
    for (const field of ["serial_number", "asset_tag", "name"]) {
      labels[`items.${place}.${field}`] = name;
    }
    labels[`items.${place}`] = name;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFound({ error: read.error, countError: read.countError });
    if (read.error || read.countError) {
      action.clear();
      return;
    }
    const result = await action.run(() =>
      api.request("post", "/api/v1/purchase-lines/{hid}/receive", {
        path: { hid: line.hid },
        body: {
          row_version: line.row_version,
          ...receiptOf(read),
          ...(day === "" ? {} : { delivered_on: day }),
          ...(chosen === "" ? {} : { location_hid: chosen }),
        },
      }),
    );
    if (result.ok) {
      const made = result.value;
      onReceived(
        [
          `${plural(made.items.length, "item was", "items were")} received on ${made.name}, in the state Delivered.`,
          read.quantity > 0
            ? `${plural(read.quantity, "of them is", "of them are")} named for the line until ${read.quantity === 1 ? "it has a serial number" : "they have serial numbers"}.`
            : "",
          made.pending_quantity === 0
            ? "Nothing more is to come on it."
            : `${made.pending_quantity} still to come.`,
          made.request_status === "received" && line.request_status !== "received"
            ? `Every line of ${made.reference} has arrived in full: the request is Received.`
            : "",
        ]
          .filter(Boolean)
          .join(" "),
      );
    }
  }

  return (
    <section
      ref={section}
      className="panel"
      aria-labelledby="receive-line"
      data-testid="receive-line"
    >
      <h3 id="receive-line">
        Receive on {line.name}: {lineModel(line)}
      </h3>
      {stopped ? (
        <>
          <p className="warning">{stopped}</p>
          <p className="actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
          </p>
        </>
      ) : (
        <form onSubmit={submit} className="stack" noValidate>
          <p className="hint">
            {plural(line.pending_quantity, "item is", "items are")} still to come on this line. Each
            item that arrived is made in the state Delivered, of this model, naming this line: all
            of them, or none. Delivered is not a state that counts, so they are in no component
            count until they are handed to the team. Say what arrived by what it is known by, or how
            many arrived that nothing is known of yet, or both.
          </p>
          <Problem error={action.error} shown={known} labels={labels} onReload={onReload} />
          {found.error && (
            <div className="alert alert-error" role="alert" data-testid="receive-problem">
              <p>{found.error}</p>
            </div>
          )}
          <div className="fields">
            <SelectField
              label="What arrived, by"
              name="arrived_by"
              value={by}
              onChange={(next) => setBy(isArrivedBy(next) ? next : "serial_number")}
              disabled={action.busy}
              hint="Every item needs a serial number, an asset tag or a name. The rest is filled in on the item."
            >
              {ARRIVED_BY.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </SelectField>
            <TextAreaField
              label={ARRIVED_BY.find((option) => option.value === by)?.label ?? "What arrived"}
              name="arrived"
              rows={6}
              value={typed}
              onChange={(next) => {
                setTyped(next);
                setFound({ error: "", countError: "" });
              }}
              disabled={action.busy}
              hint="One item to a line. Left blank when nothing is known of what arrived."
            />
            <TextField
              label="How many more arrived, with nothing to know them by yet"
              name="quantity"
              value={count}
              onChange={(next) => {
                setCount(next);
                setFound({ error: "", countError: "" });
              }}
              inputMode="numeric"
              autoComplete="off"
              disabled={action.busy}
              error={found.countError || refused.quantity}
              hint={`Each is given a name made from the line, as ${line.name}-003, to be known by until it has a serial number, which is given to it by hand or by a file that names it so.`}
            />
            <TextField
              label="Delivered on"
              name="delivered_on"
              type="date"
              value={day}
              onChange={setDay}
              disabled={action.busy}
              error={refused.delivered_on}
              hint="Left blank, today."
            />
            <LocationField
              // A new search when where it looks changes: what was found elsewhere is not kept.
              key={onlyThere ? "there" : "anywhere"}
              label="Location they were put in"
              name="location_hid"
              value={chosen}
              onChange={(hid) => {
                setTouched(true);
                setLocation(hid);
              }}
              known={theOne ? [theOne] : []}
              blank="Not said"
              disabled={action.busy}
              error={refused.location_hid}
              site={onlyThere && site ? site.hid : undefined}
              {...(site
                ? {
                    hint: onlyThere
                      ? `Looked for at ${site.name}, where the line is going.`
                      : "Looked for at every site.",
                  }
                : {})}
            />
            {site && (
              <CheckField
                label={`Only at ${site.name}`}
                name="only_at_site"
                checked={onlyThere}
                onChange={setOnlyThere}
                disabled={action.busy}
                hint="Clear it to choose a location at any other site."
              />
            )}
          </div>
          <p className="actions">
            <button
              type="submit"
              className="primary"
              disabled={action.busy || (typed.trim() === "" && count.trim() === "")}
            >
              Receive {read.total > 0 ? plural(read.total, "item") : "items"}
            </button>
            <button type="button" onClick={onClose} disabled={action.busy}>
              Cancel
            </button>
          </p>
        </form>
      )}
    </section>
  );
}

type Item = Schemas["ItemOut"];

/** The one location of a site, by its path, or null where it has none or more than one. */
async function oneLocationOf(
  site: string,
  signal: AbortSignal,
): Promise<{ value: string; label: string } | null> {
  const page = await api.request("post", "/api/v1/locations/query", {
    body: queryBody({
      filter: { field: "site_hid", op: "eq", value: site },
      sort: ["name"],
      limit: 2,
      offset: 0,
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
  const [one] = page.items;
  return page.total === 1 && one ? { value: one.hid, label: one.path } : null;
}

/** The items that arrived on a line: those that name it, read from the item list. */
function Arrived({ line, onClose }: { line: PurchaseLine; onClose: () => void }) {
  const sort = useServerSort<Item>({
    fields: {
      name: "name",
      serial: "serial_number",
      asset: "asset_tag",
      state: "effective.lifecycle_state",
      delivered: "delivered_on",
      location: "location.name",
    },
  });
  const items = sort.held(
    useLoad(`arrived ${line.hid} ${line.received_quantity} ${sort.param ?? ""}`, (signal) =>
      api.request("post", "/api/v1/items/query", {
        body: queryBody({
          filter: { field: "purchase_line_hid", op: "eq", value: line.hid },
          sort: sort.param === undefined ? ["name"] : sort.param.split(","),
          limit: ARRIVED_SHOWN,
          offset: 0,
          // What arrived is listed whatever became of it since.
          include_archived: true,
          include_drafts: true,
        }),
        signal,
      }),
    ),
  );
  const rows = items.data?.items ?? [];
  const holdsAll = items.data !== undefined && items.data.total <= rows.length;
  return (
    <section className="panel" aria-labelledby="arrived-on" data-testid="arrived-items">
      <h3 id="arrived-on">Arrived on {line.name}</h3>
      <Problem error={items.error} />
      {items.loading && !items.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {items.data && rows.length === 0 && <p className="muted">Nothing has arrived on it yet.</p>}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="arrived">
            <caption className="visually-hidden">The items that arrived on {line.name}</caption>
            <thead>
              <tr>
                <SortTh sort={sort.header("name", holdsAll)} column="name">
                  Item
                </SortTh>
                <SortTh sort={sort.header("serial", holdsAll)} column="serial">
                  Serial number
                </SortTh>
                <SortTh sort={sort.header("asset", holdsAll)} column="asset">
                  Asset tag
                </SortTh>
                <SortTh sort={sort.header("state", holdsAll)} column="state">
                  State
                </SortTh>
                <SortTh sort={sort.header("delivered", holdsAll)} column="delivered">
                  Delivered
                </SortTh>
                <SortTh sort={sort.header("location", holdsAll)} column="location">
                  Location
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sort.arrange(rows, holdsAll).map((item) => (
                <tr key={item.hid} data-item={item.hid}>
                  <th scope="row">
                    <Link to={`/items/${encodeURIComponent(item.hid)}`}>{itemName(item)}</Link>
                    {item.purchase_line_mismatch && (
                      <span className="badge" data-mark="mismatch" title={MISMATCH_NOTE}>
                        Of another model
                      </span>
                    )}
                  </th>
                  <td className="mono">{item.serial_number || <Dash />}</td>
                  <td>{item.asset_tag || <Dash />}</td>
                  <td>{effectiveText(item.effective.lifecycle_state) || <Dash />}</td>
                  <td className="nowrap">{item.delivered_on ?? <Dash />}</td>
                  <td>{effectiveLabel(item.effective.location_hid) || <Dash />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="actions">
        <Link to={arrivedPath(line.hid)}>
          {items.data && !holdsAll
            ? `All ${items.data.total} of them, in the grid of items`
            : "These items in the grid"}
        </Link>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}
