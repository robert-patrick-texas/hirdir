// Contracts → Renewals: the worklist of what a person must act on to keep the cover going,
// as of today. The counts of each list come first, of the whole worklist and of each
// vendor and agreement, and the rows of a list are read only when it is opened: they are
// the list of contracts, or of items for those under more than one contract, with the
// filter the server gives for that list, so they are sorted, filtered, paged and
// exported like any other.

import { type FormEvent, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api";
import { ContractsNav } from "../components/ContractParts";
import { CheckField, TextField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { ItemsGrid } from "../components/ItemsGrid";
import { Problem } from "../components/Problem";
import { SortTh } from "../components/SortTh";
import {
  agreementPath,
  CONTRACT_STATUSES,
  type Contract,
  contractPath,
  LAPSED_NOTE,
  nextTermText,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
} from "../lib/contracts";
import { effectiveText } from "../lib/effective";
import { filterText, parseFilter, viewFilter } from "../lib/filter";
import { plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useLoad, useTitle } from "../lib/hooks";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import {
  AGREEMENT_SECTIONS,
  findGroup,
  groupKey,
  groupLabel,
  isRenewalSection,
  listFilter,
  type Opened,
  pendingText,
  RENEWAL_SECTIONS,
  type RenewalGroup,
  type RenewalsReport,
  renewalsPath,
  sectionInfo,
} from "../lib/renewals";
import { useSorting } from "../lib/useSorting";

/** The columns of a list of contracts on the worklist: what each must be acted on by. */
const COLUMNS: GridColumn<Contract>[] = [
  {
    id: "number",
    header: "Number",
    kind: "text",
    value: (contract) => contract.number,
    link: true,
    width: 170,
  },
  {
    id: "vendor",
    header: "Vendor",
    kind: "text",
    value: (contract) => contract.vendor.name,
    width: 140,
  },
  {
    id: "agreement.name",
    header: "Agreement",
    kind: "text",
    column: "agreement",
    value: (contract) => contract.agreement?.name,
    linkTo: (contract) => (contract.agreement ? agreementPath(contract.agreement.hid) : null),
    width: 220,
  },
  {
    // The end of the period in force: its own, or its agreement's, shown lighter.
    id: "effective.ends_on",
    header: "Ends",
    kind: "date",
    column: "ends_on",
    value: (contract) => effectiveText(contract.effective.ends_on),
    effective: (contract) => contract.effective.ends_on,
    width: 130,
  },
  {
    id: "status",
    header: "Status",
    kind: "choice",
    value: (contract) => optionLabel(CONTRACT_STATUSES, contract.status),
    hint: (contract) => (contract.status === RENEWAL_PENDING ? RENEWAL_PENDING_NOTE : ""),
    choices: CONTRACT_STATUSES,
    width: 150,
  },
  {
    // The days since the end of the term the renewal is for: none before that end.
    id: "renewal_pending_days",
    header: "Pending for",
    kind: "integer",
    value: (contract) => pendingText(contract.renewal_pending_days),
    numeric: true,
    width: 130,
  },
  {
    // Pending for longer than the setting renewal_pending_overdue_days.
    id: "renewal_overdue",
    header: "Overdue",
    kind: "boolean",
    value: (contract) => (contract.renewal_overdue ? "Overdue" : ""),
    hint: (contract) =>
      contract.renewal_overdue
        ? "Pending for longer than the setting renewal_pending_overdue_days: ask why"
        : "",
    choices: [
      { value: "true", label: "Overdue: pending too long" },
      { value: "false", label: "Not overdue" },
    ],
    width: 110,
  },
  {
    id: "lapsed",
    header: "Lapsed",
    kind: "boolean",
    column: null,
    value: (contract) => (contract.lapsed ? "Lapsed" : ""),
    hint: (contract) => (contract.lapsed ? LAPSED_NOTE : ""),
    choices: [
      { value: "true", label: "Lapsed: ended, and still says Active" },
      { value: "false", label: "Not lapsed" },
    ],
    width: 100,
  },
  {
    id: "covered_items",
    header: "Items covered",
    kind: "integer",
    field: null,
    sortField: "covered_items",
    value: (contract) => String(contract.covered_items),
    numeric: true,
    width: 130,
  },
  {
    // Marked by the team not to renew, as when a site closes: a note (P-129).
    id: "ends_with_term",
    header: "Not to be renewed",
    kind: "boolean",
    value: (contract) => (contract.ends_with_term ? "Yes" : ""),
    choices: [
      { value: "true", label: "Marked not to renew" },
      { value: "false", label: "Not marked" },
    ],
    width: 160,
  },
  {
    // Whom to go through while a renewal is pending.
    id: "effective.account_manager",
    header: "Account manager",
    kind: "text",
    column: "account_manager",
    value: (contract) => effectiveText(contract.effective.account_manager),
    effective: (contract) => contract.effective.account_manager,
    hide: true,
    width: 220,
  },
  {
    id: "next_starts_on",
    header: "Next term starts",
    kind: "date",
    value: (contract) => contract.next_term?.starts_on,
    hint: (contract) => (contract.next_term ? nextTermText(contract.next_term) : ""),
    hide: true,
    width: 160,
  },
  {
    id: "annual_cost",
    header: "Annual cost",
    kind: "number",
    value: (contract) => contract.annual_cost,
    numeric: true,
    hide: true,
    width: 130,
  },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (contract) => optionLabel(RECORD_STATUSES, contract.record_status),
    choices: RECORD_STATUSES,
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (contract) => contract.hid,
    mono: true,
    hide: true,
  },
];

/** The columns of the items under more than one contract that this list is about. */
const OVERLAPPING_COLUMNS = ["contract_count", "contract.number", "covered_until"];

/** What the worklist is asked with: its view, as the server takes it. */
interface ReportQuery {
  filter?: string;
  within_days?: number;
  include_drafts?: boolean;
  include_archived?: boolean;
}

/** What the address of the worklist asks for: its view, and the list that is open. */
interface View {
  filter: string;
  days: string;
  includeDrafts: boolean;
  includeArchived: boolean;
}

function viewOf(params: URLSearchParams): View {
  return {
    filter: params.get("filter") ?? "",
    days: params.get("days") ?? "",
    includeDrafts: params.get("drafts") === "1",
    includeArchived: params.get("archived") === "1",
  };
}

/** The view as the parameters of the address, kept when a list is opened. */
function viewParams(view: View): Record<string, string> {
  return {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(daysOf(view.days) === null ? {} : { days: view.days.trim() }),
    ...(view.includeDrafts ? { drafts: "1" } : {}),
    ...(view.includeArchived ? { archived: "1" } : {}),
  };
}

/** A number of days as typed, or null for none or one that is not a whole number above 0. */
function daysOf(typed: string): number | null {
  const text = typed.trim();
  if (!/^\d{1,5}$/.test(text)) return null;
  const days = Number.parseInt(text, 10);
  return days > 0 ? days : null;
}

/** The list the address has open, if any: none until a count is chosen. */
function openedOf(params: URLSearchParams): Opened | null {
  const section = params.get("section");
  if (!isRenewalSection(section)) return null;
  const vendor = params.get("vendor") ?? "";
  return vendor ? { section, vendor, agreement: params.get("agreement") ?? "none" } : { section };
}

export function Renewals() {
  useTitle("Renewals");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params);
  const opened = openedOf(params);
  const days = daysOf(view.days);
  const query: ReportQuery = {
    ...(view.filter.trim() ? { filter: view.filter.trim() } : {}),
    ...(days === null ? {} : { within_days: days }),
    ...(view.includeDrafts ? { include_drafts: true } : {}),
    ...(view.includeArchived ? { include_archived: true } : {}),
  };
  // The counts alone: no list is asked for until one is opened.
  const report = useLoad(`renewals ${JSON.stringify(query)}`, (signal) =>
    api.request("get", "/api/v1/reports/renewals", { query, signal }),
  );
  const data = report.data;
  const refused = fieldErrors(report.error, ["filter", "within_days"]).shown;
  const kept = viewParams(view);

  function show(next: View) {
    const keep = viewParams(next);
    // A list that is open stays open over another view.
    if (opened) {
      const path = renewalsPath(opened, keep);
      setParams(new URLSearchParams(path.slice(path.indexOf("?") + 1)));
    } else setParams(keep);
  }

  return (
    <>
      <ContractsNav />
      <h1>Renewals</h1>
      <p>
        What must be acted on to keep the cover going, as of today: the contracts that have lapsed,
        those whose renewal is pending and of them those pending too long, those that end soon with
        no renewal entered, those the team marked not to renew, the members to review after a
        renewal of their agreement, and the items under more than one contract. Each count leads to
        its rows, which are read when the list is opened.
      </p>
      <ViewForm
        key={`${view.filter} ${view.days}`}
        view={view}
        defaultDays={data?.within_days ?? 90}
        filterRefused={refused.filter}
        daysRefused={refused.within_days}
        onShow={show}
      />
      <Problem error={report.error} shown={["filter", "within_days"]} />
      {report.loading && !data && (
        <p role="status" className="muted loading-late">
          Counting…
        </p>
      )}
      {data && (
        <>
          <p className="hint" data-testid="renewals-as-of">
            As of {data.as_of}. Ending soon is within {plural(data.within_days, "day")}, and a
            renewal is overdue once it has been pending for more than{" "}
            {plural(data.overdue_after, "day")}, as the settings say.
          </p>
          <Lists report={data} opened={opened} keep={kept} />
          <Groups report={data} opened={opened} keep={kept} />
          <Agreements report={data} />
          {opened && (
            <OpenList
              key={`${opened.section} ${opened.vendor ?? ""} ${opened.agreement ?? ""}`}
              report={data}
              opened={opened}
              query={query}
              keep={kept}
            />
          )}
        </>
      )}
    </>
  );
}

