import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { effectiveText, inheritHint, isInherited, sourceHint, sourceLabel } from "../lib/effective";
import { formatTime } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useChoices, useEntryOptions, useTags, useVendorOptions, withCurrent } from "../lib/lists";
import {
  CATALOG_KINDS,
  choiceFilterOptions,
  choiceLabel,
  choiceOptions,
  optionLabel,
  RECORD_STATUSES,
  REVIEW_STATUSES,
  SETTABLE_STATUSES,
} from "../lib/options";
import type { FieldSpec, Option } from "../lib/patch";
import { allows } from "../lib/roles";

type Entry = Schemas["CatalogEntryOut"];
type Choice = Schemas["ChoiceOut"];

function entryColumns(choices: readonly Choice[] | undefined): GridColumn<Entry>[] {
  const day = (id: keyof Entry, header: string, hide = true): GridColumn<Entry> => ({
    id,
    header,
    kind: "date",
    value: (entry) => entry[id] as string | null,
    hide,
    width: 130,
  });
  const amount = (id: keyof Entry, header: string, hide = false): GridColumn<Entry> => ({
    id,
    header,
    kind: "number",
    value: (entry) => entry[id] as string | null,
    numeric: true,
    hide,
    width: 150,
  });
  return [
    {
      id: "vendor",
      header: "Vendor",
      kind: "text",
      value: (entry) => entry.vendor.name,
      width: 150,
    },
    { id: "pid", header: "PID", kind: "text", value: (entry) => entry.pid, link: true, width: 170 },
    {
      id: "model_name",
      header: "Model",
      kind: "text",
      value: (entry) => entry.model_name,
      width: 240,
    },
    {
      id: "kind",
      header: "Kind",
      kind: "choice",
      value: (entry) => optionLabel(CATALOG_KINDS, entry.kind),
      choices: CATALOG_KINDS,
      width: 130,
    },
    {
      id: "type",
      header: "Type",
      kind: "choice",
      value: (entry) => choiceLabel(choices, "catalog_type", entry.type),
      choices: choiceFilterOptions(choices, "catalog_type"),
      width: 140,
    },
    {
      id: "function",
      header: "Function",
      kind: "choice",
      value: (entry) => choiceLabel(choices, "catalog_function", entry.function),
      choices: choiceFilterOptions(choices, "catalog_function"),
      width: 140,
    },
    {
      id: "description",
      header: "Description",
      kind: "text",
      value: (entry) => entry.description,
      hide: true,
    },
    amount("est_value", "Estimated value"),
    amount("support_weight", "Support weight"),
    amount("annual_support_cost", "Annual support cost", true),
    {
      id: "stack_discount_pct",
      header: "Stack discount %",
      kind: "number",
      value: (entry) => effectiveText(entry.effective.stack_discount_pct),
      effective: (entry) => entry.effective.stack_discount_pct,
      numeric: true,
      width: 150,
    },
    day("end_of_sale", "End of sale"),
    day("end_of_sw_support", "End of software support"),
    day("end_of_hw_support", "End of hardware support"),
    day("ldos", "LDoS", false),
    {
      id: "review_status",
      header: "Review",
      kind: "choice",
      value: (entry) => optionLabel(REVIEW_STATUSES, entry.review_status),
      choices: REVIEW_STATUSES,
      hide: true,
    },
    {
      id: "record_status",
      header: "Record status",
      kind: "choice",
      value: (entry) => optionLabel(RECORD_STATUSES, entry.record_status),
      choices: RECORD_STATUSES,
      hide: true,
    },
    { id: "tags", header: "Tags", kind: "tags", value: (entry) => entry.tags.join(", ") },
    {
      id: "updated_at",
      header: "Changed",
      kind: "timestamp",
      value: (entry) => formatTime(entry.updated_at),
      hide: true,
    },
    {
      id: "vendor_hid",
      header: "Vendor HID",
      kind: "reference",
      // A file names a vendor by its name: no export has this column.
      column: null,
      value: (entry) => entry.vendor_hid,
      mono: true,
      hide: true,
    },
    {
      id: "hid",
      header: "HID",
      kind: "reference",
      value: (entry) => entry.hid,
      mono: true,
      hide: true,
    },
  ];
}

