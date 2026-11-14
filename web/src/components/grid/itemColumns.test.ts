import { describe, expect, it } from "vitest";
import type { Schemas } from "../../api/client";
import { exportColumns } from "../../lib/transfer";
import { cellHint, columnDefaults, queryColumns } from "./columns";
import { itemColumns, itemIsDimmed, MAJOR_ITEMS } from "./itemColumns";

type Item = Schemas["ItemOut"];
type InForce = Schemas["EffectiveValue"];

const SWITCH = "0193a1f4-0000-7000-8000-0000000000a1";
const SUPPLY = "0193a1f4-0000-7000-8000-0000000000a2";
const OWNER = "0193a1f4-0000-7000-8000-0000000000b1";
const none: InForce = { value: null, source: "none", source_hid: null };

function from(value: string | boolean, source: InForce["source"], hid: string): InForce {
  return { value, source, source_hid: hid };
}

/** A power supply in a switch, with nothing of its own but a name and a position. */
const supply = {
  hid: SUPPLY,
  name: null,
  hostname: "site2-sw-access-01-ps-a",
  is_major: false,
  depth: 1,
  position: "PS-A",
  parent: {
    hid: SWITCH,
    name: "site2-sw-access-01",
    serial_number: "FCW0000X001",
    asset_tag: null,
    pid: "EN-4800-48P",
  },
  lifecycle_state: null,
  disposition: null,
  expected_online: null,
  owner: null,
  record_status: "active",
  condition: null,
  observed_status: null,
  observed_at: null,
  health: {
    value: "unknown",
    reasons: ["nothing is said of its condition, and nothing is observed"],
  },
  groups: [],
  addresses: [],
  effective: {
    lifecycle_state: from("Prod", "parent_item", SWITCH),
    disposition: from("Production", "parent_item", SWITCH),
    expected_online: from(true, "parent_item", SWITCH),
    owner_hid: { ...from(OWNER, "parent_item", SWITCH), label: "Network Engineering" },
    est_value: none,
    support_weight: none,
    annual_support_cost: none,
    end_of_sale: none,
    end_of_sw_support: none,
    end_of_hw_support: none,
    ldos: none,
  },
} as unknown as Item;

/** The switch it is in: a member of a stack, with two addresses. */
const chassis = {
  ...supply,
  hid: SWITCH,
  hostname: "site2-sw-access-01",
  is_major: true,
  depth: 0,
  position: null,
  parent: null,
  lifecycle_state: "Prod",
  condition: "suspect",
  observed_status: "unreachable",
  observed_at: "2026-11-13T14:30:00Z",
  health: {
    value: "failed",
    reasons: ["it is expected online and is observed unreachable"],
  },
  groups: [
    {
      hid: "m-1",
      group_hid: "g-1",
      name: "site2-sw-stack1",
      type: "stack",
      role: "master",
      position: 1,
      joined_on: "2026-11-02",
    },
    {
      hid: "m-2",
      group_hid: "g-2",
      name: "refresh-2030",
      type: "custom",
      role: "member",
      position: null,
      joined_on: "2026-11-02",
    },
  ],
  addresses: [
    {
      hid: "a-1",
      address: "192.0.2.10",
      network: "Red",
      network_hid: "n-1",
      role: "management",
      is_primary: true,
      family: 4,
    },
    {
      hid: "a-2",
      address: "2001:db8::10",
      network: null,
      network_hid: null,
      role: "loopback",
      is_primary: false,
      family: 6,
    },
  ],
  effective: {
    ...supply.effective,
    lifecycle_state: from("Prod", "own", SWITCH),
    disposition: from("Production", "own", SWITCH),
    expected_online: from(true, "own", SWITCH),
    owner_hid: { ...from(OWNER, "own", SWITCH), label: "Network Engineering" },
  },
} as unknown as Item;

const CONDITIONS = ["untested", "good", "degraded", "suspect", "failed", "dead"].map(
  (value, place) => ({
    hid: `c-${place}`,
    list: "item_condition",
    value,
    label: value.charAt(0).toUpperCase() + value.slice(1),
    sort: place,
    active: true,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  }),
);

const COLUMNS = itemColumns(CONDITIONS, ["Assigned", "Prod", "Archived"]);

