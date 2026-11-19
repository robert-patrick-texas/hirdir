// The graph of the server's last ten minutes on About (P-266), worked out here and drawn
// by the page as SVG: where each step of five seconds stands on one axis of time, and
// two plots one above the other, each with a scale of its own: the time of an answer,
// one list of the answer as a line and another as bars behind it, and the share of one
// processor as a line. Nothing here draws or reads a clock: it is given the answer of
// `GET /about/load` and says where things go.
//
// Which lists the plot of the time of an answer draws is said once, in `TIME_SERIES`,
// with the words of each: today the average of a step as the line and its longest
// behind it. Another pair, as two percentiles of a step, is a change of that one table.

import type { Schemas } from "../api/client";
import { type At, axisTicks, pathThrough } from "./trend";

export type LoadPoints = Schemas["LoadPoints"];
export type LoadCeiling = Schemas["LoadCeiling"];

/** The lists of the answer that hold a time for each step, or null where there is none. */
type TimeList = {
  [K in keyof LoadPoints]: LoadPoints[K] extends (number | null)[] ? K : never;
}[keyof LoadPoints];

/** One list of times, as the plot of the time of an answer draws it. */
export interface TimeSeries {
  /** The member of `points` that holds it. */
  list: TimeList;
  /** What it is of each step, in the legend: "the average of each 5 seconds". */
  legend: string;
  /** What it is called beside its number, where a step is pointed at. */
  said: string;
}

/** The two lists of times the graph draws: one as a line, one as bars behind it. */
export interface TimeSeriesPair {
  line: TimeSeries;
  behind: TimeSeries;
}

export const TIME_SERIES: TimeSeriesPair = {
  line: { list: "average_ms", legend: "the average of each", said: "average" },
  behind: { list: "high_ms", legend: "the longest of each", said: "longest" },
};

/** The room the graph is drawn in, in the units of its own box. */
export interface GraphLayout {
  width: number;
  /** Left of the plots: the numbers of the scales. */
  left: number;
  right: number;
  /** Above the first plot: its name, and the marks of busy. */
  top: number;
  /** The height of the plot of the time of an answer. */
  times: number;
  /** Between the plots: the name of the second. */
  gap: number;
  /** The height of the plot of the processor. */
  cpu: number;
  /** Beneath the plots: the minutes of the clock. */
  bottom: number;
}

export const GRAPH: GraphLayout = {
  width: 720,
  left: 56,
  right: 16,
  top: 32,
  times: 120,
  gap: 34,
  cpu: 80,
  bottom: 28,
};

/** The whole height of a graph laid out so. */
export function graphHeight(layout: GraphLayout = GRAPH): number {
  return layout.top + layout.times + layout.gap + layout.cpu + layout.bottom;
}

/** One of the two plots: where it stands, its scale, and its ceiling where it shows. */
export interface Plot {
  top: number;
  bottom: number;
  /** The steps of the scale, from nothing up, each with where it stands. */
  ticks: Array<{ value: number; y: number }>;
  /** Where the ceiling stands, or null where none is looked at or it is off the scale. */
  ceiling: number | null;
}

/** A line with gaps: its runs as one path, and each point that stands alone. */
export interface Line {
  path: string;
  dots: At[];
}

/** One step of five seconds, as it stands on the graph. */
export interface Step {
  /** The middle of the step. */
  x: number;
  /** When the step began, in milliseconds of the epoch; null where the server gave no time that reads. */
  at: number | null;
  requests: number;
  /** The time drawn as the line, and the time drawn behind it: see `TIME_SERIES`. */
  line: number | null;
  behind: number | null;
  cpu: number | null;
  busy: number;
}

export interface LoadGraph {
  /** The left and right edges of both plots. */
  left: number;
  right: number;
  /** How wide one step is. */
  stepWidth: number;
  /** When the axis of time begins and ends, in milliseconds of the epoch. */
  from: number | null;
  to: number | null;
  times: Plot;
  cpu: Plot;
  /** The time of an answer that is drawn as a line. */
  timeLine: Line;
  /** The time of an answer drawn behind it: one closed shape of a bar for each step that has one. */
  timeBars: string;
  /** The share of one processor. */
  processor: Line;
  /** What lies under the line of the processor: closed shapes, one for each run of it. */
  processorArea: string;
  /** The steps the server has run, the oldest first, the last at the right edge. */
  steps: Step[];
  /** The steps in which an answer of busy was given. */
  busy: Step[];
  /** Each whole minute of the clock on the axis of time. */
  minutes: Array<{ x: number; at: number }>;
}

/** A number of the server's, or null for anything else: a null, or an answer of another shape. */
function numberOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Where a value stands between two heights, on a scale from nothing to `highest`. */
function heightOf(top: number, bottom: number, highest: number, value: number): number {
  return round(bottom - (value / (highest || 1)) * (bottom - top));
}

/** A plot between two heights whose scale reaches `most`, in about four steps. */
function plotOf(top: number, bottom: number, most: number, ceiling: number): Plot {
  const values = axisTicks(most, 4);
  const highest = values.at(-1) ?? 1;
  return {
    top,
    bottom,
    ticks: values.map((value) => ({ value, y: heightOf(top, bottom, highest, value) })),
    ceiling: ceiling > 0 && ceiling <= highest ? heightOf(top, bottom, highest, ceiling) : null,
  };
}

