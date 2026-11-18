// What the portfolio of a vendor counts, as the server answers it: the totals, the four
// kinds, the models with their dates and their cover, the agreements, the contracts and
// the capacity lines. Nothing is counted here. Each table holds all of its rows, and is
// sorted by its headers in the browser.

import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Schemas } from "../api/client";
import { capacityLinePath, measureText, SIDES } from "../lib/capacity";
import { agreementPath, CONTRACT_STATUSES, contractPath, periodText } from "../lib/contracts";
import { effectiveText } from "../lib/effective";
import { choiceLabel, optionLabel, RECORD_STATUSES } from "../lib/options";
import { dateValue, decimalValue } from "../lib/sort";
import { amountText, countText, kindLabel } from "../lib/summary";
import { type SortControl, useSorting } from "../lib/useSorting";
import { useFirstRows } from "./FirstRows";
import { SortTh } from "./SortTh";

type Portfolio = Schemas["PortfolioOut"];
type Measures = Schemas["PortfolioMeasures"];
type Choice = Schemas["ChoiceOut"];

function Dash() {
  return <span className="muted">—</span>;
}

/** What a row of the kinds and of the models is sorted by under each measure. */
const MEASURE_SORTS = {
  items: (row: Measures) => row.items,
  components: (row: Measures) => row.component_count,
  weight: (row: Measures) => decimalValue(row.support_weight),
  value: (row: Measures) => decimalValue(row.est_value),
  cost: (row: Measures) => decimalValue(row.annual_support_cost),
  covered: (row: Measures) => row.covered,
  uncovered: (row: Measures) => row.uncovered,
};

function MeasureHeads({ sort, money }: { sort: SortControl; money: string }) {
  return (
    <>
      <SortTh sort={sort} column="items" className="number">
        Items
      </SortTh>
      <SortTh sort={sort} column="components" className="number">
        Components
      </SortTh>
      <SortTh sort={sort} column="weight" className="number">
        Support weight
      </SortTh>
      <SortTh sort={sort} column="value" className="number">
        Estimated value{money}
      </SortTh>
      <SortTh sort={sort} column="cost" className="number">
        Annual support cost{money}
      </SortTh>
      <SortTh sort={sort} column="covered" className="number">
        Covered
      </SortTh>
      <SortTh sort={sort} column="uncovered" className="number">
        Not covered
      </SortTh>
    </>
  );
}

function MeasureCells({ row }: { row: Measures }) {
  return (
    <>
      <td className="number" data-measure="items">
        {countText(row.items)}
      </td>
      <td className="number" data-measure="components">
        {countText(row.component_count)}
      </td>
      <td className="number" data-measure="weight">
        {amountText(row.support_weight)}
      </td>
      <td className="number" data-measure="value">
        {amountText(row.est_value)}
      </td>
      <td className="number" data-measure="cost">
        {amountText(row.annual_support_cost)}
      </td>
      <td className="number" data-measure="covered">
        {countText(row.covered)}
      </td>
      <td className="number" data-measure="uncovered">
        {countText(row.uncovered)}
      </td>
    </>
  );
}

interface PortfolioCountsProps {
  portfolio: Portfolio;
  /** The installation's currency, as a heading names it after an amount. */
  money: string;
  /** The editable lists, to call a type by its label. */
  choices: readonly Choice[] | undefined;
  /** What stands after the models and before the agreements: the vendor's items (P-211). */
  children?: ReactNode;
}

/**
 * What a portfolio counts: the totals, the four kinds, the models, the agreements, the
 * contracts and the capacity lines, each table sorted by its headers in the browser,
 * since it holds all of its rows. The models show the first twenty until Show all.
 */