function column(id: string) {
  const found = COLUMNS.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`no column ${id}`);
  return found;
}

function asked(id: string) {
  const found = queryColumns(COLUMNS).find((candidate) => candidate.id === id);
  if (!found) throw new Error(`no column ${id}`);
  return found;
}

describe("the standing and the owner in the item grid", () => {
  it("shows a minor item the state, disposition, intent and owner in force", () => {
    expect(column("lifecycle_state").value(supply)).toBe("Prod");
    expect(column("disposition").value(supply)).toBe("Production");
    expect(column("expected_online").value(supply)).toBe("Yes");
    expect(column("owner.label").value(supply)).toBe("Network Engineering");
  });

  it("marks them as inherited for the minor item, and not for the item that has them", () => {
    for (const id of ["lifecycle_state", "disposition", "expected_online", "owner.label"]) {
      expect(column(id).effective?.(supply)?.source, id).toBe("parent_item");
      expect(column(id).effective?.(chassis)?.source, id).toBe("own");
    }
  });

  it("filters and sorts each of them by the value in force, which is what the cell shows", () => {
    expect(asked("lifecycle_state")).toMatchObject({
      field: "effective.lifecycle_state",
      sortField: "effective.lifecycle_state",
      kind: "choice",
    });
    expect(asked("disposition")).toMatchObject({
      field: "effective.disposition",
      sortField: "effective.disposition",
    });
    expect(asked("expected_online")).toMatchObject({
      field: "effective.expected_online",
      sortField: "effective.expected_online",
      kind: "boolean",
    });
    // The label of the owner in force already.
    expect(asked("owner.label")).toMatchObject({ field: "owner.label", sortField: "owner.label" });
  });

  it("keeps the names those columns were remembered and exported under", () => {
    // An export writes the value in force under the plain name of the column.
    const state = COLUMNS.filter((one) => !one.hide).map((one) => ({ colId: one.id }));
    const exported = exportColumns(COLUMNS, state);
    expect(exported).toContain("lifecycle_state");
    expect(exported).toContain("disposition");
    expect(exported).toContain("expected_online");
    expect(exported).toContain("owner.label");
    expect(exported).not.toContain("effective.lifecycle_state");
  });
});

describe("health, condition and what is observed in the item grid", () => {
  it("shows the health by its word, with a mark in its colour and the reasons as its hint", () => {
    const health = column("health");
    expect(health.value(chassis)).toBe("Failed");
    expect(health.mark?.(chassis)).toBe("failed");
    expect(cellHint(health, chassis)).toBe("it is expected online and is observed unreachable");
    expect(health.value(supply)).toBe("Unknown");
    expect(health.mark?.(supply)).toBe("unknown");
  });

  it("filters and sorts by the health the server works out, among its four values", () => {
    expect(asked("health")).toMatchObject({ field: "health", sortField: "health", kind: "choice" });
    expect(column("health").choices?.map((choice) => choice.value)).toEqual([
      "good",
      "degraded",
      "failed",
      "unknown",
    ]);
  });

  it("shows the condition by the label of its list, and what is observed in words", () => {
    expect(column("condition").value(chassis)).toBe("Suspect");
    expect(column("condition").value(supply)).toBe("");
    expect(column("condition").choices?.map((choice) => choice.value)).toEqual([
      "untested",
      "good",
      "degraded",
      "suspect",
      "failed",
      "dead",
    ]);
    expect(column("observed_status").value(chassis)).toBe("Unreachable");
    expect(column("observed_status").value(supply)).toBe("");
    expect(column("observed_status").choices?.map((choice) => choice.value)).toEqual([
      "online",
      "degraded",
      "unreachable",
      "present",
    ]);
    expect(column("observed_at").value(chassis)).toMatch(/2026/);
    expect(column("observed_at").value(supply)).toBe("");
  });

  it("filters and sorts the two facts and the moment by their own fields", () => {
    expect(asked("condition")).toMatchObject({ field: "condition", sortField: "condition" });
    expect(asked("observed_status")).toMatchObject({
      field: "observed_status",
      sortField: "observed_status",
    });
    expect(asked("observed_at")).toMatchObject({ field: "observed_at", kind: "timestamp" });
  });

  it("hides the condition and what is observed until they are asked for", () => {
    expect(column("health").hide).toBeUndefined();
    for (const id of ["condition", "observed_status", "observed_at"]) {
      expect(column(id).hide, id).toBe(true);
    }
  });
});

