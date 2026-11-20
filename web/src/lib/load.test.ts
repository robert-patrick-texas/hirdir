import { describe, expect, it } from "vitest";
import {
  bandCount,
  becauseWords,
  bytesText,
  clockText,
  countText,
  healthOfLoad,
  kept,
  type Load,
  loadAverageText,
  loadOf,
  minuteText,
  msText,
  NOT_KNOWN,
  noCeiling,
  percentText,
  personKey,
  requestText,
  stillAnswered,
  waitText,
  whoWords,
  whyNothingRefused,
  workerWords,
} from "./load";

const VERA = { kind: "person", hid: "USR-000007", username: "vera" } as const;

function answer(): Load {
  return {
    health: "good",
    refusing: "nothing",
    because: [],
    ceiling: { response_ms: 3000, cpu_percent: 95, over_seconds: 30, fewest_requests: 21 },
    measures: { response_ms: null, requests: 0, reads_ms: null, reads: 0, cpu_percent: 2.5 },
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
      response_ms: { low: 1.2, average: 8.4, high: 40, p50: 7, p95: 31, p99: 40 },
      cpu_percent: { low: 0.1, average: 2, high: 9.5 },
      bands: { bounds_ms: [1000, 2000, 3000], counts: [11, 0, 0, 0] },
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
      p50_ms: [7, 8],
      p95_ms: [31, 20],
      cpu_percent: [2, null],
      busy: [0, 1],
    },
    slowest: [
      {
        at: "2026-01-15T11:59:51Z",
        method: "GET",
        route: "/api/v1/items/{hid}",
        ms: 40,
        status: 200,
        request_id: "req-0001",
        who: { ...VERA },
      },
    ],
    slowest_long: [],
    people: [
      {
        ...VERA,
        requests: 12,
        bands: [11, 0, 0, 0],
        slowest_ms: 40,
        busy: 1,
        failed: 0,
        last_at: "2026-01-15T11:59:58Z",
      },
    ],
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

  it("is nothing where the bands, the slowest or the people are not what a table draws", () => {
    const whole = answer();
    expect(loadOf({ ...whole, totals: { ...whole.totals, bands: null } })).toBeNull();
    expect(
      loadOf({ ...whole, totals: { ...whole.totals, bands: { bounds_ms: [], counts: 4 } } }),
    ).toBeNull();
    expect(loadOf({ ...whole, slowest: null })).toBeNull();
    expect(loadOf({ ...whole, slowest: [null] })).toBeNull();
    expect(loadOf({ ...whole, slowest: [{ ...whole.slowest[0], who: null }] })).toBeNull();
    expect(loadOf({ ...whole, slowest_long: {} })).toBeNull();
    expect(loadOf({ ...whole, people: undefined })).toBeNull();
    expect(loadOf({ ...whole, people: ["vera"] })).toBeNull();
    // None slow and nobody about is an answer all the same.
    const quiet = { ...whole, slowest: [], slowest_long: [], people: [] };
    expect(loadOf(quiet)).toBe(quiet);
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
    // The rows of the tables are the ones that were drawn, where none of them changed.
    expect(now.slowest).toBe(was.slowest);
    expect(now.people).toBe(was.people);
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
  it("read the health and what is refused from an answer, or neither", () => {
    expect(healthOfLoad({ health: "busy", refusing: "reads" })).toEqual({
      health: "busy",
      refusing: "reads",
    });
    expect(healthOfLoad({ health: "good", refusing: "nothing" })).toEqual({
      health: "good",
      refusing: "nothing",
    });
    expect(healthOfLoad({ health: "ok", refusing: "nothing" })).toBeNull();
    expect(healthOfLoad({ health: "busy" })).toBeNull();
    expect(healthOfLoad({ state: "busy" } as { health?: unknown })).toBeNull();
  });

  it("say what the health stands on", () => {
    expect(becauseWords([])).toBe("");
    expect(becauseWords(["cpu_percent"])).toBe(
      "It is read from the processor time the server uses.",
    );
    expect(becauseWords(["cpu_percent", "response_ms"])).toBe(
      "It is read from how long requests take, and from the processor time the server uses.",
    );
    expect(becauseWords(["memory"])).toBe("");
  });

  it("say that no ceiling is in force only where neither measure is looked at", () => {
    expect(noCeiling({ response_ms: 0, cpu_percent: 0 })).toBe(true);
    expect(noCeiling({ response_ms: 0, cpu_percent: 95 })).toBe(false);
    expect(noCeiling({ response_ms: 3000, cpu_percent: 0 })).toBe(false);
  });

  const FEW_OR_NOT_READS =
    "Nothing is refused for it: it is not the reads that are slow, or there are too few of them for it to be load.";

  it("say one thing that is true of red or orange that refuses nothing, few requests or many", () => {
    const slow = {
      ...answer(),
      health: "busy",
      refusing: "nothing",
      because: ["response_ms"],
      measures: { response_ms: 4200, requests: 7, reads_ms: 900, reads: 5, cpu_percent: 3 },
    } satisfies Load;
    expect(whyNothingRefused(slow)).toBe(FEW_OR_NOT_READS);
    expect(whyNothingRefused({ ...slow, health: "very_slow" })).toBe(FEW_OR_NOT_READS);
    // It is said of slow saves among many requests as of a few slow reads: the count of
    // the requests does not decide it.
    const many = {
      ...slow,
      measures: { response_ms: 4200, requests: 500, reads_ms: 40, reads: 400, cpu_percent: 3 },
    };
    expect(whyNothingRefused(many)).toBe(FEW_OR_NOT_READS);
  });

  it("say that no ceiling is set for time, where that is why nothing is refused", () => {
    const slow = {
      ...answer(),
      health: "busy",
      refusing: "nothing",
      because: ["response_ms"],
      ceiling: { response_ms: 0, cpu_percent: 0, over_seconds: 30, fewest_requests: 20 },
    } satisfies Load;
    expect(whyNothingRefused(slow)).toBe(
      "Nothing is refused for it: no ceiling is set for how long requests take.",
    );
  });

  it("say nothing of why where the server refuses, or is quicker than that", () => {
    const base = answer();
    expect(whyNothingRefused({ ...base, health: "busy", refusing: "reads" })).toBe("");
    expect(whyNothingRefused({ ...base, health: "very_slow", refusing: "long" })).toBe("");
    expect(whyNothingRefused({ ...base, health: "good", refusing: "nothing" })).toBe("");
    expect(whyNothingRefused({ ...base, health: "slow", refusing: "nothing" })).toBe("");
  });

  it("say what a busy server still answers", () => {
    expect(stillAnswered("long")).toBe("Everything else is answered, and every change is stored.");
    expect(stillAnswered("reads")).toBe("Sign-ins are taken and every change is stored.");
    expect(stillAnswered("nothing")).toBe("");
    expect(stillAnswered(undefined)).toBe("");
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

describe("the rows of the tables", () => {
  it("say a request by its method and its route as a pattern", () => {
    expect(requestText({ method: "GET", route: "/api/v1/items/{hid}" })).toBe(
      "GET /api/v1/items/{hid}",
    );
    expect(requestText({ method: "POST", route: null })).toBe("POST a path that no route answers");
  });

  it("name a person by the username, with the account to link it to", () => {
    expect(whoWords({ kind: "person", hid: "USR-000007", username: "vera" })).toEqual({
      name: "vera",
      hid: "USR-000007",
      note: "",
    });
  });

  it("name a service token by its username, and say that it is one", () => {
    expect(whoWords({ kind: "service", hid: "USR-000009", username: "monitoring" })).toEqual({
      name: "monitoring",
      hid: "USR-000009",
      note: "service token",
    });
    expect(whoWords({ kind: "service", hid: null, username: null })).toEqual({
      name: "A service token",
      hid: null,
      note: "",
    });
  });

  it("say the unnamed row and the row of the rest as what they are, with no link", () => {
    expect(whoWords({ kind: "unnamed", hid: null, username: null })).toEqual({
      name: "Nobody named: not signed in, or signing in",
      hid: null,
      note: "",
    });
    expect(whoWords({ kind: "others", hid: null, username: null })).toEqual({
      name: "Everyone else, counted together",
      hid: null,
      note: "",
    });
  });

  it("name nobody it does not know, and link nothing without a name", () => {
    expect(whoWords({ kind: "person", hid: "USR-000007", username: null })).toEqual({
      name: NOT_KNOWN,
      hid: null,
      note: "",
    });
    expect(whoWords({ kind: "robot", hid: "USR-000007", username: "r2" })).toEqual({
      name: "r2",
      hid: null,
      note: "",
    });
    expect(whoWords({})).toEqual({ name: NOT_KNOWN, hid: null, note: "" });
  });

  it("tell one row of the people from another by its kind and its account", () => {
    const keys = [
      personKey({ kind: "person", hid: "USR-000007" }),
      personKey({ kind: "person", hid: "USR-000008" }),
      personKey({ kind: "service", hid: "USR-000009" }),
      personKey({ kind: "unnamed", hid: null }),
      personKey({ kind: "others", hid: null }),
    ];
    expect(new Set(keys).size).toBe(5);
    expect(personKey({ kind: "person", hid: "USR-000007" })).toBe(keys[0]);
  });

  it("read a count of a band in its place, and 0 where there is none", () => {
    expect(bandCount([11, 2, 0, 1], 0)).toBe(11);
    expect(bandCount([11, 2, 0, 1], 3)).toBe(1);
    expect(bandCount([11, 2], 3)).toBe(0);
    expect(bandCount(null, 0)).toBe(0);
    expect(bandCount(["many"], 0)).toBe(0);
  });
});
