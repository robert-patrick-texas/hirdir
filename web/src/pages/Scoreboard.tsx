import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { saveFile } from "../components/grid/save";
import { HealthMark } from "../components/Health";
import { OperatorMark } from "../components/Operator";
import { Problem } from "../components/Problem";
import { ReportsNav } from "../components/ReportsNav";
import { type ItemView, ItemViewForm, paramsOfView, viewOfParams } from "../components/ViewForm";
import { plural } from "../lib/format";
import { HEALTHS } from "../lib/health";
import { type Loaded, useLoad, useTitle } from "../lib/hooks";
import { markOf } from "../lib/operators";
import { placePath } from "../lib/places";
import {
  operatorCondition,
  operatorOfRow,
  operatorsCsv,
  ranked,
  rowItemsPath,
  type ScoreRow,
  share,
  shareText,
  siteCondition,
  sitesCsv,
  underOpenLabels,
} from "../lib/scoreboard";
import { amountText, countText } from "../lib/summary";

/** The query of the summary for a view, by one thing, with the operators of each row. */
function scoreQuery(view: ItemView, by: "operator" | "site") {
  const filter = view.filter.trim();
  return {
    by,
    operators: true,
    ...(filter === "" ? {} : { filter }),
    ...(view.includeArchived ? { include_archived: true } : {}),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
}

/** Have the browser save a table as a CSV file, made from what the page holds. */
function saveCsv(text: string, name: string) {
  saveFile(new Blob([text], { type: "text/csv;charset=utf-8" }), name);
}

/** The measures every row of the scoreboard has, as cells. */
function Measures({ row }: { row: ScoreRow }) {
  return (
    <>
      <td className="number" data-measure="components">
        {countText(row.component_count)}
      </td>
      <td className="number" data-measure="nodes">
        {countText(row.managed_node_count)}
      </td>
      <td className="number" data-measure="items">
        {countText(row.items)}
      </td>
      <td className="number" data-measure="weight">
        {amountText(row.support_weight)}
      </td>
    </>
  );
}

/** A link to the items of a row in the grid, or nothing when the view cannot be added to. */
function ItemsLink({ view, condition }: { view: ItemView; condition: string }) {
  const path = rowItemsPath(view.filter, condition);
  return path ? <Link to={path}>items</Link> : null;
}

/**
 * Reports → Scoreboard: who looks after how much, and where. The operators, each with
 * what it is in force for, the most support weight first, with what nobody is assigned
 * to and what is under an open label; and the sites likewise, each with the operators
 * involved there. It is the summary by operator and by site, for a view of the items,
 * which is in the address of the page. It holds no money.
 */
export function Scoreboard() {
  useTitle("Scoreboard");
  const [params, setParams] = useSearchParams();
  const view = viewOfParams(params);
  const operatorsQuery = scoreQuery(view, "operator");
  const sitesQuery = scoreQuery(view, "site");
  const operators = useLoad(`score ${JSON.stringify(operatorsQuery)}`, (signal) =>
    api.request("get", "/api/v1/reports/summary", { query: operatorsQuery, signal }),
  );
  const sites = useLoad(`score ${JSON.stringify(sitesQuery)}`, (signal) =>
    api.request("get", "/api/v1/reports/summary", { query: sitesQuery, signal }),
  );

  return (
    <>
      <ReportsNav />
      <h1>Scoreboard</h1>
      <p>
        Who looks after how much, and where: the operators in force for the items in view, each with
        its components, managed nodes and support weight, the most support weight first, and the
        sites in the same way, each with the operators involved there. Every item the filter keeps
        is counted, major and minor. The counts by owner, state and the rest are in the{" "}
        <Link to="/reports">summary</Link>.
      </p>
      <ItemViewForm
        key={view.filter}
        view={view}
        onShow={(next) => setParams(paramsOfView(next))}
        label="Filter"
        hint="The filter of the item list: field:op:value, as in tags:has:refresh-2030. Blank is every item."
      />
      <OperatorsBoard view={view} summary={operators} />
      <SitesBoard view={view} summary={sites} />
    </>
  );
}

type Summary = Loaded<Schemas["SummaryOut"]>;

/** The operators, the one with the most support weight first, and what nobody is assigned to. */
function OperatorsBoard({ view, summary }: { view: ItemView; summary: Summary }) {
  const data = summary.data;
  const { rows, blank } = ranked(data?.rows);
  const whole = data?.totals.support_weight ?? "0";
  const open = underOpenLabels(rows);
  const openItems = rowItemsPath(view.filter, "operator.is_open:eq:true");

  return (
    <section aria-labelledby="score-operators">
      <h2 id="score-operators">Operators</h2>
      <Problem error={summary.error} />
      {summary.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <div className="scroll">
            <table data-testid="score-operators">
              <caption className="visually-hidden">
                The operators in force for the items in view, the most support weight first, each
                with its components, managed nodes, items, support weight and share
              </caption>
              <thead>
                <tr>
                  <th scope="col">Operator</th>
                  <th scope="col" className="number">
                    Components
                  </th>
                  <th scope="col" className="number">
                    Managed nodes
                  </th>
                  <th scope="col" className="number">
                    Items
                  </th>
                  <th scope="col" className="number">
                    Support weight
                  </th>
                  <th scope="col">Share of the weight</th>
                  {HEALTHS.map((health) => (
                    <th scope="col" className="number" key={health.value}>
                      <HealthMark value={health.value} />
                    </th>
                  ))}
                  <th scope="col">In the grid</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const mark = operatorOfRow(row);
                  return (
                    <tr key={row.key} data-operator={row.key} data-label={mark?.label ?? ""}>
                      <th scope="row">
                        {mark ? <OperatorMark mark={mark} withPerson /> : row.label}
                      </th>
                      <Measures row={row} />
                      <ShareCell part={row.support_weight} whole={whole} of={mark?.label ?? ""} />
                      {HEALTHS.map((health) => (
                        <td className="number" key={health.value} data-health={health.value}>
                          {countText(row.by_health[health.value])}
                        </td>
                      ))}
                      <td>
                        <ItemsLink view={view} condition={operatorCondition(row.key)} />
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={11} className="muted">
                      No item in view has an operator.
                    </td>
                  </tr>
                )}
              </tbody>
              {blank && (
                <tfoot>
                  <tr data-operator="" data-testid="score-nobody">
                    <th scope="row" className="tree-count tree-count-first">
                      Nobody is assigned
                    </th>
                    <td className="number tree-count tree-count-first" data-measure="components">
                      {countText(blank.component_count)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="nodes">
                      {countText(blank.managed_node_count)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="items">
                      {countText(blank.items)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="weight">
                      {amountText(blank.support_weight)}
                    </td>
                    <td className="tree-count tree-count-first">
                      {shareText(blank.support_weight, whole)}
                    </td>
                    {HEALTHS.map((health) => (
                      <td className="number tree-count tree-count-first" key={health.value}>
                        {countText(blank.by_health[health.value])}
                      </td>
                    ))}
                    <td className="tree-count tree-count-first">
                      <ItemsLink view={view} condition={operatorCondition(null)} />
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <p data-testid="score-open" data-labels={open.labels}>
            {open.labels > 0 ? (
              <>
                Under {plural(open.labels, "label")} that nobody is behind for now:{" "}
                {plural(open.components, "component")}, {plural(open.items, "item")} and a support
                weight of {amountText(open.support_weight)}
                {openItems && (
                  <>
                    {" · "}
                    <Link to={openItems}>these items in the grid</Link>
                  </>
                )}
                .
              </>
            ) : (
              <span className="muted">No label in view is open.</span>
            )}
          </p>
          <p className="actions">
            <button
              type="button"
              disabled={rows.length === 0 && !blank}
              onClick={() =>
                saveCsv(operatorsCsv(rows, blank, whole), "hirdir-scoreboard-operators.csv")
              }
            >
              Export CSV
              <span className="visually-hidden"> of the operators</span>
            </button>
          </p>
          <p className="hint">
            An operator is in force for an item that is given it, or that has it from the item it is
            in, from its group or from where it is. The share is of the support weight of all items
            in view, {amountText(whole)}. A stack whose members have two operators is a managed node
            of both.
          </p>
        </>
      )}
    </section>
  );
}

/** A share of the view's support weight: the number, and a plain bar that says the same. */
function ShareCell({ part, whole, of }: { part: string; whole: string; of: string }) {
  const text = shareText(part, whole);
  return (
    <td data-measure="share" className="share">
      <span className="share-text">{text}</span>{" "}
      <meter
        min={0}
        max={100}
        value={share(part, whole) / 100}
        aria-label={`Share of the support weight under ${of}: ${text}`}
      />
    </td>
  );
}

/** The sites, the one with the most support weight first, each with the operators involved. */
function SitesBoard({ view, summary }: { view: ItemView; summary: Summary }) {
  const data = summary.data;
  const { rows, blank } = ranked(data?.rows);

  const involved = (row: ScoreRow) => (
    <ul className="plain-list involved" data-testid="involved">
      {(row.operators ?? []).map((operator) => {
        const mark = markOf(operator);
        return (
          <li key={operator.hid ?? ""} data-operator={operator.hid ?? ""}>
            {mark ? (
              <OperatorMark mark={mark} />
            ) : (
              <span className="muted">Nobody is assigned</span>
            )}
            <span className={mark ? undefined : "muted"}>
              {" "}
              · {plural(operator.component_count, "component")}, weight{" "}
              {amountText(operator.support_weight)}
            </span>
          </li>
        );
      })}
      {(row.operators ?? []).length === 0 && <li className="muted">—</li>}
    </ul>
  );

  return (
    <section aria-labelledby="score-sites">
      <h2 id="score-sites">Sites</h2>
      <Problem error={summary.error} />
      {summary.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <div className="scroll">
            <table data-testid="score-sites">
              <caption className="visually-hidden">
                The sites of the items in view, the most support weight first, each with its
                components, managed nodes, items, support weight and the operators involved
              </caption>
              <thead>
                <tr>
                  <th scope="col">Site</th>
                  <th scope="col" className="number">
                    Components
                  </th>
                  <th scope="col" className="number">
                    Managed nodes
                  </th>
                  <th scope="col" className="number">
                    Items
                  </th>
                  <th scope="col" className="number">
                    Support weight
                  </th>
                  <th scope="col">Operators involved</th>
                  <th scope="col">In the grid</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key} data-site={row.key} data-path={row.label ?? ""}>
                    <th scope="row">
                      {row.key ? (
                        <Link to={placePath("site", row.key)}>{row.label ?? row.key}</Link>
                      ) : (
                        row.label
                      )}
                    </th>
                    <Measures row={row} />
                    <td>{involved(row)}</td>
                    <td>
                      <ItemsLink view={view} condition={siteCondition(row.key)} />
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
                      No item in view is at a site.
                    </td>
                  </tr>
                )}
              </tbody>
              {blank && (
                <tfoot>
                  <tr data-site="" data-testid="score-nowhere">
                    <th scope="row" className="tree-count tree-count-first">
                      Nowhere: no location
                    </th>
                    <td className="number tree-count tree-count-first" data-measure="components">
                      {countText(blank.component_count)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="nodes">
                      {countText(blank.managed_node_count)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="items">
                      {countText(blank.items)}
                    </td>
                    <td className="number tree-count tree-count-first" data-measure="weight">
                      {amountText(blank.support_weight)}
                    </td>
                    <td className="tree-count tree-count-first">{involved(blank)}</td>
                    <td className="tree-count tree-count-first">
                      <ItemsLink view={view} condition={siteCondition(null)} />
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <p className="actions">
            <button
              type="button"
              disabled={rows.length === 0 && !blank}
              onClick={() => saveCsv(sitesCsv(rows, blank), "hirdir-scoreboard-sites.csv")}
            >
              Export CSV
              <span className="visually-hidden"> of the sites</span>
            </button>
          </p>
          <p className="hint">
            A site is named by its path, and is the way to its place under Geography. The operators
            involved are those in force for the items there, the one with the most support weight
            first, and what nobody is assigned to last.
          </p>
        </>
      )}
    </section>
  );
}
