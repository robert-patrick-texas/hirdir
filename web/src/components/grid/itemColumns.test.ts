import { describe, expect, it } from "vitest";
import type { Schemas } from "../../api/client";
import { exportColumns } from "../../lib/transfer";
import { columnDefaults, queryColumns } from "./columns";
import { itemColumns, itemIsDimmed } from "./itemColumns";

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
    },
    {
      hid: "a-2",
      address: "2001:db8::10",
      network: null,
      network_hid: null,
      role: "loopback",
      is_primary: false,
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

const COLUMNS = itemColumns([], ["Assigned", "Prod", "Archived"]);

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

describe("major and minor items in the item grid", () => {
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
    expect(column("mgmt_address").value(supply)).toBeUndefined();
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
    for (const name of ["is_major", "parent", "position", "depth", "mgmt_address"]) {
      expect(exported, name).toContain(name);
    }
    for (const name of ["group.name", "group.type", "address", "network.label"]) {
      expect(exported, name).not.toContain(name);
    }
  });
});

describe("the columns a reader starts with", () => {
  it("are the ones of the last release: every new column is there to be shown when wanted", () => {
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
      "owner.label",
      "tags",
      "effective.est_value",
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
