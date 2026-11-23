import { describe, expect, it } from "vitest";
import { announced } from "./said";

describe("what a live region says (review R1, R2, D1)", () => {
  const saying = (ready: boolean, first: string, changed = false) => ({ ready, first, changed });
  const waiting = "Waiting to be previewed, in its turn.";

  it("holds nothing as it comes, so that what it is given a moment later is heard", () => {
    expect(announced(waiting, true, saying(false, waiting))).toBe("");
    expect(announced(waiting, true, saying(true, waiting))).toBe(waiting);
  });

  it("does not say again what had ended before the page came, until something else is said", () => {
    const old = "Nothing was applied: a record was changed after this preview was made.";
    expect(announced(old, false, saying(true, old))).toBe("");
    expect(announced("Waiting to be applied, in its turn.", false, saying(true, old, true))).toBe(
      "Waiting to be applied, in its turn.",
    );
    // Said again once it has been something else in between.
    expect(announced(old, false, saying(true, old, true))).toBe(old);
  });

  it("says what came after the page did, and holds it while it stays the same", () => {
    const failed = "The preview failed, and nothing was applied: an error.";
    expect(announced(failed, false, saying(true, ""))).toBe(failed);
    expect(announced(failed, false, saying(true, "", true))).toBe(failed);
  });
});
