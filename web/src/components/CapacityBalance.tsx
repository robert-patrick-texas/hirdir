// The capacity balance as the server worked it out: every measure of the view without
// the drafts beside the view with them, and demand beside supply by category. Nothing is
// added up here.

import { useMemo } from "react";
import { Link } from "react-router";
import {
  balanceRows,
  balanceTone,
  balanceWords,
  type CapacityReport,
  type CapacityView,
  capacityLinePath,
  MEASURES,
  type MultiplyingLine,
  measureText,
  type RegionRow,
  regionRows,
  targetsText,
} from "../lib/capacity";
import { placePath } from "../lib/places";
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
      <Multiplying report={report} />
      <DemandByRegion report={report} />
    </section>
  );
}

/**
 * The lines that multiply, in each view: what each adds, and the staff lines it works
 * on. Its gain is in its own category above, so the team's own share stays that of its
 * positions.
 */
function Multiplying({ report }: { report: CapacityReport }) {
  const any =
    report.active.multiplying_lines.length > 0 || report.with_drafts.multiplying_lines.length > 0;
  return (
    <section aria-labelledby="capacity-multiplying" data-testid="capacity-multiplying">
      <h3 id="capacity-multiplying">Lines that multiply</h3>
      {any ? (
        <>
          <p className="hint">
            A tool or a service that makes people more effective adds (factor − 1) × share × the
            units of the staff lines it works on that count in the view. Each works on those units
            alone, and none compounds another.
          </p>
          <MultiplyingTable
            title="Without the drafts"
            which="active"
            lines={report.active.multiplying_lines}
          />
          <MultiplyingTable
            title="With the drafts"
            which="with_drafts"
            lines={report.with_drafts.multiplying_lines}
          />
        </>
      ) : (
        <p className="muted">
          No line multiplies the staff lines. A line of tools or of services may, from its own page.
        </p>
      )}
    </section>
  );
}

function MultiplyingTable(props: {
  title: string;
  which: "active" | "with_drafts";
  lines: readonly MultiplyingLine[];
}) {
  const { title, which, lines } = props;
  const sorting = useSorting(lines, {
    name: (line) => line.name,
    category: (line) => line.category,
    factor: (line) => decimalValue(line.factor),
    share: (line) => decimalValue(line.share),
    targets: (line) => targetsText(line),
    base: (line) => decimalValue(line.base_units),
    units: (line) => decimalValue(line.units),
  });
  return (
    <div className="scroll">
      <table data-testid={`multiplying-${which}`}>
        <caption>{title}, in resource units</caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="name">
              Line
            </SortTh>
            <SortTh sort={sorting} column="category">
              Category
            </SortTh>
            <SortTh sort={sorting} column="factor" className="number">
              Factor
            </SortTh>
            <SortTh sort={sorting} column="share" className="number">
              Share
            </SortTh>
            <SortTh sort={sorting} column="targets">
              Works on
            </SortTh>
            <SortTh sort={sorting} column="base" className="number">
              Units worked on
            </SortTh>
            <SortTh sort={sorting} column="units" className="number">
              Gain
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((line) => (
            <tr key={line.hid} data-line={line.name}>
              <th scope="row">
                <Link to={capacityLinePath(line.hid)}>{line.name}</Link>
              </th>
              <td>{line.category}</td>
              <td className="number">{measureText(line.factor, "units")}</td>
              <td className="number">{measureText(line.share, "units")}</td>
              <td>
                <ul className="plain-list">
                  {line.applies_to.map((target) => (
                    <li
                      key={target.hid}
                      data-target={target.name}
                      data-counted={target.counted ? "true" : "false"}
                    >
                      <Link to={capacityLinePath(target.hid)}>{target.name}</Link>{" "}
                      {target.counted ? (
                        <span className="muted">{measureText(target.units, "units")}</span>
                      ) : (
                        <span className="muted">not counted in this view</span>
                      )}
                    </li>
                  ))}
                </ul>
              </td>
              <td className="number" data-testid="multiplying-base" data-value={line.base_units}>
                {measureText(line.base_units, "units")}
              </td>
              <td className="number" data-testid="multiplying-gain" data-value={line.units}>
                {measureText(line.units, "units")}
              </td>
            </tr>
          ))}
          {lines.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                No line that multiplies counts in this view.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Where the work is: the support weight of the items at or beneath each region, the
 * infrastructure demand that is, and its share of the whole. The balance stays one for
 * the whole team: no supply is divided among the regions.
 */
function DemandByRegion({ report }: { report: CapacityReport }) {
  const rows = useMemo(() => regionRows(report), [report]);
  const sorting = useSorting(rows, {
    path: (row) => row.path,
    weight: (row) => decimalValue(row.active?.support_weight),
    demand: (row) => decimalValue(row.active?.infrastructure_demand),
    share: (row) => decimalValue(row.active?.share_pct),
    drafts_weight: (row) => decimalValue(row.drafts?.support_weight),
    drafts_demand: (row) => decimalValue(row.drafts?.infrastructure_demand),
    drafts_share: (row) => decimalValue(row.drafts?.share_pct),
  });
  return (
    <section aria-labelledby="capacity-regions" data-testid="capacity-regions">
      <h3 id="capacity-regions">The demand of each region</h3>
      <p className="hint">
        The balance is of the whole operations team, whose tools and services serve every region: no
        supply is divided among the regions. This says where the work is. A region holds what is
        beneath it, so the regions at the top and the items that are nowhere add up to the whole.
      </p>
      <div className="scroll">
        <table data-testid="demand-by-region">
          <caption className="visually-hidden">
            The demand of each region, without the drafts and with them
          </caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="path">
                Region
              </SortTh>
              <SortTh sort={sorting} column="weight" className="number">
                Support weight
              </SortTh>
              <SortTh sort={sorting} column="demand" className="number">
                Infrastructure demand
              </SortTh>
              <SortTh sort={sorting} column="share" className="number">
                Share
              </SortTh>
              <SortTh sort={sorting} column="drafts_weight" className="number">
                Support weight with drafts
              </SortTh>
              <SortTh sort={sorting} column="drafts_demand" className="number">
                Demand with drafts
              </SortTh>
              <SortTh sort={sorting} column="drafts_share" className="number">
                Share with drafts
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <RegionLine key={row.key} row={row} indent={sorting.state === null} />
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No item carries a support weight.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RegionLine({ row, indent }: { row: RegionRow; indent: boolean }) {
  const cells = (region: RegionRow["active"], which: string) => (
    <>
      <td className="number" data-testid={`${which}-weight`} data-value={region?.support_weight}>
        {measureText(region?.support_weight, "weight")}
      </td>
      <td className="number" data-testid={`${which}-demand`}>
        {measureText(region?.infrastructure_demand, "units")}
      </td>
      <td className="number" data-testid={`${which}-share`} data-value={region?.share_pct ?? ""}>
        {measureText(region?.share_pct, "percent")}
      </td>
    </>
  );
  return (
    <tr data-region={row.path ?? ""} data-depth={row.depth}>
      <th
        scope="row"
        className={indent && row.depth > 0 ? `tree-depth-${Math.min(row.depth, 9)}` : undefined}
      >
        {row.path === null ? (
          <span className="muted">Nowhere: items with no location in force</span>
        ) : row.key ? (
          <Link to={placePath("region", row.key)}>{row.path}</Link>
        ) : (
          row.path
        )}
      </th>
      {cells(row.active, "active")}
      {cells(row.drafts, "drafts")}
    </tr>
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
