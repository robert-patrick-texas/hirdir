import { describe, expect, it } from "vitest";
import { locationSearch } from "./places";
import { locationsWithin } from "./within";

describe("locationsWithin", () => {
  it("is the search for a location as it was, where no site is given", () => {
    expect(locationsWithin("rack a1")).toEqual(locationSearch("rack a1"));
    expect(locationsWithin("  ")).toBeNull();
  });

  it("is the site's locations before anything is typed", () => {
    expect(locationsWithin("", "S1")).toEqual({ field: "site_hid", op: "eq", value: "S1" });
  });

  it("looks for the words within the site", () => {
    const words = locationSearch("bay");
    expect(words).not.toBeNull();
    expect(locationsWithin("bay", "S1")).toEqual({
      and: [{ field: "site_hid", op: "eq", value: "S1" }, words],
    });
  });
});