export function PortfolioCounts({ portfolio, money, choices, children }: PortfolioCountsProps) {
  const { totals } = portfolio;
  return (
    <>
      <dl className="totals" data-testid="portfolio-totals">
        <div>
          <dt>Items, major and minor</dt>
          <dd data-testid="portfolio-items">{countText(totals.items)}</dd>
        </div>
        <div>
          <dt>Components</dt>
          <dd data-testid="portfolio-components">{countText(totals.component_count)}</dd>
        </div>
        <div>
          <dt>Support weight</dt>
          <dd data-testid="portfolio-weight">{amountText(totals.support_weight)}</dd>
        </div>
        <div>
          <dt>Estimated value{money}</dt>
          <dd data-testid="portfolio-value">{amountText(totals.est_value)}</dd>
        </div>
        <div>
          <dt>Annual support cost{money}</dt>
          <dd data-testid="portfolio-cost">{amountText(totals.annual_support_cost)}</dd>
        </div>
        <div>
          <dt>Covered</dt>
          <dd data-testid="portfolio-covered">{countText(totals.covered)}</dd>
        </div>
        <div>
          <dt>Not covered</dt>
          <dd data-testid="portfolio-uncovered">{countText(totals.uncovered)}</dd>
        </div>
      </dl>
      <Kinds kinds={portfolio.kinds} money={money} />
      <Models models={portfolio.models} money={money} choices={choices} />
      {/* 0.9.6: what stands between the models and the agreements: the vendor's items (P-211). */}
      {children}
      <Agreements agreements={portfolio.agreements} />
      <Contracts contracts={portfolio.contracts} vendorHid={portfolio.vendor.hid} money={money} />
      <CapacityLines lines={portfolio.capacity_lines} money={money} />
    </>
  );
}

