import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ContractContacts } from "../components/ContractContacts";
import {
  ContractsNav,
  contractSpecs,
  Dash,
  ENDS_WITH_TERM_NOTE,
  EndsWithTermMark,
  InForceValue,
  Lines,
  StatusMarks,
  SupportLink,
} from "../components/ContractParts";
import { ContractsTable } from "../components/ContractsTable";
import { ContractCoverage } from "../components/Coverage";
import { SelectField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem, StaleCause } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Renew } from "../components/Renew";
import { Retire } from "../components/Retire";
import { ContractTerms } from "../components/Terms";
import { Time } from "../components/Time";
import {
  agreementPath,
  beganByLabel,
  CONTRACT_STATUSES,
  type Contract,
  contractPath,
  coveredItemsPath,
  INHERITED,
  type Inherited,
  inForce,
  LAPSED,
  LAPSED_NOTE,
  nextTermText,
  periodText,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
  STANDALONE,
  staleCause,
} from "../lib/contracts";
import { effectiveLabel, effectiveText } from "../lib/effective";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY, useAgreementOptions, useMoney, useTags, useVendorOptions } from "../lib/lists";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { leftBehindText } from "../lib/renewals";
import { allows } from "../lib/roles";
import { amountText } from "../lib/summary";

type ContractRenewed = Schemas["ContractRenewed"];

