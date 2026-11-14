import { describe, expect, it } from "vitest";
import {
  ariaSort,
  columnSorts,
  compareValues,
  dateValue,
  decimalValue,
  isBlank,
  nextSort,
  type SortColumns,
  sortMark,
  sortParam,
  sortRows,
} from "./sort";

interface Row {
  name: string | null;
  count: number | null;
  since: string | null;
  weight: string | null;
  offered?: boolean;
}

const COLUMNS: SortColumns<Row> = {
  name: (row) => row.name,
  count: (row) => row.count,
  since: (row) => dateValue(row.since),
  weight: (row) => decimalValue(row.weight),
  offered: (row) => row.offered,
};

const row = (name: string | null, more: Partial<Row> = {}): Row => ({
  name,
  count: null,
  since: null,
  weight: null,
  ...more,
});
const names = (rows: readonly Row[]) => rows.map((one) => one.name);

describe("comparing two values", () => {
  it("sorts text without regard to case", () => {
    expect(compareValues("alpha", "Bravo")).toBeLessThan(0);
    expect(compareValues("Bravo", "alpha")).toBeGreaterThan(0);
    expect(compareValues("ALPHA", "alpha")).toBe(0);
  });

  it("reads the digits in text as numbers: Site-2 comes before Site-10", () => {
    expect(compareValues("Site-2", "Site-10")).toBeLessThan(0);
  });

  it("sorts numbers as numbers, and not as text", () => {
    expect(compareValues(9, 10)).toBeLessThan(0);
    expect(compareValues(10, 9)).toBeGreaterThan(0);
    expect(compareValues(2.5, 2.5)).toBe(0);
  });

  it("sorts a truth value with No before Yes, and a number before text", () => {
    expect(compareValues(false, true)).toBeLessThan(0);
    expect(compareValues(5, "5 or so")).toBeLessThan(0);
    expect(compareValues("5 or so", 5)).toBeGreaterThan(0);
  });
});

describe("what is blank", () => {
  it("is nothing, blank text, and what is no number", () => {
    expect(isBlank(null)).toBe(true);
    expect(isBlank(undefined)).toBe(true);
    expect(isBlank("")).toBe(true);
    expect(isBlank("  ")).toBe(true);
    expect(isBlank(Number.NaN)).toBe(true);
    expect(isBlank(0)).toBe(false);
    expect(isBlank(false)).toBe(false);
    expect(isBlank("0")).toBe(false);
  });
});

describe("a date and a decimal to sort by", () => {
  it("reads a date and a time as the same kind of number, so that both sort as dates", () => {
    const day = dateValue("2026-11-02");
    const moment = dateValue("2026-11-02T09:30:00Z");
    const later = dateValue("2026-11-14");
    expect(day).not.toBeNull();
    expect((day ?? 0) < (moment ?? 0)).toBe(true);
    expect((moment ?? 0) < (later ?? 0)).toBe(true);
  });

  it("has nothing for no date, and for what is none", () => {
    expect(dateValue(null)).toBeNull();
    expect(dateValue("")).toBeNull();
    expect(dateValue("soon")).toBeNull();
  });

  it("reads a decimal as the server writes it, digit for digit", () => {
    expect(decimalValue("2.80")).toBe(2.8);
    expect(decimalValue("10.00")).toBe(10);
    expect(decimalValue(3)).toBe(3);
    expect(decimalValue(null)).toBeNull();
    expect(decimalValue("")).toBeNull();
    expect(decimalValue("many")).toBeNull();
  });
});

