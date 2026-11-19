import { describe, expect, it } from "vitest";
import {
  areaUnder,
  GRAPH,
  graphHeight,
  heightOn,
  lineWithGaps,
  loadGraph,
  TIME_SERIES,
} from "./loadGraph";

const CEILING = { response_ms: 5000, cpu_percent: 95, over_seconds: 30 };
const NONE = { response_ms: 0, cpu_percent: 0, over_seconds: 30 };
// 12:00:00 by a clock in UTC: a whole minute.
const NOON = "2026-01-15T12:00:00Z";
const noon = Date.parse(NOON);

/** `count` steps from noon, each as `step` says, or quiet. */
function points(
  count: number,
  step: (place: number) => Partial<{
    requests: number;
    average: number | null;
    high: number | null;
    cpu: number | null;
    busy: number;
  }> = () => ({}),
  at = NOON,
) {
  const all = Array.from({ length: count }, (_, place) => step(place));
  return {
    at,
    requests: all.map((one) => one.requests ?? 0),
    average_ms: all.map((one) => one.average ?? null),
    high_ms: all.map((one) => one.high ?? null),
    cpu_percent: all.map((one) => (one.cpu === undefined ? 1 : one.cpu)),
    busy: all.map((one) => one.busy ?? 0),
  };
}

describe("lineWithGaps", () => {
  it("is one run through points side by side", () => {
    expect(
      lineWithGaps([
        [0, 1],
        [5, 2],
        [10, 3],
      ]),
    ).toEqual({ path: "M0 1 L5 2 L10 3", dots: [] });
  });

  it("breaks where a step has no value, and never goes to nothing there", () => {
    const line = lineWithGaps([[0, 1], [5, 2], null, null, [20, 3], [25, 4]]);
    expect(line.path).toBe("M0 1 L5 2 M20 3 L25 4");
    expect(line.dots).toEqual([]);
  });

  it("gives a point that stands alone as a dot, since a line of one point is not drawn", () => {
    const line = lineWithGaps([null, [5, 2], null, [15, 3], [20, 4], null, [30, 9]]);
    expect(line.path).toBe("M15 3 L20 4");
    expect(line.dots).toEqual([
      [5, 2],
      [30, 9],
    ]);
  });

  it("is nothing for no points, and for none with a value", () => {
    expect(lineWithGaps([])).toEqual({ path: "", dots: [] });
    expect(lineWithGaps([null, null])).toEqual({ path: "", dots: [] });
  });
});

describe("areaUnder", () => {
  it("is a closed shape from the foot, through each run, to the foot again", () => {
    expect(areaUnder([[0, 10], [5, 20], null, [15, 30], [20, 40]], 100, 2)).toBe(
      "M0 100 L0 10 L5 20 V100 Z M15 100 L15 30 L20 40 V100 Z",
    );
  });

  it("is a bar as wide as its step for a point that stands alone", () => {
    expect(areaUnder([null, [10, 30], null], 100, 2.5)).toBe("M7.5 100 V30 H12.5 V100 Z");
  });

  it("is nothing where no step has a value", () => {
    expect(areaUnder([], 100, 2)).toBe("");
    expect(areaUnder([null], 100, 2)).toBe("");
  });
});

