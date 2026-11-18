import { describe, expect, it, vi } from "vitest";
import { ASK_AFTER, BUILT_AS, dueToAsk, otherVersion, VersionStore } from "./version";

describe("BUILT_AS", () => {
  it("is a version, as web/package.json gives it when the page is built", () => {
    expect(BUILT_AS).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

describe("otherVersion", () => {
  it("names the version the server runs where it is another", () => {
    expect(otherVersion("0.9.7", { version: "0.9.8" })).toBe("0.9.8");
    expect(otherVersion("0.9.7", { version: " 0.9.6 " })).toBe("0.9.6");
  });

  it("says nothing of the same version, or of an answer without one", () => {
    expect(otherVersion("0.9.7", { version: "0.9.7" })).toBeNull();
    for (const answer of [null, undefined, {}, [], "0.9.8", { version: 98 }, { version: "" }]) {
      expect(otherVersion("0.9.7", answer)).toBeNull();
    }
  });
});

describe("dueToAsk", () => {
  it("asks at a change of page only after five minutes", () => {
    expect(dueToAsk(0, ASK_AFTER)).toBe(false);
    expect(dueToAsk(0, ASK_AFTER + 1)).toBe(true);
  });
});

function store(answer: () => Promise<unknown>, signedIn = true) {
  let now = 1_000;
  const ask = vi.fn(answer);
  const versions = new VersionStore("0.9.7", { ask, signedIn: () => signedIn, now: () => now });
  return { versions, ask, later: (ms: number) => (now += ms) };
}

describe("VersionStore", () => {
  it("keeps a new version once it is known, and tells who follows it", async () => {
    const { versions, ask } = store(async () => ({ version: "0.9.8" }));
    const told = vi.fn();
    versions.subscribe(told);
    expect(versions.get()).toBeNull();
    await versions.check();
    expect(versions.get()).toBe("0.9.8");
    expect(told).toHaveBeenCalledTimes(1);
    // Known once, it is not asked again, and it never goes back.
    await versions.check();
    expect(ask).toHaveBeenCalledTimes(1);
    expect(versions.get()).toBe("0.9.8");
  });

  it("says nothing where the request fails or the version is the same", async () => {
    const failing = store(async () => {
      throw new Error("no answer");
    });
    await failing.versions.check();
    expect(failing.versions.get()).toBeNull();
    const same = store(async () => ({ version: "0.9.7" }));
    await same.versions.check();
    expect(same.versions.get()).toBeNull();
  });

  it("asks nobody while nobody is signed in", async () => {
    const { versions, ask } = store(async () => ({ version: "0.9.8" }), false);
    await versions.check();
    expect(ask).not.toHaveBeenCalled();
  });

  it("asks at a change of page only where the last question is five minutes old", async () => {
    const { versions, ask, later } = store(async () => ({ version: "0.9.7" }));
    // The page was just served: a change of page soon after does not ask.
    versions.checkIfDue();
    expect(ask).not.toHaveBeenCalled();
    later(ASK_AFTER + 1);
    versions.checkIfDue();
    expect(ask).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    later(1_000);
    versions.checkIfDue();
    expect(ask).toHaveBeenCalledTimes(1);
  });
});
