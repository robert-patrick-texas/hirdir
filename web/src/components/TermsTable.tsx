// The table of the terms a contract or an agreement had before it was renewed: its
// purchase history. An earlier term of a contract has the dates it had in force: where
// the contract had none of its own, those of the agreement's term it began in, as the
// agreement stood then, which are shown as an inherited value is shown everywhere,
// lighter and with where they came from. The table holds all of its rows, so it is sorted by its
// headers in the browser.

import type { Schemas } from "../api/client";
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
  const { terms, testId, caption, money, inheritedFrom } = props;
  const sorting = useSorting<T>(terms, {
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
            <SortTh sort={sorting} column="cost" className="number">
              Annual cost{money}
            </SortTh>
            <SortTh sort={sorting} column="reference">
              Purchase reference
            </SortTh>
            <SortTh sort={sorting} column="renewed">
              Renewed
            </SortTh>
            <SortTh sort={sorting} column="by">
              By
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((term) => {
            const from = inheritedFrom?.(term) ?? "its agreement";
            return (
              <tr key={`${term.renewed_at} ${term.number ?? ""}`} data-term={term.number ?? ""}>
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
