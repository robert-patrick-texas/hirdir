import { describe, expect, it } from "vitest";
import { tickState, withCount } from "./selection";

describe("the buttons that act on the rows chosen say how many (P-233)", () => {
  it("counts the rows ticked", () => {
    expect(withCount("Copy", { ticked: 3, allMatching: false, total: 40 })).toBe("Copy (3)");
    expect(withCount("Retire", { ticked: 1204, allMatching: false, total: 2000 })).toBe(
      "Retire (1,204)",
    );
  });

  it("says all that match, with their count", () => {
    expect(withCount("Bulk edit", { ticked: 0, allMatching: true, total: 34778 })).toBe(
      "Bulk edit (all 34,778)",
    );
  });

  it("is the label alone with nothing chosen, or for particular rows while all match", () => {
    expect(withCount("Export CSV", { ticked: 0, allMatching: false, total: 12 })).toBe(
      "Export CSV",
    );
    expect(withCount("Retire", { ticked: 0, allMatching: true, total: 12 }, true)).toBe("Retire");
    expect(withCount("Copy", { ticked: 0, allMatching: true, total: null })).toBe("Copy");
  });
});

describe("the box in the heading (P-233)", () => {
  it("is clear, part ticked, or ticked by the rows on show", () => {
    expect(tickState(0, 0)).toBe("none");
    expect(tickState(10, 0)).toBe("none");
    expect(tickState(10, 4)).toBe("some");
    expect(tickState(10, 10)).toBe("all");
  });
});
