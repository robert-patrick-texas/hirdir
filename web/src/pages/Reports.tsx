import { type FormEvent, useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router";
import { api } from "../api";
import { CheckField, SelectField, TextField } from "../components/Field";
import { HealthMark } from "../components/Health";
import { Pager, toOffset } from "../components/Pager";
import { Problem } from "../components/Problem";
import { ConditionTotals, HeadlineTotals, ManagementTotals } from "../components/Totals";
import { addressRoleLabel, holderKind, holderPath, networkText } from "../lib/addresses";
import { itemsPath, parseShort } from "../lib/filter";
import { plural } from "../lib/format";
import { HEALTHS } from "../lib/health";
import { useLoad, useTitle } from "../lib/hooks";
import { useChoices, useSettings } from "../lib/lists";
import type { Option } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { settingText } from "../lib/settings";
import {
  amountText,
  byLabel,
  countText,
  isBy,
  isByPlace,
  isManagementBy,
  MANAGEMENT_BY,
  type ReportView,
  rowLabel,
  SUMMARY_BY,
  settingList,
  summaryQuery,
} from "../lib/summary";

const DUPLICATES_PAGE = 50;

// What to say beneath a report whose rows are places.
const PLACE_ROWS = {
  site: "A site is named by its path, and holds the items whose location in force is in it. The items that are nowhere are in a row of their own.",
  region:
    "A region is named by its path, and its row holds everything at or beneath it: an item is in the row of each region above it, and the totals count it once. The items that are nowhere are in a row of their own.",
} as const;

/** The second row of navigation on the report pages. */
function ReportsNav() {
  return (
    <nav className="sub" aria-label="Reports">
      <ul>
        <li>
          <NavLink to="/reports" end>
            Summary
          </NavLink>
        </li>
        <li>
          <NavLink to="/reports/management">Management</NavLink>
        </li>
        <li>
          <NavLink to="/reports/duplicates">Addresses held more than once</NavLink>
        </li>
      </ul>
    </nav>
  );
}

/** What the address of the page asks a report for. `known` says what that report can be by. */
function viewOf<B extends string>(
  params: URLSearchParams,
  known: (value: string) => value is B,
): ReportView<B> {
  const by = params.get("by") ?? "";
  return {
    filter: params.get("filter") ?? "",
    by: known(by) ? by : "",
    includeArchived: params.get("archived") === "1",
    includeDrafts: params.get("drafts") === "1",
  };
}

function paramsOf(view: ReportView<string>): Record<string, string> {
  return {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(view.by ? { by: view.by } : {}),
    ...(view.includeArchived ? { archived: "1" } : {}),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
  };
}

interface ViewFormProps<B extends string> {
  view: ReportView<B>;
  /** What the report can be by. */
  by: ReadonlyArray<Option & { value: B }>;
  /**
   * What the report is by when the view names nothing. Left out, the totals only, which
   * the form then offers; the management report is by site, and has no such view.
   */
  unasked?: B;
  known: (value: string) => value is B;
  /** What the server said of the filter, if it refused it. */
  filterRefused: string | undefined;
  onShow: (view: ReportView<B>) => void;
}

/**
 * The view a report is of: the filter of the item list, what the report is by, and the
 * switches of the list. Both reports take the same.
 */
function ViewForm<B extends string>(props: ViewFormProps<B>) {
  const { view, by, unasked, known, filterRefused, onShow } = props;
  const [draft, setDraft] = useState(view.filter);
  const [filterError, setFilterError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const typed = draft.trim();
    // The short form is read here as the server reads it. A filter tree as JSON is the
    // server's to judge.
    const parsed = typed.startsWith("{") ? null : parseShort(typed);
    if (parsed && !parsed.ok) {
      setFilterError(parsed.error);
      return;
    }
    setFilterError("");
    onShow({ ...view, filter: typed });
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <div className="fields">
        <TextField
          label="Filter"
          name="filter"
          type="search"
          value={draft}
          onChange={setDraft}
          autoComplete="off"
          hint="The filter of the item list: field:op:value, as in tags:has:refresh-2030"
          error={filterError || filterRefused}
        />
        <SelectField
          label="By"
          name="by"
          value={view.by || (unasked ?? "")}
          onChange={(next) => onShow({ ...view, by: known(next) ? next : "" })}
          hint="One row for each value. An item with no value is in a row of its own."
        >
          {unasked === undefined && <option value="">The totals only</option>}
          {by.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <div className="inline">
        <CheckField
          label="Include archived"
          name="include_archived"
          checked={view.includeArchived}
          onChange={(on) => onShow({ ...view, includeArchived: on })}
        />
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
        <button
          type="button"
          disabled={!view.filter && !draft}
          onClick={() => {
            setDraft("");
            setFilterError("");
            onShow({ ...view, filter: "" });
          }}
        >
          Clear
        </button>
        {view.filter && !view.filter.startsWith("{") && (
          <Link to={itemsPath(view.filter)}>These items in the grid</Link>
        )}
      </p>
    </form>
  );
}

/**
 * Reports → Summary, for the people who run the network: the components beside the
 * managed nodes, the support weight, and the components by health and by condition, for
 * a view of the items, with one row for each value of what the view is taken by. It
 * holds no money. The view is in the address of the page, so a summary can be linked to
 * and come back to.
 */
export function Summary() {
  useTitle("Summary");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params, isBy);
  const settings = useSettings();
  const choices = useChoices();
  const query = summaryQuery(view);
  const summary = useLoad(`summary ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/summary", { query, signal }),
  );
  const data = summary.data;
  const by = data?.by ?? "";

  return (
    <>
      <ReportsNav />
      <h1>Summary</h1>
      <p>
        The component count beside the managed-node count, the support weight, and the components by
        health and by condition, for the items in view: every item the filter keeps, major and
        minor. Estimated value and annual support cost are in the{" "}
        <Link to="/reports/management">management report</Link>.
      </p>
      <ViewForm
        key={view.filter}
        view={view}
        by={SUMMARY_BY}
        known={isBy}
        filterRefused={fieldErrors(summary.error, ["filter"]).shown.filter}
        onShow={(next) => setParams(paramsOf(next))}
      />
      <Problem error={summary.error} shown={["filter"]} />
      <Problem error={choices.error} />
      {summary.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <section aria-labelledby="summary-totals">
            <h2 id="summary-totals">Totals</h2>
            <HeadlineTotals
              totals={data.totals}
              countKinds={settingList(settings.data, "count_kinds")}
            />
            <ConditionTotals conditions={data.totals.by_condition} choices={choices.data} />
            <p className="hint">
              Health is worked out from the condition of an item, what is observed of it and whether
              it is expected online. The counts by health and by condition are of the components:
              the major items in hand.
            </p>
          </section>
          {by !== "" && (
            <section aria-labelledby="summary-rows">
              <h2 id="summary-rows">By {byLabel(by).toLowerCase()}</h2>
              <div className="scroll">
                <table data-testid="summary-rows">
                  <caption className="visually-hidden">
                    The measures of the items in view, one row for each {byLabel(by).toLowerCase()}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">{byLabel(by)}</th>
                      <th scope="col" className="number">
                        Items
                      </th>
                      <th scope="col" className="number">
                        Components
                      </th>
                      <th scope="col" className="number">
                        Managed nodes
                      </th>
                      <th scope="col" className="number">
                        Support weight
                      </th>
                      {HEALTHS.map((health) => (
                        <th scope="col" className="number" key={health.value}>
                          <HealthMark value={health.value} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row) => (
                      <tr key={row.key ?? ""} data-key={row.key ?? ""}>
                        <th scope="row" className={row.key === null ? "muted" : undefined}>
                          {rowLabel(by, row, choices.data)}
                        </th>
                        <td className="number">{countText(row.items)}</td>
                        <td className="number">{countText(row.component_count)}</td>
                        <td className="number">{countText(row.managed_node_count)}</td>
                        <td className="number">{amountText(row.support_weight)}</td>
                        {HEALTHS.map((health) => (
                          <td className="number" key={health.value} data-health={health.value}>
                            {countText(row.by_health[health.value])}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {data.rows.length === 0 && (
                      <tr>
                        <td colSpan={9} className="muted">
                          No item is in view.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="hint">
                The four columns of health count the components of the row. A minor item is in the
                row of the owner, state and disposition in force for it.
                {by === "tag" &&
                  " An item with several tags is in the row of each, and the totals count it once."}{" "}
                A stack whose members fall in two rows is a managed node in both, and one in the
                totals.
                {isByPlace(by) && ` ${PLACE_ROWS[by]}`}
              </p>
            </section>
          )}
        </>
      )}
    </>
  );
}

/**
 * Reports → Management, for the people who pay for the network: the estimated value and
 * the annual support cost of a view of the items, whole and with one row for each value
 * of what the view is taken by. It holds neither condition nor health. It is by site
 * unless asked otherwise: the whole inventory, and each site beneath it.
 */
export function ManagementReport() {
  useTitle("Management report");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params, isManagementBy);
  const settings = useSettings();
  const choices = useChoices();
  const query = summaryQuery(view);
  const report = useLoad(`management ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/management", { query, signal }),
  );
  const currency = settingText(settings.data?.find((one) => one.key === "currency")?.value);
  const money = currency ? ` (${currency})` : "";
  const data = report.data;
  const by = data?.by ?? "";

  return (
    <>
      <ReportsNav />
      <h1>Management report</h1>
      <p>
        The estimated value and the annual support cost of the items in view: every item the filter
        keeps, major and minor. An estimated value is a planning estimate. The annual support cost
        of a stack is that of its switches: the stack discount never applies to it. Components,
        managed nodes, support weight and health are in the <Link to="/reports">summary</Link>.
      </p>
      <ViewForm
        key={view.filter}
        view={view}
        by={MANAGEMENT_BY}
        unasked="site"
        known={isManagementBy}
        filterRefused={fieldErrors(report.error, ["filter"]).shown.filter}
        onShow={(next) => setParams(paramsOf(next))}
      />
      <Problem error={report.error} shown={["filter"]} />
      <Problem error={choices.error} />
      {report.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <section aria-labelledby="management-totals">
            <h2 id="management-totals">Totals</h2>
            <ManagementTotals totals={data.totals} currency={currency} />
          </section>
          {by !== "" && (
            <section aria-labelledby="management-rows">
              <h2 id="management-rows">By {byLabel(by).toLowerCase()}</h2>
              <div className="scroll">
                <table data-testid="management-rows">
                  <caption className="visually-hidden">
                    The value and the cost of the items in view, one row for each{" "}
                    {byLabel(by).toLowerCase()}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">{byLabel(by)}</th>
                      <th scope="col" className="number">
                        Items
                      </th>
                      <th scope="col" className="number">
                        Components
                      </th>
                      <th scope="col" className="number">
                        Estimated value{money}
                      </th>
                      <th scope="col" className="number">
                        Annual support cost{money}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row) => (
                      <tr key={row.key ?? ""} data-key={row.key ?? ""}>
                        <th scope="row" className={row.key === null ? "muted" : undefined}>
                          {rowLabel(by, row, choices.data)}
                        </th>
                        <td className="number">{countText(row.items)}</td>
                        <td className="number">{countText(row.component_count)}</td>
                        <td className="number">{amountText(row.est_value)}</td>
                        <td className="number">{amountText(row.annual_support_cost)}</td>
                      </tr>
                    ))}
                    {data.rows.length === 0 && (
                      <tr>
                        <td colSpan={5} className="muted">
                          No item is in view.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {by === "tag" && (
                <p className="hint">
                  An item with several tags is in the row of each, and the totals count it once.
                </p>
              )}
              {isByPlace(by) && <p className="hint">{PLACE_ROWS[by]}</p>}
            </section>
          )}
        </>
      )}
    </>
  );
}

