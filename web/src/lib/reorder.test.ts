import { describe, expect, it } from "vitest";
import { reordered } from "./reorder";

function rows(...sorts: number[]) {
  return sorts.map((sort, place) => ({ hid: `c${place + 1}`, sort, row_version: place + 1 }));
}

describe("reordered", () => {
  it("changes only the two rows that swap, when the order has room in it", () => {
    expect(reordered(rows(10, 20, 30, 40), "c3", -1)).toEqual([
      { hid: "c3", row_version: 3, sort: 20 },
      { hid: "c2", row_version: 2, sort: 30 },
    ]);
    expect(reordered(rows(10, 20, 30, 40), "c1", 1)).toEqual([
      { hid: "c2", row_version: 2, sort: 10 },
      { hid: "c1", row_version: 1, sort: 20 },
    ]);
  });

  it("gives every row a place of its own when rows share a number", () => {
    expect(reordered(rows(0, 0, 0), "c3", -1)).toEqual([
      { hid: "c1", row_version: 1, sort: 10 },
      { hid: "c3", row_version: 3, sort: 20 },
      { hid: "c2", row_version: 2, sort: 30 },
    ]);
  });

  it("changes nothing for a move off either end, or of a row that is not there", () => {
    expect(reordered(rows(10, 20), "c1", -1)).toEqual([]);
    expect(reordered(rows(10, 20), "c2", 1)).toEqual([]);
    expect(reordered(rows(10, 20), "c9", 1)).toEqual([]);
    expect(reordered([], "c1", 1)).toEqual([]);
  });

  it("carries the version each row was read at", () => {
    const [change] = reordered(rows(10, 20), "c2", -1);
    expect(change).toEqual({ hid: "c2", row_version: 2, sort: 10 });
  });
});
