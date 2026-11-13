import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Problem } from "../components/Problem";
import { CreateForm } from "../components/RecordForm";
import { effectiveText } from "../lib/effective";
import { formatMac, formatTime, itemName } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useTitle } from "../lib/hooks";
import { stateNames } from "../lib/lifecycle";
import { useChoices, useEntryOptions, useOwnerOptions, useRules, useTags } from "../lib/lists";
import { CATALOG_KINDS, choiceFilterOptions, choiceLabel, RECORD_STATUSES } from "../lib/options";
import type { FieldSpec, Option } from "../lib/patch";
import { allows } from "../lib/roles";

type Item = Schemas["ItemOut"];
type Choice = Schemas["ChoiceOut"];

const INHERITED: ReadonlyArray<[field: keyof Item["effective"], header: string, shown: boolean]> = [
  ["est_value", "Estimated value", true],
  ["support_weight", "Support weight", false],
  ["annual_support_cost", "Annual support cost", false],
  ["end_of_sale", "End of sale", false],
  ["end_of_sw_support", "End of software support", false],
  ["end_of_hw_support", "End of hardware support", false],
  ["ldos", "LDoS", true],
];
const AMOUNTS = ["est_value", "support_weight", "annual_support_cost"];
const DAYS: ReadonlyArray<[field: keyof Item, header: string]> = [
  ["procured_on", "Procured"],
  ["delivered_on", "Delivered"],
  ["in_service_on", "In service"],
  ["warranty_start", "Warranty start"],
  ["warranty_end", "Warranty end"],
];

function yesNo(value: boolean | null): string {
  return value === null ? "" : value ? "Yes" : "No";
}

/** The columns of the item grid. Most are there to be shown when wanted. */
export function itemColumns(
  choices: readonly Choice[] | undefined,
  states: readonly string[],
): GridColumn<Item>[] {
  const named = (list: readonly string[]): Option[] =>
    list.map((value) => ({ value, label: value }));
  return [
    { id: "name", header: "Name", kind: "text", value: itemName, link: true, width: 220 },
    {
      id: "hostname",
      header: "Hostname",
      kind: "text",
      value: (item) => item.hostname,
      hide: true,
    },
    {
      id: "catalog.vendor",
      header: "Vendor",
      kind: "text",
      value: (item) => item.catalog?.vendor,
      width: 130,
    },
    {
      id: "catalog.pid",
      header: "PID",
      kind: "text",
      value: (item) => item.catalog?.pid,
      width: 150,
    },
    {
      id: "catalog.model_name",
      header: "Model",
      kind: "text",
      value: (item) => item.catalog?.model_name,
      hide: true,
    },
    {
      id: "serial_number",
      header: "Serial number",
      kind: "text",
      value: (item) => item.serial_number,
      mono: true,
      width: 150,
    },
    {
      id: "asset_tag",
      header: "Asset tag",
      kind: "text",
      value: (item) => item.asset_tag,
      hide: true,
    },
    {
      id: "lifecycle_state",
      header: "State",
      kind: "choice",
      value: (item) => item.lifecycle_state,
      choices: named(states),
      width: 140,
    },
    {
      id: "disposition",
      header: "Disposition",
      kind: "choice",
      value: (item) => item.disposition,
      choices: named(["Staging", "Production", "Spare", "Excess"]),
      width: 130,
    },
    {
      id: "expected_online",
      header: "Expected online",
      kind: "boolean",
      value: (item) => yesNo(item.expected_online),
      width: 140,
    },
    {
      id: "state_reason",
      header: "State reason",
      kind: "choice",
      value: (item) => choiceLabel(choices, "state_reason", item.state_reason),
      choices: choiceFilterOptions(choices, "state_reason"),
      hide: true,
    },
    {
      id: "state_changed_at",
      header: "State changed",
      kind: "timestamp",
      value: (item) => formatTime(item.state_changed_at),
      hide: true,
    },
    {
      id: "owner.label",
      header: "Owner",
      kind: "text",
      value: (item) => item.owner?.label,
      width: 170,
    },
    { id: "tags", header: "Tags", kind: "tags", value: (item) => item.tags.join(", "), width: 160 },
    ...INHERITED.map(
      ([field, header, shown]): GridColumn<Item> => ({
        id: `effective.${field}`,
        header,
        kind: AMOUNTS.includes(field) ? "number" : "date",
        value: (item) => effectiveText(item.effective[field]),
        effective: (item) => item.effective[field],
        numeric: AMOUNTS.includes(field),
        hide: !shown,
        width: 150,
      }),
    ),
    {
      id: "catalog.kind",
      header: "Kind",
      kind: "choice",
      value: (item) => CATALOG_KINDS.find((kind) => kind.value === item.catalog?.kind)?.label,
      choices: CATALOG_KINDS,
      hide: true,
    },
    {
      id: "catalog.type",
      header: "Type",
      kind: "choice",
      value: (item) => choiceLabel(choices, "catalog_type", item.catalog?.type),
      choices: choiceFilterOptions(choices, "catalog_type"),
      hide: true,
    },
    {
      id: "catalog.function",
      header: "Function",
      kind: "choice",
      value: (item) => choiceLabel(choices, "catalog_function", item.catalog?.function),
      choices: choiceFilterOptions(choices, "catalog_function"),
      hide: true,
    },
    {
      id: "mac_address",
      header: "MAC address",
      kind: "mac",
      value: (item) => formatMac(item.mac_address),
      mono: true,
      hide: true,
    },
    { id: "fqdn", header: "FQDN", kind: "text", value: (item) => item.fqdn, hide: true },
    {
      id: "quantity",
      header: "Quantity",
      kind: "integer",
      value: (item) => String(item.quantity),
      numeric: true,
      hide: true,
    },
    ...DAYS.map(
      ([field, header]): GridColumn<Item> => ({
        id: field,
        header,
        kind: "date",
        value: (item) => item[field] as string | null,
        hide: true,
      }),
    ),
    {
      id: "description",
      header: "Description",
      kind: "text",
      value: (item) => item.description,
      hide: true,
    },
    {
      id: "comments",
      header: "Comments",
      kind: "text",
      value: (item) => item.comments,
      hide: true,
    },
    {
      id: "record_status",
      header: "Record status",
      kind: "choice",
      value: (item) => RECORD_STATUSES.find((status) => status.value === item.record_status)?.label,
      choices: RECORD_STATUSES,
      hide: true,
    },
    {
      id: "updated_at",
      header: "Changed",
      kind: "timestamp",
      value: (item) => formatTime(item.updated_at),
      hide: true,
    },
    {
      id: "created_at",
      header: "Created",
      kind: "timestamp",
      value: (item) => formatTime(item.created_at),
      hide: true,
    },
    {
      id: "hid",
      header: "HID",
      kind: "reference",
      value: (item) => item.hid,
      mono: true,
      hide: true,
    },
  ];
}

