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

  it("says in the hint of the owner which item or group it came from", () => {
    expect(cellHint(column("owner.label"), supply)).toBe(
      "Inherited from the item site2-sw-access-01",
    );
    expect(cellHint(column("owner.label"), chassis)).toBe("");
    // A member with no owner of its own has the owner of its group.
    const member = {
      ...chassis,
      effective: {
        ...chassis.effective,
        owner_hid: { ...from(OWNER, "device_group", "g-1"), label: "Network Engineering" },
      },
    } as unknown as Item;
    expect(column("owner.label").effective?.(member)?.source).toBe("device_group");
    expect(cellHint(column("owner.label"), member)).toBe(
      "Inherited from the group site2-sw-stack1",
    );
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
    // Expected online is in the column chooser (P-193): asked for, it is exported.
    const state = COLUMNS.filter((one) => !one.hide || one.id === "expected_online").map((one) => ({
      colId: one.id,
    }));
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
    // The item above is found by its HID, and sorted by its name.
    expect(asked("parent")).toMatchObject({ field: null, sortField: "parent.name" });
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

  it("filters by any of them, and sorts by the first of what an item may have several of", () => {
    for (const id of ["group.name", "group.type", "address", "network.label"]) {
      expect(asked(id), id).toMatchObject({ field: id, sortField: id });
    }
    expect(asked("address").kind).toBe("address");
  });

  it("does not filter the primary address by a field that finds any address, and sorts by it", () => {
    // `mgmt_address` is sorted by and not filtered by.
    expect(asked("mgmt_address")).toMatchObject({ field: null, sortField: "mgmt_address" });
  });

  it("sorts every column of the grid on the server: none is left without a field", () => {
    const unsorted = COLUMNS.map((one) => asked(one.id))
      .filter((one) => one.sortField === null)
      .map((one) => one.id);
    expect(unsorted).toEqual([]);
    expect(asked("tags")).toMatchObject({ field: "tags", sortField: "tags" });
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
  const OP2 = "0193a1f4-0000-7000-8000-0000000000e1";
  const LEE = "0193a1f4-0000-7000-8000-0000000000e2";
  const STACK = "g-1";
  const SITE_PATH = "Americas > Central > Site-2";
  const operator = (
    source: InForce["source"],
    hid: string | null,
    from: string | null,
    open = false,
  ) => ({
    value: source === "none" ? null : OP2,
    label: source === "none" ? null : "Op2",
    colour: source === "none" ? null : "#1f6feb",
    contact_hid: open || source === "none" ? null : LEE,
    contact: open || source === "none" ? null : "Lee Marchetti",
    is_open: open,
    source,
    source_hid: hid,
    source_label: from,
  });
  const withOperator = (item: Item, inForce: ReturnType<typeof operator>) =>
    ({
      ...item,
      effective: { ...item.effective, operator_hid: inForce },
    }) as unknown as Item;
  const fromStack = withOperator(chassis, operator("device_group", STACK, "site2-sw-stack1"));
  const fromSwitch = withOperator(supply, operator("parent_item", SWITCH, "site2-sw-access-01"));
  const fromSite = withOperator(chassis, operator("site", "s-1", SITE_PATH));
  const own = withOperator(chassis, operator("own", SWITCH, null));
  const open = withOperator(chassis, operator("own", SWITCH, null, true));
  const nobody = withOperator(chassis, operator("none", null, null));

  it("shows the label of the operator in force, and nothing for an item nobody is assigned to", () => {
    expect(column("operator.label").value(fromStack)).toBe("Op2");
    expect(column("operator.label").value(own)).toBe("Op2");
    expect(column("operator.label").value(nobody)).toBe("");
  });

  it("shows it as a mark: a dot in its colour, a link to the operator, and open when it is", () => {
    expect(column("operator.label").chip?.(own)).toEqual({
      colour: "#1f6feb",
      path: `/operators/${OP2}`,
    });
    expect(column("operator.label").chip?.(open)).toEqual({
      colour: "#1f6feb",
      path: `/operators/${OP2}`,
      note: "open",
    });
    expect(column("operator.label").chip?.(nobody)).toBeNull();
  });

  it("marks it as inherited where it comes from above: the item, the group or the place", () => {
    expect(column("operator.label").effective?.(fromStack)?.source).toBe("device_group");
    expect(column("operator.label").effective?.(fromSwitch)?.source).toBe("parent_item");
    expect(column("operator.label").effective?.(fromSite)?.source).toBe("site");
    expect(column("operator.label").effective?.(own)?.source).toBe("own");
  });

  it("says the person behind the label and the record it came from as the hint of the cell", () => {
    expect(cellHint(column("operator.label"), fromStack)).toBe(
      "Lee Marchetti · Inherited from the group site2-sw-stack1",
    );
    expect(cellHint(column("operator.label"), fromSwitch)).toBe(
      "Lee Marchetti · Inherited from the item site2-sw-access-01",
    );
    expect(cellHint(column("operator.label"), fromSite)).toBe(
      `Lee Marchetti · Inherited from the site ${SITE_PATH}`,
    );
    expect(cellHint(column("operator.label"), own)).toBe("Lee Marchetti");
    expect(cellHint(column("operator.label"), open)).toBe("Open: nobody is behind this label");
    expect(cellHint(column("operator.label"), nobody)).toBe("");
  });

  it("filters and sorts by the label of the operator in force, exports as `operator`, and is shown from the start", () => {
    expect(asked("operator.label")).toMatchObject({
      field: "operator.label",
      sortField: "operator.label",
      kind: "text",
    });
    expect(exportColumns(COLUMNS, [{ colId: "name" }, { colId: "operator.label" }])).toEqual([
      "hid",
      "name",
      "operator",
    ]);
    expect(columnDefaults(COLUMNS).find((one) => one.id === "operator.label")?.hide).toBe(false);
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
        source_label: "site2-sw-access-01",
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
      `${PATH} · Inherited from the item site2-sw-access-01`,
    );
    const inGroup = {
      ...within,
      effective: {
        ...within.effective,
        location_hid: {
          ...within.effective.location_hid,
          source: "device_group",
          source_hid: "g-1",
          source_label: "Stack 4",
        },
      },
    } as unknown as Item;
    expect(cellHint(column("location.name"), inGroup)).toBe(
      `${PATH} · Inherited from the group Stack 4`,
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

  it("shows the location and the site from the start, and hides the exception (P-193)", () => {
    const hidden = columnDefaults(COLUMNS)
      .filter((one) => one.hide)
      .map((one) => one.id);
    for (const id of ["owner_exception", "owner_exception_reason"]) {
      expect(hidden, id).toContain(id);
    }
    for (const id of ["location.name", "site"]) {
      expect(hidden, id).not.toContain(id);
    }
  });
});

describe("the planned location in the item grid", () => {
  const PATH = "Americas > East > Site-9 > Room 1";
  const plan = (source: string, hid: string | null, label: string | null) => ({
    value: "l-9",
    label: PATH,
    site: "Site-9",
    site_hid: "s-9",
    region: "East",
    region_hid: "r-9",
    source,
    source_hid: hid,
    source_label: label,
  });
  const noPlan = { ...plan("none", null, null), value: null, label: null };
  const withPlan = (planned: unknown) =>
    ({
      ...chassis,
      effective: { ...chassis.effective, planned_location_hid: planned },
    }) as unknown as Item;
  const planned = withPlan(plan("own", SWITCH, null));
  const fromGroup = withPlan(plan("device_group", "g-1", "Stack 4"));
  const unplanned = withPlan(noPlan);

  it("shows where the item is going by the name of the place, with its path as the hint", () => {
    expect(column("planned_location").value(planned)).toBe("Room 1");
    expect(cellHint(column("planned_location"), planned)).toBe(PATH);
    expect(column("planned_location").value(unplanned) ?? "").toBe("");
    expect(cellHint(column("planned_location"), unplanned)).toBe("");
  });

  it("shows the plan an item has from its group, and says in the hint where it came from", () => {
    expect(column("planned_location").value(fromGroup)).toBe("Room 1");
    expect(column("planned_location").effective?.(fromGroup)?.source).toBe("device_group");
    expect(cellHint(column("planned_location"), fromGroup)).toBe(
      `${PATH} · Inherited from the group Stack 4`,
    );
  });

  it("filters and sorts by the name of the place, on the server", () => {
    expect(asked("planned_location")).toMatchObject({
      field: "planned_location.name",
      sortField: "planned_location.name",
      kind: "text",
    });
  });

  it("exports as `planned_location`, and is hidden until it is asked for", () => {
    expect(exportColumns(COLUMNS, [{ colId: "name" }, { colId: "planned_location" }])).toEqual([
      "hid",
      "name",
      "planned_location",
    ]);
    expect(columnDefaults(COLUMNS).find((one) => one.id === "planned_location")?.hide).toBe(true);
  });
});

describe("coverage, registrations and the purchase line in the item grid", () => {
  const CONTRACT = "0193a1f4-0000-7000-8000-0000000000c1";
  const LINE = "0193a1f4-0000-7000-8000-0000000000d1";
  const ref = (number: string, inForce: boolean) => ({
    hid: `cov-${number}-${inForce}`,
    contract_hid: CONTRACT,
    contract: {
      hid: CONTRACT,
      number,
      vendor: "Cisco",
      status: "active",
      record_status: "active",
    },
    starts_on: "2026-01-01",
    ends_on: inForce ? "2027-12-31" : "2026-03-31",
    in_force: inForce,
  });
  const registration = (name: string, status: string) => ({
    hid: `reg-${name}`,
    system_hid: `sys-${name}`,
    system: { hid: `sys-${name}`, name, kind: "monitoring" },
    external_id: null,
    status,
    confirmed_at: null,
  });
  /** A switch under two contracts, one of them ended, registered with two systems. */
  const covered = {
    ...chassis,
    covered: true,
    covered_until: "2027-12-31",
    coverage: [ref("CON-2026-0001", true), ref("CON-2025-0009", false), ref("CON-2026-0001", true)],
    registrations: [registration("NetWatch", "registered"), registration("ConfigVault", "removed")],
    group_registrations: [],
    contract_count: 1,
    purchase_line_hid: LINE,
    purchase_line: {
      hid: LINE,
      request_hid: "req-1",
      reference: "RITM0012345",
      line: 2,
      name: "RITM0012345/2",
    },
  } as unknown as Item;
  /** One that nothing covers, that is registered nowhere and arrived on no line. */
  const bare = {
    ...chassis,
    covered: false,
    covered_until: null,
    coverage: [],
    registrations: [],
    group_registrations: [],
    contract_count: 0,
    purchase_line_hid: null,
    purchase_line: null,
  } as unknown as Item;
  /**
   * A member of a stack: under two contracts at once, one of them with its renewal
   * pending, with no registration of its own and the stack's two beside it.
   */
  const member = {
    ...covered,
    covered_until: null,
    contract_count: 2,
    coverage: [
      ref("CON-2026-0001", true),
      {
        ...ref("CON-2025-0044", true),
        contract: { ...ref("CON-2025-0044", true).contract, status: "renewal_pending" },
      },
    ],
    registrations: [],
    group_registrations: [
      {
        ...registration("NetWatch", "registered"),
        group: { hid: "g-1", name: "site2-sw-stack1", type: "stack" },
      },
      {
        ...registration("Fabric Controller", "removed"),
        group: { hid: "g-1", name: "site2-sw-stack1", type: "stack" },
      },
    ],
  } as unknown as Item;

  it("says how many contracts cover the item today, and the status of each", () => {
    expect(column("contract_count").value(covered)).toBe("1");
    expect(column("contract_count").value(bare)).toBe("0");
    expect(column("contract_count").value(member)).toBe("2");
    expect(column("contract.status").value(covered)).toBe("Active");
    expect(column("contract.status").value(member)).toBe("Active, Renewal pending");
    expect(column("contract.status").value(bare)).toBe("");
  });

  it("says of cover under a contract whose renewal is pending whom to go through", () => {
    expect(column("covered").value(member)).toBe("Yes");
    expect(cellHint(column("covered"), member)).toBe(
      "Renewal pending: go through the account manager",
    );
    expect(cellHint(column("contract.status"), member)).toContain("account manager");
    expect(cellHint(column("covered"), covered)).toBe("");
  });

  it("lists for a member what its stack is registered with, and says through which group", () => {
    // The filter of the item list finds the member by the stack's system too.
    expect(column("registration.system").value(member)).toBe("NetWatch");
    expect(cellHint(column("registration.system"), member)).toBe(
      "Through site2-sw-stack1, which it is a member of",
    );
    expect(cellHint(column("registration.system"), covered)).toBe("");
  });

  it("filters and sorts the count and the status by the fields the server has, and hides both", () => {
    expect(asked("contract_count")).toMatchObject({
      field: "contract_count",
      sortField: "contract_count",
      kind: "integer",
    });
    expect(asked("contract.status")).toMatchObject({
      field: "contract.status",
      sortField: "contract.status",
      kind: "choice",
    });
    expect(column("contract_count").hide).toBe(true);
    expect(column("contract.status").hide).toBe(true);
    // An export has the count, and no column for the status.
    expect(
      exportColumns(COLUMNS, [{ colId: "contract_count" }, { colId: "contract.status" }]),
    ).toEqual(["hid", "contract_count"]);
  });

  it("says whether a contract covers the item today, and the last day its cover runs to", () => {
    expect(column("covered").value(covered)).toBe("Yes");
    expect(column("covered").value(bare)).toBe("No");
    expect(column("covered_until").value(covered)).toBe("2027-12-31");
    expect(column("covered_until").value(bare)).toBeNull();
  });

  it("lists the contracts that cover it today by their numbers, each once", () => {
    // A coverage that has ended is not among them, and two under one contract are one.
    expect(column("contract.number").value(covered)).toBe("CON-2026-0001");
    expect(column("contract.number").value(bare)).toBe("");
  });

  it("lists the systems it is registered with, one that was removed not counting", () => {
    expect(column("registration.system").value(covered)).toBe("NetWatch");
    expect(column("registration.system").value(bare)).toBe("");
  });

  it("shows the purchase line by its name, and says its HID as the hint of the cell", () => {
    expect(column("purchase_line_hid").value(covered)).toBe("RITM0012345/2");
    expect(cellHint(column("purchase_line_hid"), covered)).toContain(LINE);
    expect(column("purchase_line_hid").value(bare)).toBeUndefined();
    expect(cellHint(column("purchase_line_hid"), bare)).toBe("");
  });

  it("filters and sorts each by the field the server has for it", () => {
    expect(asked("covered")).toMatchObject({ field: "covered", sortField: "covered" });
    expect(asked("covered")).toMatchObject({ kind: "boolean" });
    expect(asked("covered_until")).toMatchObject({
      field: "covered_until",
      sortField: "covered_until",
      kind: "date",
    });
    // Found by any of the contracts, and sorted by the first of them.
    expect(asked("contract.number")).toMatchObject({
      field: "contract.number",
      sortField: "contract.number",
    });
    expect(asked("registration.system")).toMatchObject({
      field: "registration.system",
      sortField: "registration.system",
    });
    // The list knows the line by its HID.
    expect(asked("purchase_line_hid")).toMatchObject({
      field: "purchase_line_hid",
      sortField: "purchase_line_hid",
      kind: "reference",
    });
  });

  it("hides all five until they are asked for", () => {
    for (const id of [
      "covered",
      "covered_until",
      "contract.number",
      "registration.system",
      "purchase_line_hid",
    ]) {
      expect(column(id).hide, id).toBe(true);
    }
  });

  it("exports the cover and the line under the names a file of items has, and no registration", () => {
    const exported = exportColumns(COLUMNS, [
      { colId: "covered" },
      { colId: "covered_until" },
      { colId: "contract.number" },
      { colId: "registration.system" },
      { colId: "purchase_line_hid" },
    ]);
    // `contract.number` and `purchase_line_hid` are names the export reads as its
    // columns `contracts` and `purchase_line`.
    expect(exported).toEqual([
      "hid",
      "covered",
      "covered_until",
      "contract.number",
      "purchase_line_hid",
    ]);
  });
});

describe("the columns a reader starts with", () => {
  it("are the ones of 0.3.0, the health and the operator, which stands after the owner, and where each is, in place of Expected online (P-193)", () => {
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
      "health",
      "owner.label",
      "operator.label",
      "location.name",
      "site",
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

describe("what still counts an item out of service, and a line of another model, in the item grid", () => {
  const counted = (...numbers: string[]) =>
    ({
      ...chassis,
      out_of_service_contracts: numbers.map((number, at) => ({
        hid: `0193a1f4-0000-7000-8000-0000000000c${at}`,
        number,
        vendor: "Cisco",
        status: "active",
        record_status: "active",
      })),
      purchase_line_mismatch: numbers.length > 0,
    }) as unknown as Item;
  const archived = counted("CON-2026-0001", "CON-2025-0009");
  const inService = counted();

  it("lists the contracts the server says still count it, by their numbers, as the list for the vendor", () => {
    expect(column("out_of_service_contract.number").value(archived)).toBe(
      "CON-2026-0001, CON-2025-0009",
    );
    expect(cellHint(column("out_of_service_contract.number"), archived)).toContain(
      "the list to send the vendor",
    );
    // Blank for an item in service.
    expect(column("out_of_service_contract.number").value(inService)).toBe("");
    expect(cellHint(column("out_of_service_contract.number"), inService)).toBe("");
  });

  it("filters and sorts by those contracts on the server, as the contracts that cover it are", () => {
    expect(asked("out_of_service_contract.number")).toMatchObject({
      field: "out_of_service_contract.number",
      sortField: "out_of_service_contract.number",
      kind: "text",
    });
    expect(column("out_of_service_contract.number").header).toBe("Still counted under");
  });

  it("says where an item is on a line of another model, and filters by it", () => {
    expect(column("purchase_line_mismatch").value(archived)).toBe("Yes");
    expect(cellHint(column("purchase_line_mismatch"), archived)).toContain("0.6.0 let in");
    expect(column("purchase_line_mismatch").value(inService)).toBe("");
    expect(asked("purchase_line_mismatch")).toMatchObject({
      field: "purchase_line_mismatch",
      sortField: "purchase_line_mismatch",
      kind: "boolean",
    });
  });

  it("hides both until they are asked for, and exports them under the names a file of items has", () => {
    expect(column("out_of_service_contract.number").hide).toBe(true);
    expect(column("purchase_line_mismatch").hide).toBe(true);
    // The export reads `out_of_service_contract.number` as its column `out_of_service_contracts`.
    expect(
      exportColumns(COLUMNS, [
        { colId: "out_of_service_contract.number" },
        { colId: "purchase_line_mismatch" },
      ]),
    ).toEqual(["hid", "out_of_service_contract.number", "purchase_line_mismatch"]);
  });
});
