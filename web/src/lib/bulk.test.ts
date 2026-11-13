import { describe, expect, it } from "vitest";
import {
  type BulkDraft,
  type BulkField,
  buildBulk,
  bulkIdentity,
  bulkRows,
  CATALOG_ENTRY,
  NOT_IN_BULK,
} from "./bulk";
import type { GridView } from "./transfer";

const FIELDS: BulkField[] = [
  { name: CATALOG_ENTRY, label: "Catalog entry", kind: "choice" },
  { name: "owner", label: "Owner", kind: "choice", clearable: true },
  { name: "lifecycle_state", label: "Lifecycle state", kind: "choice" },
  { name: "expected_online", label: "Expected online", kind: "tristate", clearable: true },
  { name: "quantity", label: "Quantity", kind: "integer" },
  { name: "est_value", label: "Estimated value", kind: "decimal", places: 2, clearable: true },
  { name: "ldos", label: "LDoS", kind: "date", clearable: true },
  { name: "comments", label: "Comments", kind: "longtext", clearable: true },
  // Not a field the form offers. It is here to show that it is refused all the same.
  { name: "serial_number", label: "Serial number", kind: "text" },
];
const ENTRIES = { "c-1": { vendor: "v-1", pid: "C9300-48P" } };
const ROWS = { hids: ["i-1", "i-2"] };
const VIEW: GridView = {
  filter: { field: "tags", op: "has", value: "refresh-2030" },
  sort: ["name"],
  include_archived: true,
  include_drafts: false,
};

function draft(more: Partial<BulkDraft> = {}): BulkDraft {
  return { lines: [], reason: "", addTags: [], removeTags: [], ...more };
}

describe("bulkRows", () => {
  it("names particular rows by their HIDs, and sends no filter with them", () => {
    expect(bulkRows({ kind: "rows", hids: ["i-1", "i-2"] }, VIEW)).toEqual({
      hids: ["i-1", "i-2"],
    });
  });

  it("names all that match by the filter and the switches of the list, never by rows", () => {
    expect(bulkRows({ kind: "all", count: 51234 }, VIEW)).toEqual({
      filter: { field: "tags", op: "has", value: "refresh-2030" },
      include_archived: true,
      include_drafts: false,
    });
  });

  it("says that every item is meant when there is no filter", () => {
    expect(bulkRows({ kind: "all", count: 39 }, { ...VIEW, filter: null })).toEqual({
      all_rows: true,
      include_archived: true,
      include_drafts: false,
    });
  });
});

