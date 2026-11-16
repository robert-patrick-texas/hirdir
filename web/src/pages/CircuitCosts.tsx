// 0.8.0: Reports → Circuit costs, what circuits cost in one fiscal year (P-151).

import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api";
import { CheckField, SelectField, TextField } from "../components/Field";
import { Problem } from "../components/Problem";
import { ReportsNav } from "../components/ReportsNav";
import { SortTh } from "../components/SortTh";
import {
  CIRCUIT_COSTS_BY,
  type CircuitCostRow,
  type CircuitCosts,
  type CircuitCostsView,
  circuitCostsByLabel,
  circuitCostsParams,
  circuitCostsQuery,
  circuitCostsRowLabel,
  circuitCostsView,
  circuitsPath,
  isCircuitCostsBy,
} from "../lib/circuitCosts";
import { parseShort } from "../lib/filter";
import { useLoad, useTitle } from "../lib/hooks";
import { fieldErrors } from "../lib/problems";
import { decimalValue } from "../lib/sort";
import { amountText, countText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";

// What to say beneath the rows of each grouping, where a circuit may be in more than one.
const ROWS_SAY: Readonly<Partial<Record<CircuitCosts["by"], string>>> = {
  carrier:
    "A cost line counts under the carrier that bills it, its own or the circuit's primary carrier, so a circuit is in the row of each carrier that bills any of it; the totals count each circuit once.",
  site: "A circuit counts at the site of the side its cost is assigned to, its A side unless it was switched to its Z side.",
  region:
    "A region is named by its path, and its row holds what counts at a site at or beneath it: a circuit is in the row of each region above its site, and the totals count it once.",
  group: "A circuit in several groups is in the row of each, and the totals count it once.",
  tag: "A circuit with several tags is in the row of each, and the totals count it once.",
};

/**
 * Reports → Circuit costs: for one fiscal year, the present one unless another is chosen,
 * and by carrier unless another grouping is, each row with its circuits, what the year
 * costs, and the monthly and annual figures on the day the report is of, the totals
 * beneath, and each row leading to its circuits in the circuit grid.
 */
export function CircuitCostsReport() {
  useTitle("Circuit costs");
  const [params, setParams] = useSearchParams();
  const view = circuitCostsView(params);
  const query = circuitCostsQuery(view);
  const report = useLoad(`circuit-costs ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/circuit-costs", { query, signal }),
  );
  const data = report.data;
  const refused = fieldErrors(report.error, ["filter", "fiscal_year", "by"]).shown;

  return (
    <>
      <ReportsNav />
      <h1>Circuit costs</h1>
      <p>
        What circuits cost in one fiscal year, as the carriers bill them: each cost line counts its
        monthly cost for every month of the year it is billed in, a whole month in full and a month
        the circuit is in service for only in part for its days. Beside the year&apos;s cost are the
        monthly figure on the day the report is of and twelve times that, the annual figure, as
        support costs are read.
      </p>
      <CostsForm
        key={`${view.filter} ${view.year}`}
        view={view}
        shown={data?.fiscal_year ?? null}
        refused={refused}
        onShow={(next) => setParams(circuitCostsParams(next))}
      />
      <Problem error={report.error} shown={["filter", "fiscal_year"]} />
      {report.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && <CostsTables report={data} includeDrafts={view.includeDrafts} />}
    </>
  );
}

interface CostsFormProps {
  view: CircuitCostsView;
  /** The fiscal year the report on show is of. */
  shown: number | null;
  refused: Readonly<Record<string, string>>;
  onShow: (view: CircuitCostsView) => void;
}

/** The year, the grouping, a filter of the circuit list and whether drafts count. */
function CostsForm({ view, shown, refused, onShow }: CostsFormProps) {
  const [year, setYear] = useState(view.year);
  const [filter, setFilter] = useState(view.filter);
  const [found, setFound] = useState<{ year?: string; filter?: string }>({});

  function submit(event: FormEvent) {
    event.preventDefault();
    const typedYear = year.trim();
    const typed = filter.trim();
    const wrong: { year?: string; filter?: string } = {};
    if (typedYear !== "" && !/^\d{4}$/.test(typedYear)) {
      wrong.year = "A year of four digits, as 2027, or blank for the present one.";
    }
    // The short form is read here as the server reads it; a tree as JSON is the server's.
    const parsed = typed.startsWith("{") ? null : parseShort(typed);
    if (parsed && !parsed.ok) wrong.filter = parsed.error;
    setFound(wrong);
    if (wrong.year || wrong.filter) return;
    onShow({ ...view, year: typedYear, filter: typed });
  }

  const step = (by: number) => {
    const from = view.year ? Number(view.year) : shown;
    if (from === null) return;
    onShow({ ...view, year: String(from + by) });
  };

  return (
    <form onSubmit={submit} className="stack" noValidate data-testid="circuit-costs-form">
      <div className="fields">
        <TextField
          label="Fiscal year"
          name="fiscal_year"
          value={year}
          onChange={setYear}
          inputMode="numeric"
          autoComplete="off"
          placeholder={shown === null ? "" : String(shown)}
          hint="Named for the calendar year it ends in. Blank: the one today is in."
          error={found.year || refused.fiscal_year}
        />
        <SelectField
          label="By"
          name="by"
          value={view.by}
          onChange={(next) => onShow({ ...view, by: isCircuitCostsBy(next) ? next : "carrier" })}
          hint="One row for each value. The circuits with none are in a row of their own."
          error={refused.by}
        >
          {CIRCUIT_COSTS_BY.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Filter"
          name="filter"
          type="search"
          value={filter}
          onChange={setFilter}
          autoComplete="off"
          hint="The filter of the circuit list: field:op:value, as in circuit_type:eq:internet. Retired circuits are among those it chooses: one disconnected in the year ran for part of it."
          error={found.filter || refused.filter}
        />
      </div>
      <div className="inline">
        <CheckField
          label="Include drafts"
          name="include_drafts"
          checked={view.includeDrafts}
          onChange={(on) => onShow({ ...view, includeDrafts: on })}
        />
      </div>
      <p className="actions">
        <button type="submit" className="primary">
          Apply
        </button>
        <button type="button" disabled={shown === null} onClick={() => step(-1)}>
          Year before
        </button>
        <button type="button" disabled={shown === null} onClick={() => step(1)}>
          Year after
        </button>
        <button
          type="button"
          disabled={!view.year}
          onClick={() => {
            setYear("");
            onShow({ ...view, year: "" });
          }}
        >
          The present year
        </button>
      </p>
    </form>
  );
}

/** The rows of the report, sorted by their headers, and the totals beneath. */
function CostsTables({ report, includeDrafts }: { report: CircuitCosts; includeDrafts: boolean }) {
  const by = report.by;
  const label = (row: CircuitCostRow) => circuitCostsRowLabel(by, row);
  const sorting = useSorting(report.rows, {
    name: label,
    circuits: (row) => row.circuits,
    cost: (row) => decimalValue(row.cost),
    monthly_cost: (row) => decimalValue(row.monthly_cost),
    annual_cost: (row) => decimalValue(row.annual_cost),
  });
  const money = report.currency ? ` (${report.currency})` : "";
  const totalsPath = circuitsPath(report.totals, includeDrafts, true);
  return (
    <section
      aria-labelledby="circuit-costs-rows"
      data-testid="circuit-costs"
      data-fiscal-year={report.fiscal_year}
      data-by={by}
    >
      <h2 id="circuit-costs-rows">
        Fiscal year {report.fiscal_year}, by {circuitCostsByLabel(by).toLowerCase()}
      </h2>
      <p className="hint" data-testid="circuit-costs-period">
        From {report.starts_on} to {report.ends_on}. The monthly figure is what is billed for a
        month on {report.as_of}: today for the present year, the last day of a past one and the
        first day of one to come.
      </p>
      <div className="scroll">
        <table data-testid="circuit-costs-rows">
          <caption className="visually-hidden">
            What circuits cost in fiscal year {report.fiscal_year}, one row for each{" "}
            {circuitCostsByLabel(by).toLowerCase()}, and the totals
          </caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="name">
                {circuitCostsByLabel(by)}
              </SortTh>
              <SortTh sort={sorting} column="circuits" className="number">
                Circuits
              </SortTh>
              <SortTh sort={sorting} column="cost" className="number">
                Cost of the year{money}
              </SortTh>
              <SortTh sort={sorting} column="monthly_cost" className="number">
                Monthly{money}
              </SortTh>
              <SortTh sort={sorting} column="annual_cost" className="number">
                Annual{money}
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <CostRow
                key={row.key ?? ""}
                row={row}
                name={label(row)}
                path={circuitsPath(row, includeDrafts)}
              />
            ))}
            {report.rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No circuit was in service in the year.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr data-testid="circuit-costs-totals" data-key="totals">
              <th scope="row">
                {totalsPath ? <Link to={totalsPath}>Totals</Link> : "Totals"}
                <span className="muted"> · each circuit once</span>
              </th>
              <td
                className="number"
                data-testid="cost-circuits"
                data-value={report.totals.circuits}
              >
                {countText(report.totals.circuits)}
              </td>
              <td className="number" data-testid="cost-year" data-value={report.totals.cost}>
                {amountText(report.totals.cost)}
              </td>
              <td
                className="number"
                data-testid="cost-monthly"
                data-value={report.totals.monthly_cost}
              >
                {amountText(report.totals.monthly_cost)}
              </td>
              <td
                className="number"
                data-testid="cost-annual"
                data-value={report.totals.annual_cost}
              >
                {amountText(report.totals.annual_cost)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {ROWS_SAY[by] && <p className="hint">{ROWS_SAY[by]}</p>}
      <p className="hint">
        A row leads to its circuits in the circuit grid, retired ones among them, greyed: a circuit
        that was disconnected during the year counts for the days it was in service. Every sum is
        worked out exactly and rounded to two places once.
      </p>
    </section>
  );
}

function CostRow({ row, name, path }: { row: CircuitCostRow; name: string; path: string | null }) {
  return (
    <tr data-key={row.key ?? ""} data-label={name}>
      <th scope="row" className={row.key === null ? "muted" : undefined}>
        {path ? <Link to={path}>{name}</Link> : name}
      </th>
      <td className="number" data-testid="cost-circuits" data-value={row.circuits}>
        {countText(row.circuits)}
      </td>
      <td className="number" data-testid="cost-year" data-value={row.cost}>
        {amountText(row.cost)}
      </td>
      <td className="number" data-testid="cost-monthly" data-value={row.monthly_cost}>
        {amountText(row.monthly_cost)}
      </td>
      <td className="number" data-testid="cost-annual" data-value={row.annual_cost}>
        {amountText(row.annual_cost)}
      </td>
    </tr>
  );
}