/** Where a value stands on a plot. */
export function heightOn(plot: Plot, value: number): number {
  return heightOf(plot.top, plot.bottom, plot.ticks.at(-1)?.value ?? 1, value);
}

/** A line through the steps that have a value: a gap where one has none, never a 0. */
export function lineWithGaps(points: ReadonlyArray<At | null>): Line {
  const runs: At[][] = [];
  let run: At[] = [];
  for (const point of [...points, null]) {
    if (point) {
      run.push(point);
    } else if (run.length > 0) {
      runs.push(run);
      run = [];
    }
  }
  return {
    path: runs
      .filter((one) => one.length > 1)
      .map(pathThrough)
      .join(" "),
    dots: runs.filter((one) => one.length === 1).flat(),
  };
}

/**
 * What lies under a line with gaps, down to `foot`: one closed shape for each run, and
 * for a point that stands alone a bar as wide as its step, `half` to each side.
 */
export function areaUnder(points: ReadonlyArray<At | null>, foot: number, half: number): string {
  const shapes: string[] = [];
  let run: At[] = [];
  for (const point of [...points, null]) {
    if (point) {
      run.push(point);
      continue;
    }
    const [first] = run;
    const last = run.at(-1);
    if (first && last) {
      const [from, to] = run.length === 1 ? [first[0] - half, last[0] + half] : [first[0], last[0]];
      const through =
        run.length === 1
          ? `V${round(first[1])} H${round(to)}`
          : pathThrough(run).replace(/^M/, "L");
      shapes.push(`M${round(from)} ${foot} ${through} V${foot} Z`);
    }
    run = [];
  }
  return shapes.join(" ");
}

/**
 * The graph of what `GET /about/load` answered in `points`. The axis of time is as long
 * as the window whatever the server has run of it, so a server that started a minute ago
 * fills the right-hand tenth and the graph does not stretch; the step under way is at
 * the right edge.
 */
export function loadGraph(
  points: LoadPoints,
  windowSeconds: number,
  stepSeconds: number,
  ceiling: LoadCeiling,
  layout: GraphLayout = GRAPH,
  series: TimeSeriesPair = TIME_SERIES,
): LoadGraph {
  const step = stepSeconds > 0 ? stepSeconds : 5;
  const most = Math.max(1, Math.round((windowSeconds > 0 ? windowSeconds : 600) / step));
  const all = Array.isArray(points.requests) ? points.requests.length : 0;
  // No more steps than the window holds: the newest are kept.
  const skipped = Math.max(0, all - most);
  const count = all - skipped;
  const left = layout.left;
  const right = layout.width - layout.right;
  const stepWidth = (right - left) / most;
  const began = Date.parse(points.at);
  const start = Number.isFinite(began) ? began + skipped * step * 1000 : null;
  const to = start === null ? null : start + count * step * 1000;
  const from = to === null ? null : to - most * step * 1000;

  const steps: Step[] = [];
  for (let place = 0; place < count; place += 1) {
    const entry = skipped + place;
    steps.push({
      x: round(left + (most - count + place + 0.5) * stepWidth),
      at: start === null ? null : start + place * step * 1000,
      requests: numberOf(points.requests[entry]) ?? 0,
      line: numberOf(points[series.line.list]?.[entry]),
      behind: numberOf(points[series.behind.list]?.[entry]),
      cpu: numberOf(points.cpu_percent?.[entry]),
      busy: numberOf(points.busy?.[entry]) ?? 0,
    });
  }

  const longest = Math.max(1, ...steps.map((one) => Math.max(one.behind ?? 0, one.line ?? 0)));
  const busiest = Math.max(100, ...steps.map((one) => one.cpu ?? 0));
  const timesTop = layout.top;
  const timesBottom = timesTop + layout.times;
  const cpuTop = timesBottom + layout.gap;
  const cpuBottom = cpuTop + layout.cpu;
  const times = plotOf(timesTop, timesBottom, longest, numberOf(ceiling.response_ms) ?? 0);
  const cpu = plotOf(cpuTop, cpuBottom, busiest, numberOf(ceiling.cpu_percent) ?? 0);

  const half = stepWidth / 2;
  const timeBars = steps
    .filter((one) => one.behind !== null)
    .map((one) => {
      const y = heightOn(times, one.behind ?? 0);
      return `M${round(one.x - half)} ${times.bottom} V${y} H${round(one.x + half)} V${times.bottom} Z`;
    })
    .join(" ");

  const shares = steps.map((one): At | null =>
    one.cpu === null ? null : [one.x, heightOn(cpu, one.cpu)],
  );

  const minutes: LoadGraph["minutes"] = [];
  if (from !== null && to !== null) {
    for (let at = Math.ceil(from / 60_000) * 60_000; at <= to; at += 60_000) {
      minutes.push({ x: round(left + ((at - from) / (to - from)) * (right - left)), at });
    }
  }

  return {
    left,
    right,
    stepWidth: round(stepWidth),
    from,
    to,
    times,
    cpu,
    timeLine: lineWithGaps(
      steps.map((one): At | null =>
        one.line === null ? null : [one.x, heightOn(times, one.line)],
      ),
    ),
    timeBars,
    processor: lineWithGaps(shares),
    processorArea: areaUnder(shares, cpu.bottom, half),
    steps,
    busy: steps.filter((one) => one.busy > 0),
    minutes,
  };
}