describe("buildBulk", () => {
  it("sets the fields on the form, typed as a file has them, and leaves the rest out", () => {
    const built = buildBulk(
      FIELDS,
      draft({
        lines: [
          { name: "owner", clear: false, value: "o-1" },
          { name: "expected_online", clear: false, value: "false" },
          { name: "quantity", clear: false, value: "250" },
          { name: "est_value", clear: false, value: "18000.50" },
          { name: "ldos", clear: false, value: "2034-04-30" },
        ],
      }),
      ROWS,
    );
    expect(built.errors).toEqual({});
    expect(built.empty).toBe(false);
    expect(built.body).toEqual({
      hids: ["i-1", "i-2"],
      set: {
        owner: "o-1",
        expected_online: false,
        quantity: 250,
        est_value: "18000.50",
        ldos: "2034-04-30",
      },
    });
  });

  it("clears a field with null, so that it is blank or inherits again", () => {
    const built = buildBulk(
      FIELDS,
      draft({
        lines: [
          { name: "est_value", clear: true, value: "999" },
          { name: "owner", clear: true, value: "" },
        ],
      }),
      ROWS,
    );
    expect(built.errors).toEqual({});
    expect(built.body.set).toEqual({ est_value: null, owner: null });
  });

  it("does not clear a field that cannot be cleared", () => {
    const built = buildBulk(
      FIELDS,
      draft({ lines: [{ name: "quantity", clear: true, value: "" }] }),
      ROWS,
    );
    expect(built.errors).toEqual({ quantity: "This field cannot be cleared." });
    expect(built.body).not.toHaveProperty("set");
  });

  it("asks for a value where a line was added and left blank", () => {
    const built = buildBulk(
      FIELDS,
      draft({
        lines: [
          { name: "owner", clear: false, value: "" },
          { name: "quantity", clear: false, value: " " },
        ],
      }),
      ROWS,
    );
    expect(built.errors).toEqual({
      owner: "Give a value, or choose to clear the field.",
      quantity: "Give a value.",
    });
    expect(built.empty).toBe(false);
  });

  it("finds what cannot be sent before it is sent", () => {
    const built = buildBulk(
      FIELDS,
      draft({
        lines: [
          { name: "quantity", clear: false, value: "2.5" },
          { name: "est_value", clear: false, value: "18,000" },
          { name: "ldos", clear: false, value: "30/04/2034" },
        ],
      }),
      ROWS,
    );
    expect(Object.keys(built.errors)).toEqual(["quantity", "est_value", "ldos"]);
    expect(built.body).not.toHaveProperty("set");
  });

  it("names a catalog entry as a file does: by its vendor and its PID", () => {
    const built = buildBulk(
      FIELDS,
      draft({ lines: [{ name: CATALOG_ENTRY, clear: false, value: "c-1" }] }),
      ROWS,
      ENTRIES,
    );
    expect(built.body.set).toEqual({ vendor: "v-1", pid: "C9300-48P" });
    const unknown = buildBulk(
      FIELDS,
      draft({ lines: [{ name: CATALOG_ENTRY, clear: false, value: "c-9" }] }),
      ROWS,
      ENTRIES,
    );
    expect(unknown.errors).toEqual({ [CATALOG_ENTRY]: "Choose a catalog entry." });
  });

  it("sends a lifecycle move as the state with its reason", () => {
    const built = buildBulk(
      FIELDS,
      draft({ lines: [{ name: "lifecycle_state", clear: false, value: "Down" }], reason: "rma " }),
      ROWS,
    );
    expect(built.body.set).toEqual({ lifecycle_state: "Down", state_reason: "rma" });
  });

  it("sends no reason without a move, and none that was not given", () => {
    const noMove = buildBulk(
      FIELDS,
      draft({ lines: [{ name: "comments", clear: false, value: "Checked" }], reason: "rma" }),
      ROWS,
    );
    expect(noMove.body.set).toEqual({ comments: "Checked" });
    const noReason = buildBulk(
      FIELDS,
      draft({ lines: [{ name: "lifecycle_state", clear: false, value: "Prod" }] }),
      ROWS,
    );
    expect(noReason.body.set).toEqual({ lifecycle_state: "Prod" });
  });

  it("never sets a field that tells one item from another", () => {
    expect(NOT_IN_BULK).toEqual([
      "serial_number",
      "asset_tag",
      "mac_address",
      "name",
      "hostname",
      "fqdn",
    ]);
    for (const name of NOT_IN_BULK) {
      const built = buildBulk(
        [...FIELDS, { name, label: name, kind: "text" }],
        draft({ lines: [{ name, clear: false, value: "FCW0000X001" }] }),
        ROWS,
      );
      expect(built.errors).toEqual({ [name]: "This field is not set in bulk." });
      expect(built.body).not.toHaveProperty("set");
    }
  });

  it("adds and removes tags, each named once", () => {
    const built = buildBulk(
      FIELDS,
      draft({ addTags: ["refresh-2030", "refresh-2030"], removeTags: ["lab"] }),
      ROWS,
    );
    expect(built.errors).toEqual({});
    expect(built.empty).toBe(false);
    expect(built.body).toEqual({
      hids: ["i-1", "i-2"],
      add_tags: ["refresh-2030"],
      remove_tags: ["lab"],
    });
  });

  it("refuses a tag that is both added and removed", () => {
    const built = buildBulk(FIELDS, draft({ addTags: ["lab"], removeTags: ["lab", "core"] }), ROWS);
    expect(built.errors).toEqual({ remove_tags: "Also among the tags to add: lab." });
  });

  it("is empty until something is on the form", () => {
    const built = buildBulk(FIELDS, draft(), ROWS);
    expect(built.empty).toBe(true);
    expect(built.body).toEqual({ hids: ["i-1", "i-2"] });
  });

  it("carries the rows as they were chosen", () => {
    const rows = bulkRows({ kind: "all", count: 3 }, VIEW);
    const built = buildBulk(FIELDS, draft({ addTags: ["lab"] }), rows);
    expect(built.body).toEqual({ ...rows, add_tags: ["lab"] });
    expect(built.body).not.toHaveProperty("hids");
  });
});

describe("bulkIdentity", () => {
  it("is the same for the same edit, and no other", () => {
    const one = buildBulk(FIELDS, draft({ addTags: ["lab"] }), ROWS).body;
    const same = buildBulk(FIELDS, draft({ addTags: ["lab"] }), ROWS).body;
    const other = buildBulk(FIELDS, draft({ addTags: ["core"] }), ROWS).body;
    expect(bulkIdentity(one)).toBe(bulkIdentity(same));
    expect(bulkIdentity(one)).not.toBe(bulkIdentity(other));
  });
});
