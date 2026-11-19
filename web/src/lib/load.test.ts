import { describe, expect, it } from "vitest";
import {
  becauseWords,
  bytesText,
  clockText,
  countText,
  kept,
  type Load,
  loadAverageText,
  loadOf,
  minuteText,
  msText,
  NOT_KNOWN,
  noCeiling,
  percentText,
  stateWords,
  waitText,
  workerWords,
} from "./load";

function answer(): Load {
  return {
    state: "ok",
    because: [],
    ceiling: { response_ms: 5000, cpu_percent: 95, over_seconds: 30 },
    measures: { response_ms: null, cpu_percent: 2.5 },
    window_seconds: 600,
    step_seconds: 5,
    started_at: "2026-01-15T11:00:00Z",
    at: "2026-01-15T12:00:00Z",
    totals: {
      requests: 12,
      ok: 10,
      not_accepted: 1,
      failed: 0,
      busy: 1,
      response_ms: { low: 1.2, average: 8.4, high: 40 },
      cpu_percent: { low: 0.1, average: 2, high: 9.5 },
    },
    in_flight: { count: 0, oldest_ms: null },
    process: { memory_bytes: 120_000_000 },
    host: {
      memory_total_bytes: 8_000_000_000,
      memory_used_bytes: 3_000_000_000,
      memory_free_bytes: 5_000_000_000,
      disk_total_bytes: 100_000_000_000,
      disk_free_bytes: 60_000_000_000,
      processors: 4,
      load_1m: 0.42,
    },
    worker: "running",
    points: {
      at: "2026-01-15T11:59:50Z",
      requests: [5, 7],
      average_ms: [8, 8.7],
      high_ms: [40, 22],
      cpu_percent: [2, null],
      busy: [0, 1],
    },
  };
}

describe("loadOf", () => {
  it("is the answer where it has the parts the page draws", () => {
    const given = answer();
    expect(loadOf(given)).toBe(given);
  });

  it("is nothing for an answer of another shape", () => {
    for (const other of [null, undefined, "busy", 5, [], {}, { at: "now" }]) {
      expect(loadOf(other)).toBeNull();
    }
    const whole = answer();
    expect(loadOf({ ...whole, points: [] })).toBeNull();
    expect(loadOf({ ...whole, points: { ...whole.points, busy: null } })).toBeNull();
    expect(loadOf({ ...whole, totals: { ...whole.totals, response_ms: null } })).toBeNull();
    expect(loadOf({ ...whole, host: null })).toBeNull();
    expect(loadOf({ ...whole, because: "cpu_percent" })).toBeNull();
    expect(loadOf({ ...whole, at: 12 })).toBeNull();
  });
});

describe("kept", () => {
  it("is the new answer where there was none", () => {
    const next = answer();
    expect(kept(null, next)).toBe(next);
    expect(kept(undefined, next)).toBe(next);
  });

  it("is the answer that was there where every part holds the same", () => {
    const was = answer();
    expect(kept(was, answer())).toBe(was);
  });

  it("keeps each part that holds the same, and takes each that does not", () => {
    const was = answer();
    const next = answer();
    next.at = "2026-01-15T12:00:05Z";
    next.totals.requests = 13;
    const now = kept(was, next);
    expect(now).not.toBe(was);
    expect(now.at).toBe("2026-01-15T12:00:05Z");
    expect(now.totals).toBe(next.totals);
    // The graph's lists, the host and the ceiling are the objects the page drew from.
    expect(now.points).toBe(was.points);
    expect(now.host).toBe(was.host);
    expect(now.ceiling).toBe(was.ceiling);
    expect(now.because).toBe(was.because);
  });

  it("takes a part whose list grew by a step", () => {
    const was = answer();
    const next = answer();
    next.points.requests = [5, 7, 0];
    expect(kept(was, next).points).toBe(next.points);
  });

  it("is not the answer that was there where a part has gone", () => {
    const was = answer();
    const { worker: _, ...less } = answer();
    const now = kept(was as Partial<Load>, less);
    expect(now).not.toBe(was);
    expect(Object.hasOwn(now, "worker")).toBe(false);
  });
});

