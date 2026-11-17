import { describe, expect, it } from "vitest";
import { barShare, largestOf, rankColumn, ranking, ranks } from "./rank";

interface Row {
  key: string | null;
  items: number;
  weight: string;
}

const rows: Row[] = [
  { key: "a", items: 4, weight: "2.50" },
  { key: "b", items: 9, weight: "12.00" },
  { key: "c", items: 4, weight: "0.75" },
  { key: null, items: 30, weight: "1.00" },
  { key: "d", items: 1, weight: "12.00" },
];

const counts = {
  items: { value: (row: Row) => row.items, text: (row: Row) => String(row.items), label: "items" },
  weight: {
    value: (row: Row) => Number(row.weight),
    text: (row: Row) => row.weight,
    label: "support weight",
  },
};
const blank = (row: Row) => row.key === null;

describe("the rank of a table of a report", () => {
  it("is 1 for the most, and two of one count share a rank, the next ranked as if they had not", () => {
    const ranked = ranks(rows, (row) => row.items, blank);
    expect(rows.map((row) => ranked.get(row) ?? null)).toEqual([2, 1, 2, null, 4]);
  });

  it("gives the blank row none, and takes no place from the others for it", () => {
    // The blank row holds the most items, and the first of the others is still 1.
    const ranked = ranks(rows, (row) => row.items, blank);
    expect(ranked.has(rows[3] as Row)).toBe(false);
    expect(ranked.get(rows[1] as Row)).toBe(1);
  });

  it("gives a row with nothing in the column no rank", () => {
    const ranked = ranks(rows, (row) => (row.key === "c" ? null : row.items), blank);
    expect(ranked.get(rows[2] as Row)).toBeUndefined();
    expect(ranked.get(rows[0] as Row)).toBe(2);
  });

  it("is by the column the table is sorted by, whichever way the order runs", () => {
    const up = ranking(rows, { column: "weight", descending: false }, counts, {
      fallback: "items",
      blank,
    });
    expect(up.column).toBe("weight");
    expect(up.label).toBe("support weight");
    // 12.00 twice, then 2.50 third: two that share a rank take two places.
    expect(rows.map(up.rank)).toEqual([3, 1, 4, null, 1]);
  });

  it("is by the column named for it when the table is sorted by no count, or not at all", () => {
    expect(rankColumn({ column: "name", descending: false }, counts, "items")).toBe("items");
    expect(rankColumn(null, counts, "weight")).toBe("weight");
    expect(rankColumn({ column: "items", descending: true }, counts, "weight")).toBe("items");
    const byName = ranking(rows, { column: "name", descending: false }, counts, {
      fallback: "items",
      blank,
    });
    expect(byName.column).toBe("items");
    expect(rows.map(byName.rank)).toEqual([2, 1, 2, null, 4]);
  });

  it("does not take a name that only an object has for a column of counts", () => {
    expect(rankColumn({ column: "toString", descending: false }, counts, "items")).toBe("items");
  });
});

describe("the bars of a table of a report", () => {
  it("are as long as a count is to the largest of its column, the blank row's among them", () => {
    const table = ranking(rows, null, counts, { fallback: "items", blank });
    expect(table.share("items", rows[3] as Row)).toBe(1);
    expect(table.share("items", rows[1] as Row)).toBeCloseTo(0.3);
    expect(table.share("weight", rows[1] as Row)).toBe(1);
    expect(table.share("weight", rows[4] as Row)).toBe(1);
    expect(table.share("weight", rows[2] as Row)).toBeCloseTo(0.0625);
  });

  it("are nothing for nothing, and for a column of nothing but nothing", () => {
    expect(barShare(0, 10)).toBe(0);
    expect(barShare(null, 10)).toBe(0);
    expect(barShare(5, 0)).toBe(0);
    expect(barShare(-1, 10)).toBe(0);
    expect(largestOf([{ n: 0 }, { n: 0 }], (row) => row.n)).toBe(0);
    expect(largestOf([], () => 1)).toBe(0);
  });

  it("are never longer than the column's largest", () => {
    expect(barShare(12, 10)).toBe(1);
  });

  it("line up: each column knows the longest of what is written in it", () => {
    const table = ranking(rows, null, counts, { fallback: "items", blank });
    expect(table.figure("items")).toBe(2);
    expect(table.figure("weight")).toBe(5);
    expect(table.figure("nothing")).toBe(0);
    expect(table.text("weight", rows[0] as Row)).toBe("2.50");
  });
});
