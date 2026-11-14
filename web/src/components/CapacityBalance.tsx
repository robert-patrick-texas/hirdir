// The capacity balance as the server worked it out: every measure of the view without
// the drafts beside the view with them, and demand beside supply by category. Nothing is
// added up here.

import { useMemo } from "react";
import {
  balanceRows,
  balanceTone,
  balanceWords,
  type CapacityReport,
  type CapacityView,
  MEASURES,
  measureText,
} from "../lib/capacity";
import { decimalValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { SortTh } from "./SortTh";

function Dash() {
  return <span className="muted">—</span>;
}

interface BalanceProps {
  report: CapacityReport;
  /** The installation's currency, as a heading names it after an amount. */
  money: string;
}

/** The balance: the headline of each view, then demand beside supply by category. */
export function Balance({ report, money }: BalanceProps) {
  const rows = useMemo(() => balanceRows(report), [report]);
  const sorting = useSorting(rows, {
    side: (row) => row.side,
    name: (row) => row.name,
    active: (row) => decimalValue(row.active),
    drafts: (row) => decimalValue(row.drafts),
    lines: (row) => row.lines,
    draft_lines: (row) => row.draftLines,
    cost: (row) => decimalValue(row.cost),
    draft_cost: (row) => decimalValue(row.draftCost),
  });
  return (
    <section
      aria-labelledby="capacity-balance"
      data-testid="capacity-report"
      data-as-of={report.as_of}
    >
      <h2 id="capacity-balance">The balance, as of {report.as_of}</h2>
      <p className="hint">
        One resource unit carries a support weight of{" "}
        {measureText(report.weight_per_resource_unit, "weight")}: a mid-level position, by
        convention. It is the <span className="mono">weight_per_resource_unit</span> setting.
      </p>
      <div className="two-up">
        <Headline title="Without the drafts" view={report.active} which="active" />
        <Headline
          title="With the drafts, as if they were active"
          view={report.with_drafts}
          which="with_drafts"
        />
      </div>
      <div className="scroll">
        <table data-testid="capacity-sides">
          <caption>Demand beside supply by category, in resource units</caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="side">
                Side
              </SortTh>
              <SortTh sort={sorting} column="name">
                What
              </SortTh>
              <SortTh sort={sorting} column="active" className="number">
                Units
              </SortTh>
              <SortTh sort={sorting} column="drafts" className="number">
                Units with drafts
              </SortTh>
              <SortTh sort={sorting} column="lines" className="number">
                Lines
              </SortTh>
              <SortTh sort={sorting} column="draft_lines" className="number">
                Lines with drafts
              </SortTh>
              <SortTh sort={sorting} column="cost" className="number">
                Annual cost{money}
              </SortTh>
              <SortTh sort={sorting} column="draft_cost" className="number">
                Annual cost with drafts{money}
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <tr key={row.key} data-row={row.key} data-side={row.side.toLowerCase()}>
                <td>{row.side}</td>
                <th scope="row">{row.name}</th>
                <td className="number" data-testid="units-active" data-value={row.active}>
                  {measureText(row.active, "units")}
                </td>
                <td className="number" data-testid="units-with-drafts" data-value={row.drafts}>
                  {measureText(row.drafts, "units")}
                </td>
                <td className="number">{row.lines ?? <Dash />}</td>
                <td className="number">{row.draftLines ?? <Dash />}</td>
                <td className="number">
                  {row.cost === null ? <Dash /> : measureText(row.cost, "money")}
                </td>
                <td className="number">
                  {row.draftCost === null ? <Dash /> : measureText(row.draftCost, "money")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        A line counts when it is active and in date; with drafts, the draft lines and the draft
        items count as if they were active. Every number is worked out exactly by the server and
        rounded to two places once.
      </p>
    </section>
  );
}

/** One view of the balance: every measure under its name, the balance in words too. */
function Headline(props: { title: string; view: CapacityView; which: "active" | "with_drafts" }) {
  const { title, view, which } = props;
  const tone = balanceTone(view.balance);
  return (
    <section
      className="panel"
      aria-label={title}
      data-testid={`capacity-${which}`}
      data-balance={tone}
    >
      <h3>{title}</h3>
      <dl className="totals">
        {MEASURES.map((measure) => (
          <div key={measure.key} title={measure.about}>
            <dt>{measure.label}</dt>
            <dd data-testid={`${which}-${measure.key}`} data-value={view[measure.key] ?? ""}>
              {measureText(view[measure.key], measure.kind)}
            </dd>
          </div>
        ))}
      </dl>
      <p
        className={tone === "short" ? "warning" : undefined}
        data-testid={`${which}-balance-words`}
      >
        {balanceWords(view.balance)}.
      </p>
    </section>
  );
}
