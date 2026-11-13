import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import {
  changeText,
  countsText,
  firstPage,
  isOutcome,
  isOutOfDate,
  type Job,
  outcomeCount,
  outcomeLabel,
  outcomeOptions,
  type Preview,
  type PreviewRow,
  ROWS_PAGE,
  reasonText,
  recordPath,
  rowsQuery,
  staleRows,
  statusLabel,
  valueText,
} from "./preview";

function job(more: Partial<Job> = {}): Job {
  return {
    hid: "j-1",
    source: "file",
    entity: "items",
    mode: "upsert",
    status: "previewed",
    file_name: "items.csv",
    file_sha256: null,
    row_count: 9,
    created: 2,
    updated: 3,
    unchanged: 3,
    rejected: 1,
    skip_rejected: null,
    failure: null,
    created_at: "2026-11-13T21:31:18Z",
    applied_by: null,
    applied_by_name: null,
    created_by: "u-1",
    created_by_name: "ada",
    applied_at: null,
    ...more,
  };
}

function row(number: number, more: Partial<PreviewRow> = {}): PreviewRow {
  return {
    row: number,
    outcome: "update",
    key: `site2-sw-access-${number}`,
    record_hid: `i-${number}`,
    changes: [],
    reasons: [],
    notes: [],
    ...more,
  };
}

function rows(count: number): PreviewRow[] {
  return Array.from({ length: count }, (_, place) => row(place + 1));
}

describe("outcomes", () => {
  it("are counted from the job, and all rows with no outcome", () => {
    const counted = job();
    expect(outcomeCount(counted, "")).toBe(9);
    expect(outcomeCount(counted, "create")).toBe(2);
    expect(outcomeCount(counted, "update")).toBe(3);
    expect(outcomeCount(counted, "unchanged")).toBe(3);
    expect(outcomeCount(counted, "rejected")).toBe(1);
  });

  it("are offered as a filter, each with its count", () => {
    expect(outcomeOptions(job())).toEqual([
      { value: "", label: "All rows (9)" },
      { value: "create", label: "Create (2)" },
      { value: "update", label: "Update (3)" },
      { value: "unchanged", label: "Unchanged (3)" },
      { value: "rejected", label: "Rejected (1)" },
    ]);
  });

  it("are told from anything else", () => {
    expect(isOutcome("rejected")).toBe(true);
    expect(isOutcome("deleted")).toBe(false);
    expect(outcomeLabel("unchanged")).toBe("Unchanged");
    expect(outcomeLabel("deleted")).toBe("deleted");
  });
});

describe("rowsQuery", () => {
  it("asks for one page of all rows, or of one outcome", () => {
    expect(rowsQuery("", 0)).toEqual({ limit: ROWS_PAGE, offset: 0 });
    expect(rowsQuery("rejected", 200)).toEqual({ outcome: "rejected", limit: 100, offset: 200 });
  });

  it("never asks for a place before the first row", () => {
    expect(rowsQuery("", -100).offset).toBe(0);
    expect(rowsQuery("", 150.5).offset).toBe(150);
  });
});

describe("firstPage", () => {
  const small: Preview = { job: job({ row_count: 9 }), rows: rows(9) };
  const large: Preview = { job: job({ row_count: 2500 }), rows: rows(ROWS_PAGE) };

  it("is the rows the preview's own answer holds, with the number of all rows", () => {
    expect(firstPage(small, "", 0)).toEqual({ items: small.rows, total: 9 });
    expect(firstPage(large, "", 0)?.total).toBe(2500);
    expect(firstPage(large, "", 0)?.items).toHaveLength(100);
  });

  it("is not the page of one outcome, nor any page after the first", () => {
    expect(firstPage(small, "rejected", 0)).toBeNull();
    expect(firstPage(large, "", 100)).toBeNull();
  });

  it("is asked for when the answer holds fewer rows than a page", () => {
    const short: Preview = { job: job({ row_count: 2500 }), rows: rows(50) };
    expect(firstPage(short, "", 0)).toBeNull();
    expect(firstPage(null, "", 0)).toBeNull();
    expect(firstPage(undefined, "", 0)).toBeNull();
  });
});