describe("loadGraph", () => {
  const width = GRAPH.width - GRAPH.left - GRAPH.right;

  it("lays the two plots one above the other, between the same edges", () => {
    const graph = loadGraph(points(120), 600, 5, CEILING);
    expect(graph.left).toBe(GRAPH.left);
    expect(graph.right).toBe(GRAPH.width - GRAPH.right);
    expect(graph.times.top).toBe(GRAPH.top);
    expect(graph.times.bottom).toBe(GRAPH.top + GRAPH.times);
    expect(graph.cpu.top).toBe(graph.times.bottom + GRAPH.gap);
    expect(graph.cpu.bottom + GRAPH.bottom).toBe(graphHeight());
  });

  it("puts a whole window edge to edge, the oldest step first", () => {
    const graph = loadGraph(points(120), 600, 5, CEILING);
    expect(graph.steps).toHaveLength(120);
    expect(graph.stepWidth).toBeCloseTo(width / 120, 1);
    expect(graph.steps[0]?.x).toBeCloseTo(GRAPH.left + width / 240, 1);
    expect(graph.steps.at(-1)?.x).toBeCloseTo(graph.right - width / 240, 1);
    expect(graph.steps[0]?.at).toBe(noon);
    expect(graph.steps[1]?.at).toBe(noon + 5000);
    expect(graph.from).toBe(noon);
    expect(graph.to).toBe(noon + 600_000);
  });

  it("keeps the axis ten minutes long for a server that started a minute ago", () => {
    const graph = loadGraph(points(12), 600, 5, CEILING);
    expect(graph.steps).toHaveLength(12);
    // The twelve steps are the right-hand tenth: the step under way at the right edge.
    expect(graph.steps.at(-1)?.x).toBeCloseTo(graph.right - width / 240, 1);
    expect(graph.steps[0]?.x).toBeCloseTo(graph.right - (11.5 * width) / 120, 1);
    expect(graph.to).toBe(noon + 60_000);
    expect(graph.from).toBe(noon + 60_000 - 600_000);
  });

  it("draws the newest steps where the server answers more than the window holds", () => {
    const graph = loadGraph(
      points(125, (place) => ({ requests: place })),
      600,
      5,
      CEILING,
    );
    expect(graph.steps).toHaveLength(120);
    expect(graph.steps[0]?.requests).toBe(5);
    expect(graph.steps[0]?.at).toBe(noon + 25_000);
    expect(graph.steps.at(-1)?.requests).toBe(124);
  });

  it("leaves a gap in the lines where a step has no value, not a 0", () => {
    const graph = loadGraph(
      points(6, (place) =>
        place === 2 || place === 3
          ? { cpu: place === 2 ? 40 : null }
          : { requests: 3, average: 10, high: 40, cpu: 40 },
      ),
      600,
      5,
      CEILING,
    );
    // Two runs of the average, and nothing between them.
    expect(graph.timeLine.path.match(/M/g)).toHaveLength(2);
    expect(graph.timeLine.dots).toEqual([]);
    // The processor is known in the third step and not in the fourth: its line stops there.
    expect(graph.processor.path.match(/M/g)).toHaveLength(2);
    expect(graph.processor.path.match(/L/g)).toHaveLength(3);
    expect(graph.processorArea.match(/Z/g)).toHaveLength(2);
    // The longest is a bar for each step that has one, and none for the two that have not.
    expect(graph.timeBars.match(/Z/g)).toHaveLength(4);
    const quiet = graph.steps[2];
    expect(quiet?.line).toBeNull();
    expect(quiet?.behind).toBeNull();
    expect(graph.steps[3]?.cpu).toBeNull();
  });

  it("stands each value at its height on the scale of its own plot", () => {
    const graph = loadGraph(
      points(120, () => ({ requests: 2, average: 50, high: 100, cpu: 50 })),
      600,
      5,
      CEILING,
    );
    expect(graph.times.ticks.map((tick) => tick.value)).toEqual([0, 50, 100]);
    expect(graph.times.ticks[0]?.y).toBe(graph.times.bottom);
    expect(graph.times.ticks.at(-1)?.y).toBe(graph.times.top);
    expect(heightOn(graph.times, 50)).toBe((graph.times.top + graph.times.bottom) / 2);
    expect(
      graph.timeLine.path.startsWith(`M${graph.steps[0]?.x} ${heightOn(graph.times, 50)} `),
    ).toBe(true);
    // The share of the processor is on a scale to 100 at the least.
    expect(graph.cpu.ticks.map((tick) => tick.value)).toEqual([0, 50, 100]);
    expect(heightOn(graph.cpu, 50)).toBe((graph.cpu.top + graph.cpu.bottom) / 2);
    expect(
      graph.processor.path.startsWith(`M${graph.steps[0]?.x} ${heightOn(graph.cpu, 50)} `),
    ).toBe(true);
    // A bar of the longest goes from the foot of its plot to its height, a step wide.
    const first = graph.steps[0]?.x ?? 0;
    expect(
      graph.timeBars.startsWith(
        `M${Math.round((first - width / 240) * 10) / 10} ${graph.times.bottom} V${graph.times.top} `,
      ),
    ).toBe(true);
  });

  it("reaches past 100 for a process that used more than one processor", () => {
    const graph = loadGraph(
      points(10, () => ({ cpu: 130 })),
      600,
      5,
      CEILING,
    );
    expect(graph.cpu.ticks.at(-1)?.value).toBeGreaterThanOrEqual(130);
  });

  it("has a scale to stand on where nothing was answered at all", () => {
    const graph = loadGraph(points(3), 600, 5, CEILING);
    expect(graph.times.ticks.length).toBeGreaterThan(1);
    expect(graph.timeLine).toEqual({ path: "", dots: [] });
    expect(graph.timeBars).toBe("");
  });

  it("draws the two lists of times it is told to, where it is told others", () => {
    const given = points(4, (place) => ({ requests: 1, average: 10 + place, high: 80 }));
    const usual = loadGraph(given, 600, 5, CEILING);
    expect(usual.steps.map((one) => one.line)).toEqual([10, 11, 12, 13]);
    expect(usual.steps.map((one) => one.behind)).toEqual([80, 80, 80, 80]);
    // The other way about: the longest as the line, and the average behind it.
    const other = loadGraph(given, 600, 5, CEILING, GRAPH, {
      line: { list: "high_ms", legend: "the longest of each", said: "longest" },
      behind: { list: "average_ms", legend: "the average of each", said: "average" },
    });
    expect(other.steps.map((one) => one.line)).toEqual([80, 80, 80, 80]);
    expect(other.steps.map((one) => one.behind)).toEqual([10, 11, 12, 13]);
    expect(other.timeLine.path).not.toBe(usual.timeLine.path);
    expect(other.timeBars).not.toBe(usual.timeBars);
    // A list the answer does not hold is a gap at every step, and nothing fails.
    const absent = loadGraph(given, 600, 5, CEILING, GRAPH, {
      line: { list: "p95_ms" as "high_ms", legend: "", said: "" },
      behind: TIME_SERIES.behind,
    });
    expect(absent.steps.map((one) => one.line)).toEqual([null, null, null, null]);
    expect(absent.timeLine).toEqual({ path: "", dots: [] });
  });

  it("marks each step in which an answer of busy was given, and no other", () => {
    const graph = loadGraph(
      points(120, (place) => (place === 7 || place === 119 ? { busy: place } : {})),
      600,
      5,
      CEILING,
    );
    expect(graph.busy.map((one) => one.busy)).toEqual([7, 119]);
    expect(graph.busy[0]?.x).toBe(graph.steps[7]?.x);
    expect(graph.busy[0]?.at).toBe(noon + 35_000);
    expect(loadGraph(points(120), 600, 5, CEILING).busy).toEqual([]);
  });

  it("draws a ceiling that is looked at and on the scale, and no other", () => {
    const slow = loadGraph(
      points(120, () => ({ requests: 1, average: 3000, high: 6000 })),
      600,
      5,
      CEILING,
    );
    expect(slow.times.ceiling).toBe(heightOn(slow.times, 5000));
    expect(slow.cpu.ceiling).toBe(heightOn(slow.cpu, 95));
    // Quick answers: a ceiling of five seconds is far above the scale.
    const quick = loadGraph(
      points(120, () => ({ requests: 1, average: 8, high: 30 })),
      600,
      5,
      CEILING,
    );
    expect(quick.times.ceiling).toBeNull();
    const none = loadGraph(
      points(120, () => ({ requests: 1, average: 3000, high: 6000 })),
      600,
      5,
      NONE,
    );
    expect(none.times.ceiling).toBeNull();
    expect(none.cpu.ceiling).toBeNull();
  });

  it("names each whole minute of the clock on the axis of time", () => {
    const whole = loadGraph(points(120), 600, 5, CEILING);
    expect(whole.minutes).toHaveLength(11);
    expect(whole.minutes[0]).toEqual({ x: whole.left, at: noon });
    expect(whole.minutes.at(-1)).toEqual({ x: whole.right, at: noon + 600_000 });
    // Begun twenty seconds past the minute: the minutes stand a third of a minute in.
    const later = loadGraph(
      points(120, () => ({}), "2026-01-15T12:00:20Z"),
      600,
      5,
      CEILING,
    );
    expect(later.minutes).toHaveLength(10);
    expect(later.minutes[0]?.at).toBe(noon + 60_000);
    expect(later.minutes[0]?.x).toBeCloseTo(later.left + (40 / 600) * width, 1);
  });

  it("draws what it can of an answer whose time does not read, or that is of another shape", () => {
    const graph = loadGraph(
      points(4, () => ({ requests: 1, average: 5, high: 9 }), "soon"),
      600,
      5,
      {
        ...CEILING,
      },
    );
    expect(graph.from).toBeNull();
    expect(graph.minutes).toEqual([]);
    expect(graph.steps.map((one) => one.at)).toEqual([null, null, null, null]);
    expect(graph.timeLine.path).not.toBe("");
    const odd = loadGraph(
      {
        at: NOON,
        requests: [1, 2],
        average_ms: ["quick"],
        busy: [],
      } as unknown as Parameters<typeof loadGraph>[0],
      0,
      0,
      CEILING,
    );
    expect(odd.steps).toHaveLength(2);
    expect(odd.steps[0]).toMatchObject({
      requests: 1,
      line: null,
      behind: null,
      cpu: null,
      busy: 0,
    });
    const empty = loadGraph({} as unknown as Parameters<typeof loadGraph>[0], 600, 5, CEILING);
    expect(empty.steps).toEqual([]);
    expect(empty.busy).toEqual([]);
  });
});
