import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { ContractContacts } from "../components/ContractContacts";
import {
  agreementSpecs,
  ContractsNav,
  contractSpecs,
  Dash,
  EndsWithTermMark,
  Lines,
  StatusMarks,
  SupportLink,
} from "../components/ContractParts";
import { SelectField, TextField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem, StaleCause } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Renew } from "../components/Renew";
import { Retire } from "../components/Retire";
import { SortTh } from "../components/SortTh";
import { AgreementTerms } from "../components/Terms";
import { Time } from "../components/Time";
import {
  type Agreement,
  agreementPath,
  CONTRACT_STATUSES,
  type Contract,
  contractPath,
  contractsOfPath,
  costCounted,
  costTotal,
  INHERITED,
  inForce,
  LAPSED_NOTE,
  nextTermText,
  periodText,
  staleCause,
} from "../lib/contracts";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { type Loaded, toApiError, useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY, useMoney, useTags, useVendorOptions } from "../lib/lists";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import {
  applyToSelected,
  type ForSelected,
  leftBehindText,
  MEMBER_CHOICES,
  type MemberDraft,
  memberDrafts,
  memberLabels,
  membersBody,
  membersText,
  membersToReviewText,
  toConfirm,
  toReviewText,
  type Update,
  type Updated,
  updatedText,
} from "../lib/renewals";

/** The values of the statuses of a contract, to read a choice of one back. */
const CONTRACT_STATUS_VALUES = CONTRACT_STATUSES.map((one) => one.value as Contract["status"]);

import { allows } from "../lib/roles";
import { amountText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";
import { oneLink, page } from "../lib/valueLinks";

type AgreementRenewed = Schemas["AgreementRenewed"];
type ContractRef = Schemas["ContractRef"];

const COLUMNS: GridColumn<Agreement>[] = [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (agreement) => agreement.name,
    link: true,
    width: 260,
  },
  {
    id: "number",
    header: "Number",
    kind: "text",
    value: (agreement) => agreement.number,
    width: 150,
  },
  {
    id: "vendor",
    header: "Vendor",
    kind: "text",
    value: (agreement) => agreement.vendor.name,
    links: (agreement) => oneLink(agreement.vendor.name, page("vendor", agreement.vendor.hid)),
    width: 140,
  },
  {
    id: "account_manager",
    header: "Account manager",
    kind: "text",
    value: (agreement) => agreement.account_manager,
    // 0.9.6 (P-212): shown from the start, beside the vendor: whom to go through is the question most asked.
    width: 240,
  },
  {
    id: "status",
    header: "Status",
    kind: "choice",
    value: (agreement) => optionLabel(CONTRACT_STATUSES, agreement.status),
    choices: CONTRACT_STATUSES,
    width: 150,
  },
  {
    // Its period has ended and its status still says Active.
    id: "lapsed",
    header: "Lapsed",
    kind: "boolean",
    column: null,
    value: (agreement) => (agreement.lapsed ? "Lapsed" : ""),
    hint: (agreement) => (agreement.lapsed ? LAPSED_NOTE : ""),
    choices: [
      { value: "true", label: "Lapsed: ended, and still says Active" },
      { value: "false", label: "Not lapsed" },
    ],
    width: 100,
  },
  {
    // A renewal that is still to begin: the day its term starts.
    id: "next_starts_on",
    header: "Next term starts",
    kind: "date",
    value: (agreement) => agreement.next_term?.starts_on,
    hint: (agreement) => (agreement.next_term ? nextTermText(agreement.next_term) : ""),
    hide: true,
    width: 160,
  },
  {
    id: "starts_on",
    header: "Starts",
    kind: "date",
    value: (agreement) => agreement.starts_on,
    width: 130,
  },
  {
    id: "ends_on",
    header: "Ends",
    kind: "date",
    value: (agreement) => agreement.ends_on,
    width: 130,
  },
  {
    // How many contracts that are not retired it groups: counted by the server.
    id: "contracts",
    header: "Contracts",
    kind: "integer",
    field: null,
    sortField: "contracts",
    value: (agreement) => String(agreement.contracts),
    numeric: true,
    width: 120,
  },
  {
    id: "support_level",
    header: "Support level",
    kind: "text",
    value: (agreement) => agreement.support_level,
    width: 200,
  },
  {
    id: "reseller",
    header: "Reseller",
    kind: "text",
    value: (agreement) => agreement.reseller?.name,
    links: (agreement) =>
      oneLink(agreement.reseller?.name, page("vendor", agreement.reseller?.hid)),
    width: 160,
  },
  {
    id: "annual_cost",
    header: "Annual cost",
    kind: "number",
    value: (agreement) => agreement.annual_cost,
    numeric: true,
    width: 130,
  },
  {
    id: "purchase_reference",
    header: "Purchase reference",
    kind: "text",
    value: (agreement) => agreement.purchase_reference,
    hide: true,
  },
  {
    id: "support_contact",
    header: "Support contact",
    kind: "text",
    value: (agreement) => agreement.support_contact,
    hide: true,
    width: 240,
  },
  {
    id: "support_url",
    header: "Support URL",
    kind: "text",
    value: (agreement) => agreement.support_url,
    hide: true,
    width: 240,
  },
  { id: "notes", header: "Notes", kind: "text", value: (agreement) => agreement.notes, hide: true },
  {
    id: "tags",
    header: "Tags",
    kind: "tags",
    value: (agreement) => agreement.tags.join(", "),
    width: 150,
  },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (agreement) => optionLabel(RECORD_STATUSES, agreement.record_status),
    choices: RECORD_STATUSES,
    hide: true,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (agreement) => formatTime(agreement.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (agreement) => agreement.hid,
    mono: true,
    hide: true,
  },
];