interface ViewFormProps {
  view: View;
  defaultDays: number;
  filterRefused: string | undefined;
  daysRefused: string | undefined;
  onShow: (view: View) => void;
}

/** The view the worklist is of: a filter of the list of contracts, the days, the drafts. */
function ViewForm({ view, defaultDays, filterRefused, daysRefused, onShow }: ViewFormProps) {
  const [draft, setDraft] = useState(view.filter);
  const [days, setDays] = useState(view.days);
  const [filterError, setFilterError] = useState("");
  const [daysError, setDaysError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseFilter(draft);
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
          hint="The filter of the list of contracts: field:op:value, as in vendor:eq:Cisco"
          error={filterError || filterRefused}
        />
        <TextField
          label="Ending within"
          name="within_days"
          value={days}
          onChange={setDays}
          inputMode="numeric"
          autoComplete="off"
          placeholder={String(defaultDays)}
          hint={`In days. Left blank, the setting renewal_warning_days: ${defaultDays}.`}
          error={daysError || daysRefused}
        />
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

interface PartProps {
  report: RenewalsReport;
  opened: Opened | null;
  /** The view, kept in the address of every count. */
  keep: Record<string, string>;
}

/** The lists of the whole worklist, each with its count, which opens its rows. */
function Lists({ report, opened, keep }: PartProps) {
  return (
    <section aria-labelledby="renewal-lists">
      <h2 id="renewal-lists">The lists</h2>
      <div className="cards">
        {RENEWAL_SECTIONS.map((one) => {
          const count = report.totals[one.value];
          const open = opened?.section === one.value && !opened.vendor;
          return (
            <div
              key={one.value}
              className="panel section-card"
              data-section={one.value}
              data-shown={open ? "true" : "false"}
            >
              <h3>{one.label}</h3>
              <p
                className="section-count"
                data-testid={`renewals-count-${one.value}`}
                data-count={count}
              >
                <Link
                  to={renewalsPath({ section: one.value }, keep)}
                  aria-current={open ? "true" : undefined}
                  className="count-link"
                >
                  {plural(count, one.of === "items" ? "item" : "contract")}
                </Link>
              </p>
              <p className="hint">{one.about}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * The counts of each vendor and agreement, the contracts that stand by themselves under
 * their vendor. The table holds all of its rows, so it is sorted by its headers in the
 * browser; until one is pressed it is in the server's order, the vendors by name and
 * within one the agreements by name and those standing alone last.
 */
function Groups({ report, opened, keep }: PartProps) {
  const sorting = useSorting(report.groups, {
    vendor: (group) => group.vendor,
    agreement: (group) => group.agreement,
    ...Object.fromEntries(
      RENEWAL_SECTIONS.map((one) => [one.value, (group: RenewalGroup) => group.counts[one.value]]),
    ),
  });
  return (
    <section aria-labelledby="renewal-groups">
      <h2 id="renewal-groups">By vendor and agreement</h2>
      {report.groups.length === 0 ? (
        <p className="muted" data-testid="renewal-groups-none">
          Nothing is on any list.
        </p>
      ) : (
        <div className="scroll">
          <table data-testid="renewal-groups">
            <caption className="visually-hidden">
              The count of each list for each vendor and agreement; each count opens its rows
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="vendor">
                  Vendor
                </SortTh>
                <SortTh sort={sorting} column="agreement">
                  Agreement
                </SortTh>
                {RENEWAL_SECTIONS.map((one) => (
                  <SortTh sort={sorting} column={one.value} key={one.value} className="number">
                    {one.label}
                  </SortTh>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((group) => {
                const key = groupKey(group);
                return (
                  <tr
                    key={`${key.vendor} ${key.agreement}`}
                    data-vendor={group.vendor}
                    data-agreement={group.agreement ?? ""}
                  >
                    <th scope="row">
                      <Link to={`/vendors/${encodeURIComponent(group.vendor_hid)}`}>
                        {group.vendor}
                      </Link>
                    </th>
                    <td>
                      {group.agreement_hid ? (
                        <Link to={agreementPath(group.agreement_hid)}>{group.agreement}</Link>
                      ) : (
                        <span className="muted">Standing by themselves</span>
                      )}
                    </td>
                    {RENEWAL_SECTIONS.map((one) => {
                      const count = group.counts[one.value];
                      const open =
                        opened?.section === one.value &&
                        opened.vendor === key.vendor &&
                        (opened.agreement ?? "none") === key.agreement;
                      return (
                        <td
                          key={one.value}
                          className="number"
                          data-section={one.value}
                          data-count={count}
                        >
                          {count > 0 ? (
                            <Link
                              to={renewalsPath({ section: one.value, ...key }, keep)}
                              aria-current={open ? "true" : undefined}
                              aria-label={`${plural(count, one.of === "items" ? "item" : "contract")} ${one.label.toLowerCase()}: ${groupLabel(group)}`}
                            >
                              {count}
                            </Link>
                          ) : (
                            <span className="muted">0</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * The agreements on the lists by themselves, beside the contracts: renewing one renews
 * every contract that shares its period. Each count leads to them in the grid of
 * agreements.
 */
function Agreements({ report }: { report: RenewalsReport }) {
  const rows = AGREEMENT_SECTIONS.map((one) => ({ ...one, section: report.agreements[one.value] }));
  const sorting = useSorting(rows, {
    list: (row) => row.label,
    count: (row) => row.section?.count ?? 0,
  });
  return (
    <section aria-labelledby="renewal-agreements">
      <h2 id="renewal-agreements">Agreements</h2>
      <p className="hint">
        An agreement is on the lists by the same tests. Renewing one renews every contract that
        shares its period, each kept under its number, given a new one, or let go: see the
        agreement.
      </p>
      <div className="scroll">
        <table className="narrow" data-testid="renewal-agreements">
          <caption className="visually-hidden">The agreements on each list</caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="list">
                List
              </SortTh>
              <SortTh sort={sorting} column="count" className="number">
                Agreements
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => {
              const count = row.section?.count ?? 0;
              const filter = viewFilter(row.section?.filter);
              return (
                <tr key={row.value} data-section={row.value} data-count={count}>
                  <th scope="row">{row.label}</th>
                  <td className="number">
                    {count > 0 && filter ? (
                      <Link to={`/agreements?filter=${encodeURIComponent(filterText(filter))}`}>
                        {plural(count, "agreement")}
                      </Link>
                    ) : (
                      plural(count, "agreement")
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface OpenListProps {
  report: RenewalsReport;
  opened: Opened;
  /** The view of the worklist, as it is asked of the server. */
  query: ReportQuery;
  keep: Record<string, string>;
}

/**
 * The rows of the list that is open: the list of contracts, or of items, with the filter
 * the server gives for it, the soonest end first until a header is pressed. A list whose
 * filter the server cannot give, because the view's own is as large as a filter may be,
 * is read as the worklist gives it.
 */
function OpenList({ report, opened, query, keep }: OpenListProps) {
  const info = sectionInfo(opened.section);
  const group = findGroup(report.groups, opened.vendor, opened.agreement);
  const narrowed = Boolean(opened.vendor);
  const filter = listFilter(report, opened.section, group);
  const section = report.sections[opened.section];
  const count = group ? group.counts[opened.section] : report.totals[opened.section];
  const within = useMemo(
    () => ({
      filter,
      // The soonest end first: on items, the soonest their cover runs out.
      sort: info.of === "items" ? ["covered_until"] : ["effective.ends_on"],
      includeArchived: section?.include_archived === true,
      includeDrafts: section?.include_drafts === true,
    }),
    [filter, info.of, section],
  );
  const heading = narrowed && group ? `${info.label}: ${groupLabel(group)}` : info.label;

  return (
    <section
      aria-labelledby="renewal-open"
      data-testid="renewal-open"
      data-section={opened.section}
    >
      <h2 id="renewal-open">{heading}</h2>
      <p className="hint">
        {plural(count, info.of === "items" ? "item" : "contract")}. {info.about}{" "}
        {narrowed && (
          <Link to={renewalsPath({ section: opened.section }, keep)}>The whole list</Link>
        )}
      </p>
      {narrowed && !group && (
        <p className="warning">That vendor and agreement have nothing on this list any more.</p>
      )}
      {(!narrowed || group) && filter && info.of === "contracts" && (
        <DataGrid<Contract>
          id={`renewals-${opened.section}`}
          noun={["contract", "contracts"]}
          entity="contracts"
          columns={COLUMNS}
          load={(request, signal) =>
            api.request("get", "/api/v1/contracts", { query: queryParams(request), signal })
          }
          rowId={(contract) => contract.hid}
          rowLink={(contract) => contractPath(contract.hid)}
          dimmed={(contract) => contract.record_status !== "active"}
          shortFilter="vendor:eq:Cisco renewal_overdue:eq:true"
          within={within}
        />
      )}
      {(!narrowed || group) && filter && info.of === "items" && (
        <ItemsGrid id="renewals-overlapping" within={within} shown={OVERLAPPING_COLUMNS} />
      )}
      {!filter && (
        // The view's own filter is as large as a filter may be: the server gives none for
        // the list, and reads its rows itself, the whole list and not one group of it.
        <>
          <p className="hint">
            The filter of this view is as large as a filter may be, so the list cannot be handed on
            to a grid or exported from here: it is read as the worklist gives it
            {narrowed ? ", the whole list and not this vendor and agreement alone" : ""}. A shorter
            filter gives the whole grid.
          </p>
          {info.of === "contracts" ? (
            <DataGrid<Contract>
              id={`renewals-${opened.section}-read`}
              noun={["contract", "contracts"]}
              columns={COLUMNS.map((column) => ({
                ...column,
                field: null,
                sortField:
                  column.sortField === undefined
                    ? column.field === undefined
                      ? column.id
                      : column.field
                    : column.sortField,
              }))}
              load={async (request, signal) => {
                const page = await api.request("get", "/api/v1/reports/renewals", {
                  query: {
                    ...query,
                    section: opened.section,
                    ...(request.sort.length > 0 ? { sort: request.sort } : {}),
                    limit: request.limit,
                    offset: request.offset,
                  },
                  signal,
                });
                return { items: page.contracts, total: page.total };
              }}
              rowId={(contract) => contract.hid}
              rowLink={(contract) => contractPath(contract.hid)}
            />
          ) : (
            <ItemsGrid
              id="renewals-overlapping"
              within={{ sort: within.sort }}
              shown={OVERLAPPING_COLUMNS}
              read={async (request, signal) => {
                const page = await api.request("get", "/api/v1/reports/renewals", {
                  query: {
                    ...query,
                    section: opened.section,
                    ...(request.sort.length > 0 ? { sort: request.sort } : {}),
                    limit: request.limit,
                    offset: request.offset,
                  },
                  signal,
                });
                return { items: page.items, total: page.total };
              }}
            />
          )}
        </>
      )}
    </section>
  );
}