describe("major and minor items in the item grid", () => {
  it("leaves minor items out by a filter on is_major", () => {
    expect(MAJOR_ITEMS).toEqual({ field: "is_major", op: "eq", value: true });
  });

  it("says which an item is, where it is and how deep", () => {
    expect(column("is_major").value(supply)).toBe("Minor");
    expect(column("is_major").value(chassis)).toBe("Major");
    expect(column("parent").value(supply)).toBe("site2-sw-access-01");
    expect(column("parent").value(chassis)).toBe("");
    expect(column("position").value(supply)).toBe("PS-A");
    expect(column("depth").value(supply)).toBe("1");
    expect(column("depth").value(chassis)).toBe("0");
  });

  it("filters and sorts by is_major, position and depth, and by neither for the item above", () => {
    expect(asked("is_major")).toMatchObject({ field: "is_major", sortField: "is_major" });
    expect(column("is_major").choices).toEqual([
      { value: "true", label: "Major" },
      { value: "false", label: "Minor" },
    ]);
    expect(asked("position")).toMatchObject({ field: "position", sortField: "position" });
    expect(asked("depth")).toMatchObject({ field: "depth", sortField: "depth", kind: "integer" });
    expect(asked("parent")).toMatchObject({ field: null, sortField: null });
  });
});

describe("groups and addresses in the item grid", () => {
  it("lists every group and every address of an item", () => {
    expect(column("group.name").value(chassis)).toBe("site2-sw-stack1, refresh-2030");
    expect(column("group.type").value(chassis)).toBe("Stack, Custom");
    expect(column("mgmt_address").value(chassis)).toBe("192.0.2.10");
    expect(column("address").value(chassis)).toBe("192.0.2.10 (Red), 2001:db8::10");
    expect(column("network.label").value(chassis)).toBe("Red");
    expect(column("group.name").value(supply)).toBe("");
    expect(column("mgmt_address").value(supply)).toBe("");
  });

  it("shows the primary management address of each family, IPv4 first", () => {
    const both = {
      ...chassis,
      addresses: [
        {
          hid: "a-3",
          address: "2001:db8::10",
          network: null,
          network_hid: null,
          role: "management",
          is_primary: true,
          family: 6,
        },
        ...chassis.addresses.slice(0, 1),
      ],
    } as Item;
    expect(column("mgmt_address").value(both)).toBe("192.0.2.10, 2001:db8::10");
  });

  it("filters by any of them, and never sorts by what an item may have several of", () => {
    for (const id of ["group.name", "group.type", "address", "network.label"]) {
      expect(asked(id), id).toMatchObject({ field: id, sortField: null });
    }
    expect(asked("address").kind).toBe("address");
  });

  it("does not filter the primary address by a field that finds any address", () => {
    expect(asked("mgmt_address")).toMatchObject({ field: null, sortField: null });
  });

  it("exports only the columns a file of items has", () => {
    const every = COLUMNS.map((one) => ({ colId: one.id }));
    const exported = exportColumns(COLUMNS, every);
    for (const name of [
      "is_major",
      "parent",
      "position",
      "depth",
      "health",
      "condition",
      "observed_status",
      "observed_at",
    ]) {
      expect(exported, name).toContain(name);
    }
    for (const name of ["group.name", "group.type", "address", "network.label"]) {
      expect(exported, name).not.toContain(name);
    }
  });

  it("exports the management address as a column of each family", () => {
    const exported = exportColumns(COLUMNS, [{ colId: "name" }, { colId: "mgmt_address" }]);
    expect(exported).toEqual(["hid", "name", "mgmt_ipv4", "mgmt_ipv6"]);
  });
});

