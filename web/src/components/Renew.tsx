// Renewing a contract or a support agreement: its new number, its new period, or both.
// It is one change of the one record. A renewal that is in force at once gives the
// record its new number and period there and then. One whose period begins after today
// is kept as the next term: the present number and period stay in force until that day,
// and from that day the record shows the new ones by itself. A next term is withdrawn
// here too.

import { type FormEvent, type ReactNode, useState } from "react";
import type { Schemas } from "../api";
import {
  type Agreement,
  type Contract,
  type ContractRenew,
  followingPeriod,
  LAPSED_NOTE,
  nextTermText,
  RENEW_SPECS,
  RENEWAL_PENDING,
  renewBody,
  renewPeriodProblem,
  renewProblem,
  renewStart,
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

/** What a renewal sends: of an agreement, also what is done with each of its members. */
export type RenewBody = ContractRenew & { members?: Schemas["MemberRenewal"][] };

/**
 * More that a renewal asks for than its number and its period, given by the page: the
 * members of an agreement, each with what the renewal does with it (D-180).
 */
export interface RenewMore {
  /** Shown in the form, beneath the fields of the new term. */
  form: ReactNode;
  /** What it adds to the body, or what is wrong with what the form holds. */
  body: () => { ok: true; value: Partial<RenewBody> } | { ok: false; error: string };
  /** The names of the fields the server may refuse, said by `Problem` with these labels. */
  labels?: Readonly<Record<string, string>>;
}

interface RenewProps<R extends Renewed, A extends R = R> {
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
  /**
   * 0.9.6 (P-214): what is said under the button of the form, while it is open: how many
   * items follow into the new term, how many stay behind and how many begin with it.
   */
  scope?: ReactNode;
  send: (body: RenewBody) => Promise<A>;
  /** What to say of a renewal that is in force at once. */
  renewed: (record: A) => string;
  /**
   * What more to say of the answer, whether the renewal is in force at once or kept as
   * the next term: what was done with each member, and the coverages left behind.
   */
  afterword?: (record: A) => string;
  /** More that the form asks for: the members of an agreement. */
  more?: RenewMore;
  /** Told the answer of a renewal, whether in force at once or kept as the next term. */
  onRenewed?: (record: A) => void;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The term to come, the form of a renewal, and the withdrawal of a term to come. */
export function Renew<R extends Renewed, A extends R = R>(props: RenewProps<R, A>) {
  const { record, name, what, follows, submitLabel, note, send, renewed, onChanged, onReload } =
    props;
  const { afterword, more, onRenewed, scope } = props;
  const [open, setOpen] = useState(false);
  const stored = record as R & Readonly<Record<string, unknown>>;
  // 0.9.6 (P-214): the form begins with the period that follows the present term, and
  // a blank purchase reference.
  const start = () => renewStart(stored, formOf(RENEW_SPECS, stored));
  const [values, setValues] = useState<FormValues>(start);
  const following = record.next_term ? null : followingPeriod(record.ends_on);
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
    const extra = more?.body() ?? { ok: true as const, value: {} };
    const wrong =
      renewProblem(built.changed) || renewPeriodProblem(body, day) || (extra.ok ? "" : extra.error);
    setProblem(wrong);
    if (wrong || !extra.ok) return;
    const result = await action.run(() => send({ ...body, ...extra.value }));
    if (!result.ok) return;
    const after = result.value;
    const said = after.next_term
      ? `The renewal is kept as the next term. ${nextTermText(after.next_term)}. Until then ${name} keeps its present number and period.`
      : renewed(after);
    const besides = afterword?.(after) ?? "";
    onRenewed?.(after);
    onChanged(besides ? `${said} ${besides}` : said);
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
          <Problem
            error={action.error}
            shown={names}
            onReload={onReload}
            {...(more?.labels ? { labels: more.labels } : {})}
          />
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
            {following &&
              `The new period begins as the one that follows the present term, ${following.starts_on} to ${following.ends_on}: from the day after it ends, for a year. `}
            A period that begins today or earlier is in force at once, and the status is then
            Active. A period that begins after today is kept as the next term: say the day it ends,
            or leave that blank for none. The present term runs on until then. The purchase
            reference begins blank: the new term has the one typed here, and no other.
          </p>
          {following && (
            <p className="actions">
              {/* For a renewal that gives a new number alone: the period stays as it is. */}
              <button
                type="button"
                disabled={action.busy}
                onClick={() => {
                  const present = formOf(RENEW_SPECS, stored);
                  change("starts_on", present.starts_on ?? "");
                  change("ends_on", present.ends_on ?? "");
                }}
              >
                Keep the present period
              </button>
            </p>
          )}
          {more?.form}
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
                setValues(start());
                setFound({});
                setProblem("");
                action.clear();
              }}
            >
              Cancel
            </button>
          </p>
          {scope && <div data-testid="renew-follows">{scope}</div>}
        </form>
      )}
    </section>
  );
}