/** The fields of a catalog entry, for the form that makes one and the form that changes one. */
function entrySpecs(lists: {
  vendors: readonly Option[];
  entries: readonly Option[];
  tags: readonly string[];
  choices: readonly Choice[] | undefined;
  entry: Entry | null;
}): FieldSpec[] {
  const { vendors, entries, tags, choices, entry } = lists;
  const labels = [...new Set([...tags, ...(entry?.tags ?? [])])];
  return [
    {
      name: "vendor_hid",
      label: "Vendor",
      kind: "choice",
      required: true,
      options: withCurrent(vendors, entry && { value: entry.vendor.hid, label: entry.vendor.name }),
      ...(entry ? {} : { blank: "Choose a vendor" }),
    },
    {
      name: "pid",
      label: "PID",
      kind: "text",
      required: true,
      maxLength: 100,
      hint: "The product ID as the vendor writes it",
    },
    { name: "model_name", label: "Model name", kind: "text", maxLength: 200 },
    { name: "kind", label: "Kind", kind: "choice", options: CATALOG_KINDS },
    {
      name: "type",
      label: "Type",
      kind: "choice",
      blank: "No type",
      options: choiceOptions(choices, "catalog_type", entry?.type ?? null),
    },
    {
      name: "function",
      label: "Function",
      kind: "choice",
      blank: "No function",
      options: choiceOptions(choices, "catalog_function", entry?.function ?? null),
    },
    { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
    {
      name: "est_value",
      label: "Estimated value",
      kind: "decimal",
      places: 2,
      hint: "A planning estimate for one unit",
      heading: "What every item of this model inherits",
    },
    {
      name: "support_weight",
      label: "Support weight",
      kind: "decimal",
      places: 2,
      hint: "The relative effort to support one unit",
    },
    {
      name: "annual_support_cost",
      label: "Annual support cost",
      kind: "decimal",
      places: 2,
      hint: "For one unit, for one year",
    },
    { name: "end_of_sale", label: "End of sale", kind: "date" },
    { name: "end_of_sw_support", label: "End of software support", kind: "date" },
    { name: "end_of_hw_support", label: "End of hardware support", kind: "date" },
    { name: "ldos", label: "Last day of support (LDoS)", kind: "date" },
    {
      name: "stack_discount_pct",
      label: "Stack discount %",
      kind: "decimal",
      places: 2,
      hint: "0 to 100. Blank inherits the global setting.",
      heading: "Planning",
    },
    {
      name: "successor_hid",
      label: "Successor",
      kind: "choice",
      blank: "No successor",
      options: entries.filter((option) => option.value !== entry?.hid),
      hint: "The model that replaces this one",
    },
    { name: "review_status", label: "Review status", kind: "choice", options: REVIEW_STATUSES },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: labels.map((label) => ({ value: label, label })),
    },
  ];
}

/** Catalog: the entries by vendor, and the form for a new one. */
export function Catalog() {
  useTitle("Catalog");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const choices = useChoices();
  const columns = useMemo(() => entryColumns(choices.data), [choices.data]);

  return (
    <>
      <h1>Catalog</h1>
      <Problem error={choices.error} />
      {adding && (
        <NewEntry
          choices={choices.data}
          onCancel={() => setAdding(false)}
          onCreated={(entry) => navigate(`/catalog/${encodeURIComponent(entry.hid)}`)}
        />
      )}
      {choices.loading && <p role="status">Loading…</p>}
      {!choices.loading && (
        <DataGrid<Entry>
          key={startFilter ?? ""}
          id="catalog"
          noun={["catalog entry", "catalog entries"]}
          entity="catalog_entries"
          columns={columns}
          load={(request, signal) =>
            api.request("post", "/api/v1/catalog-entries/query", {
              body: queryBody(request),
              signal,
            })
          }
          rowId={(entry) => entry.hid}
          rowLink={(entry) => `/catalog/${encodeURIComponent(entry.hid)}`}
          dimmed={(entry) => entry.record_status !== "active"}
          shortFilter="vendor:eq:Cisco pid:glob:C93*"
          startFilter={startFilter}
          switches={{ archived: "Include retired", drafts: "Include drafts" }}
        >
          {allows(user.role, "inventory") && !adding && (
            <button type="button" className="primary" onClick={() => setAdding(true)}>
              New catalog entry
            </button>
          )}
        </DataGrid>
      )}
    </>
  );
}

