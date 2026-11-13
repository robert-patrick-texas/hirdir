import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { formatTime } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";

type Owner = Schemas["OwnerOut"];

const COLUMNS: GridColumn<Owner>[] = [
  {
    id: "label",
    header: "Label",
    kind: "text",
    value: (owner) => owner.label,
    link: true,
    width: 260,
  },
  {
    id: "organization",
    header: "Organization",
    kind: "text",
    value: (owner) => owner.organization,
    width: 220,
  },
  {
    id: "is_external",
    header: "External",
    kind: "boolean",
    value: (owner) => (owner.is_external ? "Yes" : "No"),
    width: 120,
  },
  {
    id: "exception_reason",
    header: "Reason for the exception",
    kind: "text",
    value: (owner) => owner.exception_reason,
    width: 320,
  },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (owner) => optionLabel(RECORD_STATUSES, owner.record_status),
    choices: RECORD_STATUSES,
    width: 140,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (owner) => formatTime(owner.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (owner) => owner.hid,
    mono: true,
    hide: true,
  },
];

const SPECS: FieldSpec[] = [
  { name: "label", label: "Label", kind: "text", required: true, maxLength: 200 },
  { name: "organization", label: "Organization", kind: "text", maxLength: 200 },
  {
    name: "is_external",
    label: "Outside the operations team",
    kind: "boolean",
    hint: "An owner outside the team is an exception, and needs a reason",
  },
  {
    name: "exception_reason",
    label: "Reason for the exception",
    kind: "longtext",
    maxLength: 10000,
    hint: "Required for an owner outside the operations team",
  },
  { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
];

/** Owners: who answers for an item. */
export function Owners() {
  useTitle("Owners");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);

  return (
    <>
      <h1>Owners</h1>
      {adding && (
        <CreateForm<Schemas["OwnerCreate"], Owner>
          title="New owner"
          specs={SPECS}
          start={{ record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/owners", { body })}
          onCreated={(owner) => navigate(`/owners/${encodeURIComponent(owner.hid)}`)}
          onCancel={() => setAdding(false)}
          submitLabel="Create owner"
        />
      )}
      <DataGrid<Owner>
        id="owners"
        noun={["owner", "owners"]}
        entity="owners"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/owners", { query: queryParams(request), signal })
        }
        rowId={(owner) => owner.hid}
        rowLink={(owner) => `/owners/${encodeURIComponent(owner.hid)}`}
        dimmed={(owner) => owner.record_status !== "active"}
        switches={{ archived: "Include retired", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New owner
          </button>
        )}
      </DataGrid>
    </>
  );
}

/** Owners → one owner. */
export function OwnerDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const owner = useLoad(`owner ${hid}`, (signal) =>
    api.request("get", "/api/v1/owners/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const record = owner.data;
  useTitle(record ? record.label : "Owner");

  function changed(text: string) {
    setDone(text);
    owner.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/owners">Owners</Link>
      </p>
      <h1>
        {record ? record.label : "Owner"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={owner.error} />
      <Notice text={done} />
      {owner.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <p>
            <Link to={`/items?filter=${encodeURIComponent(`owner_hid:eq:${record.hid}`)}`}>
              Items of this owner
            </Link>
          </p>
          <dl className="facts">
            <dt>Label</dt>
            <dd>{record.label}</dd>
            <dt>Organization</dt>
            <dd>{record.organization || <span className="muted">—</span>}</dd>
            <dt>Outside the operations team</dt>
            <dd>{record.is_external ? "Yes" : "No"}</dd>
            <dt>Reason for the exception</dt>
            <dd>{record.exception_reason || <span className="muted">—</span>}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          {mayEdit && record.record_status !== "retired" && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<Owner, Schemas["OwnerPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={SPECS}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/owners/{hid}", { path: { hid: record.hid }, body })
                }
                onSaved={() => changed("The owner was saved.")}
                onReload={owner.reload}
              />
            </section>
          )}
          {mayEdit && (
            <OwnerStatus
              key={`status ${record.hid} ${record.row_version}`}
              owner={record}
              onChanged={changed}
              onReload={owner.reload}
            />
          )}
        </>
      )}
    </>
  );
}

interface OwnerStatusProps {
  owner: Owner;
  onChanged: (text: string) => void;
  onReload: () => void;
}

function OwnerStatus({ owner, onChanged, onReload }: OwnerStatusProps) {
  const action = useAction();

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/owners/{hid}/retire", {
        path: { hid: owner.hid },
        body: { row_version: owner.row_version },
      }),
    );
    if (result.ok) onChanged("The owner was retired.");
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/owners/{hid}", {
        path: { hid: owner.hid },
        body: { row_version: owner.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged("The owner is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{owner.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {owner.record_status === "retired" ? (
        <>
          <p>This owner is retired. Items keep it.</p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
        </>
      ) : (
        <>
          <p>A retired owner is no longer offered for items. Items that have it keep it.</p>
          <p className="actions">
            <ConfirmButton
              label="Retire owner"
              title={`Retire ${owner.label}?`}
              confirmLabel="Retire owner"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>Items of this owner keep it. The owner can be brought back.</p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
