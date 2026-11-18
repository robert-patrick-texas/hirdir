// The columns of the grid of circuits and of the grid of circuit groups, and which field
// of the server each one filters and sorts by (P-154). They are kept apart from the
// pages so that those choices can be tested.

import type { Schemas } from "../../api/client";
import {
  CIRCUIT_TYPE_LIST,
  type Circuit,
  type CircuitGroup,
  mbpsText,
  moneyText,
  ownerPath,
  SIDES,
  sideCell,
  sideHint,
  vendorPath,
  weightHint,
} from "../../lib/circuits";
import { effectiveText } from "../../lib/effective";
import { formatTime } from "../../lib/format";
import { choiceFilterOptions, choiceLabel, RECORD_STATUSES } from "../../lib/options";
import { placePath } from "../../lib/places";
import { page } from "../../lib/valueLinks";
import type { GridColumn } from "./columns";

type Choice = Schemas["ChoiceOut"];

const DAYS: ReadonlyArray<
  [field: "installed_on" | "activated_on" | "disconnected_on", header: string]
> = [
  ["installed_on", "Installed"],
  ["activated_on", "Activated"],
  ["disconnected_on", "Disconnected"],
];

/** What the cost of a circuit that is not in service today says on hover. */
export const NOT_IN_SERVICE =
  "Not in service today, so 0.00: an ordered draft, or one disconnected. Its lines keep their amounts.";

/** The numbers its carriers give a circuit: the primary carrier's first, then the others'. */
export function carrierNumbers(circuit: Circuit): string {
  const others = (circuit.carriers ?? []).map((carrier) => carrier.circuit_number);
  return [circuit.carrier_circuit_number, ...others].filter(Boolean).join(", ");
}

/** The speed on hover: the port and the rate in force each way, with where it came from. */
export function speedHint(circuit: Circuit): string {
  if (!circuit.port_mbps) return "";
  const rate = (value: Schemas["EffectiveValue"]) =>
    value.source === "port"
      ? "the full rate of the port"
      : `${mbpsText(effectiveText(value))} Mbps`;
  return [
    `Port ${mbpsText(circuit.port_mbps)} Mbps`,
    `down ${rate(circuit.effective.down_mbps)}`,
    `up ${rate(circuit.effective.up_mbps)}`,
  ].join(", ");
}

/**
 * The columns of the circuit grid. Name, Enterprise ID, Type, Speed, Carrier, Carrier's
 * number, A side, Z side, Monthly cost, Annual cost, Owner and Tags are shown from the
 * start; the rest are in the column chooser.
 *
 * Speed shows the speed written short, as the server writes it, `1G / 200M / 20M`, and
 * is filtered and sorted by the speed of the port; the rates in force each way are
 * columns of their own, a blank rate showing the port's in the lighter style of a value
 * that came from elsewhere. A side shows the name of its location, with its path on
 * hover, or its note where it has none, and is filtered and sorted by the name of its
 * location. Carrier is the primary carrier; the numbers every carrier gives the circuit
 * are a column of their own, filtered by any of them.
 */
