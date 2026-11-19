// The graph of the server's last ten minutes on About (P-266): the ten minutes on one
// axis of time, and two plots one above the other, each with a scale of its own named
// with its unit: the time of an answer, the average of each step as a line and the
// longest as bars behind it, and the share of one processor as a line over its area. A
// step in which an answer of busy was given has a band down both plots and a triangle
// above them. Which two lists of times are drawn, and the words of each in the legend and
// where a step is pointed at, are `TIME_SERIES` of `lib/loadGraph.ts` and nothing here.
//
// It is drawn here, in SVG, with no library, from where `lib/loadGraph.ts` says things
// go. The lines are told apart without colour: by the plot each is in, by the legend,
// which shows each as it is drawn, and by the shape of the mark of busy. The numbers of
// the ten minutes are in the tables beside it, for whoever does not read a graph.
//
// It is drawn again only when the steps or the ceiling are other values than they were:
// About keeps the lists it was given where a new answer holds the same (P-264).

import { memo, useId, useMemo } from "react";
import { plural } from "../lib/format";
import { clockText, minuteText, msText, percentText } from "../lib/load";
import {
  GRAPH,
  graphHeight,
  type LoadCeiling,
  type LoadPoints,
  loadGraph,
  type Plot,
  type Step,
  TIME_SERIES,
} from "../lib/loadGraph";

interface LoadGraphProps {
  points: LoadPoints;
  ceiling: LoadCeiling;
  windowSeconds: number;
  stepSeconds: number;
}

const HEIGHT = graphHeight();

/** What a step says when it is pointed at. */
function stepTitle(step: Step): string {
  const said = [plural(step.requests, "request answered", "requests answered")];
  if (step.line !== null) said.push(`${TIME_SERIES.line.said} ${msText(step.line)}`);
  if (step.behind !== null) said.push(`${TIME_SERIES.behind.said} ${msText(step.behind)}`);
  said.push(`processor ${percentText(step.cpu, "not known yet")}`);
  if (step.busy > 0) said.push(`${plural(step.busy, "answer")} of busy`);
  return `${step.at === null ? "" : `${clockText(step.at)}: `}${said.join(", ")}`;
}

/** The steps of the scale of a plot, its name, and its ceiling where it shows. */
function Scale({
  plot,
  name,
  left,
  right,
}: {
  plot: Plot;
  name: string;
  left: number;
  right: number;
}) {
  return (
    <g>
      <text className="load-plot-name" x={left} y={plot.top - 9}>
        {name}
      </text>
      {plot.ticks.map((tick) => (
        <g key={tick.value}>
          <line className="load-grid" x1={left} x2={right} y1={tick.y} y2={tick.y} />
          <text x={left - 8} y={tick.y} dy="0.32em" textAnchor="end">
            {tick.value.toLocaleString("en-US")}
          </text>
        </g>
      ))}
      {plot.ceiling !== null && (
        <line
          className="load-ceiling"
          data-testid="load-ceiling-line"
          x1={left}
          x2={right}
          y1={plot.ceiling}
          y2={plot.ceiling}
        />
      )}
    </g>
  );
}

