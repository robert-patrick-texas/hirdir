import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { VendorContacts } from "../components/CircuitContacts";
import { CircuitsGrid } from "../components/CircuitsGrid";
import { CIRCUIT_GROUP_COLUMNS } from "../components/grid/circuitColumns";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { VendorPortfolio } from "../components/Portfolio";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import {
  type CircuitGroup,
  circuitGroupPath,
  circuitIsDimmed,
  circuitsOfCarrier,
  networksOfCarrier,
} from "../lib/circuits";
import { formatTime } from "../lib/format";
import { queryBody, queryParams } from "../lib/gridQuery";
import { useLoad, useTitle } from "../lib/hooks";
import { optionLabel, REVIEW_STATUSES } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";

type Vendor = Schemas["VendorOut"];

const COLUMNS: GridColumn<Vendor>[] = [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (vendor) => vendor.name,
    link: true,
    width: 240,
  },
  {
    id: "aliases",
    header: "Also known as",
    kind: "text",
    // The server does not filter or sort by an alias.
    field: null,
    sortField: "aliases",
    value: (vendor) => vendor.aliases.join(", "),
    width: 280,
  },
  { id: "notes", header: "Notes", kind: "text", value: (vendor) => vendor.notes, width: 360 },
  {
    // An import that had to create a vendor leaves it unreviewed, for somebody to look at.
    id: "review_status",
    header: "Review",
    kind: "choice",
    value: (vendor) => optionLabel(REVIEW_STATUSES, vendor.review_status),
    choices: REVIEW_STATUSES,
    width: 130,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (vendor) => formatTime(vendor.updated_at),
    width: 180,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (vendor) => vendor.hid,
    mono: true,
    hide: true,
  },
];

const SPECS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text", required: true, maxLength: 200 },
  {
    name: "aliases",
    label: "Also known as",
    kind: "lines",
    hint: "Other spellings accepted on import, one to a line",
  },
  { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
  { name: "review_status", label: "Review status", kind: "choice", options: REVIEW_STATUSES },
];

/** Vendors: manufacturers and support providers. */
export function Vendors() {
  useTitle("Vendors");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);

  return (
    <>
      <h1>Vendors</h1>
      <p>
        Manufacturers and support providers. A vendor has a page of its own, with its portfolio:
        everything it makes or provides, with the cover of each model.
      </p>
      {adding && (
        <CreateForm<Schemas["VendorCreate"], Vendor>
          title="New vendor"
          specs={SPECS}
          start={{ review_status: "reviewed" }}
          create={(body) => api.request("post", "/api/v1/vendors", { body })}
          onCreated={(vendor) => navigate(`/vendors/${encodeURIComponent(vendor.hid)}`)}
          onCancel={() => setAdding(false)}
          submitLabel="Create vendor"
        />
      )}
      <DataGrid<Vendor>
        key={startFilter ?? ""}
        id="vendors"
        noun={["vendor", "vendors"]}
        entity="vendors"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/vendors", { query: queryParams(request), signal })
        }
        rowId={(vendor) => vendor.hid}
        rowLink={(vendor) => `/vendors/${encodeURIComponent(vendor.hid)}`}
        shortFilter="name:contains:Networks review_status:eq:unreviewed"
        quickFields={["name"]}
        startFilter={startFilter}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New vendor
          </button>
        )}
      </DataGrid>
    </>
  );
}

/**
 * Vendors → one vendor: its name, the other names it goes by and its notes, and its
 * portfolio: the totals, the kinds, the models with their dates and their cover,
 * the agreements, the contracts and the capacity lines of the vendor, and its items.
 */
export function VendorDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const vendor = useLoad(`vendor ${hid}`, (signal) =>
    api.request("get", "/api/v1/vendors/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const record = vendor.data;
  useTitle(record ? record.name : "Vendor");

  return (
    <>
      <p className="crumbs">
        <Link to="/vendors">Vendors</Link>
      </p>
      <h1>
        {record ? record.name : "Vendor"}
        {record?.review_status === "unreviewed" && <span className="badge">Unreviewed</span>}
      </h1>
      <Problem error={vendor.error} />
      <Notice text={done} />
      {vendor.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <p>
            <Link to={`/catalog?filter=${encodeURIComponent(`vendor_hid:eq:${record.hid}`)}`}>
              Catalog entries of this vendor
            </Link>
          </p>
          <dl className="facts">
            <dt>Name</dt>
            <dd>{record.name}</dd>
            <dt>Also known as</dt>
            <dd>{record.aliases.join(", ") || <span className="muted">—</span>}</dd>
            <dt>Notes</dt>
            <dd>{record.notes || <span className="muted">—</span>}</dd>
            <dt>Review status</dt>
            <dd data-testid="review-status">
              {optionLabel(REVIEW_STATUSES, record.review_status)}
            </dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <VendorPortfolio key={record.hid} vendor={record} />
          {/* 0.8.0: a carrier's account team and support desk, and its circuits (P-149). */}
          <VendorContacts
            key={`contacts ${record.hid} ${record.row_version}`}
            vendor={record}
            mayEdit={allows(user.role, "inventory")}
            onChanged={(text) => {
              setDone(text);
              vendor.reload();
            }}
          />
          <section aria-labelledby="vendor-circuits">
            <h2 id="vendor-circuits">Circuits</h2>
            <p className="hint">
              The circuits {record.name} is a carrier of, as the primary carrier or another.
            </p>
            <CircuitsGrid
              id="vendor-circuits"
              within={{ filter: circuitsOfCarrier(record.hid) }}
              switches
            />
          </section>
          {/* 0.9.18: the networks it is the carrier of, which a Z side may name (P-320). */}
          <section aria-labelledby="vendor-networks">
            <h2 id="vendor-networks">Networks</h2>
            <p className="hint">
              The circuit groups of the kind Network whose carrier {record.name} is: what the Z side
              of a circuit may name as the network it reaches.
            </p>
            <DataGrid<CircuitGroup>
              id="vendor-networks"
              noun={["network", "networks"]}
              entity="circuit_groups"
              columns={CIRCUIT_GROUP_COLUMNS}
              within={{ filter: networksOfCarrier(record.hid) }}
              load={(request, signal) =>
                api.request("post", "/api/v1/circuit-groups/query", {
                  body: queryBody(request),
                  signal,
                })
              }
              rowId={(group) => group.hid}
              rowLink={(group) => circuitGroupPath(group.hid)}
              dimmed={circuitIsDimmed}
              switches={{ archived: "Include archived" }}
            />
          </section>
          {allows(user.role, "inventory") && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<Vendor, Schemas["VendorPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={SPECS}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/vendors/{hid}", { path: { hid: record.hid }, body })
                }
                onSaved={() => {
                  setDone("The vendor was saved.");
                  vendor.reload();
                }}
                onReload={vendor.reload}
              />
            </section>
          )}
        </>
      )}
    </>
  );
}
