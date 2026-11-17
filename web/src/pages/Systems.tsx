import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { ChangeRegistration } from "../components/Registrations";
import { Retire } from "../components/Retire";
import { Time } from "../components/Time";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useLoad, useTitle } from "../lib/hooks";
import { useChoices } from "../lib/lists";
import {
  choiceFilterOptions,
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";
import {
  type ExternalSystem,
  leftOutHint,
  REGISTRATION_STATUSES,
  type Registration,
  registeredPath,
  registeredRecord,
  SYSTEM_KIND_LIST,
  startingKind,
  systemPath,
} from "../lib/systems";

type Choice = Schemas["ChoiceOut"];

/**
 * The columns of the list of systems. 0.9.3: a kind is shown by its label in the list
 * `system_kind`, a value that is no longer offered among them, and filtered by any of its
 * values (P-170).
 */
const systemColumns = (choices: readonly Choice[] | undefined): GridColumn<ExternalSystem>[] => [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (system) => system.name,
    link: true,
    width: 220,
  },
  {
    id: "kind",
    header: "Kind",
    kind: "choice",
    value: (system) => choiceLabel(choices, SYSTEM_KIND_LIST, system.kind),
    choices: choiceFilterOptions(choices, SYSTEM_KIND_LIST),
    width: 190,
  },
  {
    // How many records are registered with it, those removed not counted.
    id: "registrations",
    header: "Registrations",
    kind: "integer",
    field: null,
    sortField: "registrations",
    column: null,
    value: (system) => String(system.registrations),
    numeric: true,
    width: 140,
  },
  { id: "url", header: "URL", kind: "text", value: (system) => system.url, width: 280 },
  { id: "notes", header: "Notes", kind: "text", value: (system) => system.notes, width: 320 },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (system) => optionLabel(RECORD_STATUSES, system.record_status),
    choices: RECORD_STATUSES,
    hide: true,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (system) => formatTime(system.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (system) => system.hid,
    mono: true,
    hide: true,
  },
];

/**
 * The fields of a system. The kinds offered are the active values of the list, with
 * their labels; a system that holds one no longer offered is offered it too, marked as
 * inactive, so that a change of anything else keeps it. A new system may be given none.
 */
function systemSpecs(
  choices: readonly Choice[] | undefined,
  record: ExternalSystem | null,
): FieldSpec[] {
  const kind: FieldSpec = record
    ? {
        name: "kind",
        label: "Kind",
        kind: "choice",
        options: choiceOptions(choices, SYSTEM_KIND_LIST, record.kind),
      }
    : {
        name: "kind",
        label: "Kind",
        kind: "choice",
        blank: "None given",
        options: choiceOptions(choices, SYSTEM_KIND_LIST),
        hint: leftOutHint(choices),
      };
  return [
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 200,
      hint: "The installation's own name for it. Records are found by it: registration.system:eq:<name>",
    },
    kind,
    {
      name: "url",
      label: "URL",
      kind: "text",
      maxLength: 2000,
      hint: "Where the system is reached.",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
  ];
}

/**
 * External systems: the monitoring tools, SDN controllers, cloud services and the like
 * that items and device groups are registered with, each with how many records it knows.
 */
