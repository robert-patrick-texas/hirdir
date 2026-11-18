import { describe, expect, it } from "vitest";
import { faultText, isMissingPart, PartNotFetched, part } from "./fault";

describe("part", () => {
  it("says a file of the page that could not be fetched as such", async () => {
    const missing = part(() =>
      Promise.reject(new TypeError("Failed to fetch dynamically imported module: x.js")),
    );
    await expect(missing()).rejects.toBeInstanceOf(PartNotFetched);
    const fetched = part(() => Promise.resolve({ page: 1 }));
    await expect(fetched()).resolves.toEqual({ page: 1 });
  });
});

describe("isMissingPart", () => {
  it("knows what the browsers say of a module that could not be fetched", () => {
    expect(isMissingPart(new PartNotFetched(new Error("gone")))).toBe(true);
    expect(isMissingPart(new TypeError("Failed to fetch dynamically imported module: a"))).toBe(
      true,
    );
    expect(isMissingPart(new TypeError("error loading dynamically imported module: a"))).toBe(true);
    expect(isMissingPart(new TypeError("Importing a module script failed."))).toBe(true);
  });

  it("takes any other fault for one of drawing", () => {
    expect(isMissingPart(new TypeError("(e ?? []).filter is not a function"))).toBe(false);
    expect(isMissingPart("thrown text")).toBe(false);
    expect(isMissingPart(null)).toBe(false);
  });
});

describe("faultText", () => {
  const at = new Date("2026-11-18T12:00:00Z");

  it("holds the fault, the page, the version and when, then where it was drawn", () => {
    const error = new TypeError("(e ?? []).filter is not a function");
    const text = faultText({
      error,
      componentStack: "\n    at Items\n    at Shell",
      address: "http://203.0.113.10/items",
      version: "0.9.7",
      at,
    });
    const lines = text.split("\n");
    expect(lines.slice(0, 4)).toEqual([
      "TypeError: (e ?? []).filter is not a function",
      "Page: http://203.0.113.10/items",
      "Web page version: 0.9.7",
      "At: 2026-11-18T12:00:00.000Z",
    ]);
    expect(text).toContain("Drawn in:\nat Items\n    at Shell");
  });

  it("says what was thrown where it was no error", () => {
    const text = faultText({ error: "oops", address: "/", version: "0.9.7", at });
    expect(text.split("\n")[0]).toBe("Thrown: oops");
    expect(text).not.toContain("Drawn in:");
  });
});
