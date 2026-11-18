// The table of the terms a contract or an agreement had before it was renewed: its
// purchase history, each a part of the history with its days and what began it (D-181):
// a renewal, joining an agreement or leaving one, and the agreement it was in. An earlier term of a contract has the dates it had in force: where
// the contract had none of its own, those of the agreement's term it began in, as the
// agreement stood then, which are shown as an inherited value is shown everywhere,
// lighter and with where they came from. The table holds all of its rows, so it is sorted by its
// headers in the browser.

import { Link } from "react-router";
import type { Schemas } from "../api/client";
import { agreementPath, beganByLabel } from "../lib/contracts";
import { dateValue, decimalValue } from "../lib/sort";
import { amountText } from "../lib/summary";
import { useSorting } from "../lib/useSorting";
import { Dash } from "./ContractParts";
import { SortTh } from "./SortTh";
import { Time } from "./Time";

type ContractTerm = Schemas["ContractTerm"];
type AgreementTerm = Schemas["AgreementTerm"];

/** A term of either: a term of an agreement says nothing of where its dates came from. */
export type Term = AgreementTerm &
  Partial<Pick<ContractTerm, "starts_on_source" | "ends_on_source">>;

interface TermsTableProps<T extends Term> {
  terms: readonly T[] | undefined;
  /** The data-testid of the table. */
  testId: string;
  caption: string;
  /** The currency of the money, as a header says it: " (USD)", or blank. */
  money: string;
  /** What a date that came from an agreement is said to come from, in its hint. */
  inheritedFrom?: (term: T) => string;
  /**
   * For the parts of a contract's history: the agreement each was in, by name and HID,
   * or null where the contract stood by itself. Left out, the table has no such column.
   */
  agreementOf?: (term: T) => { hid: string; name: string } | null;
}

/** One day of a term: its own, or its agreement's, shown lighter with where it came from. */
function TermDay({
  day,
  inherited,
  from,
}: {
  day: string | null;
  inherited: boolean;
  from: string;
}) {
  if (!day) {
    return (
      <td className="nowrap" data-source="none">
        <Dash />
      </td>
    );
  }
  if (!inherited) {
    return (
      <td className="nowrap" data-source="own">
        {day}
      </td>
    );
  }
  const hint = `Inherited from ${from}: the date of the agreement's term this term began in, the contract having none of its own`;
  return (
    <td className="nowrap inherited" data-source="agreement" title={hint}>
      {day}
      <span className="visually-hidden"> (inherited from {from})</span>
    </td>
  );
}

/** The terms of a contract or an agreement, the latest first, sorted by their headers. */
export function TermsTable<T extends Term>(props: TermsTableProps<T>) {
  const { terms, testId, caption, money, inheritedFrom, agreementOf } = props;
  const sorting = useSorting<T>(terms, {
    began: (term) => dateValue(term.began_on),
    ended: (term) => dateValue(term.ended_on),
    by_what: (term) => beganByLabel(term.began_by),
    agreement: (term) => agreementOf?.(term)?.name ?? null,
    number: (term) => term.number,
    starts: (term) => dateValue(term.starts_on),
    ends: (term) => dateValue(term.ends_on),
    cost: (term) => decimalValue(term.annual_cost),
    reference: (term) => term.purchase_reference,
    renewed: (term) => dateValue(term.renewed_at),
    by: (term) => term.renewed_by_name,
  });
  return (
    <div className="scroll">
      <table data-testid={testId}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="number">
              Number
            </SortTh>
            <SortTh sort={sorting} column="starts">
              Started
            </SortTh>
            <SortTh sort={sorting} column="ends">
              Ended
            </SortTh>
            <SortTh sort={sorting} column="began">
              Part from
            </SortTh>
            <SortTh sort={sorting} column="ended">
              Part to
            </SortTh>
            <SortTh sort={sorting} column="by_what">
              Began by
            </SortTh>
            {agreementOf && (
              <SortTh sort={sorting} column="agreement">
                Agreement
              </SortTh>
            )}
            <SortTh sort={sorting} column="cost" className="number">
              Annual cost{money}
            </SortTh>
            <SortTh sort={sorting} column="reference">
              Purchase reference
            </SortTh>
            <SortTh sort={sorting} column="renewed">
              Changed
            </SortTh>
            <SortTh sort={sorting} column="by">
              By
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((term) => {
            const from = inheritedFrom?.(term) ?? "its agreement";
            const inAgreement = agreementOf?.(term) ?? null;
            return (
              <tr
                key={`${term.renewed_at} ${term.number ?? ""} ${term.began_on ?? ""}`}
                data-term={term.number ?? ""}
                data-began-by={term.began_by}
                data-began-on={term.began_on ?? ""}
                data-ended-on={term.ended_on ?? ""}
              >
                <th scope="row">{term.number || <Dash />}</th>
                <TermDay
                  day={term.starts_on}
                  inherited={term.starts_on_source === "agreement"}
                  from={from}
                />
                <TermDay
                  day={term.ends_on}
                  inherited={term.ends_on_source === "agreement"}
                  from={from}
                />
                <td className="nowrap" data-part="began">
                  {term.began_on || <Dash />}
                </td>
                <td className="nowrap" data-part="ended">
                  {term.ended_on || <Dash />}
                </td>
                <td className="began-by" data-part="began-by">
                  {beganByLabel(term.began_by)}
                </td>
                {agreementOf && (
                  <td data-part="agreement" data-agreement={inAgreement?.name ?? ""}>
                    {inAgreement ? (
                      <Link className="value-link" to={agreementPath(inAgreement.hid)}>
                        {inAgreement.name}
                      </Link>
                    ) : (
                      <span className="muted">Standing by itself</span>
                    )}
                  </td>
                )}
                <td className="number">{amountText(term.annual_cost) || <Dash />}</td>
                <td>{term.purchase_reference || <Dash />}</td>
                <td className="nowrap">
                  <Time at={term.renewed_at} />
                </td>
                <td>{term.renewed_by_name || <Dash />}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
