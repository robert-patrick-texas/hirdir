import { describe, expect, it } from "vitest";
import { entrySearch, interleaved, offerNote, regionSearch, siteSearch } from "./recordSearch";

describe("searching for a record to put a reference on", () => {
  it("finds a catalog entry by each word in its vendor, PID or model name", () => {
    expect(entrySearch("  ")).toBeNull();
    expect(entrySearch("C9300")).toEqual({
      or: [
        { field: "vendor", op: "contains", value: "C9300" },
        { field: "pid", op: "contains", value: "C9300" },
        { field: "model_name", op: "contains", value: "C9300" },
      ],
    });
    const two = entrySearch("Cisco 48P") as { and: unknown[] };
    expect(two.and).toHaveLength(2);
  });

  it("finds a place by the words of its path", () => {
    const site = siteSearch("Central > Site-2") as { and: Array<{ or: Array<{ value: string }> }> };
    expect(site.and.map((part) => part.or[0]?.value)).toEqual(["Central", "Site-2"]);
    expect(site.and[0]?.or.map((condition) => (condition as { field?: string }).field)).toEqual([
      "name",
      "code",
      "region.name",
    ]);
    const region = regionSearch("Americas") as { or: Array<{ field: string }> };
    expect(region.or.map((condition) => condition.field)).toEqual(["name", "code", "parent.name"]);
  });

  it("offers a few of each kind in turn, and counts them all", () => {
    const found = interleaved(
      [
        { kind: "location", offers: ["l1", "l2", "l3", "l4"], total: 40 },
        { kind: "catalog_entry", offers: [], total: 0 },
        { kind: "item", offers: ["i1", "i2"], total: 2 },
      ],
      5,
    );
    expect(found.offers).toEqual(["l1", "i1", "l2", "i2", "l3"]);
    expect(found.total).toBe(42);
    expect(interleaved([], 8)).toEqual({ offers: [], total: 0 });
  });

  it("says what kind each offer is, and that it is a draft", () => {
    expect(offerNote("catalog_entry", "active")).toBe("catalog entry");
    expect(offerNote("location", "draft")).toBe("location, draft");
  });
});
