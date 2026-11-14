import { describe, expect, it } from "vitest";
import { type GridLayout, GridStore, gridKey, mergeLayout, parseLayout } from "./gridStore";
import { memoryStorage } from "./session";

const VERA = "0193a1f4-0000-7000-8000-00000000000a";
const QUILL = "0193a1f4-0000-7000-8000-00000000000b";

const DEFAULTS = [
  { id: "name", width: 220 },
  { id: "hostname", hide: true },
  { id: "serial_number", width: 150 },
  { id: "lifecycle_state" },
];

const LAYOUT: GridLayout = {
  columns: [
    { id: "serial_number", width: 180, hide: false },
    { id: "name", width: 300, hide: false },
    { id: "lifecycle_state", hide: true },
    { id: "hostname", hide: false },
  ],
  sort: [
    { id: "lifecycle_state", descending: true },
    { id: "name", descending: false },
  ],
  filter: { name: { filterType: "text", type: "contains", filter: "site2" } },
  short: "lifecycle_state:in:Test,Prod",
  includeArchived: true,
  includeDrafts: false,
  includeMinor: true,
};

describe("GridStore", () => {
  it("gives back the layout it was given", () => {
    const store = new GridStore(memoryStorage(), VERA);
    expect(store.load("items")).toBeNull();
    store.save("items", LAYOUT);
    expect(store.load("items")).toEqual(LAYOUT);
  });

  it("keeps each user's layout of each grid apart", () => {
    const storage = memoryStorage();
    const vera = new GridStore(storage, VERA);
    const quill = new GridStore(storage, QUILL);
    vera.save("items", LAYOUT);
    quill.save("items", { ...LAYOUT, short: "tags:has:core" });
    vera.save("catalog", { ...LAYOUT, short: "" });
    expect(vera.load("items")?.short).toBe("lifecycle_state:in:Test,Prod");
    expect(quill.load("items")?.short).toBe("tags:has:core");
    expect(vera.load("catalog")?.short).toBe("");
    expect(quill.load("catalog")).toBeNull();
    expect(storage.getItem(gridKey(VERA, "items"))).toContain('"v":1');
  });

  it("forgets a layout when asked", () => {
    const store = new GridStore(memoryStorage(), VERA);
    store.save("items", LAYOUT);
    store.clear("items");
    expect(store.load("items")).toBeNull();
  });

  it("remembers nothing, and breaks nothing, when the browser refuses storage", () => {
    const refusing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    };
    const store = new GridStore(refusing, VERA);
    expect(() => store.save("items", LAYOUT)).not.toThrow();
    expect(store.load("items")).toBeNull();
    expect(() => store.clear("items")).not.toThrow();
  });
});

describe("parseLayout", () => {
  it("takes anything malformed as no layout", () => {
    for (const raw of [null, "", "{not json", "[]", '"text"', '{"v":2,"columns":[]}', '{"v":1}']) {
      expect(parseLayout(raw), String(raw)).toBeNull();
    }
  });

  it("keeps what is well formed and drops the rest", () => {
    const raw = JSON.stringify({
      v: 1,
      columns: [
        { id: "name", width: 250.4, hide: false },
        { id: "", width: 10 },
        { id: "hostname", width: "wide", hide: "yes" },
        "serial_number",
        { id: "tags", width: -5, hide: true },
      ],
      sort: [{ id: "name", descending: true }, { descending: true }, "name"],
      filter: ["not", "a", "model"],
      short: 12,
      includeDrafts: "yes",
    });
    expect(parseLayout(raw)).toEqual({
      columns: [
        { id: "name", width: 250, hide: false },
        { id: "hostname", hide: false },
        { id: "tags", hide: true },
      ],
      sort: [{ id: "name", descending: true }],
      filter: {},
      short: "",
      includeArchived: false,
      includeDrafts: false,
      includeMinor: false,
    });
  });

  it("reads a layout stored before the minor-items switch as having it off", () => {
    const raw = JSON.stringify({ v: 1, columns: [{ id: "name", hide: false }], short: "" });
    expect(parseLayout(raw)?.includeMinor).toBe(false);
    const on = JSON.stringify({ v: 1, columns: [], includeMinor: true });
    expect(parseLayout(on)?.includeMinor).toBe(true);
  });
});

describe("mergeLayout", () => {
  it("is the page's own columns when nothing is stored", () => {
    expect(mergeLayout(DEFAULTS, null)).toEqual({
      columns: [
        { id: "name", width: 220, hide: false },
        { id: "hostname", hide: true },
        { id: "serial_number", width: 150, hide: false },
        { id: "lifecycle_state", hide: false },
      ],
      sort: [],
      filter: {},
      short: "",
      includeArchived: false,
      includeDrafts: false,
      includeMinor: false,
    });
  });

  it("keeps the reader's order, widths, visibility, sort, filter and switches", () => {
    expect(mergeLayout(DEFAULTS, LAYOUT)).toEqual(LAYOUT);
  });

  it("drops a column the page no longer has, with its sort and its filter", () => {
    const stored: GridLayout = {
      ...LAYOUT,
      columns: [{ id: "gone", width: 90, hide: false }, ...LAYOUT.columns],
      sort: [{ id: "gone", descending: false }, ...LAYOUT.sort],
      filter: { ...LAYOUT.filter, gone: { filterType: "text", type: "blank" } },
    };
    expect(mergeLayout(DEFAULTS, stored)).toEqual(LAYOUT);
  });

  it("puts a column the page has gained after the one it follows there", () => {
    const stored: GridLayout = {
      ...LAYOUT,
      columns: [
        { id: "serial_number", width: 180, hide: false },
        { id: "name", width: 300, hide: false },
      ],
      sort: [],
      filter: {},
    };
    expect(mergeLayout(DEFAULTS, stored).columns.map((column) => column.id)).toEqual([
      "serial_number",
      "lifecycle_state",
      "name",
      "hostname",
    ]);
    // A new first column goes first.
    const gained = [{ id: "hid", hide: true }, ...DEFAULTS];
    expect(mergeLayout(gained, LAYOUT).columns[0]).toEqual({ id: "hid", hide: true });
  });

  it("lists a column once, however often it was stored", () => {
    const stored: GridLayout = { ...LAYOUT, columns: [...LAYOUT.columns, ...LAYOUT.columns] };
    expect(mergeLayout(DEFAULTS, stored).columns).toEqual(LAYOUT.columns);
  });
});