export const LoadGraph = memo(function LoadGraph({
  points,
  ceiling,
  windowSeconds,
  stepSeconds,
}: LoadGraphProps) {
  const id = useId();
  const graph = useMemo(
    () => loadGraph(points, windowSeconds, stepSeconds, ceiling),
    [points, windowSeconds, stepSeconds, ceiling],
  );
  const { left, right, times, cpu, stepWidth } = graph;
  const half = stepWidth / 2;
  const lastBusy = graph.busy.at(-1);
  const minutes = Math.round(windowSeconds / 60);
  const span =
    graph.from === null || graph.to === null
      ? ""
      : `From ${clockText(graph.from)} to ${clockText(graph.to)}. `;
  const busySaid =
    graph.busy.length === 0
      ? "No answer of busy was given in the time the graph shows."
      : `An answer of busy was given in ${graph.busy.length} of the graph's ${plural(graph.steps.length, "step")} of ${plural(stepSeconds, "second")}${
          lastBusy?.at ? `, the last at ${clockText(lastBusy.at)}` : ""
        }.`;
  const ceilingDrawn = times.ceiling !== null || cpu.ceiling !== null;

  return (
    <div className="load-graph-part" data-testid="load-graph">
      <svg
        className="load-graph"
        viewBox={`0 0 ${GRAPH.width} ${HEIGHT}`}
        role="img"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-desc`}
      >
        <title id={`${id}-title`}>
          {`The server's last ${plural(minutes, "minute")} in steps of ${plural(stepSeconds, "second")}: the time of an answer in milliseconds, and beneath it the share of one processor in percent, with a mark at each step in which an answer of busy was given`}
        </title>
        <desc id={`${id}-desc`}>
          {`${span}${busySaid} The lowest, the average and the highest of each are in the table above the graph.`}
        </desc>
        {graph.busy.map((step) => (
          <rect
            key={step.x}
            className="load-busy-band"
            x={step.x - half}
            y={times.top}
            width={stepWidth}
            height={cpu.bottom - times.top}
          />
        ))}
        <Scale plot={times} name="Time of an answer, in milliseconds" left={left} right={right} />
        <Scale plot={cpu} name="Share of one processor, in percent" left={left} right={right} />
        <path className="load-time-bars" d={graph.timeBars} />
        <path className="load-time-line" d={graph.timeLine.path} />
        {graph.timeLine.dots.map(([x, y]) => (
          <circle key={x} className="load-time-dot" cx={x} cy={y} r={2} />
        ))}
        <path className="load-cpu-area" d={graph.processorArea} />
        <path className="load-cpu" d={graph.processor.path} />
        {graph.processor.dots.map(([x, y]) => (
          <circle key={x} className="load-cpu-dot" cx={x} cy={y} r={2} />
        ))}
        <g className="load-minutes">
          {graph.minutes.map((minute) => (
            <g key={minute.at}>
              <line
                className="load-grid"
                x1={minute.x}
                x2={minute.x}
                y1={cpu.bottom}
                y2={cpu.bottom + 4}
              />
              <text x={minute.x} y={cpu.bottom + 17} textAnchor="middle">
                {minuteText(minute.at)}
              </text>
            </g>
          ))}
        </g>
        {graph.steps.map((step) => (
          <g key={step.at ?? step.x} className="load-step">
            <title>{stepTitle(step)}</title>
            <rect
              className="load-hit"
              x={step.x - half}
              y={times.top}
              width={stepWidth}
              height={cpu.bottom - times.top}
            />
          </g>
        ))}
        {graph.busy.map((step) => (
          <polygon
            key={step.x}
            className="load-busy-mark"
            data-testid="load-busy-mark"
            data-busy={step.busy}
            points={`${step.x - 5},${times.top - 13} ${step.x + 5},${times.top - 13} ${step.x},${times.top - 3}`}
          >
            <title>{stepTitle(step)}</title>
          </polygon>
        ))}
      </svg>
      <ul className="load-legend" aria-label="What the graph shows">
        <li>
          <span className="load-key load-key-time-line" aria-hidden="true" /> Time of an answer:{" "}
          {TIME_SERIES.line.legend} {plural(stepSeconds, "second")}
        </li>
        <li>
          <span className="load-key load-key-time-bars" aria-hidden="true" /> Time of an answer:{" "}
          {TIME_SERIES.behind.legend} {plural(stepSeconds, "second")}
        </li>
        <li>
          <span className="load-key load-key-cpu" aria-hidden="true" /> Share of one processor
        </li>
        <li>
          <span className="load-key load-key-busy" aria-hidden="true" /> A step in which an answer
          of busy was given
        </li>
        {ceilingDrawn && (
          <li>
            <span className="load-key load-key-ceiling" aria-hidden="true" /> The ceiling in force
          </li>
        )}
      </ul>
      <p className="load-busy-steps" data-testid="load-busy-steps" data-steps={graph.busy.length}>
        {busySaid} A step with no request is a gap in the line of the time of an answer.
      </p>
    </div>
  );
});