/** What is said of a contract whose renewal has been pending too long. */
const OVERDUE_NOTE =
  "Pending for longer than the setting renewal_pending_overdue_days: somebody should ask why";

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
    // The agreement it is grouped into: blank for a contract that stands by itself.
    id: "agreement.name",
    header: "Agreement",
    kind: "text",
    column: "agreement",
    value: (contract) => contract.agreement?.name,
    linkTo: (contract) => (contract.agreement ? agreementPath(contract.agreement.hid) : null),
    width: 230,
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
    // While its renewal is pending: the days since the end of the term it is for.
    id: "renewal_pending_days",
    header: "Pending for",
    kind: "integer",
    value: (contract) =>
      contract.renewal_pending_days === null ? "" : String(contract.renewal_pending_days),
    hint: (contract) => (contract.renewal_overdue ? OVERDUE_NOTE : ""),
    numeric: true,
    hide: true,
    width: 120,
  },
  {
    id: "renewal_overdue",
    header: "Overdue",
    kind: "boolean",
    value: (contract) => (contract.renewal_overdue ? "Overdue" : ""),
    hint: (contract) => (contract.renewal_overdue ? OVERDUE_NOTE : ""),
    choices: [
      { value: "true", label: "Overdue: pending too long" },
      { value: "false", label: "Not overdue" },
    ],
    hide: true,
    width: 110,
  },
  {
    // Marked by the team not to renew (D-180): a note, which changes nothing by itself.
    id: "ends_with_term",
    header: "Not to be renewed",
    kind: "boolean",
    value: (contract) => (contract.ends_with_term ? "Yes" : ""),
    hint: (contract) => (contract.ends_with_term ? ENDS_WITH_TERM_NOTE : ""),
    choices: [
      { value: "true", label: "Marked not to renew" },
      { value: "false", label: "Not marked" },
    ],
    hide: true,
    width: 160,
  },
  {
    // Its period has ended and its status still says Active: it covers nothing, and
    // wants renewing or saying that it has expired.
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
    // The period in force: the contract's own dates, or its agreement's, shown lighter.
    id: "effective.starts_on",
    header: "Starts",
    kind: "date",
    column: "starts_on",
    value: (contract) => effectiveText(contract.effective.starts_on),
    effective: (contract) => contract.effective.starts_on,
    width: 130,
  },
  {
    id: "effective.ends_on",
    header: "Ends",
    kind: "date",
    column: "ends_on",
    value: (contract) => effectiveText(contract.effective.ends_on),
    effective: (contract) => contract.effective.ends_on,
    width: 130,
  },
  {
    // Active in both senses, and today is within its period in force.
    id: "covers_today",
    header: "Covers today",
    kind: "boolean",
    column: null,
    value: (contract) => (contract.covers_today ? "Yes" : "No"),
    width: 130,
  },
  {
    // How many items it covers today: counted by the server, and sorted by that count.
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
    id: "effective.support_level",
    header: "Support level",
    kind: "text",
    column: "support_level",
    value: (contract) => effectiveText(contract.effective.support_level),
    effective: (contract) => contract.effective.support_level,
    width: 200,
  },
  {
    id: "annual_cost",
    header: "Annual cost",
    kind: "number",
    value: (contract) => contract.annual_cost,
    numeric: true,
    width: 130,
  },
  {
    id: "purchase_reference",
    header: "Purchase reference",
    kind: "text",
    value: (contract) => contract.purchase_reference,
    hide: true,
    width: 170,
  },
  {
    // A renewal that is still to begin: the day its term starts, and the number it brings.
    id: "next_starts_on",
    header: "Next term starts",
    kind: "date",
    value: (contract) => contract.next_term?.starts_on,
    hint: (contract) => (contract.next_term ? nextTermText(contract.next_term) : ""),
    hide: true,
    width: 160,
  },
  {
    id: "next_number",
    header: "Next number",
    kind: "text",
    value: (contract) => contract.next_term?.number,
    hide: true,
    width: 170,
  },
  {
    // The contract's own reseller: the list knows no name for the one it has from its
    // agreement, which the page of the contract shows.
    id: "reseller",
    header: "Reseller of its own",
    kind: "text",
    value: (contract) => contract.reseller?.name,
    hide: true,
    width: 170,
  },
  {
    id: "effective.account_manager",
    header: "Account manager",
    kind: "text",
    column: "account_manager",
    value: (contract) => effectiveText(contract.effective.account_manager),
    effective: (contract) => contract.effective.account_manager,
    hide: true,
    width: 240,
  },
  {
    id: "effective.support_contact",
    header: "Support contact",
    kind: "text",
    column: "support_contact",
    value: (contract) => effectiveText(contract.effective.support_contact),
    effective: (contract) => contract.effective.support_contact,
    hide: true,
    width: 240,
  },
  {
    id: "effective.support_url",
    header: "Support URL",
    kind: "text",
    column: "support_url",
    value: (contract) => effectiveText(contract.effective.support_url),
    effective: (contract) => contract.effective.support_url,
    hide: true,
    width: 240,
  },
  { id: "notes", header: "Notes", kind: "text", value: (contract) => contract.notes, hide: true },
  {
    id: "tags",
    header: "Tags",
    kind: "tags",
    value: (contract) => contract.tags.join(", "),
    width: 150,
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
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (contract) => formatTime(contract.updated_at),
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

/** What the forms of this page choose from: the vendors and the tags. */
function useContractLists() {
  const vendors = useVendorOptions();
  const tags = useTags();
  const lists = useMemo(
    () => ({ vendors: vendors.data ?? [], tags: (tags.data ?? []).map((tag) => tag.label) }),
    [vendors.data, tags.data],
  );
  return { lists, loading: vendors.loading || tags.loading, error: vendors.error ?? tags.error };
}

/**
 * Contracts: the support agreements, each with the contracts grouped into it, the
 * contracts that stand by themselves, and the list of every contract with how many
 * items each covers.
 */
export function Contracts() {
  useTitle("Contracts");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const { lists, error } = useContractLists();
  const agreements = useAgreementOptions();
  const specs = useMemo<FieldSpec[]>(() => {
    const [number, ...rest] = contractSpecs(lists);
    return [
      ...(number ? [number] : []),
      {
        name: "agreement_hid",
        label: "Support agreement",
        kind: "choice",
        options: agreements.data ?? [],
        blank: "None: it stands by itself",
        hint: "The agreement it is grouped into. It then has from the agreement whatever it says nothing of: the period, the reseller, the support level and whom to ask.",
      },
      ...rest,
    ];
  }, [lists, agreements.data]);

  return (
    <>
      <ContractsNav />
      <h1>Contracts</h1>
      <p>
        A contract is one record that is applied to one item or to many. What is said of it is said
        here, once: an item under it holds only the link. A contract may be grouped into a support
        agreement, and then has from the agreement whatever it says nothing of.
      </p>
      <Problem error={error ?? agreements.error} />
      {adding && (
        <CreateForm<Schemas["ContractCreate"], Contract>
          title="New contract"
          specs={specs}
          start={{ status: "active", record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/contracts", { body })}
          onCreated={(contract) => navigate(contractPath(contract.hid))}
          onCancel={() => setAdding(false)}
          submitLabel="Create contract"
        />
      )}
      {startFilter === null && <Grouped />}
      <section aria-labelledby="all-contracts">
        <h2 id="all-contracts">{startFilter === null ? "Every contract" : "Contracts"}</h2>
        {startFilter !== null && (
          <p>
            <Link to="/contracts">Every contract, by agreement</Link>
          </p>
        )}
        <DataGrid<Contract>
          key={startFilter ?? ""}
          id="contracts"
          noun={["contract", "contracts"]}
          entity="contracts"
          columns={COLUMNS}
          load={(request, signal) =>
            api.request("get", "/api/v1/contracts", { query: queryParams(request), signal })
          }
          rowId={(contract) => contract.hid}
          rowLink={(contract) => contractPath(contract.hid)}
          dimmed={(contract) => contract.record_status !== "active"}
          shortFilter="status:eq:active agreement.name:contains:Enterprise"
          startFilter={startFilter}
          switches={{ archived: "Include archived", drafts: "Include drafts" }}
        >
          {allows(user.role, "inventory") && !adding && (
            <button type="button" className="primary" onClick={() => setAdding(true)}>
              New contract
            </button>
          )}
        </DataGrid>
      </section>
    </>
  );
}

/**
 * The agreements, each with the contracts grouped into it, and after them the contracts
 * that stand by themselves. It is read whole, and says so when there is more than it
 * reads: the grid beneath holds every contract in any case.
 */
function Grouped() {
  const found = useLoad("contracts-grouped", async (signal) => {
    const [agreements, contracts] = await Promise.all([
      api.request("get", "/api/v1/agreements", { query: { limit: EVERY }, signal }),
      api.request("get", "/api/v1/contracts", { query: { limit: EVERY }, signal }),
    ]);
    return { agreements, contracts };
  });
  const data = found.data;
  const alone = data?.contracts.items.filter((contract) => contract.agreement_hid === null) ?? [];
  const whole =
    data !== undefined &&
    data.agreements.total <= data.agreements.items.length &&
    data.contracts.total <= data.contracts.items.length;
  const lapsed = data?.contracts.items.filter((contract) => contract.lapsed).length ?? 0;

  return (
    <section aria-labelledby="by-agreement" data-testid="contracts-grouped">
      <h2 id="by-agreement">By support agreement</h2>
      <Problem error={found.error} />
      {found.loading && !data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {data && !whole && (
        <p className="warning">
          There are more agreements or contracts than are grouped here at once. The grid beneath
          holds all of them: filter it by <span className="mono">agreement.name</span>.
        </p>
      )}
      {lapsed > 0 && (
        <p className="warning" data-testid="lapsed-contracts" data-count={lapsed}>
          <Link to={`/contracts?filter=${encodeURIComponent(LAPSED)}`}>
            {plural(lapsed, "contract has", "contracts have")} lapsed
          </Link>
          : the period has ended and the status still says Active. A lapsed contract covers nothing:
          renew it, or say that it has expired.
        </p>
      )}
      {data && data.agreements.items.length === 0 && (
        <p className="muted">
          There is no support agreement yet. <Link to="/agreements">Support agreements</Link> are
          made on their own page.
        </p>
      )}
      {data?.agreements.items.map((agreement) => (
        <div key={agreement.hid} data-agreement={agreement.name} className="grouped">
          <h3>
            <Link to={agreementPath(agreement.hid)}>{agreement.name}</Link>
            <span className="muted">
              {" "}
              · {agreement.vendor.name}
              {agreement.number ? ` · ${agreement.number}` : ""} ·{" "}
              {periodText(agreement.starts_on, agreement.ends_on)}
            </span>
            <StatusMarks record={agreement} />
          </h3>
          <ContractsTable
            contracts={data.contracts.items.filter(
              (contract) => contract.agreement_hid === agreement.hid,
            )}
            agreement={agreement}
            empty={
              agreement.contracts > 0
                ? "Its contracts are not among those read here: see the grid beneath."
                : "No contract is grouped into it yet."
            }
          />
        </div>
      ))}
      {data && (
        <div data-agreement="" className="grouped">
          <h3 id="standalone">Contracts that stand by themselves</h3>
          <ContractsTable
            contracts={alone}
            agreement={null}
            empty="Every contract is grouped into an agreement."
          />
          {alone.length > 0 && (
            <p className="hint">
              A contract is rolled into an agreement on its own page, which is one change of that
              contract. In the grid they are found with{" "}
              <Link to={`/contracts?filter=${encodeURIComponent(STANDALONE)}`}>{STANDALONE}</Link>.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** Contracts → one contract: what it says, what it has from its agreement, and what it covers. */
export function ContractDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const contract = useLoad(`contract ${hid}`, (signal) =>
    api.request("get", "/api/v1/contracts/{hid}", { path: { hid }, signal }),
  );
  const record = contract.data;
  const { lists, loading: listsLoading, error: listsError } = useContractLists();
  const [done, setDone] = useState("");
  const [turn, setTurn] = useState(0);
  useTitle(record ? record.number : "Contract");
  const specs = useMemo(() => contractSpecs(lists, record ?? null), [lists, record]);
  const money = useMoney();

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    contract.reload();
  }

  const open = mayEdit && record?.record_status !== "retired";
  // Whom to go through while a renewal is pending: the account manager in force.
  const accountManager = record ? effectiveText(record.effective.account_manager) : "";
  return (
    <>
      <ContractsNav />
      <p className="crumbs">
        <Link to="/contracts">Contracts</Link>
        {record?.agreement && (
          <>
            {" "}
            <Link to={agreementPath(record.agreement.hid)}>{record.agreement.name}</Link>
          </>
        )}
      </p>
      <h1>
        {record ? record.number : "Contract"}
        {record && <StatusMarks record={record} always />}
      </h1>
      <Problem error={contract.error} />
      <Problem error={listsError} />
      <Notice text={done} />
      {contract.loading && !record && <p role="status">Loading…</p>}
      {record && (
        // A change of the contract that was read before its next term began is refused
        // as stale from that day: the forms of the record say so where it has one.
        <StaleCause value={staleCause(record, "contract")}>
          <section aria-labelledby="contract-facts">
            <h2 id="contract-facts">The contract</h2>
            <dl className="facts" data-testid="contract-facts">
              <dt>Number</dt>
              <dd data-testid="contract-number">{record.number}</dd>
              <dt>Vendor</dt>
              <dd>
                <Link to={`/vendors/${encodeURIComponent(record.vendor_hid)}`}>
                  {record.vendor.name}
                </Link>
              </dd>
              <dt>Support agreement</dt>
              <dd data-testid="contract-agreement">
                {record.agreement ? (
                  <Link to={agreementPath(record.agreement.hid)}>{record.agreement.name}</Link>
                ) : (
                  <span className="muted">None: it stands by itself</span>
                )}
              </dd>
              <dt>Status</dt>
              <dd data-testid="contract-status" data-status={record.status}>
                {optionLabel(CONTRACT_STATUSES, record.status)}
                {record.status === RENEWAL_PENDING && (
                  <span data-testid="renewal-pending">
                    {" "}
                    · the term has ended and the renewal is in procurement. Support is still given,
                    by escalation: go through the account manager
                    {accountManager ? ` (${accountManager})` : ""} before the support line is
                    called.
                  </span>
                )}
                <EndsWithTermMark contract={record} />
                {record.lapsed && (
                  <span className="badge" data-testid="lapsed" title={LAPSED_NOTE}>
                    Lapsed
                  </span>
                )}
              </dd>
              {record.lapsed && (
                <>
                  <dt>Lapsed</dt>
                  <dd>
                    Its period has ended and its status still says Active: it covers nothing. Renew
                    it, or say that it has expired, or that its renewal is pending.
                  </dd>
                </>
              )}
              {record.status === RENEWAL_PENDING && (
                <>
                  <dt>Pending for</dt>
                  <dd
                    data-testid="renewal-pending-days"
                    data-days={record.renewal_pending_days ?? ""}
                    data-overdue={record.renewal_overdue ? "true" : "false"}
                  >
                    {record.renewal_pending_days === null || record.renewal_pending_days === 0
                      ? "Its term has not ended yet"
                      : `${plural(record.renewal_pending_days, "day")} since the end of the term the renewal is for`}
                    {record.renewal_overdue && (
                      <span className="badge" data-mark="overdue" title={OVERDUE_NOTE}>
                        Overdue
                      </span>
                    )}
                  </dd>
                </>
              )}
              {record.ends_with_term && (
                <>
                  <dt>Not to be renewed</dt>
                  <dd data-testid="ends-with-term">{ENDS_WITH_TERM_NOTE}</dd>
                </>
              )}
              {record.next_term && (
                <>
                  <dt>Next term</dt>
                  <dd
                    data-testid="contract-next-term"
                    data-with-agreement={record.next_term.with_agreement ? "true" : "false"}
                  >
                    {nextTermText(record.next_term)}
                    <span className="muted">
                      {" "}
                      · until then the present number and period stay in force
                    </span>
                    {record.next_term.with_agreement && record.agreement && (
                      <span className="muted" data-testid="waits-on-agreement">
                        {" "}
                        · the new number waits on the next term of{" "}
                        <Link to={agreementPath(record.agreement.hid)}>
                          {record.agreement.name}
                        </Link>
                        , whose dates are shown, and begins when that term does
                      </span>
                    )}
                  </dd>
                </>
              )}
              {record.part_began_on && (
                <>
                  <dt>This part of its history</dt>
                  <dd
                    data-testid="contract-part"
                    data-began-on={record.part_began_on}
                    data-began-by={record.part_began_by ?? ""}
                  >
                    Since {record.part_began_on}
                    {record.part_began_by
                      ? `, begun by ${beganByLabel(record.part_began_by).toLowerCase()}`
                      : ""}
                  </dd>
                </>
              )}
              <dt>Covers today</dt>
              <dd data-testid="covers-today">
                {record.covers_today ? (
                  "Yes"
                ) : (
                  <>
                    No
                    <span className="muted">
                      {" "}
                      · it covers while it is active and its status is Active, within its period, or
                      while its renewal is pending
                    </span>
                  </>
                )}
              </dd>
              <dt>Items covered today</dt>
              <dd data-testid="covered-items">
                <Link to={coveredItemsPath(record.hid)}>
                  {plural(record.covered_items, "item")}
                </Link>
              </dd>
              <dt>Items in scope</dt>
              <dd data-testid="items-in-scope">
                {plural(record.items_in_scope, "item")}
                <span className="muted"> · those whose coverage under it has not been ended</span>
              </dd>
              <dt>Purchase reference</dt>
              <dd>{record.purchase_reference || <Dash />}</dd>
              <dt>Annual cost{money}</dt>
              <dd>{amountText(record.annual_cost) || <Dash />}</dd>
              <dt>Notes</dt>
              <dd>
                <Lines text={record.notes} />
              </dd>
              <dt>Tags</dt>
              <dd data-testid="contract-tags">{record.tags.join(", ") || <Dash />}</dd>
              <dt>Changed</dt>
              <dd>
                <Time at={record.updated_at} />
              </dd>
              <dt>HID</dt>
              <dd className="mono">{record.hid}</dd>
            </dl>
          </section>
          <InForce
            key={`in-force ${record.hid} ${record.row_version}`}
            contract={record}
            mayEdit={open}
            onChanged={changed}
            onReload={contract.reload}
          />
          <ContractContacts
            of="contract"
            record={record}
            name={record.number}
            agreement={record.agreement}
            mayEdit={mayEdit}
            onChanged={changed}
          />
          {open && (
            <InAgreement
              key={`agreement ${record.hid} ${record.row_version}`}
              contract={record}
              onChanged={changed}
              onReload={contract.reload}
            />
          )}
          {open && (
            <Renew<Contract, ContractRenewed>
              key={`renew ${record.hid} ${record.row_version}`}
              record={record}
              name={record.number}
              what="contract"
              follows={
                <p>
                  A renewal gives the contract its new number and its new period. It changes this
                  one record: <strong>{plural(record.items_in_scope, "item")}</strong> in scope{" "}
                  {record.items_in_scope === 1 ? "follows" : "follow"}, and nothing is written to
                  any of them. The term it has now is kept beneath, as its history.
                </p>
              }
              submitLabel={`Renew for ${plural(record.items_in_scope, "item")}`}
              note={
                record.agreement ? (
                  <p className="form-note">
                    {record.number} is in {record.agreement.name}. A date left blank here is the
                    agreement&apos;s: the contract then ends when the agreement does.
                  </p>
                ) : undefined
              }
              send={(body) =>
                api.request("post", "/api/v1/contracts/{hid}/renew", {
                  path: { hid: record.hid },
                  body,
                })
              }
              renewed={(after) =>
                `Renewed as ${after.number}, ${periodText(
                  after.effective.starts_on.value,
                  after.effective.ends_on.value,
                ).toLowerCase()}. ${plural(after.items_in_scope, "item follows", "items follow")}: nothing was written to ${after.items_in_scope === 1 ? "it" : "any of them"}.`
              }
              afterword={(after) => leftBehindText(after.left_behind)}
              onChanged={changed}
              onReload={contract.reload}
            />
          )}
          <ContractTerms contract={record} turn={turn} />
          <StaleCause value="">
            <ContractCoverage contract={record} mayEdit={mayEdit} onChanged={changed} />
          </StaleCause>
          {open && !listsLoading && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <p className="hint">
                A change here is a change of the one record: every item under the contract shows it
                at once, and nothing is written to any of them. For a new term, with its new number
                and its new period, use Renew, which keeps the term before as history.
              </p>
              <EditForm<Contract, Schemas["ContractPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={record}
                labels={{ next_ends_on: "The end of the next term" }}
                save={(body) =>
                  api.request("patch", "/api/v1/contracts/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The contract was saved.")}
                onReload={contract.reload}
              />
            </section>
          )}
          {mayEdit && (
            <Retire
              key={`status ${record.hid} ${record.row_version}`}
              what="contract"
              name={record.number}
              retired={record.record_status === "retired"}
              about="A retired contract covers nothing any more. Its coverages stay on record."
              retiredAbout="This contract is retired: it covers nothing. Its coverages are still on record, and brought back it covers again by its status and its period."
              retire={() =>
                api.request("post", "/api/v1/contracts/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/contracts/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={contract.reload}
            />
          )}
        </StaleCause>
      )}
    </>
  );
}

interface ChangeProps {
  contract: Contract;
  onChanged: (text: string) => void;
  onReload: () => void;
}

interface InForceProps extends ChangeProps {
  mayEdit: boolean;
}

/**
 * The period of a contract and whom to ask, as they are in force: each its own, or had
 * from the agreement it is in, or its own in place of what the agreement gives, which
 * the server answers beside it. An override is given up here, and the agreement then
 * speaks again.
 */
function InForce({ contract, mayEdit, onChanged, onReload }: InForceProps) {
  const action = useAction();
  const from = contract.agreement;

  async function giveUp(field: Inherited, label: string) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/contracts/{hid}", {
        path: { hid: contract.hid },
        body: { row_version: contract.row_version, [field]: null },
      }),
    );
    if (result.ok) {
      onChanged(`${contract.number} has the ${label.toLowerCase()} of ${from?.name} again.`);
    }
  }

  return (
    <section aria-labelledby="in-force">
      <h2 id="in-force">Period, and whom to ask</h2>
      {from ? (
        <p>
          What the contract says nothing of, it has from{" "}
          <Link to={agreementPath(from.hid)}>{from.name}</Link>: that is shown lighter, and marked
          Inherited. What is marked Overrides is the contract&apos;s own, in place of what the
          agreement gives, also where the two are the same: an override stays as it is when the
          agreement&apos;s changes. A contract with no dates of its own ends when its agreement
          does.
        </p>
      ) : (
        <p className="muted">
          The contract stands by itself: everything here is its own. Put into a support agreement,
          it has from the agreement whatever it says nothing of.
        </p>
      )}
      <Problem error={action.error} onReload={onReload} />
      <dl className="facts" data-testid="contract-in-force">
        {INHERITED.map(({ field, label }) => {
          const value = inForce(contract, field);
          return (
            <div key={field} className="fact-row" data-field={field} data-standing={value.standing}>
              <dt>{label}</dt>
              <dd>
                <InForceValue value={value} agreement={from}>
                  {field === "support_url" ? (
                    <SupportLink url={value.text} />
                  ) : field === "reseller_hid" ? (
                    effectiveLabel(contract.effective.reseller_hid)
                  ) : field === "account_manager" || field === "support_contact" ? (
                    <Lines text={value.text} />
                  ) : undefined}
                </InForceValue>
                {mayEdit && from && value.standing === "override" && (
                  <button
                    type="button"
                    className="again"
                    disabled={action.busy}
                    onClick={() => giveUp(field, label)}
                  >
                    Have the agreement&apos;s again
                    <span className="visually-hidden">: {label.toLowerCase()}</span>
                  </button>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

/**
 * Put the contract into a support agreement, or take it out of one. Either is one change
 * of the contract. What the contract says of its own stays, as overrides of what the
 * agreement has.
 */
function InAgreement({ contract, onChanged, onReload }: ChangeProps) {
  const agreements = useAgreementOptions();
  const [chosen, setChosen] = useState("");
  const action = useAction();
  const refused = fieldErrors(action.error, ["agreement_hid"]).shown;
  // A contract is grouped into an agreement with its own vendor.
  const offered = (agreements.data ?? []).filter(
    (option) => option.vendorHid === contract.vendor_hid && option.value !== contract.agreement_hid,
  );

  async function send(agreementHid: string | null, done: string) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/contracts/{hid}", {
        path: { hid: contract.hid },
        body: { row_version: contract.row_version, agreement_hid: agreementHid },
      }),
    );
    if (result.ok) onChanged(done.replace("{name}", result.value.agreement?.name ?? ""));
  }

  return (
    <section aria-labelledby="in-agreement">
      <h2 id="in-agreement">Support agreement</h2>
      <p className="hint">
        {contract.agreement
          ? `${contract.number} is grouped into ${contract.agreement.name}. Taken out, it stands by itself, and has only what it says of its own.`
          : "A contract is rolled into an agreement with its own vendor. What it says of its own stays, as overrides: clear them where the agreement should speak."}
      </p>
      <Problem
        error={action.error ?? agreements.error}
        shown={["agreement_hid"]}
        onReload={onReload}
      />
      <div className="fields">
        <SelectField
          label={contract.agreement ? "Move it to another agreement" : "Put it into"}
          name="agreement_hid"
          value={chosen}
          onChange={setChosen}
          disabled={action.busy}
          error={refused.agreement_hid}
          hint={
            agreements.data && offered.length === 0
              ? `There is no ${contract.agreement ? "other " : ""}agreement with ${contract.vendor.name}.`
              : `The agreements with ${contract.vendor.name}.`
          }
        >
          <option value="">Choose an agreement</option>
          {offered.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <p className="actions">
        <button
          type="button"
          className="primary"
          disabled={action.busy || chosen === ""}
          onClick={() => send(chosen, `${contract.number} is now grouped into {name}.`)}
        >
          Put into the agreement
        </button>
        {contract.agreement && (
          <button
            type="button"
            disabled={action.busy}
            onClick={() =>
              send(
                null,
                `${contract.number} was taken out of ${contract.agreement?.name}: it stands by itself.`,
              )
            }
          >
            Take out of {contract.agreement.name}
          </button>
        )}
      </p>
    </section>
  );
}
