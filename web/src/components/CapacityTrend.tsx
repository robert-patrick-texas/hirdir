// The trend of the capacity balance as a graph of one point a week: demand and supply as
// two lines with the balance between them shaded, and a switch that stacks the supply by
// category and splits the demand into the infrastructure and other work. A week that was
// corrected is marked, and shows its corrected totals with its parts as recorded.
//
// It is drawn here, in SVG, from the records as the server answered them: nothing is
// added up but the parts stacked one on another. The table of the records beside it
// holds every figure for whoever does not read the graph.

import { useId, useMemo, useState } from "react";
import { measureText } from "../lib/capacity";
import {
  type At,
  axisTicks,
  balanceBands,
  type CapacityRecord,
  namedWeeks,
  pathThrough,
  shapeThrough,
  stackedSupply,
  type TrendPoint,
  type TrendView,
  trendCategories,
  trendPoints,
  trendTop,
} from "../lib/trend";
import { CheckField, SelectField } from "./Field";

const WIDTH = 720;
const HEIGHT = 300;
const MARGIN = { top: 16, right: 20, bottom: 40, left: 52 };
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
// How much room one week's name takes under the axis.
const WEEK_ROOM = 84;
// The colours of the categories of supply: as many as the stylesheet has, then again.
const LAYERS = 6;

/** What a week says when it is pointed at. */
function weekTitle(point: TrendPoint, parts: boolean): string {
  const lines = [
    `Week of ${point.week}`,
    `Demand ${measureText(point.text.demand, "units")}, supply ${measureText(point.text.supply, "units")}, balance ${measureText(point.text.balance, "units")}`,
  ];
  if (parts) {
    lines.push(
      `Infrastructure ${measureText(point.text.infrastructure, "units")}, other work ${measureText(point.text.other, "units")}, as recorded`,
    );
  }
  if (point.adjusted) lines.push(`Corrected${point.note ? `: ${point.note}` : ""}`);
  return lines.join("\n");
}

interface TrendGraphProps {
  records: readonly CapacityRecord[];
}

