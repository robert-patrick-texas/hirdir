import { type FormEvent, useMemo, useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { SelectField, TextAreaField, TextField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { LocationField } from "../components/LocationField";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { effectiveLabel, effectiveText } from "../lib/effective";
import { formatTime, itemName, plural, today } from "../lib/format";
import { queryBody, queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useEntryOptions, useSiteOptions } from "../lib/lists";
import { optionLabel } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import {
  ARRIVED_BY,
  type ArrivedBy,
  arrivedOf,
  arrivedPath,
  isArrivedBy,
  lineModel,
  MISMATCH_NOTE,
  mismatchedPath,
  notReceivable,
  type PurchaseLine,
  type PurchaseRequest,
  REQUEST_STATUSES,
  receiptOf,
  requestPath,
} from "../lib/purchases";
import { allows } from "../lib/roles";
import type { SortFields } from "../lib/sort";
import { useServerSort } from "../lib/useServerSort";

const LINES_PAGE = 50;
// The most items of one line the page lists itself: the grid of items holds them all.
const ARRIVED_SHOWN = 100;

function Dash() {
  return <span className="muted">—</span>;
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
    width: 140,
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
        items arrived, and makes them, in the state Delivered.
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
    width: 190,
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
    width: 130,
  },
  {
    id: "catalog.pid",
    header: "PID",
    kind: "text",
    column: "pid",
    value: (line) => line.catalog?.pid ?? null,
    width: 170,
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
    id: "quantity",
    header: "Quantity",
    kind: "integer",
    value: (line) => String(line.quantity),
    numeric: true,
    width: 110,
  },
  {
    id: "received_quantity",
    header: "Received",
    kind: "integer",
    value: (line) => String(line.received_quantity),
    numeric: true,
    width: 110,
  },
  {
    id: "pending_quantity",
    header: "Still to come",
    kind: "integer",
    value: (line) => String(line.pending_quantity),
    numeric: true,
    width: 130,
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
    width: 170,
  },
  {
    id: "expected_on",
    header: "Expected",
    kind: "date",
    value: (line) => line.expected_on,
    width: 130,
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
        <span className="mono">pending_quantity:gt:0</span>, for the list to plan by. A line is
        received on the page of its request.
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
        shortFilter="pending_quantity:gt:0 catalog.vendor:eq:Cisco"
        startFilter={startFilter}
      />
    </>
  );
}

/** `GET /purchase-requests/{hid}/lines`: the field of its `sort` behind each column. */
const LINES_SORT: SortFields = {
  line: "line",
  model: "catalog.vendor,catalog.pid",
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
                · what a person says of it, and Received by itself once every line has arrived in
                full
              </span>
            </dd>
            <dt>Requested on</dt>
            <dd>{record.requested_on ?? <Dash />}</dd>
            <dt>Asked for</dt>
            <dd data-testid="request-quantity">{plural(record.quantity, "item")}</dd>
            <dt>Received</dt>
            <dd data-testid="request-received">{plural(record.received_quantity, "item")}</dd>
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
          <table data-testid="purchase-lines">
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
                  data-pending={row.pending_quantity}
                  data-received={row.received_quantity}
                >
                  <th scope="row">{row.name}</th>
                  <td>
                    {row.catalog_entry_hid === null ? (
                      <span>
                        {lineModel(row)} <span className="muted">· not tracked</span>
                      </span>
                    ) : (
                      <Link to={`/catalog/${encodeURIComponent(row.catalog_entry_hid)}`}>
                        {lineModel(row)}
                      </Link>
                    )}
                    {row.catalog?.model_name && (
                      <span className="muted"> · {row.catalog.model_name}</span>
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
                    {row.received_quantity}
                  </td>
                  <td className="number" data-testid="line-pending">
                    {row.pending_quantity}
                  </td>
                  <td title={row.destination_site?.path}>
                    {row.destination_site?.name ?? <Dash />}
                  </td>
                  <td className="nowrap">{row.expected_on ?? <Dash />}</td>
                  <td className="row-actions">
                    {mayEdit && (
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
          onSaved={() => changed(`${line.name} was saved.`)}
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
            changed(`${made.name} was added: ${made.quantity} × ${lineModel(made)}.`)
          }
        />
      )}
    </section>
  );
}

/** The fields of a line that a form sets. */
function lineSpecs(
  entries: FieldSpec["options"],
  sites: FieldSpec["options"],
  line: PurchaseLine | null,
) {
  const model: FieldSpec = {
    name: "catalog_entry_hid",
    label: "Model",
    kind: "choice",
    required: true,
    options: entries ?? [],
    ...(line ? {} : { blank: "Choose a model" }),
  };
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
  return [model, ...rest];
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
}

function AddLine({ request, onCancel, onAdded }: AddLineProps) {
  const entries = useEntryOptions();
  const sites = useSiteOptions();
  const specs = useMemo(
    () => lineSpecs(entries.data, sites.data, null),
    [entries.data, sites.data],
  );
  return (
    <>
      <Problem error={entries.error ?? sites.error} />
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
      >
        <p className="hint">
          A model and how many. The line takes the next number of the request, and is named by the
          reference and that number, as in {request.reference}/{request.lines.length + 1}.
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

function ChangeLine({ line, onSaved, onReload, onClose }: LineFormProps & { onSaved: () => void }) {
  const entries = useEntryOptions();
  const sites = useSiteOptions();
  const specs = useMemo(
    () =>
      lineSpecs(
        withOwn(entries.data, line.catalog_entry_hid, lineModel(line)),
        withOwn(sites.data, line.destination_site_hid, line.destination_site?.path),
        line,
      ),
    [entries.data, sites.data, line],
  );
  return (
    <section className="panel" aria-labelledby="change-line" data-testid="change-line">
      <h3 id="change-line">Change {line.name}</h3>
      <Problem error={entries.error ?? sites.error} />
      <EditForm<PurchaseLine, Schemas["PurchaseLinePatch"]>
        specs={specs}
        record={line}
        save={(body) =>
          api.request("patch", "/api/v1/purchase-lines/{hid}", { path: { hid: line.hid }, body })
        }
        onSaved={onSaved}
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
  const [found, setFound] = useState({ error: "", countError: "" });
  const action = useAction();
  const known = ["delivered_on", "location_hid", "quantity"];
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
          ...(location === "" ? {} : { location_hid: location }),
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
    <section className="panel" aria-labelledby="receive-line" data-testid="receive-line">
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
              label="Location they were put in"
              name="location_hid"
              value={location}
              onChange={setLocation}
              blank="Not said"
              disabled={action.busy}
              error={refused.location_hid}
            />
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