describe("numbers", () => {
  it("are said to a tenth, with their unit and the separator of thousands", () => {
    expect(msText(8.44)).toBe("8.4 ms");
    expect(msText(0)).toBe("0 ms");
    expect(msText(12345.67)).toBe("12,345.7 ms");
    expect(percentText(97.25)).toBe("97.3%");
    expect(percentText(0)).toBe("0%");
    expect(countText(34778)).toBe("34,778");
    expect(countText(0)).toBe("0");
    expect(loadAverageText(0.4)).toBe("0.40");
    expect(loadAverageText(12)).toBe("12.00");
    expect(bytesText(3 * 1024 ** 3)).toBe("3 GB");
    expect(bytesText(0)).toBe("0 bytes");
  });

  it("are not known where the server or its host does not say, and never 0", () => {
    for (const none of [null, undefined, Number.NaN, "12", {}]) {
      expect(msText(none)).toBe(NOT_KNOWN);
      expect(percentText(none)).toBe(NOT_KNOWN);
      expect(countText(none)).toBe(NOT_KNOWN);
      expect(bytesText(none)).toBe(NOT_KNOWN);
      expect(loadAverageText(none)).toBe(NOT_KNOWN);
      expect(waitText(none)).toBe(NOT_KNOWN);
    }
    expect(bytesText(-1)).toBe(NOT_KNOWN);
  });

  it("say what there is none of in the words given", () => {
    expect(msText(null, "nothing was answered")).toBe("nothing was answered");
    expect(waitText(null, "none")).toBe("none");
  });

  it("say a wait in milliseconds under a second, and in seconds from there", () => {
    expect(waitText(0)).toBe("0 ms");
    expect(waitText(240.4)).toBe("240 ms");
    expect(waitText(999.6)).toBe("1 second");
    expect(waitText(1000)).toBe("1 second");
    expect(waitText(3240)).toBe("3.2 seconds");
    expect(waitText(65_000)).toBe("65 seconds");
  });
});

describe("times", () => {
  it("are the time of day in the zone, with its short name", () => {
    expect(clockText("2026-01-15T19:05:09Z", "America/New_York")).toBe("14:05:09 EST");
    expect(clockText(Date.parse("2026-07-15T18:05:09Z"), "America/New_York")).toBe("14:05:09 EDT");
    expect(minuteText(Date.parse("2026-01-15T19:05:00Z"), "America/New_York")).toBe("14:05");
  });

  it("are not known for no time, or one that does not read", () => {
    expect(clockText(null)).toBe(NOT_KNOWN);
    expect(clockText("")).toBe(NOT_KNOWN);
    expect(clockText("soon")).toBe(NOT_KNOWN);
    expect(minuteText(Number.NaN)).toBe("");
  });
});

describe("words", () => {
  it("name each state, and say what the server does in it", () => {
    expect(stateWords("ok").name).toBe("Not busy");
    expect(stateWords("busy").name).toBe("Busy");
    expect(stateWords("busy").what).toContain("Lists, reports, exports and previews");
    expect(stateWords("very_busy").name).toBe("Very busy");
    expect(stateWords("very_busy").what).toContain("Everything that only reads");
    expect(stateWords("resting").name).toBe("Not known");
    expect(stateWords(undefined).name).toBe("Not known");
    // A name of a member of every object is no state.
    expect(stateWords("constructor").name).toBe("Not known");
  });

  it("say by which measure the server is busy", () => {
    expect(becauseWords([])).toBe("");
    expect(becauseWords(["cpu_percent"])).toBe(
      "Past its ceiling: the share of one processor it uses.",
    );
    expect(becauseWords(["cpu_percent", "response_ms"])).toBe(
      "Past its ceiling: how long requests take, and the share of one processor it uses.",
    );
    expect(becauseWords(["memory"])).toBe("");
  });

  it("say that no ceiling is in force only where neither measure is looked at", () => {
    expect(noCeiling({ response_ms: 0, cpu_percent: 0, over_seconds: 30 })).toBe(true);
    expect(noCeiling({ response_ms: 0, cpu_percent: 95, over_seconds: 30 })).toBe(false);
    expect(noCeiling({ response_ms: 5000, cpu_percent: 0, over_seconds: 30 })).toBe(false);
  });

  it("say whether the background work is being done, and notice where it is not", () => {
    expect(workerWords("running")).toEqual({
      text: "Running, as a process of its own.",
      notice: false,
    });
    expect(workerWords("in_process").notice).toBe(false);
    expect(workerWords("in_process").text).toContain("the server itself");
    const stopped = workerWords("not_running");
    expect(stopped.notice).toBe(true);
    expect(stopped.text).toContain("Not running");
    expect(stopped.text).toContain("Imports and bulk edits wait");
    expect(workerWords(null)).toEqual({ text: NOT_KNOWN, notice: false });
  });
});
