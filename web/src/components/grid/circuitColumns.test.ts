import { describe, expect, it } from "vitest";
import type { Schemas } from "../../api/client";
import { GRID_FIELDS } from "../../lib/circuits";
import { exportColumns } from "../../lib/transfer";
import { CIRCUIT_GROUP_COLUMNS, carrierNumbers, circuitColumns, speedHint } from "./circuitColumns";
import { cellHint, columnDefaults, queryColumns } from "./columns";

type Circuit = Schemas["CircuitOut"];
type Choice = Schemas["ChoiceOut"];

const SITE = "0193a1f4-0000-7000-8000-0000000000c2";
const LOCATION = "0193a1f4-0000-7000-8000-0000000000c3";
const CARRIER = "0193a1f4-0000-7000-8000-0000000000d1";

const choices = [
  { list: "circuit_type", value: "internet", label: "Internet", active: true },
  { list: "circuit_type", value: "dark_fiber", label: "Dark fiber", active: false },
] as unknown as Choice[];

/** An internet circuit from the carrier's network to a building, limited one way. */
const circuit = {
  hid: "0193a1f4-0000-7000-8000-0000000000e1",
  name: "Site-2 internet",
  enterprise_circuit_id: "EC-0042",
  circuit_type: "internet",
  port_mbps: "1000.00",
  down_mbps: "200.00",
  up_mbps: null,
  speed: "1G / 200M / 1G",
  a_side: null,
  a_note: "carrier network",
  z_side: {
    location_hid: LOCATION,
    name: "Building 1",
    path: "Americas > Central > Site-2 > Building 1",
    site_hid: SITE,
    site_path: "Americas > Central > Site-2",
    region_hid: "r",
    record_status: "active",
  },
  z_note: null,
  cost_side: "a",
  cost_site_hid: SITE,
  cost_site_path: "Americas > Central > Site-2",
  carrier: { hid: CARRIER, name: "Example Telecom" },
  carrier_hid: CARRIER,
  carrier_circuit_number: "EXT/12345/000/EXTL",
  carriers: [{ circuit_number: "LEC-778-0001" }, { circuit_number: null }],
  monthly_cost: "12450.00",
  annual_cost: "149400.00",
  owner: { hid: "o", label: "Network Engineering", is_external: false },
  owner_exception: false,
  owner_exception_reason: null,
  groups: [{ hid: "g", name: "Internet access", record_status: "active" }],
  tags: ["wan"],
  effective: {
    support_weight: { value: "2.00", source: "setting", source_hid: null, raised_from: null },
    down_mbps: { value: "200.00", source: "own", source_hid: null },
    up_mbps: { value: "1000.00", source: "port", source_hid: null },
  },
  record_status: "active",
} as unknown as Circuit;

const columns = circuitColumns(choices);
const byId = (id: string) => {
  const found = columns.find((column) => column.id === id);
  if (!found) throw new Error(`no column ${id}`);
  return found;
};

