import { describe, expect, it } from "vitest";
import {
  appliedLabel,
  appliedText,
  changeText,
  countsText,
  firstPage,
  isOutcome,
  isWorking,
  type Job,
  kindPath,
  leftOutCount,
  leftOutQuery,
  outcomeCount,
  outcomeLabel,
  outcomeOptions,
  type Preview,
  type PreviewRow,
  progressText,
  ROWS_PAGE,
  reasonText,
  recordPath,
  refusedAtApply,
  rowsQuery,
  statusLabel,
  stoppedText,
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
    rows_done: 0,
    applied: 0,
    stale: 0,
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
    applied_outcome: null,
    applied_reasons: [],
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
  it("say what the preview found each row would do, before the apply and after it", () => {
    expect(countsText(job())).toBe("2 to create, 3 to update, 3 unchanged, 1 rejected");
    expect(countsText(job({ status: "applied" }))).toBe(
      "2 to create, 3 to update, 3 unchanged, 1 rejected",
    );
  });

  it("say what became of a job", () => {
    expect(statusLabel(job())).toBe("Previewed, not applied");
    expect(statusLabel(job({ status: "queued" }))).toBe("Waiting for another to be applied");
    expect(statusLabel(job({ status: "applying" }))).toBe("Being applied");
    expect(statusLabel(job({ status: "stopped" }))).toBe("Stopped partway, to be resumed");
    expect(statusLabel(job({ status: "failed" }))).toBe("Failed: nothing was applied");
    expect(statusLabel(job({ status: "applied", rejected: 0, skip_rejected: false }))).toBe(
      "Applied",
    );
    expect(statusLabel(job({ status: "applied", skip_rejected: true }))).toBe(
      "Applied, without the rejected rows",
    );
    expect(statusLabel(job({ status: "applied", rejected: 0, stale: 1 }))).toBe(
      "Applied, without the rows changed since the preview",
    );
    expect(statusLabel(job({ status: "applied", skip_rejected: true, stale: 2 }))).toBe(
      "Applied, without the rejected rows and the rows changed since the preview",
    );
  });
});

describe("an apply in the background", () => {
  it("is under way while the job is queued or applying, and not before or after", () => {
    expect(isWorking(job({ status: "queued" }))).toBe(true);
    expect(isWorking(job({ status: "applying" }))).toBe(true);
    for (const status of ["previewed", "applied", "stopped", "failed"] as const) {
      expect(isWorking(job({ status }))).toBe(false);
    }
  });

  it("says how far it has got", () => {
    expect(progressText(job({ rows_done: 4 }))).toBe("4 of 9 rows worked");
    expect(progressText(job({ row_count: 1 }), ["item", "items"])).toBe("0 of 1 item worked");
    expect(stoppedText(job({ rows_done: 4 }))).toBe("4 of 9 rows had been worked");
  });

  it("counts as refused what it worked and neither applied nor left out as stale", () => {
    expect(refusedAtApply(job({ rows_done: 9, applied: 6, stale: 2 }))).toBe(1);
    expect(refusedAtApply(job({ rows_done: 3, applied: 3, stale: 0 }))).toBe(0);
    // Never fewer than none, whatever a job of an older release says.
    expect(refusedAtApply(job({ rows_done: 0, applied: 2, stale: 0 }))).toBe(0);
  });

  it("says what it did in a sentence", () => {
    expect(appliedText(job({ rows_done: 9, applied: 6, stale: 2 }))).toBe(
      "6 rows applied, 2 left out as changed since the preview, 1 refused",
    );
    expect(appliedText(job({ rows_done: 1, applied: 1 }), ["item", "items"])).toBe(
      "1 item applied, none left out as changed since the preview, none refused",
    );
  });

  it("names what it did with a row, and nothing for a row it has not worked", () => {
    expect(appliedLabel("create")).toBe("Created");
    expect(appliedLabel("stale")).toBe("Changed since the preview");
    expect(appliedLabel("rejected")).toBe("Refused");
    expect(appliedLabel(null)).toBe("");
  });

  it("asks for the rows it left out, a page at a time, and counts them from the job", () => {
    expect(leftOutQuery("stale", 0)).toEqual({
      applied_outcome: "stale",
      limit: ROWS_PAGE,
      offset: 0,
    });
    expect(leftOutQuery("rejected", -5).offset).toBe(0);
    const done = job({ status: "applied", rows_done: 9, applied: 6, stale: 2 });
    expect(leftOutCount(done, "stale")).toBe(2);
    expect(leftOutCount(done, "rejected")).toBe(1);
  });
});

describe("recordPath", () => {
  it("is the page of the record, by HID, for the kinds that have a page", () => {
    expect(recordPath("items", "i-1")).toBe("/items/i-1");
    expect(recordPath("catalog_entries", "c-1")).toBe("/catalog/c-1");
    expect(recordPath("vendors", "v 1")).toBe("/vendors/v%201");
    expect(recordPath("owners", "o-1")).toBe("/owners/o-1");
    expect(recordPath("device_groups", "g-1")).toBe("/groups/g-1");
  });

  it("is nothing for a tag, and for a row that has no record yet", () => {
    expect(recordPath("tags", "t-1")).toBeNull();
    expect(recordPath("addresses", "a-1")).toBeNull();
    expect(recordPath("device_group_members", "m-1")).toBeNull();
    expect(recordPath("items", null)).toBeNull();
  });
});

describe("kindPath", () => {
  it("is the page of the record the audit trail names, by its kind and HID", () => {
    expect(kindPath("item", "i-1")).toBe("/items/i-1");
    expect(kindPath("catalog_entry", "c-1")).toBe("/catalog/c-1");
    expect(kindPath("circuit_group", "cg 1")).toBe("/circuit-groups/cg%201");
    expect(kindPath("purchase_request", "p-1")).toBe("/purchases/p-1");
    expect(kindPath("external_system", "x-1")).toBe("/systems/x-1");
    expect(kindPath("site", "s-1")).toBe("/geography/site/s-1");
    expect(kindPath("location", "l-1")).toBe("/geography/location/l-1");
    expect(kindPath("import_job", "j-1")).toBe("/import/j-1");
  });

  it("is nothing for a kind with no page, and for a change that names no record", () => {
    expect(kindPath("tag", "t-1")).toBeNull();
    expect(kindPath("address", "a-1")).toBeNull();
    expect(kindPath("device_group_member", "m-1")).toBeNull();
    expect(kindPath("setting", "s-1")).toBeNull();
    expect(kindPath("item", null)).toBeNull();
    expect(kindPath("item", "")).toBeNull();
  });

  it("names the page of an account or a group of accounts only for an Admin", () => {
    expect(kindPath("user", "u-1")).toBeNull();
    expect(kindPath("user_group", "g-1", false)).toBeNull();
    expect(kindPath("user", "u-1", true)).toBe("/admin/users/u-1");
    expect(kindPath("user_group", "g-1", true)).toBe("/admin/groups/g-1");
  });
});
