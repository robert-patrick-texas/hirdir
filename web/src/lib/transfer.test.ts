import { describe, expect, it } from "vitest";
import {
  type Chosen,
  chosenCount,
  clipboardText,
  csvToClipboard,
  exportColumns,
  exportName,
  exportRequest,
  type GridView,
  parseCsv,
} from "./transfer";

const COLUMNS = [
  { id: "name" },
  { id: "hostname" },
  { id: "catalog.pid" },
  { id: "effective.ldos" },
  { id: "vendor_hid", column: null },
  { id: "pid_again", column: "catalog.pid" },
  { id: "mgmt_address", column: ["mgmt_ipv4", "mgmt_ipv6"] },
  { id: "hid" },
];

const VIEW: GridView = {
  filter: { field: "hostname", op: "prefix", value: "site2-" },
  sort: ["site", "-effective.ldos"],
  include_archived: false,
  include_drafts: true,
};

describe("exportColumns", () => {
  it("takes the columns on show, in the order shown, with hid first", () => {
    const state = [
      { colId: "effective.ldos", hide: false },
      { colId: "name" },
      { colId: "hostname", hide: true },
      { colId: "catalog.pid", hide: null },
    ];
    expect(exportColumns(COLUMNS, state)).toEqual(["hid", "effective.ldos", "name", "catalog.pid"]);
  });

  it("puts hid first once, wherever the grid shows it, and when it is hidden", () => {
    expect(exportColumns(COLUMNS, [{ colId: "name" }, { colId: "hid" }])).toEqual(["hid", "name"]);
    expect(exportColumns(COLUMNS, [{ colId: "hid", hide: true }, { colId: "name" }])).toEqual([
      "hid",
      "name",
    ]);
    expect(exportColumns(COLUMNS, [])).toEqual(["hid"]);
  });

  it("leaves out a column no export has, and names a column once", () => {
    const state = [{ colId: "vendor_hid" }, { colId: "catalog.pid" }, { colId: "pid_again" }];
    expect(exportColumns(COLUMNS, state)).toEqual(["hid", "catalog.pid"]);
  });

  it("writes every column of an export that one column of the grid shows", () => {
    const state = [{ colId: "name" }, { colId: "mgmt_address" }, { colId: "hostname" }];
    expect(exportColumns(COLUMNS, state)).toEqual([
      "hid",
      "name",
      "mgmt_ipv4",
      "mgmt_ipv6",
      "hostname",
    ]);
  });

  it("passes over a column the page no longer has", () => {
    expect(exportColumns(COLUMNS, [{ colId: "gone" }, { colId: "name" }])).toEqual(["hid", "name"]);
  });
});

describe("exportRequest", () => {
  it("names all that match by the filter, the sort and the switches, never by rows", () => {
    const request = exportRequest("items", "csv", VIEW, ["hid", "name"], {
      kind: "all",
      count: 51234,
    });
    expect(request).toEqual({
      entity: "items",
      format: "csv",
      columns: ["hid", "name"],
      filter: { field: "hostname", op: "prefix", value: "site2-" },
      sort: ["site", "-effective.ldos"],
      include_archived: false,
      include_drafts: true,
    });
    expect(request).not.toHaveProperty("hids");
  });

  it("names particular rows by their HIDs alone, in the grid's order", () => {
    const chosen: Chosen = { kind: "rows", hids: ["i-2", "i-1"] };
    const request = exportRequest("items", "json", VIEW, ["hid"], chosen);
    expect(request.hids).toEqual(["i-2", "i-1"]);
    expect(request).not.toHaveProperty("filter");
    expect(request.sort).toEqual(VIEW.sort);
    expect(request.format).toBe("json");
  });

  it("sends no filter when the grid has none", () => {
    const request = exportRequest("vendors", "csv", { ...VIEW, filter: null, sort: [] }, ["hid"], {
      kind: "all",
      count: 3,
    });
    expect(request).not.toHaveProperty("filter");
    expect(request.sort).toEqual([]);
  });

  it("asks for values in force, as the grid shows them, and for no source columns", () => {
    const request = exportRequest("items", "csv", VIEW, ["hid"], { kind: "all", count: 1 });
    expect(request).not.toHaveProperty("own_values");
    expect(request).not.toHaveProperty("include_sources");
  });

  it("does not hand over the grid's own lists", () => {
    const columns = ["hid", "name"];
    const chosen: Chosen = { kind: "rows", hids: ["i-1"] };
    const request = exportRequest("items", "csv", VIEW, columns, chosen);
    columns.push("pid");
    chosen.hids.push("i-2");
    expect(request.columns).toEqual(["hid", "name"]);
    expect(request.hids).toEqual(["i-1"]);
  });
});