interface NewEntryProps {
  choices: readonly Choice[] | undefined;
  onCancel: () => void;
  onCreated: (entry: Entry) => void;
}

function NewEntry({ choices, onCancel, onCreated }: NewEntryProps) {
  const vendors = useVendorOptions();
  const entries = useEntryOptions();
  const tags = useTags();
  const specs = useMemo(
    () =>
      entrySpecs({
        vendors: vendors.data ?? [],
        entries: entries.data ?? [],
        tags: (tags.data ?? []).map((tag) => tag.label),
        choices,
        entry: null,
      }),
    [vendors.data, entries.data, tags.data, choices],
  );
  return (
    <CreateForm<Schemas["CatalogEntryCreate"], Entry>
      title="New catalog entry"
      specs={specs}
      start={{ kind: "hardware", review_status: "reviewed", record_status: "active" }}
      create={(body) => api.request("post", "/api/v1/catalog-entries", { body })}
      onCreated={onCreated}
      onCancel={onCancel}
      submitLabel="Create catalog entry"
    >
      <Problem error={vendors.error ?? entries.error ?? tags.error} />
      {vendors.data?.length === 0 && (
        <p className="alert alert-info">
          There are no vendors yet. <Link to="/vendors">Create a vendor</Link> first.
        </p>
      )}
    </CreateForm>
  );
}

/** Catalog → one entry: what is true of every item of the model. */
export function CatalogEntryDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const entry = useLoad(`catalog-entry ${hid}`, (signal) =>
    api.request("get", "/api/v1/catalog-entries/{hid}", { path: { hid }, signal }),
  );
  const choices = useChoices();
  const [done, setDone] = useState("");
  const record = entry.data;
  useTitle(record ? `${record.vendor.name} ${record.pid}` : "Catalog entry");

  function changed(text: string) {
    setDone(text);
    entry.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/catalog">Catalog</Link>
      </p>
      <h1>
        {record ? `${record.vendor.name} ${record.pid}` : "Catalog entry"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={entry.error} />
      <Problem error={choices.error} />
      <Notice text={done} />
      {entry.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <EntryFacts entry={record} choices={choices.data} />
          {mayEdit && record.record_status !== "retired" && (
            <EntryDetails
              key={`details ${record.hid} ${record.row_version}`}
              entry={record}
              choices={choices.data}
              onSaved={() => changed("The catalog entry was saved.")}
              onReload={entry.reload}
            />
          )}
          {mayEdit && (
            <EntryStatus
              key={`status ${record.hid} ${record.row_version}`}
              entry={record}
              onChanged={changed}
              onReload={entry.reload}
            />
          )}
        </>
      )}
    </>
  );
}

