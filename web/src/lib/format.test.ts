import { describe, expect, it } from "vitest";
import {
  appZone,
  DEFAULT_ZONE,
  formatChange,
  formatChanges,
  formatMac,
  formatTime,
  formatTimeLong,
  formatValue,
  itemName,
  momentIn,
  plural,
  setZone,
  today,
} from "./format";

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
  const winter = "2026-01-31T19:05:09Z";
  const summer = "2026-07-31T18:05:09.250Z";

  it("writes the time of the zone it is given, with the zone's short name", () => {
    expect(formatTime(winter, "America/New_York")).toBe("2026-01-31 14:05:09 EST");
    expect(formatTime(summer, "America/New_York")).toBe("2026-07-31 14:05:09 EDT");
    expect(formatTime(winter, "America/Los_Angeles")).toBe("2026-01-31 11:05:09 PST");
    expect(formatTime("2026-01-31T04:30:00Z", "America/New_York")).toBe("2026-01-30 23:30:00 EST");
    expect(formatTime("2026-01-31T05:00:00Z", "America/New_York")).toBe("2026-01-31 00:00:00 EST");
  });

  it("is blank when there is no time and passes on what it cannot read", () => {
    expect(formatTime(null)).toBe("");
    expect(formatTime(undefined)).toBe("");
    expect(formatTime("some day")).toBe("some day");
  });

  it("writes the moment out in full with the name of the zone", () => {
    expect(formatTimeLong(winter, "America/New_York")).toBe(
      "Saturday, January 31, 2026 at 2:05:09 PM EST (America/New_York)",
    );
    expect(formatTimeLong(null)).toBe("");
  });
});

describe("the application's time zone", () => {
  it("is America/New_York until the installation's setting says otherwise", () => {
    setZone(undefined);
    expect(appZone()).toBe("America/New_York");
    expect(DEFAULT_ZONE).toBe("America/New_York");
    expect(formatTime("2026-01-31T19:05:09Z")).toBe("2026-01-31 14:05:09 EST");
  });

  it("is the setting once it is read, for every time, whatever zone the browser is in", () => {
    setZone("America/Chicago");
    expect(appZone()).toBe("America/Chicago");
    expect(formatTime("2026-01-31T19:05:09Z")).toBe("2026-01-31 13:05:09 CST");
    expect(formatTimeLong("2026-01-31T19:05:09Z")).toContain("(America/Chicago)");
    setZone("no such zone");
    expect(appZone()).toBe(DEFAULT_ZONE);
    setZone(undefined);
  });
});

describe("momentIn", () => {
  const zone = "America/New_York";

  it("finds the moment a zone's clocks show a date and time", () => {
    expect(momentIn(zone, 2026, 1, 31).toISOString()).toBe("2026-01-31T05:00:00.000Z");
    expect(momentIn(zone, 2026, 7, 31).toISOString()).toBe("2026-07-31T04:00:00.000Z");
    expect(momentIn(zone, 2026, 12, 31, 17, 30).toISOString()).toBe("2026-12-31T22:30:00.000Z");
    expect(momentIn("Europe/Berlin", 2026, 1, 31).toISOString()).toBe("2026-01-30T23:00:00.000Z");
    expect(momentIn("Asia/Kolkata", 2026, 1, 31).toISOString()).toBe("2026-01-30T18:30:00.000Z");
  });

  it("is right on the days the clocks change", () => {
    // In 2026 the clocks go forward on 8 March and back on 1 November.
    expect(momentIn(zone, 2026, 3, 8).toISOString()).toBe("2026-03-08T05:00:00.000Z");
    expect(momentIn(zone, 2026, 3, 9).toISOString()).toBe("2026-03-09T04:00:00.000Z");
    expect(momentIn(zone, 2026, 11, 1).toISOString()).toBe("2026-11-01T04:00:00.000Z");
    expect(momentIn(zone, 2026, 11, 2).toISOString()).toBe("2026-11-02T05:00:00.000Z");
  });

  it("runs a day past the end of a month on into the next", () => {
    expect(momentIn(zone, 2026, 1, 32).toISOString()).toBe("2026-02-01T05:00:00.000Z");
  });

  it("reads back as the time it was asked for", () => {
    const at = momentIn(zone, 2026, 6, 15, 9, 45, 30);
    expect(formatTime(at.toISOString(), zone)).toBe("2026-06-15 09:45:30 EDT");
  });
});

describe("a moment in an audit change", () => {
  it("is shown in the application's time like every other", () => {
    setZone(undefined);
    const shown = formatValue("2026-01-31T19:05:09.123456Z");
    expect(shown).toBe(formatTime("2026-01-31T19:05:09.123456Z"));
    expect(shown).not.toContain("T19");
    expect(formatValue("2026-01-31")).toBe("2026-01-31");
    expect(formatValue("site2-sw-access-01")).toBe("site2-sw-access-01");
  });
});

describe("plural", () => {
  it("agrees with the count", () => {
    expect(plural(1, "second")).toBe("1 second");
    expect(plural(30, "second")).toBe("30 seconds");
    expect(plural(0, "membership")).toBe("0 memberships");
  });
});

describe("formatMac", () => {
  it("writes the twelve stored digits in pairs", () => {
    expect(formatMac("00005e005302")).toBe("00:00:5e:00:53:02");
    expect(formatMac("00005E0053AA")).toBe("00:00:5E:00:53:AA");
  });

  it("leaves anything else as it is", () => {
    expect(formatMac("00005e")).toBe("00005e");
    expect(formatMac(null)).toBe("");
    expect(formatMac("")).toBe("");
  });
});

describe("itemName", () => {
  it("is the name, with the hostname, serial number or asset tag standing in", () => {
    expect(itemName({ name: "Core A", hostname: "site2-sw-core-01" })).toBe("Core A");
    expect(itemName({ name: null, hostname: "site2-sw-core-01" })).toBe("site2-sw-core-01");
    expect(itemName({ name: "", serial_number: "FCW0000X001" })).toBe("FCW0000X001");
    expect(itemName({ asset_tag: "AT-000900" })).toBe("AT-000900");
    expect(itemName({})).toBe("(no name)");
  });
});

describe("today", () => {
  it("is the day in the application's zone, which may not be the day in UTC", () => {
    // 03:30 UTC on the 14th is still the evening of the 13th in New York.
    const late = new Date("2026-11-14T03:30:00Z");
    expect(today("America/New_York", late)).toBe("2026-11-13");
    expect(today("UTC", late)).toBe("2026-11-14");
    expect(today("Asia/Tokyo", late)).toBe("2026-11-14");
  });

  it("is written as a date travels, with both digits of the month and the day", () => {
    expect(today("UTC", new Date("2026-03-05T12:00:00Z"))).toBe("2026-03-05");
  });
});
