import { describe, expect, it } from "vitest";
import { buildBulk, HOST } from "./bulk";
import { knownAbove, ownerSource } from "./descent";
import {
  bulkHost,
  type HostRef,
  hostedRows,
  hostFields,
  hostHint,
  hostIsGone,
  hostPath,
  hostSourcePath,
  hostSpecs,
  hostValue,
  hostWhat,
  mayHost,
  reviewsText,
  runsOnHost,
  sentHost,
} from "./hosting";
import { operatorSource } from "./operators";
import { CATALOG_KINDS, optionLabel } from "./options";
import { atFields, buildCreate, buildPatch, changedValues, formOf, localMoment } from "./patch";

const server: HostRef = {
  item_hid: "srv-1",
  group_hid: null,
  name: "site2-esx-01",
  pid: "EX-SRV-1",
  lifecycle_state: "Prod",
  record_status: "active",
  type: null,
};
const cluster: HostRef = {
  item_hid: null,
  group_hid: "cl-1",
  name: "site2-esx-cluster",
  pid: null,
  lifecycle_state: null,
  record_status: "active",
  type: "cluster",
};

describe("the kinds", () => {
  it("runs on a host for a virtual machine, a virtual context and a container alone", () => {
    expect(["virtual_machine", "virtual_context", "container"].every(runsOnHost)).toBe(true);
    expect(runsOnHost("hardware")).toBe(false);
    expect(runsOnHost(null)).toBe(false);
  });

  it("labels each of the six kinds", () => {
    expect(CATALOG_KINDS.map((kind) => optionLabel(CATALOG_KINDS, kind.value))).toEqual([
      "Hardware",
      "Virtual machine",
      "Virtual context",
      "Container",
      "Software",
      "Service",
    ]);
  });

  it("hosts on hardware, a virtual machine, or an item of no model", () => {
    expect(mayHost("hardware")).toBe(true);
    expect(mayHost("virtual_machine")).toBe(true);
    expect(mayHost(null)).toBe(true);
    expect(mayHost("container")).toBe(false);
  });
});

describe("a host as a link", () => {
  it("leads to an item's page or a group's", () => {
    expect(hostPath(server)).toBe("/items/srv-1");
    expect(hostPath(cluster)).toBe("/groups/cl-1");
  });

  it("says which record it is", () => {
    expect(hostWhat(server)).toBe("an item");
    expect(hostWhat(cluster)).toBe("a cluster");
    expect(hostWhat({ type: "stack" })).toBe("a stack");
    expect(hostHint(server)).toBe("An item, EX-SRV-1");
  });

  it("is gone when retired or out of the team's hands", () => {
    expect(hostIsGone(server)).toBe(false);
    expect(hostIsGone({ ...server, record_status: "retired" })).toBe(true);
    expect(hostIsGone({ ...server, lifecycle_state: "Released" })).toBe(true);
    expect(hostHint({ ...server, lifecycle_state: "Archived" })).toContain(
      "out of the team's hands",
    );
  });

  it("names the record a value came from through the host, a group's page for a cluster", () => {
    expect(hostSourcePath("cl-1", cluster)).toBe("/groups/cl-1");
    expect(hostSourcePath("srv-1", server)).toBe("/items/srv-1");
    // An item above the host is an item.
    expect(hostSourcePath("chassis-1", server)).toBe("/items/chassis-1");
  });

  it("says an operator and an owner come from the host by its name", () => {
    const from = operatorSource(
      { source: "host", source_hid: "cl-1", source_label: "site2-esx-cluster" },
      cluster,
    );
    expect(from).toEqual({ text: "the host site2-esx-cluster", path: "/groups/cl-1" });
    const known = knownAbove({ parent: null, groups: [], host: cluster });
    expect(ownerSource({ value: "own-1", source: "host", source_hid: "cl-1" }, known)).toEqual({
      text: "the host site2-esx-cluster",
      path: "/groups/cl-1",
    });
  });
});