/** The graph of the balance, week by week, with the switches that change what it shows. */
export function TrendGraph({ records }: TrendGraphProps) {
  const id = useId();
  const [view, setView] = useState<TrendView>("active");
  const [parts, setParts] = useState(false);
  const points = useMemo(() => trendPoints(records, view), [records, view]);
  const categories = useMemo(() => trendCategories(records, view), [records, view]);
  const layers = useMemo(() => stackedSupply(points, categories), [points, categories]);
  const bands = useMemo(() => balanceBands(points), [points]);

  const ticks = axisTicks(trendTop(points) * 1.05);
  const highest = ticks.at(-1) ?? 1;
  const x = (place: number) =>
    points.length <= 1
      ? MARGIN.left + PLOT_WIDTH / 2
      : MARGIN.left + (place * PLOT_WIDTH) / (points.length - 1);
  const y = (amount: number) => MARGIN.top + PLOT_HEIGHT - (amount / highest) * PLOT_HEIGHT;
  const at = ([place, amount]: At): At => [x(place), y(amount)];
  const line = (amount: (point: TrendPoint) => number) =>
    pathThrough(points.map((point, place) => at([place, amount(point)])));
  const adjusted = points.filter((point) => point.adjusted).length;

  return (
    <div className="trend" data-testid="capacity-trend-graph" data-parts={parts} data-view={view}>
      <div className="inline">
        <SelectField
          label="View"
          name="trend-view"
          value={view}
          onChange={(next) => setView(next === "with_drafts" ? "with_drafts" : "active")}
        >
          <option value="active">Without the drafts</option>
          <option value="with_drafts">With the drafts, as if they were active</option>
        </SelectField>
        <CheckField
          label="Show the parts: the supply of each category, and the demand of the infrastructure and of other work"
          name="trend-parts"
          checked={parts}
          onChange={setParts}
        />
      </div>
      {points.length === 0 ? (
        <p className="muted" data-testid="trend-empty">
          No week has been recorded yet. The server records the balance by itself each Monday, and
          it may be recorded by hand at any time.
        </p>
      ) : (
        <>
          <svg
            className="trend-graph"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-labelledby={`${id}-title ${id}-desc`}
          >
            <title id={`${id}-title`}>
              {`Demand and supply in resource units, one point a week${view === "with_drafts" ? ", with the drafts" : ""}`}
            </title>
            <desc id={`${id}-desc`}>
              {`${points.length === 1 ? "One week" : `${points.length} weeks`}, from ${points[0]?.week ?? ""} to ${points.at(-1)?.week ?? ""}${adjusted > 0 ? `; ${adjusted} corrected` : ""}. Every figure is in the table of the records below.`}
            </desc>
            <g className="trend-axis">
              {ticks.map((tick) => (
                <g key={tick}>
                  <line
                    className="trend-grid"
                    x1={MARGIN.left}
                    x2={MARGIN.left + PLOT_WIDTH}
                    y1={y(tick)}
                    y2={y(tick)}
                  />
                  <text x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                    {tick}
                  </text>
                </g>
              ))}
              {namedWeeks(points.length, PLOT_WIDTH / WEEK_ROOM).map((place) => (
                <text
                  key={points[place]?.week}
                  x={x(place)}
                  y={MARGIN.top + PLOT_HEIGHT + 22}
                  textAnchor="middle"
                >
                  {points[place]?.week}
                </text>
              ))}
            </g>
            {parts ? (
              <g className="trend-parts">
                {layers.map((layer, number) => (
                  <path
                    key={layer.category}
                    className={`trend-layer trend-layer-${number % LAYERS}`}
                    data-category={layer.category}
                    d={
                      points.length === 1
                        ? shapeThrough([
                            [x(0) - 6, y(layer.upper[0] ?? 0)],
                            [x(0) + 6, y(layer.upper[0] ?? 0)],
                            [x(0) + 6, y(layer.lower[0] ?? 0)],
                            [x(0) - 6, y(layer.lower[0] ?? 0)],
                          ])
                        : shapeThrough([
                            ...layer.upper.map((amount, place): At => at([place, amount])),
                            ...layer.lower
                              .map((amount, place): At => at([place, amount]))
                              .reverse(),
                          ])
                    }
                  />
                ))}
                <path className="trend-infrastructure" d={line((point) => point.infrastructure)} />
                <path
                  className="trend-recorded-demand"
                  d={line((point) => point.infrastructure + point.other)}
                />
              </g>
            ) : (
              <g className="trend-bands">
                {bands.map((band) => (
                  <path
                    key={band.points.map(([place, amount]) => `${place},${amount}`).join(" ")}
                    className={`trend-band trend-band-${band.tone}`}
                    d={shapeThrough(band.points.map(at))}
                  />
                ))}
              </g>
            )}
            <path className="trend-demand" d={line((point) => point.demand)} />
            <path className="trend-supply" d={line((point) => point.supply)} />
            {points.map((point, place) => (
              <g
                key={point.hid}
                className="trend-point"
                data-testid="trend-point"
                data-week={point.week}
                data-demand={point.text.demand}
                data-supply={point.text.supply}
                data-balance={point.text.balance}
                data-adjusted={point.adjusted ? "true" : "false"}
              >
                <title>{weekTitle(point, parts)}</title>
                {/* A wider mark to point at than the dots themselves. */}
                <rect
                  className="trend-hit"
                  x={x(place) - 8}
                  y={MARGIN.top}
                  width={16}
                  height={PLOT_HEIGHT}
                />
                <circle className="trend-dot-demand" cx={x(place)} cy={y(point.demand)} r={4} />
                <circle className="trend-dot-supply" cx={x(place)} cy={y(point.supply)} r={4} />
                {point.adjusted && (
                  <>
                    <circle className="trend-adjusted" cx={x(place)} cy={y(point.supply)} r={8} />
                    <circle className="trend-adjusted" cx={x(place)} cy={y(point.demand)} r={8} />
                    <text
                      className="trend-adjusted-label"
                      x={x(place)}
                      y={Math.min(y(point.supply), y(point.demand)) - 12}
                      textAnchor="middle"
                    >
                      corrected
                    </text>
                  </>
                )}
              </g>
            ))}
          </svg>
          <ul className="trend-legend" aria-label="What the graph shows">
            <li>
              <span className="trend-key trend-key-demand" aria-hidden="true" /> Demand
            </li>
            <li>
              <span className="trend-key trend-key-supply" aria-hidden="true" /> Supply
            </li>
            {parts ? (
              <>
                <li>
                  <span className="trend-key trend-key-infrastructure" aria-hidden="true" />{" "}
                  Infrastructure demand, as recorded
                </li>
                <li>
                  <span className="trend-key trend-key-recorded" aria-hidden="true" />{" "}
                  Infrastructure and other work, as recorded
                </li>
                {layers.map((layer, number) => (
                  <li key={layer.category}>
                    <span
                      className={`trend-key trend-key-layer trend-layer-${number % LAYERS}`}
                      aria-hidden="true"
                    />{" "}
                    {layer.label}
                  </li>
                ))}
              </>
            ) : (
              <>
                <li>
                  <span className="trend-key trend-band-over" aria-hidden="true" /> Supply above
                  demand
                </li>
                <li>
                  <span className="trend-key trend-band-short" aria-hidden="true" /> Supply short of
                  demand
                </li>
              </>
            )}
            {adjusted > 0 && (
              <li>
                <span className="trend-key trend-key-adjusted" aria-hidden="true" /> A corrected
                week: its lines go through the corrected totals
                {parts ? ", and its parts are as they were recorded" : ""}
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}
