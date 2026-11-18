import { Link } from "react-router";
import {
  type Agreement,
  CONTRACT_STATUSES,
  type Contract,
  contractPath,
  INHERITED,
  type Inherited,
  inForce,
  LAPSED_NOTE,
  nextTermText,
  overrides,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
} from "../lib/contracts";
import { effectiveText } from "../lib/effective";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { Dash } from "./ContractParts";
import { SortTh } from "./SortTh";
import { ValueLink } from "./ValueLink";

interface ContractsTableProps {
  contracts: readonly Contract[];
  /** The agreement the contracts are grouped into: null for those that stand alone. */
  agreement: Agreement | null;
  /** What to say when there is none. */
  empty: string;
}

/**
 * The contracts of one agreement, or the ones that stand by themselves: each with its
 * period in force, how many items it covers, and for a contract in an agreement which
 * of its fields are its own in place of the agreement's. It holds all of its rows, so
 * it is sorted by its headers in the browser.
 */
export function ContractsTable({ contracts, agreement, empty }: ContractsTableProps) {
  const sorting = useSorting(contracts, {
    number: (contract) => contract.number,
    vendor: (contract) => contract.vendor.name,
    status: (contract) => optionLabel(CONTRACT_STATUSES, contract.status),
    starts: (contract) => dateValue(effectiveText(contract.effective.starts_on)),
    ends: (contract) => dateValue(effectiveText(contract.effective.ends_on)),
    support_level: (contract) => effectiveText(contract.effective.support_level),
    covered: (contract) => contract.covered_items,
    overrides: (contract) => overrides(contract).length,
  });
  if (contracts.length === 0) return <p className="muted">{empty}</p>;
  const label = (field: Inherited) =>
    INHERITED.find((known) => known.field === field)?.label ?? field;
  return (
    <div className="scroll">
      <table data-testid="contracts-of" data-agreement={agreement?.name ?? ""}>
        <caption className="visually-hidden">
          {agreement
            ? `The contracts grouped into ${agreement.name}`
            : "The contracts that stand by themselves"}
        </caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="number">
              Number
            </SortTh>
            {!agreement && (
              <SortTh sort={sorting} column="vendor">
                Vendor
              </SortTh>
            )}
            <SortTh sort={sorting} column="status">
              Status
            </SortTh>
            <SortTh sort={sorting} column="starts">
              Starts
            </SortTh>
            <SortTh sort={sorting} column="ends">
              Ends
            </SortTh>
            <SortTh sort={sorting} column="support_level">
              Support level
            </SortTh>
            <SortTh sort={sorting} column="covered" className="number">
              Items covered
            </SortTh>
            {agreement && (
              <SortTh sort={sorting} column="overrides">
                Its own, in place of the agreement&apos;s
              </SortTh>
            )}
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((contract) => {
            const own = overrides(contract);
            const cell = (field: Inherited) => {
              const value = inForce(contract, field);
              return (
                <td
                  className={value.standing === "inherited" ? "inherited" : undefined}
                  data-field={field}
                  data-standing={value.standing}
                  title={
                    value.standing === "inherited"
                      ? `Inherited from ${agreement?.name ?? "its agreement"}`
                      : value.standing === "override"
                        ? `Its own. Overrides ${value.overridden} of ${agreement?.name ?? "its agreement"}${value.same ? ", which is the same" : ""}`
                        : undefined
                  }
                >
                  {value.text || <Dash />}
                </td>
              );
            };
            return (
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
                {!agreement && (
                  <td>
                    <ValueLink kind="vendor" hid={contract.vendor.hid}>
                      {contract.vendor.name}
                    </ValueLink>
                  </td>
                )}
                <td
                  data-status={contract.status}
                  title={contract.status === RENEWAL_PENDING ? RENEWAL_PENDING_NOTE : undefined}
                >
                  {optionLabel(CONTRACT_STATUSES, contract.status)}
                  {contract.lapsed && (
                    <span className="badge" data-mark="lapsed" title={LAPSED_NOTE}>
                      Lapsed
                    </span>
                  )}
                  {contract.next_term && (
                    <span className="muted" data-mark="next-term">
                      {" "}
                      · {nextTermText(contract.next_term)}
                    </span>
                  )}
                </td>
                {cell("starts_on")}
                {cell("ends_on")}
                {cell("support_level")}
                <td className="number">{contract.covered_items}</td>
                {agreement && (
                  <td data-testid="overrides">
                    {own.length > 0 ? (
                      <>
                        <span className="badge mark">Overrides</span> {own.map(label).join(", ")}
                      </>
                    ) : (
                      <span className="muted">Nothing: all of it is the agreement&apos;s</span>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
