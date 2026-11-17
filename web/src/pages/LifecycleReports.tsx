// Reports → Coverage, End of life and Replacements. Each count of the first two leads to
// its rows: the server gives, for each, the filter that lists the same items on the item
// list, and the grid here is the item list with that filter, so it is sorted, filtered,
// paged and exported like any other.

import { type FormEvent, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { CheckField, SelectField, TextField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { ItemsGrid } from "../components/ItemsGrid";
import { Problem } from "../components/Problem";
import { ReportsNav } from "../components/ReportsNav";
import { SortTh } from "../components/SortTh";
import {
  filterText,
  ITEM_WORDS,
  itemsViewPath,
  parseFilter,
  sentFilter,
  viewFilter,
} from "../lib/filter";
import { formatTime, itemName, plural } from "../lib/format";
import { useLoad, useTitle } from "../lib/hooks";
import {
  COVERAGE_SECTIONS,
  type CoverageSection,
  daysOf,
  END_OF_LIFE_DATES,
  END_OF_LIFE_SECTIONS,
  type EndOfLifeDate,
  type EndOfLifeSection,
  endOfLifeDateLabel,
  fiscalYearStanding,
  isCoverageSection,
  isEndOfLifeDate,
  isEndOfLifeSection,
  notRenewedModelLabel,
  type ReportSection,
} from "../lib/lifecycleReports";

type CoverageReportSection = Schemas["CoverageReportSection"];

import { useChoices, useSettings } from "../lib/lists";
import { choiceFilterOptions } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import { dateValue } from "../lib/sort";
import { countText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";

/** What the address of a report page asks for. */
interface View {
  filter: string;
  days: string;
  includeArchived: boolean;
  includeDrafts: boolean;
}

function viewOf(params: URLSearchParams): View {
  return {
    filter: params.get("filter") ?? "",
    days: params.get("days") ?? "",
    includeArchived: params.get("archived") === "1",
    includeDrafts: params.get("drafts") === "1",
  };
}

function paramsOf(view: View, more: Record<string, string> = {}): Record<string, string> {
  return {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(daysOf(view.days) === null ? {} : { days: view.days.trim() }),
    ...(view.includeArchived ? { archived: "1" } : {}),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
    ...more,
  };
}

interface ViewFormProps {
  view: View;
  /** The days the report has when none are asked for. */
  defaultDays: number;
  daysLabel: string;
  /** Whether the report takes Include archived: the coverage report does not. */
  archived: boolean;
  /** What the server said of the filter, if it refused it. */
  filterRefused: string | undefined;
  daysRefused: string | undefined;
  onShow: (view: View) => void;
}

/** The view a report is of: a filter of the item list, how far ahead it looks, the switches. */
function ViewForm(props: ViewFormProps) {
  const { view, defaultDays, daysLabel, archived, filterRefused, daysRefused, onShow } = props;
  const [draft, setDraft] = useState(view.filter);
  const [days, setDays] = useState(view.days);
  const [filterError, setFilterError] = useState("");
  const [daysError, setDaysError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    // Words find items by what an item is known by (P-187).
    const parsed = parseFilter(draft, ITEM_WORDS);
    setFilterError(parsed.ok ? "" : parsed.error);
    const typed = days.trim();
    const wrong = typed !== "" && daysOf(typed) === null;
    setDaysError(wrong ? "A whole number of days, at least 1." : "");
    if (!parsed.ok || wrong) return;
    onShow({ ...view, filter: draft.trim(), days: typed });
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
          hint="Words, as in a host name, or the filter of the item list: field:op:value, as in site:eq:Site-2"
          error={filterError || filterRefused}
        />
        <TextField
          label={daysLabel}
          name="within_days"
          value={days}
          onChange={setDays}
          inputMode="numeric"
          autoComplete="off"
          placeholder={String(defaultDays)}
          hint={`In days. Left blank, ${defaultDays}.`}
          error={daysError || daysRefused}
        />
      </div>
      <div className="inline">
        {archived && (
          <CheckField
            label="Include archived"
            name="include_archived"
            checked={view.includeArchived}
            onChange={(on) => onShow({ ...view, includeArchived: on })}
          />
        )}
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
          disabled={!view.filter && !draft && !view.days && !days}
          onClick={() => {
            setDraft("");
            setDays("");
            setFilterError("");
            setDaysError("");
            onShow({ ...view, filter: "", days: "" });
          }}
        >
          Clear
        </button>
      </p>
    </form>
  );
}

interface SectionCardProps {
  name: string;
  label: string;
  about: string;
  section: ReportSection | undefined;
  shown: boolean;
  onShow: () => void;
  /** The count, where the section of the answer does not hold it. */
  count?: number;
}

/** One list of a report: how many it holds, and the two ways to its rows. */
function SectionCard({ name, label, about, section, shown, onShow }: SectionCardProps) {
  const count = section?.count ?? 0;
  return (
    <div className="panel section-card" data-section={name} data-shown={shown ? "true" : "false"}>
      <h3>{label}</h3>
      <p className="section-count" data-testid={`count-${name}`} data-count={count}>
        {plural(count, "item")}
      </p>
      <p className="hint">{about}</p>
      <p className="actions">
        <button type="button" onClick={onShow} aria-pressed={shown} disabled={shown}>
          {shown ? "Shown beneath" : "Show these items"}
        </button>
        {/* A report asked with a filter as large as a filter may be gives none to hand on. */}
        {section?.filter && (
          <Link to={itemsViewPath(section)} data-testid={`grid-link-${name}`}>
            Open in the item grid
          </Link>
        )}
      </p>
    </div>
  );
}

/** The columns that each list of the coverage report is about, after the name of the item. */
const COVERAGE_COLUMNS: Readonly<Record<CoverageSection, readonly string[]>> = {
  uncovered: ["covered", "covered_until", "contract.number"],
  expiring: ["covered_until", "contract.number", "covered"],
  // The contracts that still count each item: the list to send the vendor.
  out_of_service: ["out_of_service_contract.number", "covered", "covered_until"],
  renewal_pending: ["contract.status", "contract.number", "covered"],
  overlapping: ["contract_count", "contract.number", "covered_until"],
  // Left out of support on purpose: in service, under no contract, and not to be renewed.
  not_renewed: ["covered", "covered_until", "contract.number"],
};

/**
 * Reports → Coverage: the items in service that no contract covers, the cover that runs
 * out soon, the items out of service that a contract still counts, what is covered
 * while a renewal is pending, what more than one contract covers, and the contracts that
 * have lapsed. It is of today.
 */
export function CoverageReport() {
  useTitle("Coverage");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params);
  const asked = params.get("section");
  // The counts come first, and no list is read until one is opened (D-184).
  const shown: CoverageSection | null = isCoverageSection(asked) ? asked : null;
  const days = daysOf(view.days);
  const query = {
    ...(view.filter.trim() ? { filter: sentFilter(view.filter) } : {}),
    ...(days === null ? {} : { within_days: days }),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
  const report = useLoad(`coverage-report ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/coverage", { query, signal }),
  );
  const data = report.data;
  const section = shown === null ? undefined : data?.sections[shown];
  const refused = fieldErrors(report.error, ["filter", "within_days"]).shown;
  const within = useMemo(
    () => ({
      filter: viewFilter(section?.filter),
      // Those that run out the soonest first, until a header is pressed.
      sort: shown === "expiring" ? ["covered_until"] : [],
      includeArchived: section?.include_archived === true,
      includeDrafts: section?.include_drafts === true,
    }),
    [section, shown],
  );

  function show(next: View, which: CoverageSection | null = shown) {
    setParams(paramsOf(next, which === null ? {} : { section: which }));
  }

  return (
    <>
      <ReportsNav />
      <h1>Coverage</h1>
      <p>
        Which items a contract covers today, and where the gaps are. An item is in service when the
        lifecycle state in force for it is one of the <span className="mono">service_states</span>{" "}
        setting
        {data ? `: ${data.service_states.join(", ")}` : ""}. Minor items are left out of what is not
        covered: a power supply is covered with its switch.
      </p>
      <ViewForm
        key={`${view.filter} ${view.days}`}
        view={view}
        defaultDays={90}
        daysLabel="Cover that runs out within"
        archived={false}
        filterRefused={refused.filter}
        daysRefused={refused.within_days}
        onShow={(next) => show(next)}
      />
      <Problem error={report.error} shown={["filter", "within_days"]} />
      {report.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <section aria-labelledby="coverage-totals">
            <h2 id="coverage-totals">As of {data.as_of}</h2>
            <dl className="totals" data-testid="coverage-totals">
              <div>
                <dt>Major items in service</dt>
                <dd data-testid="total-in-service">{countText(data.totals.in_service)}</dd>
              </div>
              <div>
                <dt>Covered</dt>
                <dd data-testid="total-covered">{countText(data.totals.covered)}</dd>
              </div>
              <div>
                <dt>Not covered</dt>
                <dd data-testid="total-uncovered">{countText(data.totals.uncovered)}</dd>
              </div>
              <div>
                <dt>Cover runs out within {plural(data.within_days, "day")}</dt>
                <dd data-testid="total-expiring">{countText(data.totals.expiring)}</dd>
              </div>
              <div>
                <dt>Out of service, still counted</dt>
                <dd data-testid="total-out-of-service">{countText(data.totals.out_of_service)}</dd>
              </div>
              <div>
                <dt>Covered while a renewal is pending</dt>
                <dd data-testid="total-renewal-pending">
                  {countText(data.totals.renewal_pending)}
                </dd>
              </div>
              <div>
                <dt>Under more than one contract</dt>
                <dd data-testid="total-overlapping">{countText(data.totals.overlapping)}</dd>
              </div>
              <div>
                <dt>Not to be renewed, with no cover</dt>
                <dd data-testid="total-not-renewed">{countText(data.totals.not_renewed)}</dd>
              </div>
            </dl>
            <p
              className={data.lapsed_contracts.count > 0 ? "warning" : "muted"}
              data-testid="lapsed-contracts"
              data-count={data.lapsed_contracts.count}
            >
              {data.lapsed_contracts.count > 0 ? (
                <>
                  {/* Its filter is blank where they are more than a filter can name. */}
                  {data.lapsed_contracts.filter ? (
                    <Link
                      to={`/contracts?filter=${encodeURIComponent(
                        filterText(viewFilter(data.lapsed_contracts.filter)),
                      )}`}
                    >
                      {plural(data.lapsed_contracts.count, "contract has", "contracts have")} lapsed
                    </Link>
                  ) : (
                    <>
                      {plural(data.lapsed_contracts.count, "contract has", "contracts have")} lapsed
                    </>
                  )}
                  : the period has ended and the status still says Active. A lapsed contract covers
                  nothing, so its items are among those with no cover: renew it, or say that it has
                  expired or that its renewal is pending.
                </>
              ) : (
                "No contract has lapsed: none has a period that has ended while its status still says Active."
              )}
            </p>
          </section>
          <section aria-labelledby="coverage-lists">
            <h2 id="coverage-lists">The six lists</h2>
            <div className="cards">
              {COVERAGE_SECTIONS.map((one) => (
                <SectionCard
                  key={one.value}
                  name={one.value}
                  label={one.label}
                  about={one.about}
                  section={data.sections[one.value]}
                  shown={one.value === shown}
                  onShow={() => show(view, one.value)}
                />
              ))}
            </div>
          </section>
          <NotRenewedByModel section={data.sections.not_renewed} />
          {shown === null && (
            <p className="hint" data-testid="no-list-open">
              Choose Show these items on a list above to read its items here.
            </p>
          )}
          {shown !== null && (
            <section aria-labelledby="coverage-items">
              <h2 id="coverage-items" data-testid="section-heading">
                {COVERAGE_SECTIONS.find((one) => one.value === shown)?.label}
              </h2>
              {section?.filter && (
                <ItemsGrid
                  key={shown}
                  id={`coverage-${shown}`}
                  within={within}
                  shown={COVERAGE_COLUMNS[shown]}
                />
              )}
              {section && !section.filter && (
                // The filter the report was asked with is as large as a filter may be: the
                // server gives none for the list, and reads its items itself.
                <>
                  <p className="hint">
                    The filter of this report is as large as a filter may be, so the list cannot be
                    handed on to the item grid or exported from here: it is read as the report gives
                    it, and its columns do not filter. A shorter filter gives the whole grid.
                  </p>
                  <ItemsGrid
                    key={`${shown} section`}
                    id={`coverage-${shown}`}
                    within={{ sort: within.sort }}
                    shown={COVERAGE_COLUMNS[shown]}
                    read={(request, signal) =>
                      api.request("get", "/api/v1/reports/coverage", {
                        query: {
                          ...query,
                          section: shown,
                          ...(request.sort.length > 0 ? { sort: request.sort } : {}),
                          limit: request.limit,
                          offset: request.offset,
                        },
                        signal,
                      })
                    }
                  />
                </>
              )}
            </section>
          )}
        </>
      )}
    </>
  );
}

/**
 * The items not to be renewed, counted by model: the vendor, the PID and the name of
 * each, the items with no model last, each count leading to those items in the grid. The
 * table holds all of its rows, so it is sorted by its headers in the browser.
 */
function NotRenewedByModel({ section }: { section: CoverageReportSection | undefined }) {
  const rows = section?.by_model ?? [];
  const sorting = useSorting(rows, {
    vendor: (row) => row.vendor,
    pid: (row) => row.pid,
    model: (row) => row.model_name,
    count: (row) => row.count,
  });
  if (!section || rows.length === 0) return null;
  return (
    <section aria-labelledby="not-renewed-by-model">
      <h2 id="not-renewed-by-model">Not to be renewed, by model</h2>
      <p className="hint">
        What has been left out of support on purpose: each model with how many of its items in
        service no contract covers while their flag not to renew is in force.
      </p>
      <div className="scroll">
        <table data-testid="not-renewed-by-model">
          <caption className="visually-hidden">
            The items not to be renewed, counted by model; each count leads to its items
          </caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="vendor">
                Vendor
              </SortTh>
              <SortTh sort={sorting} column="pid">
                PID
              </SortTh>
              <SortTh sort={sorting} column="model">
                Model
              </SortTh>
              <SortTh sort={sorting} column="count" className="number">
                Items
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <tr
                key={row.catalog_entry_hid ?? "none"}
                data-pid={row.pid ?? ""}
                data-count={row.count}
              >
                <td>{row.vendor ?? <span className="muted">—</span>}</td>
                <th scope="row">
                  {row.catalog_entry_hid ? (
                    <Link to={`/catalog/${encodeURIComponent(row.catalog_entry_hid)}`}>
                      {row.pid}
                    </Link>
                  ) : (
                    <span className="muted">{notRenewedModelLabel(row)}</span>
                  )}
                </th>
                <td>{row.model_name ?? <span className="muted">—</span>}</td>
                <td className="number">
                  {row.filter ? (
                    <Link
                      to={itemsViewPath({
                        filter: row.filter,
                        include_archived: section.include_archived,
                        include_drafts: section.include_drafts,
                      })}
                      aria-label={`${plural(row.count, "item")} of ${notRenewedModelLabel(row)} not to be renewed`}
                    >
                      {row.count}
                    </Link>
                  ) : (
                    row.count
                  )}
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
 * Reports → End of life: the items whose date is past and those whose date is
 * approaching, for each of the four dates, and by fiscal year. It holds no money: the
 * management report takes the same filter.
 */
export function EndOfLifeReport() {
  useTitle("End of life");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params);
  const askedDate = params.get("date");
  const date: EndOfLifeDate = isEndOfLifeDate(askedDate) ? askedDate : "ldos";
  const askedSection = params.get("section");
  const shown: EndOfLifeSection = isEndOfLifeSection(askedSection) ? askedSection : "approaching";
  const days = daysOf(view.days);
  const query = {
    date,
    ...(view.filter.trim() ? { filter: sentFilter(view.filter) } : {}),
    ...(days === null ? {} : { within_days: days }),
    ...(view.includeArchived ? { include_archived: true } : {}),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
  };
  const report = useLoad(`end-of-life ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/end-of-life", { query, signal }),
  );
  const settings = useSettings();
  const data = report.data;
  const section = shown === null ? undefined : data?.sections[shown];
  const refused = fieldErrors(report.error, ["filter", "within_days"]).shown;
  const within = useMemo(
    () => ({
      filter: viewFilter(section?.filter),
      // The soonest date first, until a header is pressed.
      sort: [`effective.${date}`],
      includeArchived: section?.include_archived === true,
      includeDrafts: section?.include_drafts === true,
    }),
    [section, date],
  );
  const dates = useMemo(
    () =>
      END_OF_LIFE_DATES.map((known) => ({
        ...known,
        counts: data?.dates[known.value] ?? {
          past: { items: 0, component_count: 0 },
          approaching: { items: 0, component_count: 0 },
        },
      })),
    [data],
  );
  const byDate = useSorting(dates, {
    date: (row) => row.label,
    past_items: (row) => row.counts.past.items,
    past_components: (row) => row.counts.past.component_count,
    approaching_items: (row) => row.counts.approaching.items,
    approaching_components: (row) => row.counts.approaching.component_count,
  });
  const years = useSorting(data?.by_fiscal_year, {
    year: (row) => row.fiscal_year,
    starts: (row) => dateValue(row.starts_on),
    ends: (row) => dateValue(row.ends_on),
    items: (row) => row.items,
    components: (row) => row.component_count,
  });
  const startMonth = settings.data?.find((one) => one.key === "fiscal_year_start_month")?.value;

  function show(next: View, which: { date?: EndOfLifeDate; section?: EndOfLifeSection } = {}) {
    const toDate = which.date ?? date;
    const toSection = which.section ?? shown;
    setParams(
      paramsOf(next, {
        ...(toDate === "ldos" ? {} : { date: toDate }),
        ...(toSection === "approaching" ? {} : { section: toSection }),
      }),
    );
  }

  return (
    <>
      <ReportsNav />
      <h1>End of life</h1>
      <p>
        The items whose date is past, and those whose date is approaching, by the date in force for
        each: its own, or its model&apos;s. The report holds no money: the{" "}
        <Link to="/reports/management">management report</Link> takes the same filter.
      </p>
      <div className="fields">
        <SelectField
          label="Date"
          name="date"
          value={date}
          onChange={(next) => show(view, { date: isEndOfLifeDate(next) ? next : "ldos" })}
          hint="The date the two lists and the fiscal years are of. The counts beneath are of all four."
        >
          {END_OF_LIFE_DATES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <ViewForm
        key={`${view.filter} ${view.days}`}
        view={view}
        defaultDays={730}
        daysLabel="Approaching: within"
        archived
        filterRefused={refused.filter}
        daysRefused={refused.within_days}
        onShow={(next) => show(next)}
      />
      <Problem error={report.error} shown={["filter", "within_days"]} />
      {report.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <section aria-labelledby="eol-dates">
            <h2 id="eol-dates">As of {data.as_of}</h2>
            <div className="scroll">
              <table data-testid="eol-dates">
                <caption>
                  Past is before today; approaching is from today to{" "}
                  {plural(data.within_days, "day")} ahead
                </caption>
                <thead>
                  <tr>
                    <SortTh sort={byDate} column="date">
                      Date
                    </SortTh>
                    <SortTh sort={byDate} column="past_items" className="number">
                      Past: items
                    </SortTh>
                    <SortTh sort={byDate} column="past_components" className="number">
                      Past: components
                    </SortTh>
                    <SortTh sort={byDate} column="approaching_items" className="number">
                      Approaching: items
                    </SortTh>
                    <SortTh sort={byDate} column="approaching_components" className="number">
                      Approaching: components
                    </SortTh>
                  </tr>
                </thead>
                <tbody>
                  {byDate.rows.map((row) => (
                    <tr
                      key={row.value}
                      data-date={row.value}
                      data-chosen={row.value === data.date ? "true" : "false"}
                    >
                      <th scope="row">
                        {row.value === data.date ? (
                          <>
                            {row.label}
                            <span className="badge badge-plain">Shown beneath</span>
                          </>
                        ) : (
                          <Link
                            to={`/reports/end-of-life?${new URLSearchParams(
                              paramsOf(view, {
                                ...(row.value === "ldos" ? {} : { date: row.value }),
                                ...(shown === "approaching" ? {} : { section: shown }),
                              }),
                            ).toString()}`}
                          >
                            {row.label}
                          </Link>
                        )}
                      </th>
                      <td className="number" data-testid="past-items">
                        {countText(row.counts.past.items)}
                      </td>
                      <td className="number">{countText(row.counts.past.component_count)}</td>
                      <td className="number" data-testid="approaching-items">
                        {countText(row.counts.approaching.items)}
                      </td>
                      <td className="number">
                        {countText(row.counts.approaching.component_count)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby="eol-years">
            <h2 id="eol-years">{endOfLifeDateLabel(data.date)}, by fiscal year</h2>
            {data.by_fiscal_year.length === 0 ? (
              <p className="muted">No item in view has this date.</p>
            ) : (
              <div className="scroll">
                <table className="narrow" data-testid="eol-years">
                  <caption>
                    One row for each fiscal year the date of an item in view falls in. A fiscal year
                    is named for the calendar year it ends in
                    {typeof startMonth === "number" ? `, and starts in month ${startMonth}` : ""}.
                  </caption>
                  <thead>
                    <tr>
                      <SortTh sort={years} column="year">
                        Fiscal year
                      </SortTh>
                      <SortTh sort={years} column="starts">
                        From
                      </SortTh>
                      <SortTh sort={years} column="ends">
                        To
                      </SortTh>
                      <SortTh sort={years} column="items" className="number">
                        Items
                      </SortTh>
                      <SortTh sort={years} column="components" className="number">
                        Components
                      </SortTh>
                    </tr>
                  </thead>
                  <tbody>
                    {years.rows.map((year) => {
                      const standing = fiscalYearStanding(year, data.as_of);
                      return (
                        <tr
                          key={year.fiscal_year}
                          data-year={year.fiscal_year}
                          className={standing === "past" ? "muted" : undefined}
                        >
                          <th scope="row">
                            FY {year.fiscal_year}
                            {standing === "current" && (
                              <span className="badge badge-plain">This year</span>
                            )}
                          </th>
                          <td className="nowrap">{year.starts_on}</td>
                          <td className="nowrap">{year.ends_on}</td>
                          <td className="number">{countText(year.items)}</td>
                          <td className="number">{countText(year.component_count)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section aria-labelledby="eol-lists">
            <h2 id="eol-lists">{endOfLifeDateLabel(data.date)}: the two lists</h2>
            <div className="cards">
              {END_OF_LIFE_SECTIONS.map((one) => (
                <SectionCard
                  key={one.value}
                  name={one.value}
                  label={one.label}
                  about={
                    one.value === "past"
                      ? "The date is before today."
                      : `The date is from today to ${plural(data.within_days, "day")} ahead.`
                  }
                  section={data.sections[one.value]}
                  shown={one.value === shown}
                  onShow={() => show(view, { section: one.value })}
                />
              ))}
            </div>
          </section>
          <section aria-labelledby="eol-items">
            <h2 id="eol-items" data-testid="section-heading">
              {endOfLifeDateLabel(data.date)}: {shown === "past" ? "past" : "approaching"}
            </h2>
            {section && (
              <ItemsGrid
                key={`${date} ${shown}`}
                id={`end-of-life-${shown}`}
                within={within}
                shown={[`effective.${date}`]}
              />
            )}
          </section>
        </>
      )}
    </>
  );
}

type Replacement = Schemas["ReplacementRow"];
type Choice = Schemas["ChoiceOut"];

function itemPath(hid: string): string {
  return `/items/${encodeURIComponent(hid)}`;
}

function replacementColumns(choices: readonly Choice[] | undefined): GridColumn<Replacement>[] {
  return [
    {
      id: "replaced_on",
      header: "Replaced on",
      kind: "date",
      value: (row) => row.replaced_on,
      width: 140,
    },
    {
      id: "reason",
      header: "Reason",
      kind: "choice",
      value: (row) => row.reason_label || row.reason,
      choices: choiceFilterOptions(choices, "replacement_reason"),
      width: 150,
    },
    {
      id: "reference",
      header: "Reference",
      kind: "text",
      value: (row) => row.reference,
      width: 170,
    },
    {
      id: "old.name",
      header: "Item that left",
      kind: "text",
      column: "old_item",
      value: (row) => itemName(row.old_item),
      linkTo: (row) => itemPath(row.old_item_hid),
      width: 220,
    },
    {
      id: "old.serial_number",
      header: "Its serial number",
      kind: "text",
      column: null,
      value: (row) => row.old_item.serial_number,
      mono: true,
      width: 160,
    },
    {
      id: "new.name",
      header: "Item that took its place",
      kind: "text",
      column: "new_item",
      value: (row) => itemName(row.new_item),
      linkTo: (row) => itemPath(row.new_item_hid),
      width: 220,
    },
    {
      id: "new.serial_number",
      header: "Its serial number",
      kind: "text",
      column: null,
      value: (row) => row.new_item.serial_number,
      mono: true,
      width: 160,
    },
    {
      id: "created_at",
      header: "Recorded",
      kind: "timestamp",
      value: (row) => formatTime(row.created_at),
      hide: true,
    },
    {
      id: "hid",
      header: "HID",
      kind: "reference",
      value: (row) => row.hid,
      mono: true,
      hide: true,
    },
  ];
}

/**
 * Reports → Replacements: each item that left with the item that took its place, the
 * newest first, and the count of each reason among what the filter keeps.
 */
export function Replacements() {
  useTitle("Replacements");
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const choices = useChoices();
  const columns = useMemo(() => replacementColumns(choices.data), [choices.data]);
  const [reasons, setReasons] = useState<Schemas["ReasonCount"][] | null>(null);
  const sorting = useSorting(reasons, {
    reason: (row) => row.label,
    count: (row) => row.count,
  });

  return (
    <>
      <ReportsNav />
      <h1>Replacements</h1>
      <p>
        An item is replaced on its own page: the replacement links the item that left and the item
        that took its place, with the reason and the day. They are listed here, the newest first.
      </p>
      <Problem error={choices.error} />
      <section aria-labelledby="by-reason">
        <h2 id="by-reason">By reason</h2>
        {reasons === null ? (
          <p role="status" className="muted loading-late">
            Counting…
          </p>
        ) : reasons.length === 0 ? (
          <p className="muted">No replacement matches.</p>
        ) : (
          <div className="scroll">
            <table className="narrow" data-testid="replacement-reasons">
              <caption>Of the replacements the filter of the grid keeps</caption>
              <thead>
                <tr>
                  <SortTh sort={sorting} column="reason">
                    Reason
                  </SortTh>
                  <SortTh sort={sorting} column="count" className="number">
                    Replacements
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sorting.rows.map((row) => (
                  <tr key={row.reason} data-reason={row.reason}>
                    <th scope="row">{row.label}</th>
                    <td className="number">{countText(row.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!choices.loading && (
        <DataGrid<Replacement>
          key={startFilter ?? ""}
          id="replacements"
          noun={["replacement", "replacements"]}
          entity="item_replacements"
          columns={columns}
          load={async (request, signal) => {
            const page = await api.request("get", "/api/v1/reports/replacements", {
              query: {
                ...(request.filter ? { filter: JSON.stringify(request.filter) } : {}),
                ...(request.sort.length > 0 ? { sort: request.sort } : {}),
                limit: request.limit,
                offset: request.offset,
              },
              signal,
            });
            // The counts are of what the filter keeps: they come with every page of it.
            setReasons(page.by_reason);
            return page;
          }}
          rowId={(row) => row.hid}
          shortFilter="reason:eq:rma replaced_on:gte:2026-01-01"
          quickFields={["old.name", "old.serial_number", "new.name", "new.serial_number"]}
          startFilter={startFilter}
        />
      )}
    </>
  );
}