export function circuitColumns(choices: readonly Choice[] | undefined): GridColumn<Circuit>[] {
  return [
    {
      id: "name",
      header: "Name",
      kind: "text",
      value: (circuit) => circuit.name,
      link: true,
      width: 220,
    },
    {
      id: "enterprise_circuit_id",
      header: "Enterprise ID",
      kind: "text",
      value: (circuit) => circuit.enterprise_circuit_id,
      mono: true,
      width: 150,
    },
    {
      id: "circuit_type",
      header: "Type",
      kind: "choice",
      value: (circuit) => choiceLabel(choices, CIRCUIT_TYPE_LIST, circuit.circuit_type),
      choices: choiceFilterOptions(choices, CIRCUIT_TYPE_LIST),
      width: 140,
    },
    {
      // Written short by the server; the port speed is what it filters and sorts by.
      id: "speed",
      header: "Speed",
      kind: "number",
      field: "port_mbps",
      value: (circuit) => circuit.speed,
      hint: speedHint,
      width: 170,
    },
    {
      id: "carrier.name",
      header: "Carrier",
      kind: "text",
      column: "carrier",
      value: (circuit) => circuit.carrier?.name,
      linkTo: (circuit) => (circuit.carrier ? vendorPath(circuit.carrier.hid) : null),
      width: 170,
    },
    {
      id: "carrier_circuit_number",
      header: "Carrier's number",
      kind: "text",
      value: (circuit) => circuit.carrier_circuit_number,
      mono: true,
      width: 170,
    },
    ...SIDES.map(
      ({ value: side, label }): GridColumn<Circuit> => ({
        id: `${side}_location.name`,
        header: label,
        kind: "text",
        column: [`${side}_location`, `${side}_note`],
        value: (circuit) =>
          side === "a"
            ? sideCell(circuit.a_side, circuit.a_note)
            : sideCell(circuit.z_side, circuit.z_note),
        hint: (circuit) =>
          side === "a"
            ? sideHint(circuit.a_side, circuit.a_note)
            : sideHint(circuit.z_side, circuit.z_note),
        linkTo: (circuit) => {
          const at = side === "a" ? circuit.a_side : circuit.z_side;
          return at ? placePath("location", at.location_hid) : null;
        },
        width: 180,
      }),
    ),
    {
      id: "monthly_cost",
      header: "Monthly cost",
      kind: "number",
      value: (circuit) => moneyText(circuit.monthly_cost),
      hint: (circuit) =>
        circuit.in_service ? "The sum of its cost lines that are billed today" : NOT_IN_SERVICE,
      numeric: true,
      width: 140,
    },
    {
      id: "annual_cost",
      header: "Annual cost",
      kind: "number",
      value: (circuit) => moneyText(circuit.annual_cost),
      hint: (circuit) => (circuit.in_service ? "Twelve times the monthly cost" : NOT_IN_SERVICE),
      numeric: true,
      width: 140,
    },
    {
      id: "owner.label",
      header: "Owner",
      kind: "text",
      column: "owner",
      value: (circuit) => circuit.owner?.label,
      hint: (circuit) =>
        circuit.owner_exception
          ? `Outside the operations team: ${circuit.owner_exception_reason ?? ""}`.trim()
          : "",
      linkTo: (circuit) => (circuit.owner ? ownerPath(circuit.owner.hid) : null),
      width: 170,
    },
    {
      id: "tags",
      header: "Tags",
      kind: "tags",
      value: (circuit) => circuit.tags.join(", "),
      width: 160,
    },
    {
      // Any of its carriers' numbers, the primary one's among them: found by any, and
      // sorted by the first. No export has the column: each number is in its own file.
      id: "carriers.circuit_number",
      header: "Numbers of its carriers",
      kind: "text",
      column: null,
      value: carrierNumbers,
      mono: true,
      hide: true,
      width: 220,
    },
    {
      id: "description",
      header: "Description",
      kind: "text",
      value: (circuit) => circuit.description,
      hide: true,
      width: 220,
    },
    {
      id: "port_mbps",
      header: "Port speed (Mbps)",
      kind: "number",
      value: (circuit) => mbpsText(circuit.port_mbps),
      numeric: true,
      hide: true,
      width: 160,
    },
    {
      // The rate in force: its own, or the full rate of the port, shown lighter. An
      // export writes its own, blank for the full rate.
      id: "effective.down_mbps",
      header: "Rate down (Mbps)",
      kind: "number",
      column: "down_mbps",
      value: (circuit) => mbpsText(effectiveText(circuit.effective.down_mbps)),
      effective: (circuit) => circuit.effective.down_mbps,
      numeric: true,
      hide: true,
      width: 160,
    },
    {
      id: "effective.up_mbps",
      header: "Rate up (Mbps)",
      kind: "number",
      column: "up_mbps",
      value: (circuit) => mbpsText(effectiveText(circuit.effective.up_mbps)),
      effective: (circuit) => circuit.effective.up_mbps,
      numeric: true,
      hide: true,
      width: 150,
    },
    ...SIDES.map(
      ({ value: side, label }): GridColumn<Circuit> => ({
        id: `${side}_note`,
        header: `${label} note`,
        kind: "text",
        value: (circuit) => (side === "a" ? circuit.a_note : circuit.z_note),
        hide: true,
        width: 180,
      }),
    ),
    {
      id: "cost_side",
      header: "Counts at side",
      kind: "choice",
      value: (circuit) => SIDES.find((side) => side.value === circuit.cost_side)?.label,
      choices: SIDES,
      hide: true,
      width: 140,
    },
    {
      // The site its cost and its weight count at, by its path: filtered by the site's
      // HID, and sorted by the site's name, as a place is (D-132).
      id: "cost_site_hid",
      header: "Counts at site",
      kind: "reference",
      sortField: "cost_site.name",
      column: "cost_site",
      value: (circuit) => circuit.cost_site_path,
      linkTo: (circuit) =>
        circuit.cost_site_hid ? placePath("site", circuit.cost_site_hid) : null,
      hide: true,
      width: 220,
    },
    {
      id: "billing_account",
      header: "Billing account",
      kind: "text",
      value: (circuit) => circuit.billing_account,
      hide: true,
      width: 160,
    },
    {
      id: "billing_contract",
      header: "Billing contract",
      kind: "text",
      value: (circuit) => circuit.billing_contract,
      hide: true,
      width: 160,
    },
    ...DAYS.map(
      ([field, header]): GridColumn<Circuit> => ({
        id: field,
        header,
        kind: "date",
        value: (circuit) => circuit[field],
        hide: true,
        width: 140,
      }),
    ),
    {
      id: "in_service",
      header: "In service",
      kind: "boolean",
      column: null,
      value: (circuit) => (circuit.in_service ? "Yes" : "No"),
      choices: [
        { value: "true", label: "In service today" },
        { value: "false", label: "Not in service today" },
      ],
      hide: true,
      width: 120,
    },
    {
      id: "production",
      header: "Production",
      kind: "boolean",
      value: (circuit) => (circuit.production ? "Yes" : "No"),
      choices: [
        { value: "true", label: "Carries production" },
        { value: "false", label: "Carries no production" },
      ],
      hide: true,
      width: 120,
    },
    {
      // The weight in force: its own, or the default of circuits, raised to the minimum.
      id: "effective.support_weight",
      header: "Support weight",
      kind: "number",
      column: "support_weight",
      value: (circuit) => effectiveText(circuit.effective.support_weight),
      effective: (circuit) => circuit.effective.support_weight,
      hint: (circuit) => weightHint(circuit.effective.support_weight),
      numeric: true,
      hide: true,
      width: 150,
    },
    {
      id: "owner_exception",
      header: "Outside the team",
      kind: "boolean",
      value: (circuit) => (circuit.owner_exception ? "Yes" : "No"),
      hide: true,
      width: 160,
    },
    {
      id: "owner_exception_reason",
      header: "Reason for the exception",
      kind: "text",
      // The owner's own reason: a file of circuits does not carry it.
      column: null,
      value: (circuit) => circuit.owner_exception_reason,
      hide: true,
      width: 220,
    },
    {
      id: "groups.name",
      header: "Groups",
      kind: "text",
      column: "groups",
      value: (circuit) => (circuit.groups ?? []).map((group) => group.name).join(", "),
      links: (circuit) =>
        (circuit.groups ?? []).map((group) => ({
          text: group.name,
          path: page("circuit_group", group.hid),
        })),
      hide: true,
      width: 200,
    },
    {
      id: "notes",
      header: "Notes",
      kind: "text",
      value: (circuit) => circuit.notes,
      hide: true,
      width: 220,
    },
    {
      id: "record_status",
      header: "Record status",
      kind: "choice",
      value: (circuit) =>
        RECORD_STATUSES.find((status) => status.value === circuit.record_status)?.label,
      choices: RECORD_STATUSES,
      hide: true,
    },
    {
      id: "updated_at",
      header: "Changed",
      kind: "timestamp",
      value: (circuit) => formatTime(circuit.updated_at),
      hide: true,
    },
    {
      id: "created_at",
      header: "Created",
      kind: "timestamp",
      value: (circuit) => formatTime(circuit.created_at),
      hide: true,
    },
    {
      id: "hid",
      header: "HID",
      kind: "reference",
      value: (circuit) => circuit.hid,
      mono: true,
      hide: true,
    },
  ];
}