describe("valueText and changeText", () => {
  it("write a value as a file would, and say a blank in words", () => {
    expect(valueText(null)).toBe("(blank)");
    expect(valueText("")).toBe("(blank)");
    expect(valueText([])).toBe("(blank)");
    expect(valueText(["lab", "refresh-2030"])).toBe("lab; refresh-2030");
    expect(valueText(true)).toBe("true");
    expect(valueText(false)).toBe("false");
    expect(valueText(250)).toBe("250");
    expect(valueText("18000.00")).toBe("18000.00");
    expect(valueText({ a: 1 })).toBe('{"a":1}');
  });

  it("show before and after", () => {
    expect(changeText({ field: "owner", old: null, new: "Network Engineering" })).toBe(
      "owner: (blank) → Network Engineering",
    );
    expect(changeText({ field: "expected_online", old: true, new: false })).toBe(
      "expected_online: true → false",
    );
    expect(changeText({ field: "tags", old: ["lab"], new: [] })).toBe("tags: lab → (blank)");
  });

  it("name the field of a reason, when it has one", () => {
    expect(reasonText({ field: "owner", message: "there is no owner Voice" })).toBe(
      "owner: there is no owner Voice",
    );
    expect(reasonText({ field: "", message: "row 2 of the file names the same record" })).toBe(
      "row 2 of the file names the same record",
    );
  });
});

describe("countsText and statusLabel", () => {
  it("say what a preview would do, and what an applied one did", () => {
    expect(countsText(job())).toBe("2 to create, 3 to update, 3 unchanged, 1 rejected");
    expect(countsText(job({ status: "applied" }))).toBe(
      "2 created, 3 updated, 3 unchanged, 1 rejected",
    );
  });

  it("say what became of a job", () => {
    expect(statusLabel(job())).toBe("Previewed, not applied");
    expect(statusLabel(job({ status: "failed" }))).toBe("Failed: nothing was applied");
    expect(statusLabel(job({ status: "applied", rejected: 0, skip_rejected: false }))).toBe(
      "Applied",
    );
    expect(statusLabel(job({ status: "applied", skip_rejected: true }))).toBe(
      "Applied, without the rejected rows",
    );
  });
});

describe("an apply that found a record changed", () => {
  const outOfDate = new ApiError({
    status: 409,
    title: "Preview out of date",
    detail: "2 of the rows changed after the preview was made; preview again",
    fields: {
      "rows.12": "row 12, site2-sw-access-12: changed since the preview",
      "rows.3": "row 3, site2-sw-access-03: would no longer do what was previewed",
    },
  });
  const stale = new ApiError({ status: 409, title: "Stale version", fields: { "rows.1": "x" } });
  const applied = new ApiError({
    status: 409,
    title: "Conflict",
    detail: "this preview is applied already",
    fields: { status: "make a new preview to go on" },
  });

  it("is told from every other refusal", () => {
    expect(isOutOfDate(outOfDate)).toBe(true);
    expect(isOutOfDate(stale)).toBe(false);
    expect(isOutOfDate(applied)).toBe(false);
    expect(isOutOfDate(new ApiError({ status: 422, title: "Preview out of date" }))).toBe(false);
    expect(isOutOfDate(null)).toBe(false);
  });

  it("names the rows in the way, in the order of the file", () => {
    expect(staleRows(outOfDate)).toEqual([
      { row: 3, message: "row 3, site2-sw-access-03: would no longer do what was previewed" },
      { row: 12, message: "row 12, site2-sw-access-12: changed since the preview" },
    ]);
  });

  it("names no row for any other refusal", () => {
    expect(staleRows(stale)).toEqual([]);
    expect(staleRows(applied)).toEqual([]);
    expect(staleRows(null)).toEqual([]);
  });
});

describe("recordPath", () => {
  it("is the page of the record, by HID, for the kinds that have a page", () => {
    expect(recordPath("items", "i-1")).toBe("/items/i-1");
    expect(recordPath("catalog_entries", "c-1")).toBe("/catalog/c-1");
    expect(recordPath("vendors", "v 1")).toBe("/vendors/v%201");
    expect(recordPath("owners", "o-1")).toBe("/owners/o-1");
  });

  it("is nothing for a tag, and for a row that has no record yet", () => {
    expect(recordPath("tags", "t-1")).toBeNull();
    expect(recordPath("items", null)).toBeNull();
  });
});
