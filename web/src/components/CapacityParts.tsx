// 0.8.0: the support weight of the capacity report in its parts, and the balance tried
// beside the balance in force (P-155, P-156). Every number is the server's.

import { useMemo } from "react";
import type { CapacityReport } from "../lib/capacity";
import { measureText } from "../lib/capacity";
import { type CompareKind, type CompareRow, compareRows, partRows } from "../lib/capacityParts";
import { decimalValue } from "../lib/sort";
import { countText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";
import { SortTh } from "./SortTh";

function figureText(value: string | null, kind: CompareKind): string {
  if (kind === "count") return value === null ? "—" : countText(Number(value));
  return measureText(value, kind);
}

/**
 * The support weight in its parts: the items, the places and the circuits, each with how
 * many of its kind counted at the default of their kind and how many were raised to its
 * minimum, without the drafts and with them.
 */
export function WeightParts({ report }: { report: CapacityReport }) {
  const rows = useMemo(() => partRows(report), [report]);
  const sorting = useSorting(rows, {
    part: (row) => row.label,
    weight: (row) => decimalValue(row.active.weight),
    defaulted: (row) => row.active.defaulted,
    raised: (row) => row.active.raised,
    drafts_weight: (row) => decimalValue(row.drafts.weight),
    drafts_defaulted: (row) => row.drafts.defaulted,
    drafts_raised: (row) => row.drafts.raised,
  });
  return (
    <section aria-labelledby="capacity-parts" data-testid="capacity-parts">
      <h3 id="capacity-parts">The support weight in its parts</h3>
      <p className="hint">
        The items, the places and the circuits together are the support weight. An item, a site or a
        circuit that gives no weight of its own counts at the default of its kind where an Admin has
        set one, and a weight below the minimum of its kind is raised to it: the counts say how
        many, so that a weight set by policy is told apart from one set by hand. A region and a
        location count their own weight alone, so the counts of the places are of the sites.
      </p>
      <div className="scroll">
        <table data-testid="weight-parts">
          <caption className="visually-hidden">
            The support weight in its parts, without the drafts and with them
          </caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="part">
                Part
              </SortTh>
              <SortTh sort={sorting} column="weight" className="number">
                Support weight
              </SortTh>
              <SortTh sort={sorting} column="defaulted" className="number">
                At a default
              </SortTh>
              <SortTh sort={sorting} column="raised" className="number">
                Raised to a minimum
              </SortTh>
              <SortTh sort={sorting} column="drafts_weight" className="number">
                Support weight with drafts
              </SortTh>
              <SortTh sort={sorting} column="drafts_defaulted" className="number">
                At a default with drafts
              </SortTh>
              <SortTh sort={sorting} column="drafts_raised" className="number">
                Raised with drafts
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <tr key={row.key} data-part={row.key}>
                <th scope="row">
                  {row.label} <span className="muted">(counts of {row.counted})</span>
                </th>
                <td className="number" data-testid="part-weight" data-value={row.active.weight}>
                  {measureText(row.active.weight, "weight")}
                </td>
                <td
                  className="number"
                  data-testid="part-defaulted"
                  data-value={row.active.defaulted}
                >
                  {countText(row.active.defaulted)}
                </td>
                <td className="number" data-testid="part-raised" data-value={row.active.raised}>
                  {countText(row.active.raised)}
                </td>
                <td
                  className="number"
                  data-testid="part-drafts-weight"
                  data-value={row.drafts.weight}
                >
                  {measureText(row.drafts.weight, "weight")}
                </td>
                <td
                  className="number"
                  data-testid="part-drafts-defaulted"
                  data-value={row.drafts.defaulted}
                >
                  {countText(row.drafts.defaulted)}
                </td>
                <td
                  className="number"
                  data-testid="part-drafts-raised"
                  data-value={row.drafts.raised}
                >
                  {countText(row.drafts.raised)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * The balance tried beside the balance in force, figure by figure, without the drafts and
 * with them. A figure that the values tried change is marked.
 */
export function TriedBeside(props: { inForce: CapacityReport; tried: CapacityReport }) {
  const { inForce, tried } = props;
  const rows = useMemo(() => compareRows(inForce, tried), [inForce, tried]);
  const sorting = useSorting(rows, {
    figure: (row) => row.label,
    in_force: (row) => decimalValue(row.inForce.active),
    tried: (row) => decimalValue(row.tried.active),
    in_force_drafts: (row) => decimalValue(row.inForce.drafts),
    tried_drafts: (row) => decimalValue(row.tried.drafts),
    differs: (row) => (row.differs ? "Changed" : null),
  });
  const cell = (row: CompareRow, value: string | null, testId: string) => (
    <td className="number" data-testid={testId} data-value={value ?? ""}>
      {figureText(value, row.kind)}
    </td>
  );
  return (
    <div className="scroll">
      <table data-testid="try-compare">
        <caption>The balance tried beside the balance in force, as of {tried.as_of}</caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="figure">
              Figure
            </SortTh>
            <SortTh sort={sorting} column="in_force" className="number">
              In force
            </SortTh>
            <SortTh sort={sorting} column="tried" className="number">
              Tried
            </SortTh>
            <SortTh sort={sorting} column="in_force_drafts" className="number">
              In force with drafts
            </SortTh>
            <SortTh sort={sorting} column="tried_drafts" className="number">
              Tried with drafts
            </SortTh>
            <SortTh sort={sorting} column="differs">
              Changed
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((row) => (
            <tr key={row.key} data-figure={row.key} data-differs={row.differs ? "true" : "false"}>
              <th scope="row">{row.label}</th>
              {cell(row, row.inForce.active, "in-force-active")}
              {cell(row, row.tried.active, "tried-active")}
              {cell(row, row.inForce.drafts, "in-force-drafts")}
              {cell(row, row.tried.drafts, "tried-drafts")}
              <td>{row.differs ? <span className="badge mark">Changed</span> : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