/** The columns of the grid of circuit groups: each with how many circuits, and their cost. */
export const CIRCUIT_GROUP_COLUMNS: readonly GridColumn<CircuitGroup>[] = [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (group) => group.name,
    link: true,
    width: 240,
  },
  {
    id: "circuits",
    header: "Circuits",
    kind: "integer",
    value: (group) => String(group.circuits),
    numeric: true,
    width: 110,
  },
  {
    id: "in_service",
    header: "In service",
    kind: "integer",
    column: null,
    value: (group) => String(group.in_service),
    hint: () => "How many of its circuits are in service today",
    numeric: true,
    width: 120,
  },
  {
    id: "monthly_cost",
    header: "Monthly cost",
    kind: "number",
    value: (group) => moneyText(group.monthly_cost),
    hint: () => "What its circuits in service cost a month today, each circuit once",
    numeric: true,
    width: 140,
  },
  {
    id: "annual_cost",
    header: "Annual cost",
    kind: "number",
    value: (group) => moneyText(group.annual_cost),
    hint: () => "Twelve times the monthly cost",
    numeric: true,
    width: 140,
  },
  {
    id: "owner.label",
    header: "Owner",
    kind: "text",
    column: "owner",
    value: (group) => group.owner?.label,
    linkTo: (group) => (group.owner ? ownerPath(group.owner.hid) : null),
    width: 170,
  },
  { id: "tags", header: "Tags", kind: "tags", value: (group) => group.tags.join(", "), width: 160 },
  {
    id: "description",
    header: "Description",
    kind: "text",
    value: (group) => group.description,
    width: 260,
  },
  { id: "notes", header: "Notes", kind: "text", value: (group) => group.notes, hide: true },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (group) => RECORD_STATUSES.find((status) => status.value === group.record_status)?.label,
    choices: RECORD_STATUSES,
    hide: true,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (group) => formatTime(group.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (group) => group.hid,
    mono: true,
    hide: true,
  },
];
