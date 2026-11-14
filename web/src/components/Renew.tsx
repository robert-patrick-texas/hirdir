// Renewing a contract or a support agreement: its new number, its new period, or both.
// It is one change of the one record. A renewal that is in force at once gives the
// record its new number and period there and then. One whose period begins after today
// is kept as the next term: the present number and period stay in force until that day,
// and from that day the record shows the new ones by itself. A next term is withdrawn
// here too.

import { type FormEvent, type ReactNode, useState } from "react";
import {
  type Agreement,
  type Contract,
  type ContractRenew,
  LAPSED_NOTE,
  nextTermText,
  RENEW_SPECS,
  RENEWAL_PENDING,
  renewBody,
  renewPeriodProblem,
  renewProblem,
} from "../lib/contracts";
import { today } from "../lib/format";
import { useAction } from "../lib/hooks";
import { buildPatch, type FormValue, type FormValues, formOf, read } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { amountText } from "../lib/summary";
import { ConfirmButton } from "./ConfirmButton";
import { FormFields } from "./FormFields";
import { Problem } from "./Problem";

type Renewed = Contract | Agreement;

interface RenewProps<R extends Renewed> {
  record: R;
  /** What the record is called: the number of a contract, the name of an agreement. */
  name: string;
  what: "contract" | "agreement";
  /** Who follows a renewal, said before it is made. */
  follows: ReactNode;
  /** The text of the button that renews: "Renew for 2 items". */
  submitLabel: string;
  /** Something to read above the form, as that a blank date is the agreement's. */
  note?: ReactNode;
  send: (body: ContractRenew) => Promise<R>;
  /** What to say of a renewal that is in force at once. */
  renewed: (record: R) => string;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The term to come, the form of a renewal, and the withdrawal of a term to come. */
export function Renew<R extends Renewed>(props: RenewProps<R>) {
  const { record, name, what, follows, submitLabel, note, send, renewed, onChanged, onReload } =
    props;
  const [open, setOpen] = useState(false);
  const stored = record as R & Readonly<Record<string, unknown>>;
  const [values, setValues] = useState<FormValues>(() => formOf(RENEW_SPECS, stored));
  const [found, setFound] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState("");
  const action = useAction();
  // The server names the end of a term to come `next_ends_on` when it refuses it: a
  // period that would end before it starts. It is said under the end the form has.
  const names = [...RENEW_SPECS.map((spec) => spec.name), "next_ends_on"];
  const built = buildPatch<ContractRenew>(RENEW_SPECS, stored, values);
  const said = fieldErrors(action.error, names).shown;
  const { next_ends_on: nextEnd, ...own } = said;
  const refused = nextEnd && !own.ends_on ? { ...own, ends_on: nextEnd } : own;
  const next = record.next_term;
  const day = today();

  function change(field: string, value: FormValue) {
    setValues((was) => ({ ...was, [field]: value }));
    setProblem("");
    setFound((was) => {
      const { [field]: _, ...rest } = was;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFound(built.errors);
    if (Object.keys(built.errors).length > 0) return;
    // The end the form holds, as it is sent: a term to come always says its end.
    const ends = RENEW_SPECS.find((spec) => spec.name === "ends_on");
    const end = ends ? read(ends, values.ends_on) : { value: null };
    const body = renewBody(
      built.body,
      "value" in end && typeof end.value === "string" ? end.value : null,
      day,
    );
    const wrong = renewProblem(built.changed) || renewPeriodProblem(body, day);
    setProblem(wrong);
    if (wrong) return;
    const result = await action.run(() => send(body));
    if (!result.ok) return;
    const after = result.value;
    onChanged(
      after.next_term
        ? `The renewal is kept as the next term. ${nextTermText(after.next_term)}. Until then ${name} keeps its present number and period.`
        : renewed(after),
    );
  }

  async function withdraw() {
    const result = await action.run(() =>
      send({ row_version: record.row_version, withdraw: true }),
    );
    if (result.ok) {
      onChanged(`The next term was withdrawn: ${name} keeps its present number and period.`);
    }
  }

  return (
    <section aria-labelledby="renew">
      <h2 id="renew">Renew</h2>
      {record.lapsed && (
        <p className="warning" data-testid="lapsed-note">
          {LAPSED_NOTE}
        </p>
      )}
      {record.status === RENEWAL_PENDING && (
        <p className="warning" data-testid="renewal-pending-note">
          The renewal of this {what} is pending: its term has ended and the renewal is in
          procurement. It covers on meanwhile, and support goes through the account manager before
          the support line is called. Entered here, the renewal makes it Active again in its new
          period.
        </p>
      )}
      {next && (
        <div className="panel" data-testid="next-term" data-starts={next.starts_on}>
          <h3>The next term</h3>
          <p>
            <strong>{nextTermText(next)}.</strong> Until that day the present number and period stay
            in force, and from that day the {what} shows the new ones by itself.
          </p>
          <dl className="facts">
            <dt>Annual cost</dt>
            <dd>{amountText(next.annual_cost) || <span className="muted">—</span>}</dd>
            <dt>Purchase reference</dt>
            <dd>{next.purchase_reference || <span className="muted">—</span>}</dd>
          </dl>
          <p className="actions">
            <ConfirmButton
              label="Withdraw the next term"
              title={`Withdraw the next term of ${name}?`}
              confirmLabel="Withdraw"
              onConfirm={withdraw}
              disabled={action.busy}
            >
              <p>
                {nextTermText(next)}. Withdrawn, {name} keeps its present number and period, and is
                renewed anew when the renewal is known.
              </p>
            </ConfirmButton>
          </p>
        </div>
      )}
      <div data-testid="renew-scope">{follows}</div>
      {!open && <Problem error={action.error} onReload={onReload} />}
      {!open ? (
        <p className="actions">
          <button type="button" className="primary" onClick={() => setOpen(true)}>
            Renew
          </button>
        </p>
      ) : (
        <form onSubmit={submit} className="panel stack" noValidate data-testid="renew-form">
          <Problem error={action.error} shown={names} onReload={onReload} />
          {problem && (
            <div className="alert alert-error" role="alert">
              <p>{problem}</p>
            </div>
          )}
          {note}
          <FormFields
            specs={RENEW_SPECS}
            values={values}
            onChange={change}
            errors={{ ...refused, ...found }}
            disabled={action.busy}
          />
          <p className="hint">
            A period that begins today or earlier is in force at once, and the status is then
            Active. A period that begins after today is kept as the next term: say the day it ends,
            or leave that blank for none. The present term runs on until then.
          </p>
          <p className="actions">
            <button
              type="submit"
              className="primary"
              disabled={action.busy || built.changed.length === 0}
            >
              {submitLabel}
            </button>
            <button
              type="button"
              disabled={action.busy}
              onClick={() => {
                setOpen(false);
                setValues(formOf(RENEW_SPECS, stored));
                setFound({});
                setProblem("");
                action.clear();
              }}
            >
              Cancel
            </button>
          </p>
        </form>
      )}
    </section>
  );
}
