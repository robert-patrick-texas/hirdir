// The columns of the item grid, and which field of the server each one filters and
// sorts by. They are kept apart from the page so that those choices can be tested.

import type { Schemas } from "../../api/client";
import { addressList, managementText, networkLabels } from "../../lib/addresses";
import { effectiveLabel, effectiveText, locationHint } from "../../lib/effective";
import type { FilterNode } from "../../lib/filter";
import { formatMac, formatTime, itemName } from "../../lib/format";
import { GROUP_TYPES, groupTypeLabel } from "../../lib/groups";
import {
  CONDITION_LIST,
  HEALTHS,
  healthLabel,
  OBSERVED,
  observedLabel,
  reasonsText,
} from "../../lib/health";
import { DISPOSITIONS } from "../../lib/lifecycle";
import { markOf, operatorHint, operatorPath } from "../../lib/operators";
import {
  CATALOG_KINDS,
  choiceFilterOptions,
  choiceLabel,
  RECORD_STATUSES,
} from "../../lib/options";
import type { Option } from "../../lib/patch";
import { nameOf } from "../../lib/places";
import type { GridColumn } from "./columns";

type Item = Schemas["ItemOut"];
type Choice = Schemas["ChoiceOut"];

type FromCatalog =
  | "est_value"
  | "support_weight"
  | "annual_support_cost"
  | "end_of_sale"
  | "end_of_sw_support"
  | "end_of_hw_support"
  | "ldos";