describe("the one field of a form for an item or a group", () => {
  it("holds which and the HID", () => {
    expect(hostValue({ host_item_hid: "srv-1", host_group_hid: null })).toBe("item:srv-1");
    expect(hostValue({ host_item_hid: null, host_group_hid: "cl-1" })).toBe("group:cl-1");
    expect(hostValue({})).toBe("");
  });

  it("is sent as one field set and the other cleared", () => {
    expect(hostFields("group:cl-1")).toEqual({ host_item_hid: null, host_group_hid: "cl-1" });
    expect(sentHost({ row_version: 3, host_hid: "item:srv-1" })).toEqual({
      row_version: 3,
      host_item_hid: "srv-1",
      host_group_hid: null,
    });
    expect(sentHost({ row_version: 3, host_hid: null })).toEqual({
      row_version: 3,
      host_item_hid: null,
      host_group_hid: null,
    });
    // A new item sends only the one given, and a body without it is sent as it is.
    expect(sentHost({ hostname: "a", host_hid: "group:cl-1" }, true)).toEqual({
      hostname: "a",
      host_group_hid: "cl-1",
    });
    expect(sentHost({ hostname: "a" })).toEqual({ hostname: "a" });
  });

  it("is asked for while the model chosen is of a kind that runs on a host", () => {
    const kinds: Record<string, string> = { vm: "virtual_machine", sw: "hardware" };
    const specs = hostSpecs({ kindOf: (hid) => kinds[hid] });
    const host = specs.find((spec) => spec.name === "host_hid");
    expect(host?.when?.({ catalog_entry_hid: "vm" })).toBe(true);
    expect(host?.when?.({ catalog_entry_hid: "sw" })).toBe(false);
    expect(host?.when?.({ catalog_entry_hid: "" })).toBe(false);
    // The moment seen is asked for once an item seen is chosen.
    const at = specs.find((spec) => spec.name === "host_observed_at");
    expect(at?.when?.({ catalog_entry_hid: "vm", observed_host_hid: "" })).toBe(false);
    expect(at?.when?.({ catalog_entry_hid: "vm", observed_host_hid: "srv-1" })).toBe(true);
  });

  it("fills the moment seen with now as the item seen is chosen, and clears it with it", () => {
    const specs = hostSpecs({ kindOf: () => "virtual_machine" });
    const values = formOf(specs);
    const chosen = changedValues(specs, values, "observed_host_hid", "srv-1");
    expect(chosen.observed_host_hid).toBe("srv-1");
    expect(chosen.host_observed_at).toBe(localMoment(new Date()));
    expect(changedValues(specs, chosen, "observed_host_hid", "").host_observed_at).toBe("");
  });

  it("clears the host of an item whose model is made of a kind that runs on none", () => {
    const kinds: Record<string, string> = { vm: "virtual_machine", sw: "hardware" };
    const specs = [
      { name: "catalog_entry_hid", label: "Catalog entry", kind: "entry" as const },
      ...hostSpecs({ kindOf: (hid) => kinds[hid] }),
    ];
    const record = {
      row_version: 4,
      catalog_entry_hid: "vm",
      host_hid: "item:srv-1",
      observed_host_hid: null,
      host_observed_at: null,
    };
    const built = buildPatch(specs, record, { ...formOf(specs, record), catalog_entry_hid: "sw" });
    expect(built.body).toEqual({ row_version: 4, catalog_entry_hid: "sw", host_hid: null });
  });

  it("puts a refusal of either field of the server at the one field", () => {
    const specs = hostSpecs({ kindOf: () => "virtual_machine" });
    expect(atFields(specs, { host_group_hid: "is retired", name: "x" })).toEqual({
      host_hid: "is retired",
      name: "x",
    });
  });

  it("sends a moment with its zone, and takes one to the minute", () => {
    const specs = hostSpecs({ kindOf: () => "virtual_machine" });
    const values = {
      catalog_entry_hid: "vm",
      host_hid: "",
      observed_host_hid: "srv-1",
      host_observed_at: "2026-11-18T09:30",
    };
    const built = buildCreate(specs, values);
    expect(built.body).toEqual({
      observed_host_hid: "srv-1",
      host_observed_at: new Date("2026-11-18T09:30").toISOString(),
    });
    expect(buildCreate(specs, { ...values, host_observed_at: "soon" }).errors).toHaveProperty(
      "host_observed_at",
    );
    expect(localMoment("2026-11-18T09:30:41.5Z")).toBe(
      localMoment(new Date("2026-11-18T09:30:00Z")),
    );
  });
});

describe("what runs on a record", () => {
  it("is listed each once, in the order sent, with its depth", () => {
    const item = (hid: string) => ({ hid }) as never;
    const rows = hostedRows([
      { depth: 1, host_hid: "srv-1", item: item("vm-1") },
      { depth: 2, host_hid: "vm-1", item: item("ctr-1") },
      { depth: 1, host_hid: "srv-1", item: item("vm-1") },
    ]);
    expect(rows.map((row) => [(row.item as { hid: string }).hid, row.depth])).toEqual([
      ["vm-1", 1],
      ["ctr-1", 2],
    ]);
  });
});

describe("what is to be looked at", () => {
  it("is said in words, with what each is about", () => {
    expect(reviewsText([])).toBe("");
    expect(
      reviewsText([
        { reason: "no_host", about: null },
        {
          reason: "not_reported",
          about: { hid: "sys", record_type: "external_system", label: "Example vCenter" },
        },
      ]),
    ).toBe("Names no host; Reported no more: Example vCenter");
  });
});

describe("a bulk edit of the host", () => {
  const fields = [{ name: HOST, label: "Host", kind: "host" as const, clearable: true }];
  const rows = { hids: ["vm-1", "vm-2"] };
  const draft = (value: string, clear = false) => ({
    lines: [{ name: HOST, clear, value }],
    reason: "",
    addTags: [],
    removeTags: [],
  });

  it("sets an item by its HID, and a stack or a cluster by its name", () => {
    expect(buildBulk(fields, draft("item:srv-1"), rows).body.set).toEqual({ host: "srv-1" });
    expect(
      buildBulk(fields, draft("group:cl-1"), rows, {}, { "group:cl-1": "site2-esx-cluster" }).body
        .set,
    ).toEqual({ host_group: "site2-esx-cluster" });
    expect(bulkHost("group:cl-1", undefined)).toBeNull();
    expect(buildBulk(fields, draft("group:cl-1"), rows).errors).toHaveProperty(HOST);
  });

  it("clears both where it is cleared", () => {
    expect(buildBulk(fields, draft("", true), rows).body.set).toEqual({
      host: null,
      host_group: null,
    });
  });
});