export function Systems() {
  useTitle("External systems");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const choices = useChoices();
  const columns = useMemo(() => systemColumns(choices.data), [choices.data]);

  return (
    <>
      <h1>External systems</h1>
      <p>
        The other systems that know the inventory: a monitoring tool, an SDN controller, a cloud
        service. An item or a device group is registered with a system on its own page, and a stack
        that a system knows as one device is registered as the stack.
      </p>
      <Problem error={choices.error} />
      {adding && choices.data && (
        <CreateForm<Schemas["ExternalSystemCreate"], ExternalSystem>
          title="New external system"
          specs={systemSpecs(choices.data, null)}
          start={{ kind: startingKind(choices.data), record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/external-systems", { body })}
          onCreated={(system) => navigate(systemPath(system.hid))}
          onCancel={() => setAdding(false)}
          submitLabel="Create system"
        />
      )}
      {choices.loading && <p role="status">Loading…</p>}
      {!choices.loading && (
        <DataGrid<ExternalSystem>
          key={startFilter ?? ""}
          id="external-systems"
          noun={["system", "systems"]}
          entity="external_systems"
          columns={columns}
          load={(request, signal) =>
            api.request("get", "/api/v1/external-systems", { query: queryParams(request), signal })
          }
          rowId={(system) => system.hid}
          rowLink={(system) => systemPath(system.hid)}
          dimmed={(system) => system.record_status !== "active"}
          shortFilter="kind:eq:monitoring"
          quickFields={["name"]}
          startFilter={startFilter}
          switches={{ archived: "Include archived", drafts: "Include drafts" }}
        >
          {allows(user.role, "inventory") && !adding && (
            <button type="button" className="primary" onClick={() => setAdding(true)}>
              New system
            </button>
          )}
        </DataGrid>
      )}
    </>
  );
}

const REGISTRATION_COLUMNS: GridColumn<Registration>[] = [
  {
    // What is registered, an item or a group, by the name it is shown by.
    id: "holder",
    header: "Record",
    kind: "text",
    column: ["item", "group"],
    value: (registration) => registeredRecord(registration)?.name,
    hint: (registration) => registeredRecord(registration)?.kind,
    link: true,
    width: 240,
  },
  {
    // Filled for a registration of a device group, as that of a stack: blank for an item.
    id: "group.name",
    header: "Device group",
    kind: "text",
    column: "group",
    value: (registration) => registration.group?.name,
    width: 200,
  },
  {
    id: "item.serial_number",
    header: "Serial number",
    kind: "text",
    column: null,
    value: (registration) => registration.item?.serial_number,
    mono: true,
    width: 150,
  },
  {
    id: "external_id",
    header: "Its key there",
    kind: "text",
    value: (registration) => registration.external_id,
    mono: true,
    width: 180,
  },
  {
    id: "status",
    header: "Status",
    kind: "choice",
    value: (registration) => optionLabel(REGISTRATION_STATUSES, registration.status),
    choices: REGISTRATION_STATUSES,
    width: 130,
  },
  {
    id: "confirmed_at",
    header: "Confirmed",
    kind: "timestamp",
    value: (registration) => formatTime(registration.confirmed_at),
    width: 190,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    column: null,
    value: (registration) => formatTime(registration.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (registration) => registration.hid,
    mono: true,
    hide: true,
  },
];

/** External systems → one system: what it is, and the records registered with it. */
export function SystemDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const system = useLoad(`system ${hid}`, (signal) =>
    api.request("get", "/api/v1/external-systems/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const [done, setDone] = useState("");
  const record = system.data;
  useTitle(record ? record.name : "External system");
  // 0.9.3: the kind by its label in the list, which a site may have changed (P-170).
  const kind = record ? choiceLabel(choices.data, SYSTEM_KIND_LIST, record.kind) : "";

  function changed(text: string) {
    setDone(text);
    system.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/systems">External systems</Link>
      </p>
      <h1>
        {record ? record.name : "External system"}
        {record && (
          <span className="badge badge-plain" data-testid="system-kind">
            {kind}
          </span>
        )}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={system.error ?? choices.error} />
      <Notice text={done} />
      {system.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="facts" data-testid="system-facts">
            <dt>Name</dt>
            <dd>{record.name}</dd>
            <dt>Kind</dt>
            <dd data-testid="system-kind-fact">{kind}</dd>
            <dt>URL</dt>
            <dd>
              {record.url && /^https?:\/\//i.test(record.url) ? (
                <a href={record.url} target="_blank" rel="noopener noreferrer">
                  {record.url}
                </a>
              ) : (
                record.url || <span className="muted">—</span>
              )}
            </dd>
            <dt>Registered with it</dt>
            <dd data-testid="system-registrations">
              {plural(record.registrations, "record")}
              <span className="muted"> · registrations that are removed are not counted: </span>
              <Link to={registeredPath("items", record.name)}>the items</Link>
              <span className="muted"> and </span>
              <Link to={registeredPath("groups", record.name)}>the device groups</Link>
              <span className="muted"> in their grids</span>
            </dd>
            <dt>Notes</dt>
            <dd>{record.notes || <span className="muted">—</span>}</dd>
            <dt>Record status</dt>
            <dd>{optionLabel(RECORD_STATUSES, record.record_status)}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <SystemRegistrations system={record} mayEdit={mayEdit} onChanged={changed} />
          {mayEdit && record.record_status !== "retired" && choices.data && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<ExternalSystem, Schemas["ExternalSystemPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={systemSpecs(choices.data, record)}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/external-systems/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The system was saved.")}
                onReload={system.reload}
              />
            </section>
          )}
          {mayEdit && (
            <Retire
              key={`status ${record.hid} ${record.row_version}`}
              what="system"
              name={record.name}
              retired={record.record_status === "retired"}
              about="A retired system takes no new registration. Its registrations stay on record."
              retiredAbout="This system is retired: it takes no new registration. Its registrations are still on record."
              retire={() =>
                api.request("post", "/api/v1/external-systems/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/external-systems/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={system.reload}
            />
          )}
        </>
      )}
    </>
  );
}

interface SystemRegistrationsProps {
  system: ExternalSystem;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * The registrations of one system, as a grid: sorted, filtered and paged by the server.
 * A record is registered from its own page; here the registration of a row selected is
 * changed, and one that ends is given the status Removed.
 */
function SystemRegistrations({ system, mayEdit, onChanged }: SystemRegistrationsProps) {
  const [reloads, setReloads] = useState(0);
  const [editing, setEditing] = useState<Registration | null>(null);
  const within = useMemo(
    () => ({ filter: { field: "system_hid", op: "eq" as const, value: system.hid } }),
    [system.hid],
  );
  return (
    <section aria-labelledby="system-registrations">
      <h2 id="system-registrations">Registrations</h2>
      <p>
        The items and the device groups registered with {system.name}, those removed among them. A
        record is registered with a system from its own page, under Registered with.
      </p>
      {mayEdit && editing && (
        <ChangeRegistration
          key={`${editing.hid} ${editing.row_version}`}
          registration={editing}
          onSaved={() => {
            const name = registeredRecord(editing)?.name ?? "the record";
            setEditing(null);
            setReloads((count) => count + 1);
            onChanged(`The registration of ${name} was saved.`);
          }}
          onRemoved={() => {
            const name = registeredRecord(editing)?.name ?? "the record";
            setEditing(null);
            setReloads((count) => count + 1);
            onChanged(
              `The registration of ${name} with ${system.name} was removed. The audit trail holds what it was.`,
            );
          }}
          onReload={() => {
            setEditing(null);
            setReloads((count) => count + 1);
          }}
          onClose={() => setEditing(null)}
        />
      )}
      <DataGrid<Registration>
        id="system-registrations"
        noun={["registration", "registrations"]}
        entity="registrations"
        columns={REGISTRATION_COLUMNS}
        within={within}
        reloadKey={reloads}
        load={(request, signal) =>
          api.request("get", "/api/v1/registrations", { query: queryParams(request), signal })
        }
        rowId={(registration) => registration.hid}
        rowLink={(registration) => registeredRecord(registration)?.path ?? systemPath(system.hid)}
        dimmed={(registration) => registration.status === "removed"}
        {...(mayEdit
          ? {
              actions: [
                {
                  label: "Change registration",
                  rowsOnly: true,
                  run: (_chosen, _view, rows) =>
                    setEditing(rows.length === 1 ? (rows[0] ?? null) : null),
                },
              ],
            }
          : {})}
      />
      {mayEdit && (
        <p className="hint">
          Change registration takes one row: select it, then choose the button. A registration that
          ends is given the status Removed and stays on record; one that was a mistake is removed
          there.
        </p>
      )}
    </section>
  );
}
