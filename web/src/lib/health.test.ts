import { describe, expect, it } from "vitest";
import {
  HEALTHS,
  healthCounts,
  healthHint,
  healthLabel,
  healthTone,
  isHealth,
  isObserved,
  OBSERVED,
  OBSERVED_CHOICES,
  observationPatch,
  observedLabel,
  observedWhen,
  reasonsText,
} from "./health";

describe("health as words", () => {
  it("names the four healths, the best first", () => {
    expect(HEALTHS.map((health) => health.value)).toEqual([
      "good",
      "degraded",
      "failed",
      "unknown",
    ]);
    expect(healthLabel("degraded")).toBe("Degraded");
    expect(healthLabel(null)).toBe("");
    expect(isHealth("failed")).toBe(true);
    expect(isHealth("fine")).toBe(false);
  });

  it("shows a health it does not know as sent, in the colour of the unknown", () => {
    expect(healthLabel("recovering")).toBe("recovering");
    expect(healthTone("recovering")).toBe("unknown");
    expect(healthTone(null)).toBe("unknown");
    expect(healthTone("failed")).toBe("failed");
  });

  it("gives the reasons as one line, with the word in front", () => {
    const health = {
      value: "failed" as const,
      reasons: ["its condition is failed", "it is expected online and is observed unreachable"],
    };
    expect(reasonsText(health)).toBe(
      "its condition is failed; it is expected online and is observed unreachable",
    );
    expect(healthHint(health)).toBe(
      "Failed: its condition is failed; it is expected online and is observed unreachable",
    );
    expect(healthHint({ value: "good", reasons: [] })).toBe("Good");
    expect(healthHint(null)).toBe("");
    expect(reasonsText(undefined)).toBe("");
  });

  it("lists the counts of a summary in the order of the healths", () => {
    expect(healthCounts({ unknown: 30, failed: 0, degraded: 1, good: 12 })).toEqual([
      { value: "good", label: "Good", count: 12 },
      { value: "degraded", label: "Degraded", count: 1 },
      { value: "failed", label: "Failed", count: 0 },
      { value: "unknown", label: "Unknown", count: 30 },
    ]);
  });
});

describe("what is observed", () => {
  it("names the four, and says of present that a person saw it", () => {
    expect(OBSERVED.map((observed) => observed.value)).toEqual([
      "online",
      "degraded",
      "unreachable",
      "present",
    ]);
    expect(observedLabel("unreachable")).toBe("Unreachable");
    expect(observedLabel(null)).toBe("");
    expect(observedLabel("sleeping")).toBe("sleeping");
    expect(isObserved("present")).toBe(true);
    expect(isObserved("absent")).toBe(false);
    const present = OBSERVED_CHOICES.find((option) => option.value === "present");
    expect(present?.label).toMatch(/a person saw it/);
    const online = OBSERVED_CHOICES.find((option) => option.value === "online");
    expect(online?.label).toMatch(/on the network/);
  });

  it("calls the moment of present the last check, and of the rest when it was seen", () => {
    expect(observedWhen("present")).toBe("last checked");
    expect(observedWhen("online")).toBe("seen");
  });
});

describe("observationPatch", () => {
  it("sets a status and leaves the moment to the server", () => {
    expect(observationPatch("set", "online")).toEqual({ observed_status: "online" });
  });

  it("states a status again and leaves the moment to the server's clock", () => {
    expect(observationPatch("again", "present")).toEqual({ observed_status: "present" });
  });

  it("clears the status, and sends no moment with that", () => {
    expect(observationPatch("clear", "online")).toEqual({ observed_status: null });
    expect(observationPatch("clear", null)).toEqual({ observed_status: null });
  });

  it("sends nothing for a status that is none of the four", () => {
    expect(observationPatch("set", "")).toBeNull();
    expect(observationPatch("again", null)).toBeNull();
    expect(observationPatch("set", "sleeping")).toBeNull();
  });
});