/**
 * Reports → Addresses held more than once: each address that two or more items or
 * groups hold under one network, the unlabelled address space counting as one network.
 * The same address under two networks is two addresses, and is not here.
 */
export function Duplicates() {
  useTitle("Addresses held more than once");
  const [params, setParams] = useSearchParams();
  const offset = toOffset(params.get("offset"));
  const includeArchived = params.get("archived") === "1";
  const includeDrafts = params.get("drafts") === "1";
  const found = useLoad(`duplicates ${offset} ${includeArchived} ${includeDrafts}`, (signal) =>
    api.request("get", "/api/v1/reports/duplicates", {
      query: {
        limit: DUPLICATES_PAGE,
        offset,
        ...(includeArchived ? { include_archived: true } : {}),
        ...(includeDrafts ? { include_drafts: true } : {}),
      },
      signal,
    }),
  );
  const rows = found.data?.items ?? [];

  function show(next: { offset?: number; archived?: boolean; drafts?: boolean }) {
    const archived = next.archived ?? includeArchived;
    const drafts = next.drafts ?? includeDrafts;
    const at = next.offset ?? 0;
    setParams({
      ...(archived ? { archived: "1" } : {}),
      ...(drafts ? { drafts: "1" } : {}),
      ...(at > 0 ? { offset: String(at) } : {}),
    });
  }

  return (
    <>
      <ReportsNav />
      <h1>Addresses held more than once</h1>
      <p>
        The same address twice under one network is accepted, because shared and virtual addresses
        are real, and is listed here. Addresses with no network are in one address space of their
        own. The same address under two networks is two addresses, and is not listed.
      </p>
      <div className="inline">
        <CheckField
          label="Include archived and retired"
          name="include_archived"
          checked={includeArchived}
          onChange={(on) => show({ archived: on })}
        />
        <CheckField
          label="Include drafts"
          name="include_drafts"
          checked={includeDrafts}
          onChange={(on) => show({ drafts: on })}
        />
      </div>
      <Problem error={found.error} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {found.data && (
        <>
          <div className="scroll">
            <table data-testid="duplicates">
              <caption className="visually-hidden">
                Addresses held more than once under one network, with who holds each
              </caption>
              <thead>
                <tr>
                  <th scope="col">Address</th>
                  <th scope="col">Network</th>
                  <th scope="col">Held</th>
                  <th scope="col">By</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.network_hid ?? ""} ${row.address}`}
                    data-address={row.address}
                    data-network={row.network ?? ""}
                  >
                    <th scope="row" className="mono">
                      {row.address}
                    </th>
                    <td className={row.network ? undefined : "muted"}>
                      {networkText(row.network)}
                    </td>
                    <td className="nowrap">{plural(row.count, "time")}</td>
                    <td>
                      <ul className="plain-list">
                        {row.holders.map((holder) => {
                          const path = holderPath(holder);
                          const name = holder.name || "(no name)";
                          return (
                            <li key={holder.address_hid}>
                              {path ? <Link to={path}>{name}</Link> : name}
                              <span className="muted">
                                {" "}
                                · {holderKind(holder)} · {addressRoleLabel(holder.role)}
                                {holder.is_primary ? " · primary" : ""}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No address is held more than once under one network.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={found.data.total}
            limit={DUPLICATES_PAGE}
            offset={offset}
            noun="addresses"
            onChange={(at) => show({ offset: at })}
          />
        </>
      )}
    </>
  );
}
