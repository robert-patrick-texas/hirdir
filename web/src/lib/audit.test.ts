import { describe, expect, it } from "vitest";
import { deletedRecords, isDeleted } from "./audit";

const GROUP = "01a1f0e8-0000-7000-8000-000000000001";
const ITEM = "01a1f0e8-0000-7000-8000-000000000002";

describe("the records the audit trail on show says were deleted", () => {
  const events = [
    { action: "delete", record_type: "device_group", record_hid: GROUP },
    { action: "update", record_type: "device_group", record_hid: GROUP },
    { action: "create", record_type: "device_group", record_hid: GROUP },
    { action: "create", record_type: "item", record_hid: ITEM },
    { action: "sign_in", record_type: "user", record_hid: null },
  ];
  const gone = deletedRecords(events);

  it("are those of an event of the action delete, and every event of them", () => {
    for (const event of events.slice(0, 3)) expect(isDeleted(gone, event)).toBe(true);
  });

  it("are not a record that no event held deletes, nor an event that names none", () => {
    for (const event of events.slice(3)) expect(isDeleted(gone, event)).toBe(false);
  });

  it("are told apart by their kind as well as their HID", () => {
    expect(isDeleted(gone, { action: "create", record_type: "item", record_hid: GROUP })).toBe(
      false,
    );
  });
});