const INHERITED: ReadonlyArray<[field: FromCatalog, header: string, shown: boolean]> = [
  // The money is in the management report. In the grid it is there for the asking.
  ["est_value", "Estimated value", false],
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

const MAJOR_OR_MINOR: readonly Option[] = [
  { value: "true", label: "Major" },
  { value: "false", label: "Minor" },
];

/** The types of the groups an item is a current member of, each once. */
function groupTypes(item: Item): string {
  return [...new Set(item.groups.map((group) => groupTypeLabel(group.type)))].join(", ");
}

/**
 * The columns of the item grid. Most are there to be shown when wanted.
 *
 * The state, the disposition, the intent and the owner are the ones in force: a minor
 * item with none of its own shows those of the item it is in, in the lighter style of an
 * inherited value, and each of these columns filters and sorts by the value in force
 * too, so that a filter keeps the rows whose cell shows what was asked for. The item's
 * own state is `lifecycle_state` in the filter box.
 *
 * Health is shown from the start, as a mark in its colour with its word, and filters and
 * sorts by the health the server works out. The condition and what is observed, the two
 * facts a person sets, are columns to be asked for.
 *
 * The location, the site and the region are those of the location in force: a minor
 * item with no location of its own is where the item it is in is, and shows that
 * lighter. The Location column shows the name of the location, which is what the server
 * filters and sorts by, with the whole path as the hint of the cell and in an export;
 * the Region column shows the name of the region the site is in. All three are hidden
 * until asked for, as every column that arrived after the first ones is.
 *
 * An item may be in several groups and have several addresses. The columns that show
 * them are filtered by any of them, and the server does not sort by them.
 */
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
      id: "is_major",
      header: "Major or minor",
      kind: "boolean",
      value: (item) => (item.is_major ? "Major" : "Minor"),
      choices: MAJOR_OR_MINOR,
      hide: true,
      width: 140,
    },
    {
      id: "parent",
      header: "In item",
      kind: "text",
      // The list is filtered by the HID of the item above, not by its name: see the
      // link from an item's page to its minor items.
      field: null,
      sortField: null,
      value: (item) => (item.parent ? itemName(item.parent) : ""),
      hide: true,
      width: 200,
    },
    {
      id: "position",
      header: "Position",
      kind: "text",
      value: (item) => item.position,
      hide: true,
      width: 110,
    },
    {
      id: "depth",
      header: "Depth",
      kind: "integer",
      value: (item) => String(item.depth),
      numeric: true,
      hide: true,
      width: 90,
    },
    {
      id: "lifecycle_state",
      header: "State",
      kind: "choice",
      field: "effective.lifecycle_state",
      value: (item) => effectiveText(item.effective.lifecycle_state),
      effective: (item) => item.effective.lifecycle_state,
      choices: named(states),
      width: 140,
    },
    {
      id: "disposition",
      header: "Disposition",
      kind: "choice",
      field: "effective.disposition",
      value: (item) => effectiveText(item.effective.disposition),
      effective: (item) => item.effective.disposition,
      choices: named(DISPOSITIONS),
      width: 130,
    },
    {
      id: "expected_online",
      header: "Expected online",
      kind: "boolean",
      field: "effective.expected_online",
      value: (item) => effectiveText(item.effective.expected_online),
      effective: (item) => item.effective.expected_online,
      width: 140,
    },
    {
      // Worked out by the server from the condition, what is observed and the intent.
      id: "health",
      header: "Health",
      kind: "choice",
      value: (item) => healthLabel(item.health.value),
      mark: (item) => item.health.value,
      hint: (item) => reasonsText(item.health),
      choices: HEALTHS,
      width: 130,
    },
    {
      id: "condition",
      header: "Condition",
      kind: "choice",
      value: (item) => choiceLabel(choices, CONDITION_LIST, item.condition),
      choices: choiceFilterOptions(choices, CONDITION_LIST),
      hide: true,
      width: 130,
    },
    {
      id: "observed_status",
      header: "Observed status",
      kind: "choice",
      value: (item) => observedLabel(item.observed_status),
      choices: OBSERVED,
      hide: true,
      width: 150,
    },
    {
      id: "observed_at",
      header: "Observed at",
      kind: "timestamp",
      value: (item) => formatTime(item.observed_at),
      hide: true,
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
      // `owner.label` is the label of the owner in force, which is what the cell shows.
      id: "owner.label",
      header: "Owner",
      kind: "text",
      value: (item) => effectiveLabel(item.effective.owner_hid),
      effective: (item) => item.effective.owner_hid,
      width: 170,
    },
    {
      // The operator in force: the label of who of the team looks after the item, its
      // own or the one it has from the item it is in, from its group or from where it
      // is. `operator.label` is what the list filters and sorts by. The cell is the mark
      // of that operator: the label, a dot in its colour, and "open" when nobody is
      // behind it; the person and where it came from are the hint.
      id: "operator.label",
      header: "Operator",
      kind: "text",
      column: "operator",
      value: (item) => effectiveLabel(item.effective.operator_hid),
      effective: (item) => item.effective.operator_hid,
      hint: (item) => operatorHint(item.effective.operator_hid),
      chip: (item) => {
        const mark = markOf(item.effective.operator_hid);
        return (
          mark && {
            colour: mark.colour,
            path: operatorPath(mark.hid),
            ...(mark.open ? { note: "open" } : {}),
          }
        );
      },
      hide: true,
      width: 180,
    },
    {
      // True for an item whose owner in force is outside the operations team.
      id: "owner_exception",
      header: "Outside the team",
      kind: "boolean",
      value: (item) => (item.owner_exception ? "Yes" : "No"),
      hide: true,
      width: 190,
    },
    {
      // The reason of that owner, which is the owner's own: an item holds none.
      id: "owner_exception_reason",
      header: "Reason for the exception",
      kind: "text",
      value: (item) => item.owner_exception_reason,
      hide: true,
      width: 240,
    },
    {
      // The location in force, by its name: `location.name` is what the list filters and
      // sorts by. An export writes the whole path, in the column `location`.
      id: "location.name",
      header: "Location",
      kind: "text",
      column: "location",
      value: (item) => nameOf(item.effective.location_hid.label),
      effective: (item) => item.effective.location_hid,
      hint: (item) => locationHint(item.effective.location_hid),
      hide: true,
      width: 200,
    },
    {
      // Where the item is going: a place that is not in use yet. The cell shows the name
      // of that location, with its path as the hint and in an export. The list finds it
      // with `planned_location:within:<place>` in the filter box, which is no comparison
      // of text: the column has no filter of its own, and the list is not sorted by it.
      id: "planned_location",
      header: "Planned location",
      kind: "text",
      field: null,
      sortField: null,
      value: (item) => item.planned_location?.name,
      hint: (item) => item.planned_location?.path,
      hide: true,
      width: 200,
    },
    {
      // The site of the location in force.
      id: "site",
      header: "Site",
      kind: "text",
      value: (item) => item.effective.location_hid.site,
      effective: (item) => item.effective.location_hid,
      hide: true,
      width: 150,
    },
    {
      // The region that site is in, by its name: what `region` filters, sorts and exports.
      id: "region",
      header: "Region",
      kind: "text",
      value: (item) => item.effective.location_hid.region,
      effective: (item) => item.effective.location_hid,
      hide: true,
      width: 150,
    },
    {
      id: "group.name",
      header: "Groups",
      kind: "text",
      sortField: null,
      column: null,
      value: (item) => item.groups.map((group) => group.name).join(", "),
      hide: true,
      width: 200,
    },
    {
      id: "group.type",
      header: "Group types",
      kind: "choice",
      sortField: null,
      column: null,
      value: groupTypes,
      choices: GROUP_TYPES,
      hide: true,
      width: 150,
    },
    {
      // The primary one of each family, IPv4 then IPv6. They are found through the
      // Addresses column, which filters by every address an item has: a filter here
      // would keep rows that show another. An export writes one column for each family.
      id: "mgmt_address",
      header: "Management address",
      kind: "address",
      field: null,
      sortField: null,
      column: ["mgmt_ipv4", "mgmt_ipv6"],
      value: (item) => managementText(item.addresses),
      mono: true,
      hide: true,
      width: 240,
    },
    {
      id: "address",
      header: "Addresses",
      kind: "address",
      sortField: null,
      column: null,
      value: (item) => addressList(item.addresses),
      mono: true,
      hide: true,
      width: 240,
    },
    {
      id: "network.label",
      header: "Networks",
      kind: "text",
      sortField: null,
      column: null,
      value: (item) => networkLabels(item.addresses).join(", "),
      hide: true,
      width: 140,
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

/**
 * What leaves minor items out of the item grid. The team mostly works with lists of
 * major items, so this is part of every filter the grid sends until Include minor items
 * is turned on.
 */
export const MAJOR_ITEMS: FilterNode = { field: "is_major", op: "eq", value: true };

/**
 * An item that a list shows greyed: a draft, a retired record, or one in Archived. The
 * state is the one in force: a module of an archived chassis is archived with it.
 */
export function itemIsDimmed(item: Item): boolean {
  return item.record_status !== "active" || item.effective.lifecycle_state.value === "Archived";
}
