import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { saveFile } from "../components/grid/save";
import { HealthMark } from "../components/Health";
import { OperatorMark } from "../components/Operator";
import { Problem } from "../components/Problem";
import { Bar, Counted, RankCell, RankHead, RankNote } from "../components/Ranked";
import { ReportsNav } from "../components/ReportsNav";
import { SortTh } from "../components/SortTh";
import { type ItemView, ItemViewForm, paramsOfView, viewOfParams } from "../components/ViewForm";
import { itemsPath } from "../lib/filter";
import { plural } from "../lib/format";
import { groupTypeLabel } from "../lib/groups";
import { HEALTHS } from "../lib/health";
import { type Loaded, useLoad, useTitle } from "../lib/hooks";
import { markOf } from "../lib/operators";
import { placePath } from "../lib/places";
import { namedFile, useSite } from "../lib/product";
import { type Ranking, ranking } from "../lib/rank";
import {
  BY_WEIGHT,
  board,
  groupCondition,
  groupsCsv,
  operatorCondition,
  operatorOfRow,
  operatorsCsv,
  rowItemsPath,
  rowName,
  type ScoreRow,
  SPLIT,
  scoreColumns,
  scoreCounts,
  share,
  shareText,
  siteCondition,
  sitesCsv,
  splitPath,
  underOpenLabels,
} from "../lib/scoreboard";
import type { SortState } from "../lib/sort";
import { amountText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";

// What the blank row of each table is called: it is a row like the others.
const NOBODY = "Nobody is assigned";
const NOWHERE = "Nowhere: no location";
const NO_GROUP = "In no group";

/** The query of the summary for a view, by one thing, with the operators of each row. */
function scoreQuery(view: ItemView, by: "operator" | "site" | "group") {
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

/**
 * The measures every row of the scoreboard has, as cells, each with its bar. `items`, where
 * given, is where the count of items leads: the list of exactly those items.
 */
function Measures({
  row,
  ranked,
  items,
}: {
  row: ScoreRow;
  ranked: Ranking<ScoreRow>;
  items?: string | null;
}) {
  return (
    <>
      <td className="number" data-measure="components">
        <Counted ranking={ranked} column="components" row={row} />
      </td>
      <td className="number" data-measure="nodes">
        <Counted ranking={ranked} column="nodes" row={row} />
      </td>
      <td className="number" data-measure="items">
        <Counted ranking={ranked} column="items" row={row} href={items} />
      </td>
      <td className="number" data-measure="weight">
        <Counted ranking={ranked} column="weight" row={row} />
      </td>
    </>
  );
}

/** Rank a scoreboard by the count it is sorted by, and by support weight at first. */
function rankBoard(sorting: { rows: ScoreRow[]; state: SortState | null }, whole: string) {
  return ranking(sorting.rows, sorting.state, scoreCounts(whole), {
    fallback: "weight",
    blank: (row) => row.key === null,
  });
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
  // 0.9.4: the device groups, ranked as the operators are (P-178).
  const groupsQuery = scoreQuery(view, "group");
  const groups = useLoad(`score ${JSON.stringify(groupsQuery)}`, (signal) =>
    api.request("get", "/api/v1/reports/summary", { query: groupsQuery, signal }),
  );

  return (
    <>
      <ReportsNav />
      <h1>Scoreboard</h1>
      <p>
        Who looks after how much, and where: the operators in force for the items in view, each with
        its components, managed nodes and support weight, the most support weight first, and how its
        items have it; the device groups in the same way, each with what is under it; and the sites,
        each with the operators involved there. Each table is ranked and sorted by any column of
        counts by its header, and a file that is saved follows the order on show. Every item the
        filter keeps is counted, major and minor. The counts by owner, state and the rest are in the{" "}
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
      <GroupsBoard view={view} summary={groups} />
      <SitesBoard view={view} summary={sites} />
    </>
  );
}

type Summary = Loaded<Schemas["SummaryOut"]>;

/** The operators, the one with the most support weight first, and what nobody is assigned to. */
function OperatorsBoard({ view, summary }: { view: ItemView; summary: Summary }) {
  const data = summary.data;
  const { productName } = useSite();
  // Every row, what nobody is assigned to among them, by support weight at first: the
  // headers sort them by any column, and the file that is saved follows the order on show.
  const sorting = useSorting(board(data?.rows), scoreColumns(NOBODY), { initial: BY_WEIGHT });
  const rows = sorting.rows;
  const whole = data?.totals.support_weight ?? "0";
  const ranked = rankBoard(sorting, whole);
  const open = underOpenLabels(rows.filter((row) => row.key !== null));
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
                The operators in force for the items in view, and what nobody is assigned to, each
                with its components, managed nodes, items, support weight and share: by support
                weight at first, and sorted by any column by its header
              </caption>
              <thead>
                <tr>
                  <RankHead ranking={ranked} />
                  <SortTh sort={sorting} column="name">
                    Operator
                  </SortTh>
                  <SortTh sort={sorting} column="components" className="number">
                    Components
                  </SortTh>
                  <SortTh sort={sorting} column="nodes" className="number">
                    Managed nodes
                  </SortTh>
                  <SortTh sort={sorting} column="items" className="number">
                    Items
                  </SortTh>
                  <SortTh sort={sorting} column="weight" className="number">
                    Support weight
                  </SortTh>
                  <SortTh sort={sorting} column="share">
                    Share of the weight
                  </SortTh>
                  {SPLIT.map((part) => (
                    <SortTh
                      sort={sorting}
                      column={part.column}
                      className="number"
                      key={part.column}
                    >
                      {part.header}
                    </SortTh>
                  ))}
                  {HEALTHS.map((health) => (
                    <SortTh
                      sort={sorting}
                      column={health.value}
                      className="number"
                      key={health.value}
                    >
                      <HealthMark value={health.value} />
                    </SortTh>
                  ))}
                  <th scope="col">In the grid</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const mark = operatorOfRow(row);
                  return (
                    <tr
                      key={row.key ?? ""}
                      data-operator={row.key ?? ""}
                      data-label={mark?.label ?? ""}
                      {...(row.key === null ? { "data-testid": "score-nobody" } : {})}
                    >
                      <RankCell ranking={ranked} row={row} />
                      <th scope="row">
                        {mark ? <OperatorMark mark={mark} withPerson /> : rowName(row, NOBODY)}
                      </th>
                      <Measures row={row} ranked={ranked} />
                      <ShareCell
                        part={row.support_weight}
                        whole={whole}
                        figure={ranked.figure("share")}
                      />
                      {SPLIT.map((part) => (
                        <td className="number" key={part.column} data-measure={part.column}>
                          <Counted
                            ranking={ranked}
                            column={part.column}
                            row={row}
                            href={splitPath(view, row.key, part.column)}
                          />
                        </td>
                      ))}
                      {HEALTHS.map((health) => (
                        <td className="number" key={health.value} data-health={health.value}>
                          <Counted ranking={ranked} column={health.value} row={row} />
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
                    <td colSpan={12 + SPLIT.length} className="muted">
                      No item is in view.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <RankNote ranking={ranked} fallback="support weight" blank={NOBODY} />
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
              disabled={rows.length === 0}
              onClick={() =>
                saveCsv(
                  operatorsCsv(rows, whole),
                  namedFile(productName, "scoreboard-operators.csv"),
                )
              }
            >
              Export CSV
              <span className="visually-hidden"> of the operators</span>
            </button>
          </p>
          <p className="hint">
            An operator is in force for an item that is given it, or that has it from the item it is
            in, from its group or from where it is: Own, From item, From group and From place say
            how many of its items have it each way, and add up to its items. Groups given and Places
            given are the groups and the places given it as their own. The first four lead to their
            items, and Groups given to the groups; the places given are no one list. The share is of
            the support weight of all items in view, {amountText(whole)}. A stack whose members have
            two operators is a managed node of both.
          </p>
        </>
      )}
    </section>
  );
}

/**
 * A share of the view's support weight: the number, and a bar beside it that says the
 * same, as long as the share is of the whole. The number is read, and the bar is not.
 */
function ShareCell({ part, whole, figure }: { part: string; whole: string; figure: number }) {
  return (
    <td data-measure="share" className="number share">
      <Bar
        share={share(part, whole) / 10000}
        text={shareText(part, whole)}
        figure={figure}
        figureClass="share-text"
      />
    </td>
  );
}

/**
 * The device groups, the one with the most support weight under it first, ranked as the
 * operators are, and the items under no group (P-178). A group holds its members, those of
 * every group nested in it at any depth and the minor items of all of them; each count of
 * its items leads to exactly those items, and its members to its own members.
 */
function GroupsBoard({ view, summary }: { view: ItemView; summary: Summary }) {
  const data = summary.data;
  const { productName } = useSite();
  const sorting = useSorting(board(data?.rows), scoreColumns(NO_GROUP), { initial: BY_WEIGHT });
  const rows = sorting.rows;
  const ranked = rankBoard(sorting, data?.totals.support_weight ?? "0");

  return (
    <section aria-labelledby="score-groups">
      <h2 id="score-groups">Groups</h2>
      <Problem error={summary.error} />
      {summary.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <div className="scroll">
            <table data-testid="score-groups">
              <caption className="visually-hidden">
                The device groups of the items in view, and the items in no group, each with its
                type, members, nested groups, the items, components, managed nodes and support
                weight under it, its health and the operators involved: by support weight at first,
                and sorted by any column by its header
              </caption>
              <thead>
                <tr>
                  <RankHead ranking={ranked} />
                  <SortTh sort={sorting} column="name">
                    Group
                  </SortTh>
                  <SortTh sort={sorting} column="members" className="number">
                    Members
                  </SortTh>
                  <SortTh sort={sorting} column="nested" className="number">
                    Nested groups
                  </SortTh>
                  <SortTh sort={sorting} column="components" className="number">
                    Components
                  </SortTh>
                  <SortTh sort={sorting} column="nodes" className="number">
                    Managed nodes
                  </SortTh>
                  <SortTh sort={sorting} column="items" className="number">
                    Items
                  </SortTh>
                  <SortTh sort={sorting} column="weight" className="number">
                    Support weight
                  </SortTh>
                  {HEALTHS.map((health) => (
                    <SortTh
                      sort={sorting}
                      column={health.value}
                      className="number"
                      key={health.value}
                    >
                      <HealthMark value={health.value} />
                    </SortTh>
                  ))}
                  <SortTh sort={sorting} column="involved">
                    Operators involved
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const detail = row.type ? groupTypeLabel(row.type) : null;
                  return (
                    <tr
                      key={row.key ?? ""}
                      data-group={row.key ?? ""}
                      data-label={row.key === null ? "" : (row.label ?? "")}
                      {...(row.key === null ? { "data-testid": "score-no-group" } : {})}
                    >
                      <RankCell ranking={ranked} row={row} />
                      <th scope="row">
                        {row.key ? (
                          <>
                            <Link to={`/groups/${encodeURIComponent(row.key)}`}>
                              {row.label ?? row.key}
                            </Link>
                            {detail && <span className="row-detail">{detail}</span>}
                          </>
                        ) : (
                          rowName(row, NO_GROUP)
                        )}
                      </th>
                      <td className="number" data-measure="members">
                        <Counted
                          ranking={ranked}
                          column="members"
                          row={row}
                          href={row.key ? itemsPath(`group.hid:eq:${row.key}`) : null}
                        />
                      </td>
                      <td className="number" data-measure="nested">
                        <Counted ranking={ranked} column="nested" row={row} />
                      </td>
                      <Measures
                        row={row}
                        ranked={ranked}
                        items={rowItemsPath(view.filter, groupCondition(row.key))}
                      />
                      {HEALTHS.map((health) => (
                        <td className="number" key={health.value} data-health={health.value}>
                          <Counted ranking={ranked} column={health.value} row={row} />
                        </td>
                      ))}
                      <td>
                        <Involved row={row} />
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={14} className="muted">
                      No item is in view.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <RankNote ranking={ranked} fallback="support weight" blank={NO_GROUP} />
          <p className="actions">
            <button
              type="button"
              disabled={rows.length === 0}
              onClick={() =>
                saveCsv(groupsCsv(rows), namedFile(productName, "scoreboard-groups.csv"))
              }
            >
              Export CSV
              <span className="visually-hidden"> of the groups</span>
            </button>
          </p>
          <p className="hint">
            A group holds its current members, those of every group nested in it at any depth, and
            the minor items of all of them: an item in several groups is counted under each, and the
            totals of the view count it once. The count of items leads to exactly those items, and
            the members to the group&apos;s own members, whatever the view.
          </p>
        </>
      )}
    </section>
  );
}

/** The operators involved in a row, the one with the most support weight first. */
function Involved({ row }: { row: ScoreRow }) {
  return (
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
}

/** The sites, the one with the most support weight first, each with the operators involved. */
function SitesBoard({ view, summary }: { view: ItemView; summary: Summary }) {
  const data = summary.data;
  const { productName } = useSite();
  // Every row, the items that are nowhere among them, by support weight at first.
  const sorting = useSorting(board(data?.rows), scoreColumns(NOWHERE), { initial: BY_WEIGHT });
  const rows = sorting.rows;
  const ranked = rankBoard(sorting, data?.totals.support_weight ?? "0");

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
                The sites of the items in view, and the items that are nowhere, each with its
                components, managed nodes, items, support weight and the operators involved: by
                support weight at first, and sorted by any column by its header
              </caption>
              <thead>
                <tr>
                  <RankHead ranking={ranked} />
                  <SortTh sort={sorting} column="name">
                    Site
                  </SortTh>
                  <SortTh sort={sorting} column="components" className="number">
                    Components
                  </SortTh>
                  <SortTh sort={sorting} column="nodes" className="number">
                    Managed nodes
                  </SortTh>
                  <SortTh sort={sorting} column="items" className="number">
                    Items
                  </SortTh>
                  <SortTh sort={sorting} column="weight" className="number">
                    Support weight
                  </SortTh>
                  <SortTh sort={sorting} column="involved">
                    Operators involved
                  </SortTh>
                  <th scope="col">In the grid</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.key ?? ""}
                    data-site={row.key ?? ""}
                    data-path={row.key === null ? "" : (row.label ?? "")}
                    {...(row.key === null ? { "data-testid": "score-nowhere" } : {})}
                  >
                    <RankCell ranking={ranked} row={row} />
                    <th scope="row">
                      {row.key ? (
                        <Link to={placePath("site", row.key)}>{row.label ?? row.key}</Link>
                      ) : (
                        rowName(row, NOWHERE)
                      )}
                    </th>
                    <Measures row={row} ranked={ranked} />
                    <td>
                      <Involved row={row} />
                    </td>
                    <td>
                      <ItemsLink view={view} condition={siteCondition(row.key)} />
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">
                      No item is in view.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <RankNote ranking={ranked} fallback="support weight" blank={NOWHERE} />
          <p className="actions">
            <button
              type="button"
              disabled={rows.length === 0}
              onClick={() =>
                saveCsv(sitesCsv(rows), namedFile(productName, "scoreboard-sites.csv"))
              }
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
