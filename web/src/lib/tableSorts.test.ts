import { describe, expect, it } from "vitest";
import { sortParam } from "./sort";
import {
  AUDIT_SORT,
  CAPACITY_RECORDS_SORT,
  CHILDREN_SORT,
  DUPLICATES_SORT,
  HISTORY_SORT,
  IMPORTS_SORT,
  MEMBERS_SORT,
  PREVIEW_ROWS_SORT,
  REFERENCES_SORT,
  USERS_SORT,
} from "./tableSorts";

const ALL = {
  REFERENCES_SORT,
  USERS_SORT,
  AUDIT_SORT,
  CAPACITY_RECORDS_SORT,
  IMPORTS_SORT,
  PREVIEW_ROWS_SORT,
  DUPLICATES_SORT,
  MEMBERS_SORT,
  CHILDREN_SORT,
  HISTORY_SORT,
};

describe("the sort fields of the paged tables", () => {
  it("names the field of each route for each column of its table", () => {
    expect(USERS_SORT).toEqual({
      username: "username",
      display_name: "display_name",
      operators: "operators",
      role: "role",
      groups: "groups",
      kind: "is_service_account",
      state: "disabled",
      last_sign_in: "last_sign_in_at",
      notes: "notes",
    });
    expect(IMPORTS_SORT).toEqual({
      made: "created_at",
      file: "file_name",
      records: "entity",
      mode: "mode",
      status: "status",
      rows: "row_count",
      worked: "rows_done",
      applied: "applied",
      stale: "stale",
      by: "created_by_name",
    });
    expect(PREVIEW_ROWS_SORT).toEqual({
      row: "row",
      record: "key",
      outcome: "outcome",
      applied: "applied_outcome",
    });
    expect(CAPACITY_RECORDS_SORT).toMatchObject({
      week: "week_of",
      balance: "active.balance",
      drafts_coverage: "with_drafts.coverage_pct",
      adjusted: "adjusted",
    });
    expect(DUPLICATES_SORT).toEqual({
      address: "address",
      network: "network",
      count: "count",
      holders: "holders",
    });
    expect(HISTORY_SORT).toEqual({ at: "at", actor_name: "actor_name", action: "action" });
  });

  it("sorts the members of a group by the fields of the item each is", () => {
    expect(MEMBERS_SORT).toMatchObject({
      position: "position",
      item: "item.name",
      pid: "item.pid",
      serial_number: "item.serial_number",
      seen: "observed_master",
    });
    expect(sortParam({ column: "joined_on", descending: true }, MEMBERS_SORT)).toBe("-joined_on");
  });

  it("sorts the minor items of an item by the fields of the item list", () => {
    expect(CHILDREN_SORT).toEqual({
      position: "position",
      name: "name",
      pid: "catalog.pid",
      serial: "serial_number",
      state: "effective.lifecycle_state",
      owner: "owner.label",
      location: "location.name",
      minor: "minor_items",
    });
  });

  it("sorts the references by the fields of their route, the records by how many", () => {
    expect(REFERENCES_SORT).toEqual({
      title: "title",
      kind: "kind",
      form: "form",
      file_name: "file_name",
      size: "size_bytes",
      records: "attachment_count",
      added: "created_at",
    });
    expect(sortParam({ column: "records", descending: true }, REFERENCES_SORT)).toBe(
      "-attachment_count",
    );
  });

  it("sorts an audit event by its record as it is shown: the type, then the HID", () => {
    expect(sortParam({ column: "record_type", descending: false }, AUDIT_SORT)).toBe(
      "record_type,record_hid",
    );
    expect(sortParam({ column: "time", descending: true }, AUDIT_SORT)).toBe("-at");
  });

  it("has no field for what a page composes from a list: those are not sorted by the server", () => {
    expect(AUDIT_SORT.changes).toBeUndefined();
    expect(PREVIEW_ROWS_SORT.changes).toBeUndefined();
    expect(PREVIEW_ROWS_SORT.reasons).toBeUndefined();
  });

  it("names a field for every column it has, in the form the server reads", () => {
    for (const [table, fields] of Object.entries(ALL)) {
      for (const [column, field] of Object.entries(fields)) {
        expect(field, `${table}.${column}`).toMatch(/^[a-z_.]+(,[a-z_.]+)*$/);
      }
    }
  });
});
