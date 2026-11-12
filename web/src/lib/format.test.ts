import { describe, expect, it } from "vitest";
import { formatChange, formatChanges, formatTime, formatValue, plural } from "./format";

describe("formatChange", () => {
  it("writes field: old → new", () => {
    expect(formatChange({ field: "display_name", old: "Vera", new: "Vera Example" })).toBe(
      "display_name: Vera → Vera Example",
    );
  });

  it("says (none) for a value that was not there or is gone", () => {
    expect(formatChange({ field: "role", old: null, new: "admin" })).toBe("role: (none) → admin");
    expect(formatChange({ field: "name", old: "ops", new: null })).toBe("name: ops → (none)");
    expect(formatChange({ field: "name", new: "ops" })).toBe("name: (none) → ops");
  });

  it("shows booleans, numbers and empty text as they are", () => {
    expect(formatChange({ field: "disabled", old: false, new: true })).toBe(
      "disabled: false → true",
    );
    expect(formatChange({ field: "quantity", old: 0, new: 12 })).toBe("quantity: 0 → 12");
    expect(formatChange({ field: "email", old: "", new: "vera@example.org" })).toBe(
      'email: "" → vera@example.org',
    );
  });

  it("shows lists and objects as JSON", () => {
    expect(formatChange({ field: "tags", old: [], new: ["a", "b"] })).toBe('tags: [] → ["a","b"]');
    expect(formatChange({ field: "place", old: null, new: { site: "Site-2" } })).toBe(
      'place: (none) → {"site":"Site-2"}',
    );
  });

  it("never treats text as markup", () => {
    expect(formatChange({ field: "name", old: "<b>x</b>", new: "<script>" })).toBe(
      "name: <b>x</b> → <script>",
    );
  });

  it("shows an entry of another shape whole", () => {
    expect(formatChange({ note: "moved" })).toBe('{"note":"moved"}');
  });
});

describe("formatChanges", () => {
  it("gives one line for each change, in order", () => {
    expect(
      formatChanges([
        { field: "username", old: null, new: "vera" },
        { field: "is_service_account", old: null, new: false },
      ]),
    ).toEqual(["username: (none) → vera", "is_service_account: (none) → false"]);
  });

  it("gives nothing for an event without changes", () => {
    expect(formatChanges([])).toEqual([]);
    expect(formatChanges(null)).toEqual([]);
    expect(formatChanges(undefined)).toEqual([]);
  });
});

describe("formatValue", () => {
  it("survives a value that JSON cannot write", () => {
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    expect(formatValue(loop)).toBe("[object Object]");
  });
});

describe("formatTime", () => {
  it("writes local date and time to the second", () => {
    const at = new Date(2026, 0, 31, 14, 5, 9);
    expect(formatTime(at.toISOString())).toBe("2026-01-31 14:05:09");
  });

  it("is blank when there is no time and passes on what it cannot read", () => {
    expect(formatTime(null)).toBe("");
    expect(formatTime(undefined)).toBe("");
    expect(formatTime("some day")).toBe("some day");
  });
});

describe("plural", () => {
  it("agrees with the count", () => {
    expect(plural(1, "second")).toBe("1 second");
    expect(plural(30, "second")).toBe("30 seconds");
    expect(plural(0, "membership")).toBe("0 memberships");
  });
});
