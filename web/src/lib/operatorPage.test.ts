import { describe, expect, it } from "vitest";
import { isGapShown, labelFor, OPERATOR_GAPS, operatorsAddress } from "./operatorPage";

describe("the label of a new operator, as a user is chosen", () => {
  it("is the username while it is blank or still what the form filled in", () => {
    expect(labelFor("", "", "ex-ops")).toBe("ex-ops");
    expect(labelFor("  ", "", "ex-ops")).toBe("ex-ops");
    // Another user chosen: the label the form filled in follows.
    expect(labelFor("ex-ops", "ex-ops", "ex-net")).toBe("ex-net");
  });

  it("keeps a label typed by hand, and is as it was without a username", () => {
    expect(labelFor("Op2", "ex-ops", "ex-net")).toBe("Op2");
    expect(labelFor("ex-op", "ex-ops", "ex-net")).toBe("ex-op");
    expect(labelFor("", "", null)).toBe("");
  });
});

describe("Show on the list of operators", () => {
  it("leads to those with no user behind them, and to the open ones, by the grid's filter", () => {
    expect(OPERATOR_GAPS.map((gap) => gap.filter)).toEqual([
      "",
      "scope:ne:internal",
      "is_open:eq:true",
    ]);
    expect(operatorsAddress("scope:ne:internal")).toBe("/operators?filter=scope%3Ane%3Ainternal");
    expect(operatorsAddress("")).toBe("/operators?filter=");
  });

  it("marks the gap on show, and every operator where the list has no filter", () => {
    expect(isGapShown("is_open:eq:true", "is_open:eq:true")).toBe(true);
    expect(isGapShown("", null)).toBe(true);
    expect(isGapShown("", "label:prefix:Op")).toBe(false);
    expect(isGapShown("scope:ne:internal", null)).toBe(false);
  });
});