describe("chosenCount and exportName", () => {
  it("count the rows chosen", () => {
    expect(chosenCount({ kind: "rows", hids: ["a", "b"] })).toBe(2);
    expect(chosenCount({ kind: "all", count: 50000 })).toBe(50000);
  });

  it("name a file after what it holds", () => {
    expect(exportName("catalog_entries", "json")).toBe("hirdir-catalog_entries.json");
  });
});

describe("parseCsv", () => {
  it("reads rows of cells, and a final line break starts no row", () => {
    expect(parseCsv("hid,name\ni-1,site2-sw-access-01\n")).toEqual([
      ["hid", "name"],
      ["i-1", "site2-sw-access-01"],
    ]);
    expect(parseCsv("hid,name\ni-1,site2-sw-access-01")).toHaveLength(2);
    expect(parseCsv("")).toEqual([]);
  });

  it("keeps empty cells, also the last of a row", () => {
    expect(parseCsv("hid,name,owner\ni-1,,\n")).toEqual([
      ["hid", "name", "owner"],
      ["i-1", "", ""],
    ]);
  });

  it("reads quoted cells with commas, quotes and line breaks in them", () => {
    const text = 'hid,description\ni-1,"Rack 4, unit 12"\ni-2,"said ""spare"""\ni-3,"two\nlines"\n';
    expect(parseCsv(text)).toEqual([
      ["hid", "description"],
      ["i-1", "Rack 4, unit 12"],
      ["i-2", 'said "spare"'],
      ["i-3", "two\nlines"],
    ]);
  });

  it("reads Windows line breaks and passes over a byte order mark", () => {
    expect(parseCsv("﻿hid,name\r\ni-1,a\r\n")).toEqual([
      ["hid", "name"],
      ["i-1", "a"],
    ]);
  });

  it("keeps a row whose only cell is empty and quoted", () => {
    expect(parseCsv('hid\n""\ni-2\n')).toEqual([["hid"], [""], ["i-2"]]);
  });
});

describe("clipboardText", () => {
  it("puts a tab between cells and a line break between rows, the header first", () => {
    expect(
      clipboardText([
        ["hid", "name", "tags"],
        ["i-1", "site2-sw-access-01", "lab;refresh-2030"],
      ]),
    ).toBe("hid\tname\ttags\ni-1\tsite2-sw-access-01\tlab;refresh-2030");
  });

  it("keeps every cell in its column: a tab or a line break inside one becomes a space", () => {
    expect(clipboardText([["a\tb", "two\r\nlines", "one\nmore"]])).toBe("a b\ttwo lines\tone more");
  });
});

describe("csvToClipboard", () => {
  it("holds the cells of the exported file, and counts the records", () => {
    const csv = 'hid,name,est_value\ni-1,"Core, east",\'-5.00\ni-2,,18000.00\n';
    expect(csvToClipboard(csv)).toEqual({
      text: "hid\tname\test_value\ni-1\tCore, east\t'-5.00\ni-2\t\t18000.00",
      count: 2,
    });
  });

  it("counts no record in a file that holds only its header", () => {
    expect(csvToClipboard("hid,name\n")).toEqual({ text: "hid\tname", count: 0 });
    expect(csvToClipboard("").count).toBe(0);
  });
});
