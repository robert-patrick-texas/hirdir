import { describe, expect, it } from "vitest";
import { shiftRange, tickName, tickState, unreadText, withCount } from "./selection";

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

describe("Shift with a press or with Space (P-233)", () => {
  it("takes the rows from the one last pressed to this one, either way", () => {
    expect(shiftRange(3, 6)).toEqual([3, 6]);
    expect(shiftRange(8, 4)).toEqual([4, 8]);
    expect(shiftRange(null, 5)).toEqual([5, 5]);
  });

  it("says how many rows between were not read, and so not ticked", () => {
    expect(unreadText(0)).toBe("");
    expect(unreadText(1)).toBe(
      "1 row between was not read yet, and so not ticked: scroll through them, then press again with Shift",
    );
    expect(unreadText(1200)).toContain("1,200 rows between were not read yet");
  });
});

describe("the box in the heading (P-233)", () => {
  it("is clear, part ticked, or ticked when every row of the list is read and ticked", () => {
    expect(tickState(0, 0, null)).toBe("none");
    expect(tickState(10, 0, 10)).toBe("none");
    expect(tickState(10, 4, 10)).toBe("some");
    expect(tickState(10, 10, 10)).toBe("all");
  });

  it("is only part ticked while part of the list is read, however many of those are", () => {
    expect(tickState(100, 100, 260)).toBe("some");
    expect(tickState(160, 160, 260)).toBe("some");
    expect(tickState(100, 100, null)).toBe("some");
  });

  it("says what it does, with how many rows read", () => {
    expect(tickName(100, false)).toBe("Tick the 100 rows read so far");
    expect(tickName(1, true)).toBe("Clear the 1 row read so far");
    expect(tickName(1200, false)).toBe("Tick the 1,200 rows read so far");
  });
});
