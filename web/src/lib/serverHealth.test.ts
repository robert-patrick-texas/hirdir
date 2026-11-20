import { afterEach, describe, expect, it } from "vitest";
import {
  bandHealth,
  bandLabels,
  type Health,
  healthOfHeader,
  healthTitle,
  healthWords,
  type Refusing,
  refusedWords,
  serverHealth,
  speedWords,
} from "./serverHealth";

describe("healthOfHeader", () => {
  it("reads the health and what is refused from a header in its form", () => {
    expect(healthOfHeader("good; refusing=nothing")).toEqual({
      health: "good",
      refusing: "nothing",
    });
    expect(healthOfHeader("busy; refusing=nothing")).toEqual({
      health: "busy",
      refusing: "nothing",
    });
    expect(healthOfHeader("very_slow; refusing=long")).toEqual({
      health: "very_slow",
      refusing: "long",
    });
    expect(healthOfHeader("busy; refusing=reads")).toEqual({ health: "busy", refusing: "reads" });
    expect(healthOfHeader("slow; refusing=nothing")).toEqual({
      health: "slow",
      refusing: "nothing",
    });
  });

  it("reads it whatever blanks stand around its parts", () => {
    expect(healthOfHeader("  slow;refusing = nothing ")).toEqual({
      health: "slow",
      refusing: "nothing",
    });
  });

  it("is nothing for an answer that carries none", () => {
    expect(healthOfHeader(null)).toBeNull();
    expect(healthOfHeader(undefined)).toBeNull();
    expect(healthOfHeader("")).toBeNull();
  });

  it("is nothing for a header of another form, or with a word it does not know", () => {
    for (const other of [
      "busy",
      "busy;",
      "refusing=reads",
      "busy; refusing=",
      "busy; refusing=everything",
      "purple; refusing=nothing",
      "BUSY; refusing=nothing",
      "busy, refusing=nothing",
      "busy; refusing=nothing; more=1",
      "busy; refusing=nothing, good; refusing=nothing",
      "constructor; refusing=nothing",
    ]) {
      expect(healthOfHeader(other), other).toBeNull();
    }
    expect(healthOfHeader(5)).toBeNull();
    expect(healthOfHeader({ health: "good" })).toBeNull();
  });
});

describe("the words of the health", () => {
  const BUSY_LONG = "The server is busy: reports, exports and previews are not answered for now.";
  const BUSY_READS =
    "The server is busy: lists and everything else that only reads are not answered for now.";
  // Each health with each thing refused. Eight of them occur: nothing is refused while
  // the health is good or slow, and reads only while it is busy.
  const all: Array<[Health, Refusing, string]> = [
    ["good", "nothing", "Answers are quick."],
    ["slow", "nothing", "Answers are slow."],
    ["very_slow", "nothing", "Answers are very slow."],
    ["very_slow", "long", BUSY_LONG],
    ["very_slow", "reads", BUSY_READS],
    ["busy", "nothing", "Answers are slower than the server's ceiling."],
    ["busy", "long", BUSY_LONG],
    ["busy", "reads", BUSY_READS],
    // These do not occur, and are said by the same rule all the same.
    ["good", "long", BUSY_LONG],
    ["good", "reads", BUSY_READS],
    ["slow", "long", BUSY_LONG],
    ["slow", "reads", BUSY_READS],
  ];

  it("are of speed where nothing is refused, and say busy only where something is", () => {
    for (const [health, refusing, words] of all) {
      expect(healthWords({ health, refusing }), `${health} ${refusing}`).toBe(words);
    }
  });

  it("never call red busy while nothing is refused", () => {
    for (const health of ["good", "slow", "very_slow", "busy"] as const) {
      expect(healthWords({ health, refusing: "nothing" })).not.toMatch(/busy/i);
    }
  });

  it("are four that differ where nothing is refused", () => {
    const said = (["good", "slow", "very_slow", "busy"] as const).map(speedWords);
    expect(new Set(said).size).toBe(4);
  });

  it("say, where the mark is pointed at, that nothing is refused while answers are very slow or worse", () => {
    const about = "About shows the server's measures.";
    expect(healthTitle({ health: "good", refusing: "nothing" })).toBe(
      `Answers are quick. ${about}`,
    );
    expect(healthTitle({ health: "slow", refusing: "nothing" })).toBe(`Answers are slow. ${about}`);
    expect(healthTitle({ health: "very_slow", refusing: "nothing" })).toBe(
      `Answers are very slow. Nothing is refused. ${about}`,
    );
    expect(healthTitle({ health: "busy", refusing: "nothing" })).toBe(
      `Answers are slower than the server's ceiling. Nothing is refused. ${about}`,
    );
    expect(healthTitle({ health: "very_slow", refusing: "long" })).toBe(`${BUSY_LONG} ${about}`);
    expect(healthTitle({ health: "busy", refusing: "reads" })).toBe(`${BUSY_READS} ${about}`);
  });

  it("say what is refused, and nothing where nothing is", () => {
    expect(refusedWords("nothing")).toBeNull();
    expect(refusedWords("long")).toBe(BUSY_LONG);
    expect(refusedWords("reads")).toBe(BUSY_READS);
  });
});

