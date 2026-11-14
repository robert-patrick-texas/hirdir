import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import {
  agreementSpecs,
  ContractsNav,
  contractSpecs,
  Dash,
  Lines,
  SupportLink,
} from "../components/ContractParts";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Retire } from "../components/Retire";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import {
  type Agreement,
  agreementPath,
  CONTRACT_STATUSES,
  type Contract,
  contractPath,
  contractsOfPath,
  INHERITED,
  inForce,
  periodText,
} from "../lib/contracts";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useLoad, useTitle } from "../lib/hooks";
import { EVERY, useMoney, useTags, useVendorOptions } from "../lib/lists";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { allows } from "../lib/roles";
import { amountText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";

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
    width: 140,
  },
  {
    id: "status",
    header: "Status",
    kind: "choice",
    value: (agreement) => optionLabel(CONTRACT_STATUSES, agreement.status),
    choices: CONTRACT_STATUSES,
    width: 120,
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
    id: "account_manager",
    header: "Account manager",
    kind: "text",
    value: (agreement) => agreement.account_manager,
    hide: true,
    width: 240,
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
 * Support agreements → one agreement: its fields and tags, and its contracts with what
 * each has from it and what each overrides.
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
  const [adding, setAdding] = useState(false);
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

  function changed(text: string) {
    setDone(text);
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
        {record && (
          <span className="badge badge-plain">{optionLabel(CONTRACT_STATUSES, record.status)}</span>
        )}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={agreement.error} />
      <Problem error={listsError} />
      <Notice text={done} />
      {agreement.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
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
              </dd>
              <dt>Period</dt>
              <dd data-testid="agreement-period">{periodText(record.starts_on, record.ends_on)}</dd>
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
          <AgreementContracts agreement={record} />
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
        </>
      )}
    </>
  );
}

/**
 * The contracts grouped into an agreement, each with what it has in force of the fields
 * a contract may have from its agreement: lighter where it is the agreement's, and
 * marked where it is the contract's own in place of what the agreement has.
 */
function AgreementContracts({ agreement }: { agreement: Agreement }) {
  const found = useLoad(`agreement-contracts ${agreement.hid} ${agreement.row_version}`, (signal) =>
    api.request("get", "/api/v1/contracts", {
      query: {
        filter: `agreement_hid:eq:${agreement.hid}`,
        limit: EVERY,
        include_drafts: true,
      },
      signal,
    }),
  );
  const rows = found.data?.items ?? [];
  const sorting = useSorting(rows, {
    number: (contract) => contract.number,
    status: (contract) => optionLabel(CONTRACT_STATUSES, contract.status),
    covered: (contract) => contract.covered_items,
    ...Object.fromEntries(
      INHERITED.map(({ field }) => [
        field,
        (contract: Contract) => inForce(contract, field, agreement).text,
      ]),
    ),
  });
  const holdsAll = found.data !== undefined && found.data.total <= rows.length;

  return (
    <section aria-labelledby="agreement-contracts">
      <h2 id="agreement-contracts">Its contracts</h2>
      <p>
        What a contract says nothing of, it has from this agreement: that is shown lighter. What is
        marked Overrides is the contract&apos;s own, in place of what the agreement has. Its number,
        its status, its purchase reference, its cost and its notes are always its own.
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
                <SortTh sort={sorting} column="number">
                  Number
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="covered" className="number">
                  Items covered
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
                  <th scope="row">
                    <Link to={contractPath(contract.hid)}>{contract.number}</Link>
                    {contract.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, contract.record_status)}
                      </span>
                    )}
                  </th>
                  <td>{optionLabel(CONTRACT_STATUSES, contract.status)}</td>
                  <td className="number">{contract.covered_items}</td>
                  {INHERITED.map(({ field }) => {
                    const value = inForce(contract, field, agreement);
                    return (
                      <td
                        key={field}
                        data-field={field}
                        data-standing={value.standing}
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
                                  title={`In place of ${value.overridden}, which the agreement has`}
                                >
                                  Overrides
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
          </table>
        </div>
      )}
    </section>
  );
}