describe("the operator in the item grid", () => {
  const LEE = "0193a1f4-0000-7000-8000-0000000000e1";
  const STACK = "g-1";
  const operator = (source: InForce["source"], hid: string | null) => ({
    value: source === "none" ? null : LEE,
    label: source === "none" ? null : "Lee Marchetti",
    source,
    source_hid: hid,
  });
  const withOperator = (item: Item, source: InForce["source"], hid: string | null) =>
    ({
      ...item,
      effective: { ...item.effective, operator_hid: operator(source, hid) },
    }) as unknown as Item;
  // The switch is a member of the stack g-1, which has the operator; the supply is in it.
  const fromStack = withOperator(chassis, "device_group", STACK);
  const fromSwitch = withOperator(supply, "parent_item", SWITCH);
  const own = withOperator(chassis, "own", SWITCH);
  const nobody = withOperator(chassis, "none", null);

  it("shows the operator in force by name, and nothing for an item nobody is assigned to", () => {
    expect(column("operator.name").value(fromStack)).toBe("Lee Marchetti");
    expect(column("operator.name").value(own)).toBe("Lee Marchetti");
    expect(column("operator.name").value(nobody)).toBe("");
  });

  it("marks it as inherited where it comes from the group or from the item above", () => {
    expect(column("operator.name").effective?.(fromStack)?.source).toBe("device_group");
    expect(column("operator.name").effective?.(fromSwitch)?.source).toBe("parent_item");
    expect(column("operator.name").effective?.(own)?.source).toBe("own");
  });

  it("names the record it came from as the hint of the cell", () => {
    expect(cellHint(column("operator.name"), fromStack)).toBe(
      "Inherited from the stack site2-sw-stack1",
    );
    expect(cellHint(column("operator.name"), fromSwitch)).toBe(
      "Inherited from the item it is in, site2-sw-access-01",
    );
    expect(cellHint(column("operator.name"), own)).toBe("");
    expect(cellHint(column("operator.name"), nobody)).toBe("");
  });

  it("filters and sorts by the name of the operator in force, exports as `operator`, and is hidden at first", () => {
    expect(asked("operator.name")).toMatchObject({
      field: "operator.name",
      sortField: "operator.name",
      kind: "text",
    });
    expect(exportColumns(COLUMNS, [{ colId: "name" }, { colId: "operator.name" }])).toEqual([
      "hid",
      "name",
      "operator",
    ]);
    expect(columnDefaults(COLUMNS).find((one) => one.id === "operator.name")?.hide).toBe(true);
  });
});