/** An item that a list shows greyed: a draft, a retired record, or one in Archived. */
export function itemIsDimmed(item: Item): boolean {
  return item.record_status !== "active" || item.lifecycle_state === "Archived";
}

/** Items: the main grid, the filter box, and the form for a new item. */
export function Items() {
  useTitle("Items");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
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
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <DataGrid<Item>
          key={startFilter ?? ""}
          id="items"
          noun={["item", "items"]}
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
        >
          {allows(user.role, "inventory") && !adding && (
            <button type="button" className="primary" onClick={() => setAdding(true)}>
              New item
            </button>
          )}
        </DataGrid>
      )}
    </>
  );
}

interface NewItemProps {
  states: readonly string[];
  onCancel: () => void;
  onCreated: (item: Item) => void;
}

function NewItem({ states, onCancel, onCreated }: NewItemProps) {
  const entries = useEntryOptions();
  const owners = useOwnerOptions();
  const tags = useTags();
  const specs = useMemo<FieldSpec[]>(
    () => [
      {
        name: "catalog_entry_hid",
        label: "Catalog entry",
        kind: "choice",
        blank: "No catalog entry",
        options: entries.data ?? [],
        hint: "The vendor and PID. A serial number needs one.",
      },
      { name: "serial_number", label: "Serial number", kind: "text", maxLength: 100 },
      { name: "asset_tag", label: "Asset tag", kind: "text", maxLength: 100 },
      {
        name: "name",
        label: "Name",
        kind: "text",
        maxLength: 200,
        hint: "Left blank, the hostname is shown",
      },
      { name: "hostname", label: "Hostname", kind: "text", maxLength: 255 },
      {
        name: "mac_address",
        label: "MAC address",
        kind: "text",
        maxLength: 40,
        hint: "In any common notation",
      },
      {
        name: "owner_hid",
        label: "Owner",
        kind: "choice",
        blank: "No owner",
        options: owners.data ?? [],
      },
      {
        name: "lifecycle_state",
        label: "Lifecycle state",
        kind: "choice",
        blank: "No state yet",
        options: states.map((state) => ({ value: state, label: state })),
        hint: "The disposition and intent are set as the state has them on entry",
      },
      {
        name: "tags",
        label: "Tags",
        kind: "set",
        options: (tags.data ?? []).map((tag) => ({ value: tag.label, label: tag.label })),
      },
    ],
    [entries.data, owners.data, tags.data, states],
  );

  return (
    <CreateForm<Schemas["ItemCreate"], Item>
      title="New item"
      specs={specs}
      create={(body) => api.request("post", "/api/v1/items", { body })}
      onCreated={onCreated}
      onCancel={onCancel}
      submitLabel="Create item"
    >
      <Problem error={entries.error ?? owners.error ?? tags.error} />
      <p className="hint">
        An item needs something to know it by: a serial number with a catalog entry, an asset tag, a
        name or a hostname. Everything else may be left blank and filled in later.
      </p>
    </CreateForm>
  );
}