describe("the circuit grid", () => {
  it("shows the twelve columns of P-154 from the start, in their order", () => {
    const shown = columnDefaults(columns)
      .filter((column) => !column.hide)
      .map((column) => byId(column.id).header);
    expect(shown).toEqual([
      "Name",
      "Enterprise ID",
      "Type",
      "Speed",
      "Carrier",
      "Carrier's number",
      "A side",
      "Z side",
      "Monthly cost",
      "Annual cost",
      "Owner",
      "Tags",
    ]);
  });

  it("filters and sorts each column by a field of the circuit list", () => {
    const fields = Object.fromEntries(
      queryColumns(columns).map((column) => [column.id, [column.field, column.sortField]]),
    );
    expect(fields.speed).toEqual(["port_mbps", "port_mbps"]);
    expect(fields["a_location.name"]).toEqual(["a_location.name", "a_location.name"]);
    expect(fields["z_location.name"]).toEqual(["z_location.name", "z_location.name"]);
    expect(fields["carrier.name"]).toEqual(["carrier.name", "carrier.name"]);
    expect(fields["carriers.circuit_number"]).toEqual([
      "carriers.circuit_number",
      "carriers.circuit_number",
    ]);
    expect(fields["groups.name"]).toEqual(["groups.name", "groups.name"]);
    expect(fields["effective.down_mbps"]).toEqual(["effective.down_mbps", "effective.down_mbps"]);
    expect(fields.in_service).toEqual(["in_service", "in_service"]);
    // Every column is sorted by its header.
    for (const column of queryColumns(columns)) expect(column.sortField, column.id).not.toBeNull();
  });

  it("shows a side by the name of its location, or by its note", () => {
    expect(byId("a_location.name").value(circuit)).toBe("carrier network");
    expect(cellHint(byId("a_location.name"), circuit)).toBe("No location: carrier network");
    expect(byId("z_location.name").value(circuit)).toBe("Building 1");
    expect(cellHint(byId("z_location.name"), circuit)).toBe(
      "Americas > Central > Site-2 > Building 1",
    );
  });

  it("shows the speed short, with the port and each rate on hover", () => {
    expect(byId("speed").value(circuit)).toBe("1G / 200M / 1G");
    expect(speedHint(circuit)).toBe("Port 1,000 Mbps, down 200 Mbps, up the full rate of the port");
    // A rate that is the port's is shown as one that came from elsewhere.
    expect(byId("effective.up_mbps").value(circuit)).toBe("1,000");
    expect(cellHint(byId("effective.up_mbps"), circuit)).toBe("Inherited from the port");
  });

  it("shows money with two places, and the numbers of every carrier", () => {
    expect(byId("monthly_cost").value(circuit)).toBe("12,450.00");
    expect(byId("annual_cost").value(circuit)).toBe("149,400.00");
    expect(carrierNumbers(circuit)).toBe("EXT/12345/000/EXTL, LEC-778-0001");
    expect(byId("circuit_type").value(circuit)).toBe("Internet");
    expect(byId("groups.name").value(circuit)).toBe("Internet access");
  });

  it("offers every type in the filter, the inactive ones too", () => {
    expect(byId("circuit_type").choices).toEqual([
      { value: "internet", label: "Internet" },
      { value: "dark_fiber", label: "Dark fiber" },
    ]);
  });

  it("exports the columns on show by the names a file of circuits has", () => {
    const state = columns.map((column) => ({ colId: column.id, hide: false }));
    expect(exportColumns(columns, state)).toEqual([
      "hid",
      "name",
      "enterprise_circuit_id",
      "circuit_type",
      "speed",
      "carrier",
      "carrier_circuit_number",
      "a_location",
      "a_note",
      "z_location",
      "z_note",
      "monthly_cost",
      "annual_cost",
      "owner",
      "tags",
      "description",
      "port_mbps",
      "down_mbps",
      "up_mbps",
      "cost_side",
      "cost_site",
      "billing_account",
      "billing_contract",
      "installed_on",
      "activated_on",
      "disconnected_on",
      "production",
      "support_weight",
      "owner_exception",
      "groups",
      "notes",
      "record_status",
      "updated_at",
      "created_at",
    ]);
  });

  it("asks for the fields its columns show, the groups and the other carriers among them", () => {
    expect(GRID_FIELDS).toContain("groups");
    expect(GRID_FIELDS).toContain("carriers");
    expect(GRID_FIELDS).not.toContain("costs");
    expect(GRID_FIELDS).not.toContain("contacts");
  });
});

describe("the grid of circuit groups", () => {
  it("shows how many circuits each has and what they cost", () => {
    const shown = columnDefaults(CIRCUIT_GROUP_COLUMNS)
      .filter((column) => !column.hide)
      .map((column) => column.id);
    expect(shown).toEqual([
      "name",
      "circuits",
      "in_service",
      "monthly_cost",
      "annual_cost",
      "owner.label",
      "tags",
      "description",
    ]);
    const state = CIRCUIT_GROUP_COLUMNS.map((column) => ({ colId: column.id, hide: false }));
    expect(exportColumns(CIRCUIT_GROUP_COLUMNS, state)).toEqual([
      "hid",
      "name",
      "circuits",
      "monthly_cost",
      "annual_cost",
      "owner",
      "tags",
      "description",
      "notes",
      "record_status",
      "updated_at",
    ]);
  });
});
