import { describe, expect, it } from "vitest";
import { parseFilter } from "./filter";
import {
  holderFilter,
  REGISTRATION_STATUSES,
  type RegistrationRef,
  registeredPath,
  registeredRecord,
  registeredWith,
  SYSTEM_KINDS,
  systemPath,
  unregistered,
} from "./systems";

const ref = (name: string, status: string): RegistrationRef =>
  ({
    hid: `reg-${name}`,
    system_hid: `sys-${name}`,
    system: { hid: `sys-${name}`, name, kind: "monitoring" },
    external_id: null,
    status,
    confirmed_at: null,
  }) as RegistrationRef;

describe("what a record is registered with", () => {
  it("names the systems, and leaves out a registration that was removed", () => {
    expect(
      registeredWith([
        ref("NetWatch", "registered"),
        ref("ConfigVault", "removed"),
        ref("FabricController", "pending"),
      ]),
    ).toBe("NetWatch, FabricController");
    expect(registeredWith([])).toBe("");
  });

  it("names for an item also what its stack or cluster is registered with, each system once", () => {
    // What the filter of the item list finds an item by: its own, and its group's.
    expect(
      registeredWith(
        [ref("ConfigVault", "registered")],
        [
          ref("NetWatch", "registered"),
          ref("ConfigVault", "registered"),
          ref("Old poller", "removed"),
        ],
      ),
    ).toBe("ConfigVault, NetWatch");
    expect(registeredWith([], [ref("NetWatch", "registered")])).toBe("NetWatch");
  });

  it("is listed by the record: an item by item_hid, a group by group_hid", () => {
    expect(holderFilter({ item_hid: "i-1" })).toBe("item_hid:eq:i-1");
    expect(holderFilter({ group_hid: "g-1" })).toBe("group_hid:eq:g-1");
  });
});

describe("the record a registration is of", () => {
  it("is the group for a registration of a stack, with the page of the group", () => {
    expect(
      registeredRecord({
        group: { hid: "g-1", name: "site2-sw-stack1", type: "stack" } as never,
        group_hid: "g-1",
        item: null,
        item_hid: null,
      }),
    ).toEqual({ name: "site2-sw-stack1", path: "/groups/g-1", kind: "Device group" });
  });

  it("is the item otherwise, by the name it is shown by", () => {
    expect(
      registeredRecord({
        group: null,
        group_hid: null,
        item: { hid: "i-1", name: null, serial_number: "FCW0000X001", asset_tag: null, pid: null },
        item_hid: "i-1",
      }),
    ).toEqual({ name: "FCW0000X001", path: "/items/i-1", kind: "Item" });
  });

  it("is nothing when the answer names neither", () => {
    expect(
      registeredRecord({ group: null, group_hid: null, item: null, item_hid: null }),
    ).toBeNull();
  });
});

describe("the systems a record can still be registered with", () => {
  const systems = [
    { hid: "s-1", name: "NetWatch", record_status: "active" },
    { hid: "s-2", name: "ConfigVault", record_status: "active" },
    { hid: "s-3", name: "Old poller", record_status: "retired" },
    { hid: "s-4", name: "Pilot", record_status: "draft" },
  ] as const;

  it("are those it has no registration with, a removed one counting as one", () => {
    // A registration that was removed is the same record when it begins again.
    expect(unregistered(systems, [{ system_hid: "s-1" }])).toEqual([
      { value: "s-2", label: "ConfigVault" },
      { value: "s-4", label: "Pilot" },
    ]);
  });

  it("never offer a retired system: it takes no new registration", () => {
    expect(unregistered(systems, []).map((option) => option.label)).not.toContain("Old poller");
  });
});

describe("systems as words and links", () => {
  it("has the eight kinds of the fixed list, other last", () => {
    expect(SYSTEM_KINDS.map((kind) => kind.value)).toEqual([
      "monitoring",
      "config_backup",
      "access_control",
      "sdn_controller",
      "cloud_service",
      "dns",
      "discovery",
      "other",
    ]);
    expect(REGISTRATION_STATUSES.map((status) => status.value)).toEqual([
      "registered",
      "pending",
      "removed",
    ]);
  });

  it("leads to a system by its HID", () => {
    expect(systemPath("s-1")).toBe("/systems/s-1");
  });

  it("finds the items and the groups registered with a system by its name", () => {
    const items = new URL(registeredPath("items", "NetWatch"), "http://localhost");
    expect(items.pathname).toBe("/items");
    expect(items.searchParams.get("filter")).toBe("registration.system:eq:NetWatch");
    expect(items.searchParams.get("minor")).toBe("1");
    const groups = new URL(registeredPath("groups", "NetWatch"), "http://localhost");
    expect(groups.pathname).toBe("/groups");
    expect(groups.searchParams.get("minor")).toBeNull();
  });

  it("writes a name the short form cannot hold as a filter tree, which the grid reads too", () => {
    const awkward = new URL(registeredPath("items", "NetWatch a:eq:b"), "http://localhost");
    const filter = awkward.searchParams.get("filter") ?? "";
    expect(filter.startsWith("{")).toBe(true);
    expect(parseFilter(filter)).toEqual({
      ok: true,
      filter: { field: "registration.system", op: "eq", value: "NetWatch a:eq:b" },
    });
  });
});
