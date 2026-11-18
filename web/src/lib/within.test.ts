import { describe, expect, it } from "vitest";
import { locationSearch } from "./places";
import { broughtPaths, LINES_IN_ONE_PATH, locationsWithin, siteOption } from "./within";

const hid = (n: number) => `01a1ecba-0000-7000-8000-${String(n).padStart(12, "0")}`;
const filterOf = (path: string) =>
  decodeURIComponent(new URLSearchParams(path.split("?")[1]).get("filter") ?? "");

describe("broughtPaths", () => {
  it("names the lines on which something arrived, in one address", () => {
    const paths = broughtPaths([
      { hid: hid(2), line: 2, received_quantity: 4 },
      { hid: hid(1), line: 1, received_quantity: 1 },
      { hid: hid(3), line: 3, received_quantity: 0 },
    ]);
    expect(paths).toHaveLength(1);
    expect(paths[0]?.from).toBe(1);
    expect(paths[0]?.to).toBe(2);
    expect(filterOf(paths[0]?.path ?? "")).toBe(`purchase_line_hid:in:${hid(1)},${hid(2)}`);
    expect(paths[0]?.path).toMatch(/&minor=1&archived=1&drafts=1$/);
  });

  it("names one line by eq, and no line received on by no address", () => {
    expect(
      filterOf(broughtPaths([{ hid: hid(5), line: 5, received_quantity: 2 }])[0]?.path ?? ""),
    ).toBe(`purchase_line_hid:eq:${hid(5)}`);
    expect(broughtPaths([{ hid: hid(5), line: 5, received_quantity: 0 }])).toEqual([]);
  });

  it("gives a request of very many lines in parts, each address short enough to send", () => {
    const lines = Array.from({ length: 250 }, (_, n) => ({
      hid: hid(n + 1),
      line: n + 1,
      received_quantity: 1,
    }));
    const paths = broughtPaths(lines);
    expect(paths.map((part) => [part.from, part.to])).toEqual([
      [1, 100],
      [101, 200],
      [201, 250],
    ]);
    for (const part of paths) expect(part.path.length).toBeLessThan(4_500);
    expect(LINES_IN_ONE_PATH).toBe(100);
  });
});

describe("siteOption", () => {
  it("marks a draft site", () => {
    expect(siteOption({ hid: "S", path: "East > Site-3", record_status: "draft" }).label).toBe(
      "East > Site-3 (draft)",
    );
    expect(siteOption({ hid: "S", path: "East > Site-1", record_status: "active" })).toEqual({
      value: "S",
      label: "East > Site-1",
    });
  });
});

describe("locationsWithin", () => {
  it("is the search for a location as it was, where no site is given", () => {
    expect(locationsWithin("rack a1")).toEqual(locationSearch("rack a1"));
    expect(locationsWithin("  ")).toBeNull();
  });

  it("is the site's locations before anything is typed", () => {
    expect(locationsWithin("", "S1")).toEqual({ field: "site_hid", op: "eq", value: "S1" });
  });

  it("looks for the words within the site", () => {
    const words = locationSearch("bay");
    expect(words).not.toBeNull();
    expect(locationsWithin("bay", "S1")).toEqual({
      and: [{ field: "site_hid", op: "eq", value: "S1" }, words],
    });
  });
});