function Kinds({ kinds, money }: { kinds: Portfolio["kinds"]; money: string }) {
  const sorting = useSorting(kinds, { kind: (row) => kindLabel(row.kind), ...MEASURE_SORTS });
  return (
    <div className="scroll">
      <table data-testid="portfolio-kinds">
        <caption>The four kinds, also one the vendor has nothing of</caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="kind">
              Kind
            </SortTh>
            <MeasureHeads sort={sorting} money={money} />
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((row) => (
            <tr
              key={row.kind}
              data-kind={row.kind}
              className={row.items === 0 ? "muted" : undefined}
            >
              <th scope="row">{kindLabel(row.kind)}</th>
              <MeasureCells row={row} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ModelsProps {
  models: Portfolio["models"];
  money: string;
  choices: readonly Choice[] | undefined;
}

function Models({ models, money, choices }: ModelsProps) {
  const sorting = useSorting(models, {
    pid: (row) => row.pid,
    model: (row) => row.model_name,
    kind: (row) => kindLabel(row.kind),
    type: (row) => choiceLabel(choices, "catalog_type", row.type),
    end_of_sale: (row) => dateValue(row.end_of_sale),
    end_of_sw_support: (row) => dateValue(row.end_of_sw_support),
    end_of_hw_support: (row) => dateValue(row.end_of_hw_support),
    ldos: (row) => dateValue(row.ldos),
    covered_until: (row) => dateValue(row.covered_until),
    ...MEASURE_SORTS,
  });
  // The first twenty, as the table is sorted, and Show all (P-211, as P-196): a model
  // with no date sorts after those with one, whichever way.
  const first = useFirstRows(sorting.rows, "models");
  return (
    <>
      <h3 id="portfolio-models">Models</h3>
      {models.length === 0 ? (
        <p className="muted">No model of this vendor has an item in view.</p>
      ) : (
        <div className="scroll">
          <table data-testid="portfolio-models">
            <caption>
              One row for each model that has items in view, with the dates of the model. Covered
              until is the soonest day the cover of one of its covered items runs out.
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="pid">
                  PID
                </SortTh>
                <SortTh sort={sorting} column="model">
                  Model
                </SortTh>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="type">
                  Type
                </SortTh>
                <SortTh sort={sorting} column="end_of_sale">
                  End of sale
                </SortTh>
                <SortTh sort={sorting} column="end_of_sw_support">
                  End of software support
                </SortTh>
                <SortTh sort={sorting} column="end_of_hw_support">
                  End of hardware support
                </SortTh>
                <SortTh sort={sorting} column="ldos">
                  LDoS
                </SortTh>
                <MeasureHeads sort={sorting} money={money} />
                <SortTh sort={sorting} column="covered_until">
                  Covered until
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {first.shown.map((row) => (
                <tr key={row.catalog_entry_hid} data-pid={row.pid}>
                  <th scope="row">
                    <Link to={`/catalog/${encodeURIComponent(row.catalog_entry_hid)}`}>
                      {row.pid}
                    </Link>
                  </th>
                  <td>{row.model_name || <Dash />}</td>
                  <td>{kindLabel(row.kind)}</td>
                  <td>{choiceLabel(choices, "catalog_type", row.type) || <Dash />}</td>
                  <td className="nowrap">{row.end_of_sale ?? <Dash />}</td>
                  <td className="nowrap">{row.end_of_sw_support ?? <Dash />}</td>
                  <td className="nowrap">{row.end_of_hw_support ?? <Dash />}</td>
                  <td className="nowrap" data-testid="model-ldos">
                    {row.ldos ?? <Dash />}
                  </td>
                  <MeasureCells row={row} />
                  <td className="nowrap" data-testid="model-covered-until">
                    {row.covered_until ?? <Dash />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {first.more}
    </>
  );
}

function Agreements({ agreements }: { agreements: Portfolio["agreements"] }) {
  const sorting = useSorting(agreements, {
    name: (row) => row.name,
    number: (row) => row.number,
    status: (row) => optionLabel(CONTRACT_STATUSES, row.status),
    starts: (row) => dateValue(row.starts_on),
    ends: (row) => dateValue(row.ends_on),
    contracts: (row) => row.contracts,
  });
  return (
    <>
      <h3 id="portfolio-agreements">Support agreements</h3>
      {agreements.length === 0 ? (
        <p className="muted">There is no support agreement with this vendor.</p>
      ) : (
        <div className="scroll">
          <table data-testid="portfolio-agreements">
            <caption className="visually-hidden">The support agreements with this vendor</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Agreement
                </SortTh>
                <SortTh sort={sorting} column="number">
                  Number
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="starts">
                  Starts
                </SortTh>
                <SortTh sort={sorting} column="ends">
                  Ends
                </SortTh>
                <SortTh sort={sorting} column="contracts" className="number">
                  Contracts
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => (
                <tr key={row.hid} data-agreement={row.name}>
                  <th scope="row">
                    <Link to={agreementPath(row.hid)}>{row.name}</Link>
                    {row.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, row.record_status)}
                      </span>
                    )}
                  </th>
                  <td>{row.number || <Dash />}</td>
                  <td>{optionLabel(CONTRACT_STATUSES, row.status)}</td>
                  <td className="nowrap">{row.starts_on ?? <Dash />}</td>
                  <td className="nowrap">{row.ends_on ?? <Dash />}</td>
                  <td className="number">{countText(row.contracts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

interface ContractsProps {
  contracts: Portfolio["contracts"];
  vendorHid: string;
  money: string;
}

function Contracts({ contracts, vendorHid, money }: ContractsProps) {
  const role = (row: Portfolio["contracts"][number]) =>
    row.vendor_hid === vendorHid ? "Provides it" : "Bought through it";
  const sorting = useSorting(contracts, {
    number: (row) => row.number,
    role,
    agreement: (row) => row.agreement?.name,
    status: (row) => optionLabel(CONTRACT_STATUSES, row.status),
    starts: (row) => dateValue(effectiveText(row.effective.starts_on)),
    ends: (row) => dateValue(effectiveText(row.effective.ends_on)),
    covered: (row) => row.covered_items,
    cost: (row) => decimalValue(row.annual_cost),
  });
  return (
    <>
      <h3 id="portfolio-contracts">Contracts</h3>
      {contracts.length === 0 ? (
        <p className="muted">This vendor provides no contract, and none was bought through it.</p>
      ) : (
        <div className="scroll">
          <table data-testid="portfolio-contracts">
            <caption>
              The contracts the vendor provides or that were bought through it, each with how many
              items it covers today. A contract&apos;s annual cost is its own total, and is added to
              nothing
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="number">
                  Number
                </SortTh>
                <SortTh sort={sorting} column="role">
                  The vendor
                </SortTh>
                <SortTh sort={sorting} column="agreement">
                  Agreement
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="starts">
                  Starts
                </SortTh>
                <SortTh sort={sorting} column="ends">
                  Ends
                </SortTh>
                <SortTh sort={sorting} column="covered" className="number">
                  Items covered
                </SortTh>
                <SortTh sort={sorting} column="cost" className="number">
                  Annual cost{money}
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => (
                <tr key={row.hid} data-contract={row.number}>
                  <th scope="row">
                    <Link to={contractPath(row.hid)}>{row.number}</Link>
                    {row.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, row.record_status)}
                      </span>
                    )}
                  </th>
                  <td>{role(row)}</td>
                  <td>
                    {row.agreement ? (
                      <Link className="value-link" to={agreementPath(row.agreement.hid)}>
                        {row.agreement.name}
                      </Link>
                    ) : (
                      <span className="muted">Stands by itself</span>
                    )}
                  </td>
                  <td>{optionLabel(CONTRACT_STATUSES, row.status)}</td>
                  <td
                    className={
                      row.effective.starts_on.source === "agreement" ? "nowrap inherited" : "nowrap"
                    }
                  >
                    {effectiveText(row.effective.starts_on) || <Dash />}
                  </td>
                  <td
                    className={
                      row.effective.ends_on.source === "agreement" ? "nowrap inherited" : "nowrap"
                    }
                    title={periodText(row.effective.starts_on.value, row.effective.ends_on.value)}
                  >
                    {effectiveText(row.effective.ends_on) || <Dash />}
                  </td>
                  <td className="number">{countText(row.covered_items)}</td>
                  <td className="number">{amountText(row.annual_cost) || <Dash />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function CapacityLines({ lines, money }: { lines: Portfolio["capacity_lines"]; money: string }) {
  const sorting = useSorting(lines, {
    name: (row) => row.name,
    side: (row) => optionLabel(SIDES, row.side),
    category: (row) => row.category_label,
    units: (row) => decimalValue(row.units),
    cost: (row) => decimalValue(row.annual_cost),
    counts: (row) => row.in_date && row.record_status === "active",
  });
  return (
    <>
      <h3 id="portfolio-capacity">Capacity lines</h3>
      {lines.length === 0 ? (
        <p className="muted">No capacity line names this vendor.</p>
      ) : (
        <div className="scroll">
          <table data-testid="portfolio-capacity">
            <caption className="visually-hidden">The capacity lines that name this vendor</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Line
                </SortTh>
                <SortTh sort={sorting} column="side">
                  Side
                </SortTh>
                <SortTh sort={sorting} column="category">
                  Category
                </SortTh>
                <SortTh sort={sorting} column="units" className="number">
                  Units
                </SortTh>
                <SortTh sort={sorting} column="cost" className="number">
                  Annual cost{money}
                </SortTh>
                <SortTh sort={sorting} column="counts">
                  Counts today
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => (
                <tr key={row.hid} data-line={row.name}>
                  <th scope="row">
                    <Link to={capacityLinePath(row.hid)}>{row.name}</Link>
                    {row.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, row.record_status)}
                      </span>
                    )}
                  </th>
                  <td>{optionLabel(SIDES, row.side)}</td>
                  <td>{row.category_label}</td>
                  <td className="number">{measureText(row.units, "units")}</td>
                  <td className="number">{amountText(row.annual_cost) || <Dash />}</td>
                  <td>{row.in_date && row.record_status === "active" ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
