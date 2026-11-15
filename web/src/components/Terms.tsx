// The terms a contract or an agreement had before it was renewed: its purchase history.
// They are read from the audit trail, and are stored nowhere else.

import { api, type Schemas } from "../api";
import { useLoad } from "../lib/hooks";
import { useMoney } from "../lib/lists";
import { Problem } from "./Problem";
import { TermsTable } from "./TermsTable";

type ContractTerm = Schemas["ContractTerm"];

/**
 * The names of the agreements that earlier terms of a contract were in, other than the
 * one it is in now, whose name the page has already: each read once.
 */
function useAgreementNames(
  terms: readonly ContractTerm[] | undefined,
  known: { hid: string; name: string } | null,
): Record<string, string> {
  const others = [
    ...new Set(
      (terms ?? [])
        .map((term) => term.agreement_hid)
        .filter((hid): hid is string => hid !== null && hid !== known?.hid),
    ),
  ].sort();
  const found = useLoad(`term-agreements ${others.join(" ")}`, async (signal) => {
    const names = await Promise.all(
      others.map((hid) =>
        api.request("get", "/api/v1/agreements/{hid}", { path: { hid }, signal }).then(
          (agreement) => [hid, agreement.name] as const,
          // One that cannot be read is named as an agreement, and nothing more.
          () => [hid, ""] as const,
        ),
      ),
    );
    return Object.fromEntries(names);
  });
  return { ...(found.data ?? {}), ...(known ? { [known.hid]: known.name } : {}) };
}

interface ContractTermsProps {
  contract: Schemas["ContractOut"];
  /** Changes when something on the page changed, so that the terms are read again. */
  turn: number;
}

/**
 * The parts of the contract's history before the present one, the latest first: each
 * began when it was made, renewed, or joined or left an agreement (D-181). Its purchase
 * history. A renewal of its agreement is not among them: that is a term of the agreement.
 */
export function ContractTerms({ contract, turn }: ContractTermsProps) {
  const terms = useLoad(`terms ${contract.hid} ${contract.row_version} ${turn}`, (signal) =>
    api.request("get", "/api/v1/contracts/{hid}/terms", { path: { hid: contract.hid }, signal }),
  );
  const names = useAgreementNames(terms.data, contract.agreement);
  const money = useMoney();
  return (
    <section aria-labelledby="terms">
      <h2 id="terms">Its history: the parts before this one</h2>
      <Problem error={terms.error} />
      {terms.loading && !terms.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {terms.data && terms.data.length === 0 && (
        <p className="muted" data-testid="no-terms">
          The contract has not been renewed, nor joined or left an agreement: this is the first part
          of its history.
        </p>
      )}
      {terms.data && terms.data.length > 0 && (
        <TermsTable
          terms={terms.data}
          testId="contract-terms"
          money={money}
          caption="Each part of the history of the contract before the present one, the latest first: its days, what began it, the agreement it was in, and the number, the period and the purchase reference it had, and when the change that ended it was made: the purchase history of the contract. A date shown lighter is its agreement's, from the agreement's term the part began in"
          inheritedFrom={(term) =>
            (term.agreement_hid && names[term.agreement_hid]) || "its agreement"
          }
          agreementOf={(term) =>
            term.agreement_hid
              ? { hid: term.agreement_hid, name: names[term.agreement_hid] || "An agreement" }
              : null
          }
        />
      )}
    </section>
  );
}

interface AgreementTermsProps {
  agreement: Schemas["AgreementOut"];
  /** Changes when something on the page changed, so that the terms are read again. */
  turn: number;
}

/**
 * The terms the agreement had before it was renewed, the latest first: its purchase
 * history, as a contract has its own.
 */
export function AgreementTerms({ agreement, turn }: AgreementTermsProps) {
  const terms = useLoad(
    `agreement-terms ${agreement.hid} ${agreement.row_version} ${turn}`,
    (signal) =>
      api.request("get", "/api/v1/agreements/{hid}/terms", {
        path: { hid: agreement.hid },
        signal,
      }),
  );
  const money = useMoney();
  return (
    <section aria-labelledby="agreement-terms">
      <h2 id="agreement-terms">Terms before this one</h2>
      <Problem error={terms.error} />
      {terms.loading && !terms.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {terms.data && terms.data.length === 0 && (
        <p className="muted" data-testid="no-terms">
          The agreement has not been renewed: this is its first term.
        </p>
      )}
      {terms.data && terms.data.length > 0 && (
        <TermsTable
          terms={terms.data}
          testId="agreement-terms"
          money={money}
          caption="Each term with the number, the period and the purchase reference it had, and when it was renewed: the purchase history of the agreement. The contracts co-termed with it followed each renewal, and have no term of their own for it"
        />
      )}
    </section>
  );
}