function EntryFacts({ entry, choices }: { entry: Entry; choices: readonly Choice[] | undefined }) {
  const discount = entry.effective.stack_discount_pct;
  const inherited = isInherited(discount);
  const facts: Array<[label: string, value: string | null]> = [
    ["Model name", entry.model_name],
    ["Kind", optionLabel(CATALOG_KINDS, entry.kind)],
    ["Type", choiceLabel(choices, "catalog_type", entry.type)],
    ["Function", choiceLabel(choices, "catalog_function", entry.function)],
    ["Description", entry.description],
    ["Estimated value", entry.est_value],
    ["Support weight", entry.support_weight],
    ["Annual support cost", entry.annual_support_cost],
    ["End of sale", entry.end_of_sale],
    ["End of software support", entry.end_of_sw_support],
    ["End of hardware support", entry.end_of_hw_support],
    ["Last day of support (LDoS)", entry.ldos],
    ["Review status", optionLabel(REVIEW_STATUSES, entry.review_status)],
    ["Tags", entry.tags.join(", ")],
  ];
  return (
    <section aria-labelledby="entry">
      <h2 id="entry">Catalog entry</h2>
      <p>
        <Link to={`/items?filter=${encodeURIComponent(`catalog_entry_hid:eq:${entry.hid}`)}`}>
          Items of this entry
        </Link>
      </p>
      <dl className="facts">
        <dt>Vendor</dt>
        <dd>
          <Link to={`/vendors/${encodeURIComponent(entry.vendor.hid)}`}>{entry.vendor.name}</Link>
        </dd>
        <dt>PID</dt>
        <dd>{entry.pid}</dd>
        {facts.map(([label, value]) => (
          <FactRow key={label} label={label} value={value} />
        ))}
        <dt>Stack discount %</dt>
        <dd data-testid="stack-discount" data-source={discount.source}>
          <span
            className={inherited ? "inherited" : undefined}
            title={sourceHint(discount) || undefined}
          >
            {effectiveText(discount) || "—"}
          </span>
          <span className="muted"> · {sourceLabel(discount)}</span>
        </dd>
        {entry.successor_hid && (
          <>
            <dt>Successor</dt>
            <dd>
              <Link to={`/catalog/${encodeURIComponent(entry.successor_hid)}`}>
                The model that replaces this one
              </Link>
            </dd>
          </>
        )}
        <dt>Changed</dt>
        <dd>
          <Time at={entry.updated_at} />
        </dd>
        <dt>HID</dt>
        <dd className="mono">{entry.hid}</dd>
      </dl>
    </section>
  );
}

function FactRow({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value || <span className="muted">—</span>}</dd>
    </>
  );
}

interface EntryDetailsProps {
  entry: Entry;
  choices: readonly Choice[] | undefined;
  onSaved: () => void;
  onReload: () => void;
}

function EntryDetails({ entry, choices, onSaved, onReload }: EntryDetailsProps) {
  const vendors = useVendorOptions();
  const entries = useEntryOptions();
  const tags = useTags();
  const specs = useMemo(
    () =>
      entrySpecs({
        vendors: vendors.data ?? [],
        entries: entries.data ?? [],
        tags: (tags.data ?? []).map((tag) => tag.label),
        choices,
        entry,
      }),
    [vendors.data, entries.data, tags.data, choices, entry],
  );
  const discount = entry.effective.stack_discount_pct;
  const hints = {
    stack_discount_pct: `0 to 100. ${inheritHint(
      entry.stack_discount_pct,
      discount.source === "own" ? null : discount,
    )}`,
  };
  const ready = !vendors.loading && !entries.loading && !tags.loading;

  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <p className="hint">
        A change to a date or an amount here shows at once on every item of this model that has not
        set its own.
      </p>
      <Problem error={vendors.error ?? entries.error ?? tags.error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <EditForm<Entry, Schemas["CatalogEntryPatch"]>
          specs={specs}
          record={entry}
          hints={hints}
          save={(body) =>
            api.request("patch", "/api/v1/catalog-entries/{hid}", {
              path: { hid: entry.hid },
              body,
            })
          }
          onSaved={onSaved}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface EntryStatusProps {
  entry: Entry;
  onChanged: (text: string) => void;
  onReload: () => void;
}

function EntryStatus({ entry, onChanged, onReload }: EntryStatusProps) {
  const action = useAction();

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/catalog-entries/{hid}/retire", {
        path: { hid: entry.hid },
        body: { row_version: entry.row_version },
      }),
    );
    if (result.ok) onChanged("The catalog entry was retired.");
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/catalog-entries/{hid}", {
        path: { hid: entry.hid },
        body: { row_version: entry.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged("The catalog entry is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{entry.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {entry.record_status === "retired" ? (
        <>
          <p>This catalog entry is retired. Items of the model keep it.</p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
        </>
      ) : (
        <>
          <p>
            A retired catalog entry is no longer offered for new items. Items of the model keep it,
            and what they inherit from it.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Retire catalog entry"
              title={`Retire ${entry.vendor.name} ${entry.pid}?`}
              confirmLabel="Retire catalog entry"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>Items of this model keep it. The entry can be brought back.</p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