function useLists() {
  const vendors = useVendorOptions();
  const tags = useTags();
  const lists = useMemo(
    () => ({ vendors: vendors.data ?? [], tags: (tags.data ?? []).map((tag) => tag.label) }),
    [vendors.data, tags.data],
  );
  return { lists, loading: vendors.loading || tags.loading, error: vendors.error ?? tags.error };
}

/**
 * Support agreements: an enterprise agreement or the like, between the organization and
 * a vendor, that groups support contracts and says once what they share.
 */
export function Agreements() {
  useTitle("Support agreements");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const { lists, error } = useLists();
  const specs = useMemo(() => agreementSpecs(lists), [lists]);

  return (
    <>
      <ContractsNav />
      <h1>Support agreements</h1>
      <p>
        A support agreement groups the contracts that are under it, and says once what they share:
        the period, the reseller, the support level and whom to ask. A contract in it has each of
        those from the agreement unless it says its own.
      </p>
      <Problem error={error} />
      {adding && (
        <CreateForm<Schemas["AgreementCreate"], Agreement>
          title="New support agreement"
          specs={specs}
          start={{ status: "active", record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/agreements", { body })}
          onCreated={(agreement) => navigate(agreementPath(agreement.hid))}
          onCancel={() => setAdding(false)}
          submitLabel="Create agreement"
        />
      )}
      <DataGrid<Agreement>
        key={startFilter ?? ""}
        id="agreements"
        noun={["agreement", "agreements"]}
        entity="agreements"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/agreements", { query: queryParams(request), signal })
        }
        rowId={(agreement) => agreement.hid}
        rowLink={(agreement) => agreementPath(agreement.hid)}
        dimmed={(agreement) => agreement.record_status !== "active"}
        shortFilter="vendor:eq:Cisco status:eq:active"
        quickFields={["name", "number"]}
        startFilter={startFilter}
        switches={{ archived: "Include archived", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New agreement
          </button>
        )}
      </DataGrid>
    </>
  );
}

/**
 * Support agreements → one agreement: its fields and tags, its contracts with what each
 * has from it and what each overrides, and the terms it had before: its purchase history.
 */
export function AgreementDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const agreement = useLoad(`agreement ${hid}`, (signal) =>
    api.request("get", "/api/v1/agreements/{hid}", { path: { hid }, signal }),
  );
  const { lists, loading: listsLoading, error: listsError } = useLists();
  const [done, setDone] = useState("");
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState(false);
  // The members the last renewal made here left to be reviewed, as it answered them.
  const [review, setReview] = useState<ContractRef[]>([]);
  // The contracts selected on the page, for Update selected: one selection for its
  // contracts and for its members to review.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const selection: Selection = {
    selected,
    pick: (hid, on) =>
      setSelected((was) => {
        const next = new Set(was);
        if (on) next.add(hid);
        else next.delete(hid);
        return next;
      }),
    set: (hids) => setSelected(new Set(hids)),
  };
  const record = agreement.data;
  useTitle(record ? record.name : "Support agreement");
  const specs = useMemo(() => agreementSpecs(lists, record ?? null), [lists, record]);
  // A contract made here is in this agreement, and with its vendor: neither is asked for.
  const contractForm = useMemo(
    () => contractSpecs(lists).filter((spec) => spec.name !== "vendor_hid"),
    [lists],
  );
  const money = useMoney();
  const navigate = useNavigate();
  // Its contracts, read once for the table of them and for the form of a renewal.
  const contracts = useLoad(
    `agreement-contracts ${hid} ${record?.row_version ?? ""} ${turn}`,
    (signal) =>
      api.request("get", "/api/v1/contracts", {
        query: { filter: `agreement_hid:eq:${hid}`, limit: EVERY, include_drafts: true },
        signal,
      }),
  );

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    agreement.reload();
  }

  const open = mayEdit && record?.record_status !== "retired";
  return (
    <>
      <ContractsNav />
      <p className="crumbs">
        <Link to="/agreements">Support agreements</Link>
      </p>
      <h1>
        {record ? record.name : "Support agreement"}
        {record && <StatusMarks record={record} always />}
      </h1>
      <Problem error={agreement.error} />
      <Problem error={listsError} />
      <Notice text={done} />
      {agreement.loading && !record && <p role="status">Loading…</p>}
      {record && (
        // A change of the agreement that was read before its next term began is refused
        // as stale from that day: the forms of the record say so where it has one.
        <StaleCause value={staleCause(record, "agreement")}>
          <section aria-labelledby="agreement-facts">
            <h2 id="agreement-facts">The agreement</h2>
            <dl className="facts" data-testid="agreement-facts">
              <dt>Name</dt>
              <dd>{record.name}</dd>
              <dt>Number</dt>
              <dd>{record.number || <Dash />}</dd>
              <dt>Vendor</dt>
              <dd>
                <Link to={`/vendors/${encodeURIComponent(record.vendor_hid)}`}>
                  {record.vendor.name}
                </Link>
              </dd>
              <dt>Status</dt>
              <dd>
                {optionLabel(CONTRACT_STATUSES, record.status)}
                <span className="muted">
                  {" "}
                  · what a person says of it: a contract covers by its own status
                </span>
                {record.lapsed && (
                  <span className="badge" data-testid="lapsed" title={LAPSED_NOTE}>
                    Lapsed
                  </span>
                )}
              </dd>
              <dt>Period</dt>
              <dd data-testid="agreement-period">{periodText(record.starts_on, record.ends_on)}</dd>
              {record.next_term && (
                <>
                  <dt>Next term</dt>
                  <dd data-testid="agreement-next-term">
                    {nextTermText(record.next_term)}
                    <span className="muted">
                      {" "}
                      · until then the present number and period stay in force
                    </span>
                  </dd>
                </>
              )}
              <dt>Reseller</dt>
              <dd>
                {record.reseller ? (
                  <Link to={`/vendors/${encodeURIComponent(record.reseller.hid)}`}>
                    {record.reseller.name}
                  </Link>
                ) : (
                  <Dash />
                )}
              </dd>
              <dt>Support level</dt>
              <dd>{record.support_level || <Dash />}</dd>
              <dt>Account manager</dt>
              <dd>
                <Lines text={record.account_manager} />
              </dd>
              <dt>Support contact</dt>
              <dd>
                <Lines text={record.support_contact} />
              </dd>
              <dt>Support URL</dt>
              <dd>
                <SupportLink url={record.support_url} />
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
              <dd data-testid="agreement-tags">{record.tags.join(", ") || <Dash />}</dd>
              <dt>Changed</dt>
              <dd>
                <Time at={record.updated_at} />
              </dd>
              <dt>HID</dt>
              <dd className="mono">{record.hid}</dd>
            </dl>
          </section>
          <ContractContacts
            of="agreement"
            record={record}
            name={record.name}
            mayEdit={mayEdit}
            onChanged={changed}
          />
          <AgreementContracts
            agreement={record}
            found={contracts}
            {...(open ? { selection } : {})}
          />
          {open && (
            <UpdateSelected
              agreement={record}
              selected={selected}
              contracts={contracts.data?.items}
              onDone={(text) => {
                setSelected(new Set());
                changed(text);
              }}
            />
          )}
          {open && !adding && (
            <p className="actions">
              <button type="button" onClick={() => setAdding(true)}>
                New contract in this agreement
              </button>
            </p>
          )}
          {open && adding && (
            <CreateForm<Schemas["ContractCreate"], Contract>
              title={`New contract in ${record.name}`}
              specs={contractForm}
              start={{ status: "active", record_status: "active" }}
              create={(body) =>
                api.request("post", "/api/v1/contracts", {
                  body: { ...body, agreement_hid: record.hid },
                })
              }
              onCreated={(contract) => navigate(contractPath(contract.hid))}
              onCancel={() => setAdding(false)}
              submitLabel="Create contract"
            >
              <p className="hint">
                It is with {record.vendor.name}, as the agreement is. Whatever is left blank of the
                period, the reseller, the support level and whom to ask, it has from the agreement.
              </p>
            </CreateForm>
          )}
          {review.length > 0 && (
            <ReviewAfterRenewal members={review} onClose={() => setReview([])} />
          )}
          <MembersToReview
            agreement={record}
            contracts={contracts.data?.items}
            mayEdit={open}
            selection={selection}
            onChanged={changed}
            onDone={(text) => {
              setSelected(new Set());
              changed(text);
            }}
          />
          {open && (
            <AgreementRenew
              key={`renew ${record.hid} ${record.row_version}`}
              agreement={record}
              contracts={contracts.data?.items}
              onReview={(members) => setReview([...members])}
              onChanged={changed}
              onReload={agreement.reload}
            />
          )}
          <AgreementTerms agreement={record} turn={turn} />
          {open && !listsLoading && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <p className="hint">
                A change of what its contracts have from it reaches every contract that says nothing
                of its own, and every item under those contracts, at once: nothing is written to any
                of them.
              </p>
              <EditForm<Agreement, Schemas["AgreementPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={record}
                labels={{ next_ends_on: "The end of the next term" }}
                save={(body) =>
                  api.request("patch", "/api/v1/agreements/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The agreement was saved.")}
                onReload={agreement.reload}
              />
            </section>
          )}
          {mayEdit && (
            <Retire
              key={`status ${record.hid} ${record.row_version}`}
              what="agreement"
              name={record.name}
              retired={record.record_status === "retired"}
              about={`An agreement is retired once no contract that is not retired is in it. ${plural(record.contracts, "contract is", "contracts are")} in it now.`}
              retiredAbout="This agreement is retired. It groups no contract any more."
              retire={() =>
                api.request("post", "/api/v1/agreements/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/agreements/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={agreement.reload}
            />
          )}
        </StaleCause>
      )}
    </>
  );
}

/**
 * The contracts grouped into an agreement, each with what it has in force of the fields
 * a contract may have from its agreement: lighter where it is the agreement's, and
 * marked where it is the contract's own in place of what the agreement has.
 */
function AgreementContracts({
  agreement,
  found,
  selection,
}: {
  agreement: Agreement;
  found: Loaded<{ items: Contract[]; total: number }>;
  /** The contracts selected for Update selected, for one who may change them. */
  selection?: Selection;
}) {
  const rows = found.data?.items ?? [];
  const money = useMoney();
  const sorting = useSorting(rows, {
    number: (contract) => contract.number,
    status: (contract) => optionLabel(CONTRACT_STATUSES, contract.status),
    covered: (contract) => contract.covered_items,
    cost: (contract) => (contract.annual_cost === null ? null : Number(contract.annual_cost)),
    ...Object.fromEntries(
      INHERITED.map(({ field }) => [field, (contract: Contract) => inForce(contract, field).text]),
    ),
  });
  const holdsAll = found.data !== undefined && found.data.total <= rows.length;
  // 0.9.6 (P-215): what its contracts cost a year together, beside the agreement's own
  // figure: each its own cost in force, a draft and a contract cancelled or expired left out.
  const { counted, drafts, ended } = costCounted(rows);
  const cost = costTotal(counted.map((contract) => contract.annual_cost));

  return (
    <section aria-labelledby="agreement-contracts">
      <h2 id="agreement-contracts">Its contracts</h2>
      <p>
        What a contract says nothing of, it has from this agreement: that is shown lighter. What is
        marked Overrides is the contract&apos;s own, in place of what the agreement gives, also
        where the two are the same. Its number, its status, its purchase reference, its cost and its
        notes are always its own.
      </p>
      <Problem error={found.error} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {found.data && rows.length === 0 && (
        <p className="muted">No contract is grouped into it yet.</p>
      )}
      {found.data && !holdsAll && (
        <p className="warning">
          It groups more contracts than are shown here at once.{" "}
          <Link to={contractsOfPath(agreement.hid)}>All of them, in the grid of contracts</Link>.
        </p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="agreement-contracts">
            <caption className="visually-hidden">
              The contracts grouped into {agreement.name}, each with what it has from the agreement
              and what it overrides
            </caption>
            <thead>
              <tr>
                {selection && (
                  <th scope="col">
                    <SelectAll rows={rows} selection={selection} label="Select every contract" />
                  </th>
                )}
                <SortTh sort={sorting} column="number">
                  Number
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="covered" className="number">
                  Items covered
                </SortTh>
                <SortTh sort={sorting} column="cost" className="number">
                  Annual cost{money}
                </SortTh>
                {INHERITED.map(({ field, label }) => (
                  <SortTh sort={sorting} column={field} key={field}>
                    {label}
                  </SortTh>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((contract) => (
                <tr
                  key={contract.hid}
                  data-contract={contract.number}
                  className={contract.record_status === "active" ? undefined : "muted"}
                >
                  {selection && (
                    <td>
                      <SelectOne
                        hid={contract.hid}
                        number={contract.number}
                        selection={selection}
                      />
                    </td>
                  )}
                  <th scope="row">
                    <Link to={contractPath(contract.hid)}>{contract.number}</Link>
                    {contract.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, contract.record_status)}
                      </span>
                    )}
                  </th>
                  <td data-status={contract.status}>
                    {optionLabel(CONTRACT_STATUSES, contract.status)}
                    {contract.lapsed && (
                      <span className="badge" data-mark="lapsed" title={LAPSED_NOTE}>
                        Lapsed
                      </span>
                    )}
                    <EndsWithTermMark contract={contract} />
                  </td>
                  <td className="number">{contract.covered_items}</td>
                  <td className="number" data-field="annual_cost">
                    {amountText(contract.annual_cost) || <Dash />}
                  </td>
                  {INHERITED.map(({ field }) => {
                    const value = inForce(contract, field);
                    return (
                      <td
                        key={field}
                        data-field={field}
                        data-standing={value.standing}
                        {...(value.standing === "override"
                          ? { "data-same": value.same ? "true" : "false" }
                          : {})}
                        className={value.standing === "inherited" ? "inherited" : undefined}
                      >
                        {value.standing === "none" ? (
                          <Dash />
                        ) : (
                          <>
                            {value.text}
                            {value.standing === "inherited" && (
                              <span className="visually-hidden"> (inherited)</span>
                            )}
                            {value.standing === "override" && (
                              <>
                                {" "}
                                <span
                                  className="badge mark"
                                  title={
                                    value.same
                                      ? `The same as ${value.overridden}, which the agreement gives: set here, it stays as it is when the agreement's changes`
                                      : `In place of ${value.overridden}, which the agreement gives`
                                  }
                                >
                                  Overrides
                                </span>
                                <span className="visually-hidden">
                                  {value.same
                                    ? ", the same as the agreement gives"
                                    : `, in place of ${value.overridden}`}
                                </span>
                              </>
                            )}
                          </>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr data-testid="agreement-contracts-total" data-total={cost.total}>
                <th scope="row" colSpan={selection ? 4 : 3}>
                  What its {plural(cost.counted + cost.none, "contract")} cost a year
                </th>
                <td className="number" data-field="annual_cost">
                  {amountText(cost.total)}
                </td>
                <td colSpan={INHERITED.length} className="muted" data-testid="agreement-own-cost">
                  The agreement&apos;s own: {amountText(agreement.annual_cost) || "none is given"}.
                  {cost.none > 0 &&
                    ` ${plural(cost.none, "contract has", "contracts have")} no cost, and ${cost.none === 1 ? "counts" : "count"} as none.`}
                  {drafts > 0 && ` ${plural(drafts, "draft is", "drafts are")} not counted.`}
                  {ended > 0 &&
                    ` ${plural(ended, "contract is", "contracts are")} cancelled or expired, and not counted.`}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  );
}

interface AgreementRenewProps {
  agreement: Agreement;
  /** Its contracts, as they were read: the members are those that share its period. */
  contracts: readonly Contract[] | undefined;
  /** Told the members the renewal left to be reviewed. */
  onReview: (members: readonly ContractRef[]) => void;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * Renew an agreement, with what the renewal does with each contract that shares its
 * period: keep its number, the default, take a new number that begins with the new
 * term, or end with this term (D-173, D-180). The answer says what was done with each,
 * and how many coverages of items not to be renewed were left behind.
 */
function AgreementRenew(props: AgreementRenewProps) {
  const { agreement, contracts, onReview, onChanged, onReload } = props;
  // What the person chose for each member; until then, the members as they were read,
  // which may arrive after the form was opened.
  const [edited, setEdited] = useState<MemberDraft[] | null>(null);
  const drafts = edited ?? memberDrafts(contracts ?? []);
  const numbers = Object.fromEntries((contracts ?? []).map((one) => [one.hid, one.number]));
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [forSelected, setForSelected] = useState<ForSelected>({ choice: "", status: "" });
  const sorting = useSorting(drafts, {
    number: (draft) => draft.number,
    covered: (draft) => draft.covered,
    current: (draft) => optionLabel(CONTRACT_STATUSES, draft.current),
    choice: (draft) => MEMBER_CHOICES.findIndex((one) => one.value === draft.choice),
    status: (draft) => (draft.status === "" ? null : optionLabel(CONTRACT_STATUSES, draft.status)),
  });
  const all = drafts.length > 0 && drafts.every((draft) => selected.has(draft.hid));
  const confirming = drafts.filter(toConfirm).length;

  function change(hid: string, part: Partial<MemberDraft>) {
    setEdited(drafts.map((draft) => (draft.hid === hid ? { ...draft, ...part } : draft)));
  }

  function pick(hid: string, on: boolean) {
    setSelected((was) => {
      const next = new Set(was);
      if (on) next.add(hid);
      else next.delete(hid);
      return next;
    });
  }

  const form = (
    <fieldset className="stack" data-testid="renew-members">
      <legend>The contracts that share its period</legend>
      {contracts === undefined ? (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      ) : drafts.length === 0 ? (
        <p className="muted" data-testid="renew-members-none">
          No contract shares its period: every contract in it has an end of its own, or is retired.
        </p>
      ) : (
        <>
          <p className="hint">
            Each contract in it that is not retired and whose end is the agreement&apos;s, having no
            end of its own, shares its period, whatever its start. For each, say what the renewal
            does with it, and confirm the status of each that moves forward: the renewal changes no
            member&apos;s status but the one chosen here, and one that still says Renewal pending or
            Expired is listed to be reviewed afterwards. Select several to set them at once.{" "}
            {MEMBER_CHOICES.map((one) => `${one.label}: ${one.about}`).join(" ")}
          </p>
          {confirming > 0 && (
            <p className="warning" data-testid="renew-members-to-confirm" data-count={confirming}>
              {plural(confirming, "member still says", "members still say")} Renewal pending or
              Expired: set Active for each that moves forward with the new term.
            </p>
          )}
          <div className="inline" data-testid="renew-members-toolbar">
            <SelectField
              label="For those selected: with the renewal"
              name="selected-choice"
              value={forSelected.choice}
              onChange={(next) =>
                setForSelected((was) => ({
                  ...was,
                  choice: MEMBER_CHOICES.find((one) => one.value === next)?.value ?? "",
                }))
              }
            >
              <option value="">As each is set</option>
              {MEMBER_CHOICES.map((one) => (
                <option key={one.value} value={one.value}>
                  {one.label}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="For those selected: status from the renewal"
              name="selected-status"
              value={forSelected.status}
              onChange={(next) =>
                setForSelected((was) => ({
                  ...was,
                  status:
                    next === "keep"
                      ? "keep"
                      : (CONTRACT_STATUS_VALUES.find((one) => one === next) ?? ""),
                }))
              }
            >
              <option value="">As each is set</option>
              <option value="keep">Leave it as it is</option>
              {CONTRACT_STATUSES.map((one) => (
                <option key={one.value} value={one.value}>
                  {one.label}
                </option>
              ))}
            </SelectField>
            <button
              type="button"
              disabled={
                selected.size === 0 || (forSelected.choice === "" && forSelected.status === "")
              }
              onClick={() => setEdited(applyToSelected(drafts, selected, forSelected))}
            >
              Apply to {plural(selected.size, "selected member", "selected members")}
            </button>
          </div>
          <div className="scroll">
            <table data-testid="renew-members-table">
              <caption className="visually-hidden">
                The contracts that share the period of {agreement.name}, each with what the renewal
                does with it and the status it is to have
              </caption>
              <thead>
                <tr>
                  <th scope="col">
                    <input
                      type="checkbox"
                      aria-label="Select every member"
                      checked={all}
                      onChange={(event) =>
                        setSelected(
                          event.currentTarget.checked
                            ? new Set(drafts.map((draft) => draft.hid))
                            : new Set(),
                        )
                      }
                    />
                  </th>
                  <SortTh sort={sorting} column="number">
                    Contract
                  </SortTh>
                  <SortTh sort={sorting} column="covered" className="number">
                    Items covered
                  </SortTh>
                  <SortTh sort={sorting} column="current">
                    Status now
                  </SortTh>
                  <SortTh sort={sorting} column="choice">
                    With the renewal
                  </SortTh>
                  <SortTh sort={sorting} column="status">
                    Status from the renewal
                  </SortTh>
                  <th scope="col">Its new term</th>
                </tr>
              </thead>
              <tbody>
                {sorting.rows.map((draft) => (
                  <tr
                    key={draft.hid}
                    data-member={draft.number}
                    data-choice={draft.choice}
                    data-status={draft.status}
                    data-current={draft.current}
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${draft.number}`}
                        checked={selected.has(draft.hid)}
                        onChange={(event) => pick(draft.hid, event.currentTarget.checked)}
                      />
                    </td>
                    <th scope="row">
                      {draft.number}
                      {draft.marked && <EndsWithTermMark contract={{ ends_with_term: true }} />}
                    </th>
                    <td className="number">{draft.covered}</td>
                    <td>
                      {optionLabel(CONTRACT_STATUSES, draft.current)}
                      {toConfirm(draft) && (
                        <span
                          className="badge"
                          data-mark="to-confirm"
                          title="Set Active here if it moves forward with the new term: the renewal changes no status by itself"
                        >
                          To confirm
                        </span>
                      )}
                    </td>
                    <td>
                      <SelectField
                        label={`What the renewal does with ${draft.number}`}
                        name={`member-${draft.hid}`}
                        value={draft.choice}
                        onChange={(next) =>
                          change(draft.hid, {
                            choice:
                              MEMBER_CHOICES.find((one) => one.value === next)?.value ?? "same",
                          })
                        }
                      >
                        {MEMBER_CHOICES.map((one) => (
                          <option key={one.value} value={one.value}>
                            {one.label}
                          </option>
                        ))}
                      </SelectField>
                    </td>
                    <td>
                      <SelectField
                        label={`Status of ${draft.number} from the renewal`}
                        name={`member-status-${draft.hid}`}
                        value={draft.status}
                        onChange={(next) =>
                          change(draft.hid, {
                            status: CONTRACT_STATUS_VALUES.find((one) => one === next) ?? "",
                          })
                        }
                      >
                        <option value="">Leave it as it is</option>
                        {CONTRACT_STATUSES.map((one) => (
                          <option key={one.value} value={one.value}>
                            {one.label}
                          </option>
                        ))}
                      </SelectField>
                    </td>
                    <td>
                      {draft.choice === "new_number" ? (
                        <div className="fields">
                          <TextField
                            label={`New number of ${draft.number}`}
                            name={`member-number-${draft.hid}`}
                            value={draft.newNumber}
                            onChange={(next) => change(draft.hid, { newNumber: next })}
                            autoComplete="off"
                            required
                          />
                          <TextField
                            label={`Annual cost of ${draft.number}`}
                            name={`member-cost-${draft.hid}`}
                            value={draft.annualCost}
                            onChange={(next) => change(draft.hid, { annualCost: next })}
                            inputMode="decimal"
                            autoComplete="off"
                          />
                          <TextField
                            label={`Purchase reference of ${draft.number}`}
                            name={`member-reference-${draft.hid}`}
                            value={draft.purchaseReference}
                            onChange={(next) => change(draft.hid, { purchaseReference: next })}
                            autoComplete="off"
                          />
                        </div>
                      ) : (
                        <span className="muted">
                          {draft.choice === "ends"
                            ? "Ends with the present term, and covers to its end"
                            : "Its number, in the new term"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </fieldset>
  );

  return (
    <Renew<Agreement, AgreementRenewed>
      record={agreement}
      name={agreement.name}
      what="agreement"
      follows={
        <p>
          A renewal gives the agreement its new period, and its new number where it has one. Each
          contract that shares its period, having no end of its own, keeps its number and follows,
          takes a new number that begins with the new term, or ends with this term: the form asks
          for each. Every item under one that follows follows too, and nothing is written to any of
          them; an item not to be renewed is left behind, its coverage ending with the present term.
          No member&apos;s status is changed: one that still says Renewal pending or Expired is
          listed to be reviewed.
        </p>
      }
      submitLabel="Renew the agreement"
      more={{
        form,
        body: () => {
          if (contracts === undefined) {
            return { ok: false, error: "Its contracts are still being read: wait a moment." };
          }
          const members = membersBody(drafts);
          return members.ok ? { ok: true, value: { members: members.value } } : members;
        },
        labels: memberLabels(drafts),
      }}
      send={(body) =>
        api.request("post", "/api/v1/agreements/{hid}/renew", {
          path: { hid: agreement.hid },
          body,
        })
      }
      renewed={(after) =>
        `${after.name} was renewed: ${periodText(after.starts_on, after.ends_on).toLowerCase()}. The contracts that are co-termed with it follow.`
      }
      afterword={(after) =>
        [
          membersText(after.members, numbers),
          leftBehindText(after.left_behind),
          toReviewText(after.to_review.length),
        ]
          .filter(Boolean)
          .join(" ")
      }
      onRenewed={(after) => onReview(after.to_review)}
      onChanged={onChanged}
      onReload={onReload}
    />
  );
}

/**
 * What the last renewal of the agreement left to be reviewed, as it answered: the members
 * that still say their renewal is pending or that they have expired, which no renewal of
 * an agreement changes, and those marked not to renew that it carried on. Each leads to
 * its contract.
 */
function ReviewAfterRenewal(props: { members: readonly ContractRef[]; onClose: () => void }) {
  const { members, onClose } = props;
  return (
    <div className="warning" data-testid="renewal-to-review" data-count={members.length}>
      <p>{toReviewText(members.length)}</p>
      <ul className="plain-list">
        {members.map((member) => (
          <li key={member.hid} data-contract={member.number}>
            <Link to={contractPath(member.hid)}>{member.number}</Link>
            <span className="muted"> · {optionLabel(CONTRACT_STATUSES, member.status)}</span>
          </li>
        ))}
      </ul>
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </div>
  );
}

interface MembersToReviewProps {
  agreement: Agreement;
  /** Its contracts, as they were read: what a change of a member is sent at. */
  contracts: readonly Contract[] | undefined;
  mayEdit: boolean;
  /** The contracts selected on the page, which these are selected among too. */
  selection: Selection;
  onChanged: (text: string) => void;
  /** Said once Update selected has gone through those selected. */
  onDone: (text: string) => void;
}

/**
 * The members of the agreement to review, as its record lists them: those that still say
 * their renewal is pending or that they have expired while it runs on (D-180). Each is
 * made active, taken out of the agreement, or retired, by a person. The table holds all
 * of its rows, so it is sorted by its headers in the browser.
 */
function MembersToReview(props: MembersToReviewProps) {
  const { agreement, contracts, mayEdit, selection, onChanged, onDone } = props;
  const members = agreement.members_to_review;
  const action = useAction();
  const sorting = useSorting(members, {
    number: (member) => member.number,
    status: (member) => optionLabel(CONTRACT_STATUSES, member.status),
  });
  if (members.length === 0) return null;

  /** The member as it was read, for its version: read again where the list did not hold it. */
  async function current(hid: string): Promise<Contract> {
    const known = contracts?.find((contract) => contract.hid === hid);
    return known ?? api.request("get", "/api/v1/contracts/{hid}", { path: { hid } });
  }

  async function activate(member: ContractRef) {
    const result = await action.run(async () => {
      const contract = await current(member.hid);
      return api.request("patch", "/api/v1/contracts/{hid}", {
        path: { hid: member.hid },
        body: { row_version: contract.row_version, status: "active" },
      });
    });
    if (result.ok) onChanged(`${member.number} is Active again, under ${agreement.name}.`);
  }

  async function takeOut(member: ContractRef) {
    const result = await action.run(async () => {
      const contract = await current(member.hid);
      return api.request("patch", "/api/v1/contracts/{hid}", {
        path: { hid: member.hid },
        body: { row_version: contract.row_version, agreement_hid: null },
      });
    });
    if (result.ok) {
      onChanged(`${member.number} was taken out of ${agreement.name}: it stands by itself.`);
    }
  }

  async function retire(member: ContractRef) {
    const result = await action.run(async () => {
      const contract = await current(member.hid);
      return api.request("post", "/api/v1/contracts/{hid}/retire", {
        path: { hid: member.hid },
        body: { row_version: contract.row_version },
      });
    });
    if (result.ok) onChanged(`${member.number} was retired: it covers nothing any more.`);
  }

  return (
    <section aria-labelledby="members-to-review" data-testid="members-to-review">
      <h2 id="members-to-review">Members to review</h2>
      <p className="warning" data-count={members.length}>
        {membersToReviewText(members.length)}
      </p>
      <Problem error={action.error} />
      <div className="scroll">
        <table className="narrow">
          <caption className="visually-hidden">
            The members of {agreement.name} to review, each with what may be done with it
          </caption>
          <thead>
            <tr>
              {mayEdit && (
                <th scope="col">
                  <SelectAll
                    rows={members}
                    selection={selection}
                    label="Select every member to review"
                  />
                </th>
              )}
              <SortTh sort={sorting} column="number">
                Contract
              </SortTh>
              <SortTh sort={sorting} column="status">
                Status
              </SortTh>
              {mayEdit && <th scope="col">Review</th>}
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((member) => (
              <tr key={member.hid} data-contract={member.number} data-status={member.status}>
                {mayEdit && (
                  <td>
                    <SelectOne hid={member.hid} number={member.number} selection={selection} />
                  </td>
                )}
                <th scope="row">
                  <Link to={contractPath(member.hid)}>{member.number}</Link>
                </th>
                <td>{optionLabel(CONTRACT_STATUSES, member.status)}</td>
                {mayEdit && (
                  <td className="row-actions">
                    <button type="button" disabled={action.busy} onClick={() => activate(member)}>
                      Make active<span className="visually-hidden">: {member.number}</span>
                    </button>
                    <button type="button" disabled={action.busy} onClick={() => takeOut(member)}>
                      Take out<span className="visually-hidden">: {member.number}</span>
                    </button>
                    <ConfirmButton
                      label="Retire"
                      title={`Retire ${member.number}?`}
                      confirmLabel="Retire contract"
                      onConfirm={() => retire(member)}
                      disabled={action.busy}
                    >
                      <p>
                        A retired contract covers nothing any more. Its coverages stay on record,
                        and it can be brought back.
                      </p>
                    </ConfirmButton>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {mayEdit && (
        <UpdateSelected
          agreement={agreement}
          selected={selection.selected}
          contracts={contracts}
          onDone={onDone}
        />
      )}
    </section>
  );
}

/** The contracts selected on the page of an agreement, and how one is selected. */
interface Selection {
  selected: ReadonlySet<string>;
  pick: (hid: string, on: boolean) => void;
  set: (hids: readonly string[]) => void;
}

/** The box that selects every row of a table, or none. */
function SelectAll(props: {
  rows: ReadonlyArray<{ hid: string }>;
  selection: Selection;
  label: string;
}) {
  const { rows, selection, label } = props;
  const all = rows.length > 0 && rows.every((row) => selection.selected.has(row.hid));
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={all}
      onChange={(event) => {
        const on = event.currentTarget.checked;
        const others = [...selection.selected].filter(
          (hid) => !rows.some((row) => row.hid === hid),
        );
        selection.set(on ? [...others, ...rows.map((row) => row.hid)] : others);
      }}
    />
  );
}

/** The box that selects one contract. */
function SelectOne(props: { hid: string; number: string; selection: Selection }) {
  const { hid, number, selection } = props;
  return (
    <input
      type="checkbox"
      aria-label={`Select ${number}`}
      checked={selection.selected.has(hid)}
      onChange={(event) => selection.pick(hid, event.currentTarget.checked)}
    />
  );
}

/** What Update selected offers, as the value of its choice. */
const UPDATES: ReadonlyArray<{ value: string; label: string; update: Update }> = [
  ...CONTRACT_STATUSES.map((one) => ({
    value: `status:${one.value}`,
    label: `Set the status to ${one.label}`,
    update: { kind: "status", status: one.value as Contract["status"] } as Update,
  })),
  { value: "take_out", label: "Take out of the agreement", update: { kind: "take_out" } },
  { value: "retire", label: "Retire", update: { kind: "retire" } },
];

interface UpdateSelectedProps {
  agreement: Agreement;
  selected: ReadonlySet<string>;
  /** Its contracts, as they were read: what each change is sent at, and their numbers. */
  contracts: readonly Contract[] | undefined;
  onDone: (text: string) => void;
}

/**
 * Update selected: one change for every contract selected at once, a status, out of the
 * agreement, or retired. Each is its own request, sent one after another, and the page
 * then says what was done and names each contract that was refused, with why.
 */
function UpdateSelected({ agreement, selected, contracts, onDone }: UpdateSelectedProps) {
  const [chosen, setChosen] = useState(UPDATES[0]?.value ?? "");
  const [busy, setBusy] = useState(false);
  const update = UPDATES.find((one) => one.value === chosen)?.update;
  const count = selected.size;

  async function run() {
    if (!update) return;
    setBusy(true);
    const outcome: Updated = { done: [], refused: [] };
    // In the order of the table of its contracts, those not among them last.
    const order = [
      ...(contracts ?? []).map((contract) => contract.hid).filter((hid) => selected.has(hid)),
      ...[...selected].filter((hid) => !(contracts ?? []).some((one) => one.hid === hid)),
    ];
    for (const hid of order) {
      let number = contracts?.find((one) => one.hid === hid)?.number ?? hid;
      try {
        const contract =
          contracts?.find((one) => one.hid === hid) ??
          (await api.request("get", "/api/v1/contracts/{hid}", { path: { hid } }));
        number = contract.number;
        if (update.kind === "retire") {
          await api.request("post", "/api/v1/contracts/{hid}/retire", {
            path: { hid },
            body: { row_version: contract.row_version },
          });
        } else {
          await api.request("patch", "/api/v1/contracts/{hid}", {
            path: { hid },
            body: {
              row_version: contract.row_version,
              ...(update.kind === "status" ? { status: update.status } : { agreement_hid: null }),
            },
          });
        }
        outcome.done.push(number);
      } catch (thrown) {
        outcome.refused.push({ number, message: toApiError(thrown).message });
      }
    }
    setBusy(false);
    onDone(updatedText(update, outcome, (status) => optionLabel(CONTRACT_STATUSES, status)));
  }

  return (
    <div className="inline" data-testid="update-selected" data-count={count}>
      <SelectField
        label={`Update selected: ${plural(count, "contract")} of ${agreement.name}`}
        name="update-selected"
        value={chosen}
        onChange={setChosen}
        disabled={busy}
      >
        {UPDATES.map((one) => (
          <option key={one.value} value={one.value}>
            {one.label}
          </option>
        ))}
      </SelectField>
      {update?.kind === "retire" ? (
        <ConfirmButton
          label={`Update selected (${count})`}
          title={`Retire ${plural(count, "contract")}?`}
          confirmLabel="Retire them"
          onConfirm={run}
          disabled={busy || count === 0}
        >
          <p>A retired contract covers nothing any more. Its coverages stay on record.</p>
        </ConfirmButton>
      ) : (
        <button type="button" className="primary" disabled={busy || count === 0} onClick={run}>
          Update selected ({count})
        </button>
      )}
    </div>
  );
}