describe("serverHealth", () => {
  afterEach(() => serverHealth.set(null));

  it("holds what the newest answer said, and nothing before any", () => {
    expect(serverHealth.get()).toBeNull();
    serverHealth.set({ health: "good", refusing: "nothing" });
    expect(serverHealth.get()).toEqual({ health: "good", refusing: "nothing" });
    serverHealth.set({ health: "busy", refusing: "reads" });
    expect(serverHealth.get()).toEqual({ health: "busy", refusing: "reads" });
    serverHealth.set(null);
    expect(serverHealth.get()).toBeNull();
  });

  it("tells whoever shows it only when the word or what is refused is another", () => {
    let told = 0;
    const stop = serverHealth.subscribe(() => {
      told += 1;
    });
    serverHealth.set({ health: "good", refusing: "nothing" });
    expect(told).toBe(1);
    const held = serverHealth.get();
    // A hundred answers that say the same draw nothing again, and the value is the same one.
    for (let answer = 0; answer < 100; answer += 1) {
      serverHealth.set({ health: "good", refusing: "nothing" });
    }
    expect(told).toBe(1);
    expect(serverHealth.get()).toBe(held);
    serverHealth.set({ health: "busy", refusing: "nothing" });
    expect(told).toBe(2);
    serverHealth.set({ health: "busy", refusing: "reads" });
    expect(told).toBe(3);
    serverHealth.set(null);
    expect(told).toBe(4);
    serverHealth.set(null);
    expect(told).toBe(4);
    stop();
    serverHealth.set({ health: "slow", refusing: "nothing" });
    expect(told).toBe(4);
  });
});

describe("bandLabels", () => {
  it("names the bands from their bounds, in seconds where they are whole tenths of them", () => {
    expect(bandLabels([1000, 2000, 3000])).toEqual([
      "Under 1 second",
      "1 to 2 seconds",
      "2 to 3 seconds",
      "Over 3 seconds",
    ]);
    expect(bandLabels([500, 1000, 1500])).toEqual([
      "Under 500 ms",
      "500 ms to 1 second",
      "1 to 1.5 seconds",
      "Over 1.5 seconds",
    ]);
    expect(bandLabels([20_000, 40_000, 60_000])).toEqual([
      "Under 20 seconds",
      "20 to 40 seconds",
      "40 to 60 seconds",
      "Over 60 seconds",
    ]);
  });

  it("names bounds that are no round numbers as they are", () => {
    expect(bandLabels([0.3, 0.7, 1])).toEqual([
      "Under 0.3 ms",
      "0.3 to 0.7 ms",
      "0.7 to 1 ms",
      "Over 1 ms",
    ]);
    expect(bandLabels([333.3, 666.7, 1000])).toEqual([
      "Under 333.3 ms",
      "333.3 to 666.7 ms",
      "666.7 ms to 1 second",
      "Over 1 second",
    ]);
  });

  it("has one name more than there are bounds, and none for bounds that are none", () => {
    expect(bandLabels([1000])).toEqual(["Under 1 second", "Over 1 second"]);
    expect(bandLabels([])).toEqual([]);
    expect(bandLabels(null)).toEqual([]);
    expect(bandLabels("1000")).toEqual([]);
    expect(bandLabels([1000, null, 3000])).toEqual([]);
    expect(bandLabels([1000, -1])).toEqual([]);
  });
});

describe("bandHealth", () => {
  it("gives each of the four bands the level of its place", () => {
    expect([0, 1, 2, 3].map(bandHealth)).toEqual(["good", "slow", "very_slow", "busy"]);
  });

  it("takes a place past the four for the worst, and one before them for the best", () => {
    expect(bandHealth(7)).toBe("busy");
    expect(bandHealth(-1)).toBe("good");
  });
});