describe("the location, the site and the region in the item grid", () => {
  const ROOM = "0193a1f4-0000-7000-8000-0000000000c1";
  const SITE = "0193a1f4-0000-7000-8000-0000000000c2";
  const REGION = "0193a1f4-0000-7000-8000-0000000000c3";
  const PATH = "Americas > Central > Site-2 > Building 1 > Room 102";
  const placed = {
    ...chassis,
    owner_exception: true,
    owner_exception_reason: "In the plant room",
    effective: {
      ...chassis.effective,
      location_hid: {
        ...from(ROOM, "own", SWITCH),
        label: PATH,
        site: "Site-2",
        site_hid: SITE,
        region: "Central",
        region_hid: REGION,
      },
    },
  } as unknown as Item;
  const within = {
    ...supply,
    owner_exception: true,
    owner_exception_reason: null,
    effective: {
      ...supply.effective,
      location_hid: {
        ...from(ROOM, "parent_item", SWITCH),
        label: PATH,
        site: "Site-2",
        site_hid: SITE,
        region: "Central",
        region_hid: REGION,
      },
    },
  } as unknown as Item;
  const nowhere = {
    ...chassis,
    owner_exception: false,
    owner_exception_reason: null,
    effective: {
      ...chassis.effective,
      location_hid: {
        ...none,
        label: null,
        site: null,
        site_hid: null,
        region: null,
        region_hid: null,
      },
    },
  } as unknown as Item;

  it("shows the region the site is in by its name, lighter where the location is inherited", () => {
    expect(column("region").value(placed)).toBe("Central");
    expect(column("region").value(within)).toBe("Central");
    expect(column("region").value(nowhere) ?? "").toBe("");
    expect(column("region").effective?.(within)?.source).toBe("parent_item");
    expect(column("region").effective?.(placed)?.source).toBe("own");
  });

  it("filters, sorts and exports the region as `region`, and hides it until it is asked for", () => {
    expect(asked("region")).toMatchObject({ field: "region", sortField: "region", kind: "text" });
    expect(exportColumns(COLUMNS, [{ colId: "site" }, { colId: "region" }])).toEqual([
      "hid",
      "site",
      "region",
    ]);
    expect(columnDefaults(COLUMNS).find((one) => one.id === "region")?.hide).toBe(true);
  });

  it("shows the location in force by its name, and its site", () => {
    expect(column("location.name").value(placed)).toBe("Room 102");
    expect(column("site").value(placed)).toBe("Site-2");
    expect(column("location.name").value(nowhere)).toBe("");
    expect(column("site").value(nowhere) ?? "").toBe("");
  });

  it("marks them as inherited for a minor item that is where the item above it is", () => {
    for (const id of ["location.name", "site"]) {
      expect(column(id).effective?.(within)?.source, id).toBe("parent_item");
      expect(column(id).effective?.(placed)?.source, id).toBe("own");
    }
  });

  it("says the whole path as the hint of the cell, with where it came from", () => {
    expect(cellHint(column("location.name"), placed)).toBe(PATH);
    expect(cellHint(column("location.name"), within)).toBe(
      `${PATH} · Inherited from the item it is in`,
    );
    expect(cellHint(column("location.name"), nowhere)).toBe("");
    expect(cellHint(column("site"), within)).toBe("Inherited from the item it is in");
  });

  it("filters and sorts by the name of the location and of the site, on the server", () => {
    expect(asked("location.name")).toMatchObject({
      field: "location.name",
      sortField: "location.name",
    });
    expect(asked("site")).toMatchObject({ field: "site", sortField: "site" });
  });

  it("exports the location by its path and the site by its name", () => {
    const exported = exportColumns(COLUMNS, [
      { colId: "name" },
      { colId: "location.name" },
      { colId: "site" },
      { colId: "owner_exception" },
      { colId: "owner_exception_reason" },
    ]);
    expect(exported).toEqual([
      "hid",
      "name",
      "location",
      "site",
      "owner_exception",
      "owner_exception_reason",
    ]);
  });

  it("says whether the owner in force is outside the team, and that owner's reason", () => {
    // The reason is the owner's own, as the server sends it with the item: a minor item
    // of such an item shows it too, and the column filters by it.
    expect(asked("owner_exception_reason")).toMatchObject({
      field: "owner_exception_reason",
      kind: "text",
    });
    expect(column("owner_exception").value(placed)).toBe("Yes");
    expect(column("owner_exception").value(nowhere)).toBe("No");
    expect(column("owner_exception_reason").value(placed)).toBe("In the plant room");
    expect(asked("owner_exception")).toMatchObject({ field: "owner_exception", kind: "boolean" });
  });

  it("hides all four until they are asked for", () => {
    const hidden = columnDefaults(COLUMNS)
      .filter((one) => one.hide)
      .map((one) => one.id);
    for (const id of ["location.name", "site", "owner_exception", "owner_exception_reason"]) {
      expect(hidden, id).toContain(id);
    }
  });
});

describe("the columns a reader starts with", () => {
  it("are the ones of 0.3.0 and the health: every other new column is shown when wanted", () => {
    const shown = columnDefaults(COLUMNS)
      .filter((one) => !one.hide)
      .map((one) => one.id);
    expect(shown).toEqual([
      "name",
      "catalog.vendor",
      "catalog.pid",
      "serial_number",
      "lifecycle_state",
      "disposition",
      "expected_online",
      "health",
      "owner.label",
      "tags",
      "effective.ldos",
    ]);
  });
});

describe("itemIsDimmed", () => {
  it("greys a draft, a retired record and an item in Archived", () => {
    expect(itemIsDimmed(chassis)).toBe(false);
    expect(itemIsDimmed({ ...chassis, record_status: "draft" })).toBe(true);
    expect(itemIsDimmed({ ...chassis, record_status: "retired" })).toBe(true);
  });

  it("goes by the state in force: a module of an archived chassis is archived with it", () => {
    const archived = {
      ...supply,
      effective: {
        ...supply.effective,
        lifecycle_state: from("Archived", "parent_item", SWITCH),
      },
    };
    expect(itemIsDimmed(archived)).toBe(true);
    expect(itemIsDimmed(supply)).toBe(false);
  });
});