describe("sorting the rows of a table", () => {
  const rows = [
    row("bravo", { count: 10, since: "2026-11-14", weight: "10.00" }),
    row("Alpha", { count: 9, since: "2026-03-01T08:00:00Z", weight: "2.80" }),
    row(null),
    row("charlie", { count: 100, since: "2025-12-31", weight: "9.5" }),
  ];

  it("keeps the order the rows came in while no header was clicked", () => {
    expect(names(sortRows(rows, COLUMNS, null))).toEqual(["bravo", "Alpha", null, "charlie"]);
    expect(sortRows(rows, COLUMNS, null)).not.toBe(rows);
  });

  it("sorts by text without regard to case, blanks last", () => {
    expect(names(sortRows(rows, COLUMNS, { column: "name", descending: false }))).toEqual([
      "Alpha",
      "bravo",
      "charlie",
      null,
    ]);
  });

  it("turns the order round, and still has the blanks last", () => {
    expect(names(sortRows(rows, COLUMNS, { column: "name", descending: true }))).toEqual([
      "charlie",
      "bravo",
      "Alpha",
      null,
    ]);
  });

  it("sorts numbers as numbers: 9, 10, 100", () => {
    expect(names(sortRows(rows, COLUMNS, { column: "count", descending: false }))).toEqual([
      "Alpha",
      "bravo",
      "charlie",
      null,
    ]);
    expect(names(sortRows(rows, COLUMNS, { column: "weight", descending: true }))).toEqual([
      "bravo",
      "charlie",
      "Alpha",
      null,
    ]);
  });

  it("sorts dates as dates, a date beside a time", () => {
    expect(names(sortRows(rows, COLUMNS, { column: "since", descending: false }))).toEqual([
      "charlie",
      "Alpha",
      "bravo",
      null,
    ]);
  });

  it("leaves equal rows in the order they came in, either way", () => {
    const equal = [row("one", { count: 1 }), row("two", { count: 1 }), row("three", { count: 0 })];
    expect(names(sortRows(equal, COLUMNS, { column: "count", descending: false }))).toEqual([
      "three",
      "one",
      "two",
    ]);
    expect(names(sortRows(equal, COLUMNS, { column: "count", descending: true }))).toEqual([
      "one",
      "two",
      "three",
    ]);
  });

  it("sorts a truth value, and does not sort by a column the table does not have", () => {
    const offered = [row("no", { offered: false }), row("yes", { offered: true }), row("unsaid")];
    expect(names(sortRows(offered, COLUMNS, { column: "offered", descending: true }))).toEqual([
      "yes",
      "no",
      "unsaid",
    ]);
    expect(names(sortRows(rows, COLUMNS, { column: "nothing", descending: false }))).toEqual(
      names(rows),
    );
  });
});

describe("a click on a header", () => {
  it("sorts by that column, ascending, and another turns the order round", () => {
    const first = nextSort(null, "name");
    expect(first).toEqual({ column: "name", descending: false });
    const second = nextSort(first, "name");
    expect(second).toEqual({ column: "name", descending: true });
    expect(nextSort(second, "name")).toEqual({ column: "name", descending: false });
  });

  it("starts ascending again on another column", () => {
    expect(nextSort({ column: "name", descending: true }, "count")).toEqual({
      column: "count",
      descending: false,
    });
  });

  it("is said by the header: which column, and which way", () => {
    const state = { column: "name", descending: true };
    expect(ariaSort(state, "name")).toBe("descending");
    expect(ariaSort({ column: "name", descending: false }, "name")).toBe("ascending");
    expect(ariaSort(state, "count")).toBe("none");
    expect(ariaSort(null, "name")).toBe("none");
    expect(sortMark(state, "name")).toBe("▼");
    expect(sortMark({ column: "name", descending: false }, "name")).toBe("▲");
    expect(sortMark(state, "count")).toBe("");
  });
});

describe("a table that the server sorts", () => {
  const FIELDS = { time: "at", who: "actor_name", record: "record_type,record_hid" };

  it("asks for the field of the column, and turns the order round with a minus", () => {
    expect(sortParam({ column: "time", descending: false }, FIELDS)).toBe("at");
    expect(sortParam({ column: "time", descending: true }, FIELDS)).toBe("-at");
    expect(sortParam({ column: "who", descending: false }, FIELDS)).toBe("actor_name");
  });

  it("turns every field of a column round where it is sorted by several", () => {
    expect(sortParam({ column: "record", descending: false }, FIELDS)).toBe(
      "record_type,record_hid",
    );
    expect(sortParam({ column: "record", descending: true }, FIELDS)).toBe(
      "-record_type,-record_hid",
    );
  });

  it("asks for nothing while no header was clicked, or for a column the server does not sort by", () => {
    expect(sortParam(null, FIELDS)).toBeUndefined();
    expect(sortParam({ column: "changes", descending: false }, FIELDS)).toBeUndefined();
  });

  it("sorts by a column the server has a field for whether or not the table holds every row", () => {
    const local = { changes: () => "" };
    expect(columnSorts("time", FIELDS, local, false)).toBe(true);
    expect(columnSorts("time", FIELDS, local, true)).toBe(true);
  });

  it("sorts by a column the page composes only while the table holds every row", () => {
    const local = { changes: () => "" };
    expect(columnSorts("changes", FIELDS, local, true)).toBe(true);
    expect(columnSorts("changes", FIELDS, local, false)).toBe(false);
    expect(columnSorts("nothing", FIELDS, local, true)).toBe(false);
  });
});
