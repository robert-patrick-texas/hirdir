import { describe, expect, it } from "vitest";
import { offeredEntries } from "./entries";

const vendor = { hid: "VEN-000001", name: "Sample Networks" };
const entry = (hid: string, pid: string) => ({
  hid,
  pid,
  model_name: null,
  vendor,
  record_status: "active" as const,
});

describe("offeredEntries", () => {
  it("offers every entry found when none is excluded", () => {
    const found = offeredEntries({ items: [entry("CAT-000001", "SN-24P")], total: 3 }, []);
    expect(found.options).toEqual([
      { value: "CAT-000001", label: "SN-24P · Sample Networks", draft: false },
    ]);
    expect(found.total).toBe(3);
  });

  it("leaves out the entry itself, as the successor of an entry, and counts it out", () => {
    const page = {
      items: [entry("CAT-000001", "SN-24P"), entry("CAT-000002", "SN-48P")],
      total: 5,
    };
    const found = offeredEntries(page, ["CAT-000002"]);
    expect(found.options.map((option) => option.value)).toEqual(["CAT-000001"]);
    expect(found.total).toBe(4);
  });
});
