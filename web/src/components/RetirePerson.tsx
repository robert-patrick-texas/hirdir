// 0.9.14: the confirmation of a retirement, shared by the pages of a user, of a contact
// and of an operator (P-291, P-297). The three are one person's and travel together: the
// confirmation reads who is linked afresh, lists each linked record that is not retired
// with Retire ticked from the start, asks of each label one of four, and sends the one
// request. It holds the one rule before anything is sent: a contact is not retired while
// its account or a label stands on it. A refusal is said here, with the records it
// names, and nothing chosen is lost. And Bring back of an account, with its retired
// contact and that contact's labels (P-298).

import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useLoad } from "../lib/hooks";
import {
  blockedWords,
  bringBackBody,
  bringBackOffer,
  type Choices,
  contactGoes,
  contactUses,
  held,
  keptChoices,
  type Linked,
  namesUnlisted,
  nothingLinked,
  notSaidLead,
  type On,
  type OperatorAction,
  operatorUses,
  othersOf,
  type RetireBody,
  refusedRows,
  retireBody,
  retiredWords,
  rowOf,
  startChoices,
  userState,
} from "../lib/linked";
import { briefMark } from "../lib/onboarding";
import { type BroughtBack, readLinked, sendBringBack, sendRetire } from "../lib/person";
import { allows, roleLabel } from "../lib/roles";
import { ContactField } from "./ContactField";
import { CheckField, RadioGroupField } from "./Field";
import { OperatorMark } from "./Operator";
import { Problem } from "./Problem";

interface DialogProps {
  title: string;
  testId: string;
  onCancel: () => void;
  children: ReactNode;
}

/** A modal dialog open from the start, which stays open until the page takes it away. */
function PersonDialog({ title, testId, onCancel, children }: DialogProps) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const shown = dialog.current;
    if (shown && !shown.open) shown.showModal();
    return () => shown?.close();
  }, []);
  return (
    // Escape closes the dialog as Cancel does.
    <dialog
      ref={dialog}
      aria-labelledby={`${id}-title`}
      className="person-dialog"
      data-testid={testId}
      onCancel={onCancel}
    >
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </dialog>
  );
}

interface RetirePersonProps {
  /** The record that is retired: which of the three it is, and its HID. */
  on: On;
  /** The version of the record the page shows. */
  rowVersion: number;
  /** The button that asks: "Retire contact", "Release". */
  label: string;
  /** The question: "Retire Kim Lee?". */
  title: string;
  /** What is said where nothing is linked: the plain confirmation of the page. */
  children: ReactNode;
  /** What is said whatever is linked: that it is the reader's own account. */
  note?: string | undefined;
  disabled?: boolean;
  /** The retirement was done: what the page says of it. */
  onRetired: (text: string) => void;
  /** Read the record again, as when someone else has changed it. */
  onReload: () => void;
}

/** Retire one of the three records of a person, saying what becomes of the others. */
export function RetirePerson(props: RetirePersonProps) {
  const { label, title, disabled, onRetired } = props;
  // Each press opens the confirmation anew: who is linked is read afresh.
  const [turn, setTurn] = useState(0);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="danger"
        disabled={disabled}
        onClick={() => {
          setTurn((count) => count + 1);
          setOpen(true);
        }}
      >
        {label}
      </button>
      {open && (
        <PersonDialog title={title} testId="retire-person" onCancel={() => setOpen(false)}>
          <RetireAsk
            key={turn}
            {...props}
            turn={turn}
            onCancel={() => setOpen(false)}
            onRetired={(text) => {
              setOpen(false);
              onRetired(text);
            }}
          />
        </PersonDialog>
      )}
    </>
  );
}

interface RetireAskProps extends RetirePersonProps {
  turn: number;
  onCancel: () => void;
}

function RetireAsk(props: RetireAskProps) {
  const { on, rowVersion, label, children, note, turn, onCancel, onRetired, onReload } = props;
  const auth = useAuth();
  const admin = allows(auth.user.role, "admin");
  const read = useLoad(`retire linked ${on.kind} ${on.hid} ${turn}`, (signal) =>
    readLinked(on, signal),
  );
  // What is chosen, of the records as they were last read: kept when they are read again.
  const [asked, setAsked] = useState<{ linked: Linked; choices: Choices } | null>(null);
  if (read.data && asked?.linked !== read.data) {
    setAsked({
      linked: read.data,
      choices: asked
        ? keptChoices(on, asked, read.data, admin)
        : startChoices(on, read.data, admin),
    });
  }
  // What is still to be chosen, said at its row before anything is sent.
  const [found, setFound] = useState<Record<string, string>>({});
  const [sent, setSent] = useState<RetireBody | null>(null);
  const action = useAction();

  const linked = asked?.linked;
  const choices = asked?.choices;
  const plain = linked ? nothingLinked(on, linked) : false;
  const blocked = linked ? blockedWords(on, linked, admin) : null;
  const refused = refusedRows(action.error?.fields ?? {}, sent);
  const rows: Readonly<Record<string, string | undefined>> = { ...refused.rows, ...found };

  function choose(next: Choices) {
    if (!linked) return;
    setFound({});
    setAsked({ linked, choices: held(on, linked, next, admin) });
  }

  async function retire() {
    if (!linked || !choices) return;
    const built = retireBody(on, linked, choices, rowVersion, admin);
    if (!built.ok) {
      action.clear();
      setFound(built.errors);
      return;
    }
    setFound({});
    setSent(built.body);
    let unlisted = false;
    const result = await action.run(async () => {
      try {
        return await sendRetire(on, built.body);
      } catch (thrown) {
        unlisted = thrown instanceof ApiError && namesUnlisted(thrown, on, linked);
        throw thrown;
      }
    });
    if (result.ok) {
      onRetired(retiredWords(on, linked, choices, admin));
      return;
    }
    // Something is linked that was not listed: the list is read again, what was chosen kept.
    if (unlisted) read.reload();
  }

  return (
    <>
      <div className="dialog-body">
        <Problem error={read.error} />
        <Problem
          error={action.error}
          shown={refused.shown}
          onReload={onReload}
          dependsLead={notSaidLead}
        />
        {read.loading && !linked && (
          <p role="status" className="muted">
            Reading what is linked…
          </p>
        )}
        {linked && plain && children}
        {linked && choices && !plain && (
          <RetireRows
            on={on}
            linked={linked}
            choices={choices}
            admin={admin}
            rows={rows}
            disabled={action.busy || blocked !== null}
            onChoose={choose}
          />
        )}
        {blocked && (
          <p className="alert alert-error" data-testid="retire-blocked">
            {blocked}
          </p>
        )}
        {linked && note && (
          <p data-testid="retire-note">
            <strong>{note}</strong>
          </p>
        )}
      </div>
      <p className="actions">
        <button type="button" onClick={onCancel} disabled={action.busy}>
          {blocked ? "Close" : "Cancel"}
        </button>
        {!blocked && (
          <button
            type="button"
            className="danger"
            onClick={() => void retire()}
            disabled={action.busy || !linked}
          >
            {label}
          </button>
        )}
      </p>
    </>
  );
}

interface RetireRowsProps {
  on: On;
  linked: Linked;
  choices: Choices;
  admin: boolean;
  /** What is said at a row: a choice still to make, or what the server refused. */
  rows: Readonly<Record<string, string | undefined>>;
  disabled: boolean;
  onChoose: (next: Choices) => void;
}

/** What a label may become, in the words of the page of an operator. */
const ACTIONS: ReadonlyArray<{ value: OperatorAction; label: string }> = [
  { value: "retire", label: "Release" },
  { value: "hand_over", label: "Hand over to" },
  { value: "open", label: "Leave open" },
  { value: "keep", label: "Keep" },
];

function actionHint(action: OperatorAction, person: string): string {
  if (action === "retire") {
    return "The label is retired: what it is on has the operator of the next level up, or none.";
  }
  if (action === "hand_over") return "Another person is behind the label from now on.";
  if (action === "open") return "The label stays on all of it, with nobody behind it.";
  return `${person || "The person"} stays behind the label.`;
}

/** Each linked record that is not retired, with what is asked of it. */
function RetireRows({ on, linked, choices, admin, rows, disabled, onChoose }: RetireRowsProps) {
  const others = othersOf(on, linked);
  const going = contactGoes(on, linked, choices);
  const person = linked.contact?.name ?? "";
  return (
    <div className="person-rows" data-testid="retire-rows">
      <p className="person-lead">
        {on.kind === "operator" ? "This label is" : "This is"} one of the records of one person. Say
        what becomes of each of the others: what is ticked is retired with it, in one change.
      </p>
      {others.user && (
        <div className="person-row" data-row="user">
          <CheckField
            label={`Retire the account ${others.user.username}`}
            name="linked_user"
            checked={choices.user}
            onChange={(ticked) => onChoose({ ...choices, user: ticked })}
            disabled={disabled || !admin || going}
            hint={
              !admin
                ? `An Admin retires an account: ${others.user.username} stays, and so its contact stays.`
                : going
                  ? "It is retired with its contact: an account does not stand on a retired contact. To keep it, keep the contact."
                  : "Ticked, it signs in no longer and leaves its groups and its role. Unticked, it stays as it is."
            }
            error={rows[rowOf("user")]}
          />
          <p className="person-about">
            {admin ? (
              <Link to={`/admin/users/${encodeURIComponent(others.user.hid)}`}>
                {others.user.username}
              </Link>
            ) : (
              <span className="mono">{others.user.username}</span>
            )}{" "}
            · {roleLabel(others.user.role)} · {userState(others.user)}
          </p>
        </div>
      )}
      {others.contact && (
        <div className="person-row" data-row="contact">
          <CheckField
            label={`Retire the contact ${others.contact.name}`}
            name="linked_contact"
            checked={choices.contact}
            onChange={(ticked) => onChoose({ ...choices, contact: ticked })}
            disabled={disabled || (others.user !== null && !admin)}
            hint={
              others.user !== null && !admin
                ? "It stays: a contact is not retired while its account stands on it."
                : "Ticked, the records that name it keep it and show it as retired. Unticked, it stays as it is."
            }
            error={rows[rowOf("contact")]}
          />
          <p className="person-about">
            <Link to={`/contacts/${encodeURIComponent(others.contact.hid)}`}>
              {others.contact.name}
            </Link>{" "}
            · {contactUses(others.contact.uses)}
          </p>
        </div>
      )}
      {others.operators.map((operator) => {
        const choice = choices.operators[operator.hid] ?? { action: "retire", contactHid: "" };
        const set = (next: { action: OperatorAction; contactHid: string }) =>
          onChoose({ ...choices, operators: { ...choices.operators, [operator.hid]: next } });
        return (
          <div
            className="person-row"
            data-row="operator"
            data-operator={operator.hid}
            key={operator.hid}
          >
            <p className="person-about">
              <OperatorMark mark={briefMark(operator)} /> · {operatorUses(operator.uses)}
            </p>
            <div className="person-choice">
              <RadioGroupField
                label={`The label ${operator.label}`}
                name={`linked_operator_${operator.hid}`}
                // With the contact going, no label is kept: Keep is not offered.
                options={ACTIONS.filter((one) => !(going && one.value === "keep"))}
                value={choice.action}
                onChange={(value) =>
                  set({
                    ...choice,
                    action: ACTIONS.find((one) => one.value === value)?.value ?? "retire",
                  })
                }
                hint={actionHint(choice.action, person)}
                error={
                  choice.action === "hand_over" ? undefined : rows[rowOf("operator", operator.hid)]
                }
                disabled={disabled}
              />
            </div>
            {/* Kept in the page while another choice is on show, so that the person
                chosen is still there when Hand over to is chosen again. */}
            <div hidden={choice.action !== "hand_over"} className="person-hand-over">
              <ContactField
                label={`Person to hand ${operator.label} over to`}
                name={`hand_over_${operator.hid}`}
                value={choice.contactHid}
                onChange={(hid) => set({ ...choice, contactHid: hid })}
                blank="Nobody chosen"
                error={
                  choice.action === "hand_over" ? rows[rowOf("operator", operator.hid)] : undefined
                }
                disabled={disabled}
              />
            </div>
          </div>
        );
      })}
      {(others.contact !== null || on.kind === "contact") && (
        <p className="hint" data-testid="retire-rule">
          A contact is not retired while its account or a label stands on it.{" "}
          {going
            ? "With the contact retired, its account is retired too, and each label is released, handed over or left open: Keep is not offered."
            : "The contact stays: its account and each label are kept or not, as chosen."}
        </p>
      )}
    </div>
  );
}

interface BringBackUserProps {
  user: { hid: string; username: string; row_version: number };
  disabled?: boolean;
  /** The account is back: the user, and its new access code, shown once. */
  onBroughtBack: (answer: BroughtBack) => void;
  onReload: () => void;
}

/**
 * Bring a retired account back (P-296, P-298): with its contact where that is retired,
 * ticked and needed unless the contact is taken off first, and the retired labels of
 * that contact, each unticked. The account is active again with a new access code, no
 * role and no group.
 */
export function BringBackUser({ user, disabled, onBroughtBack, onReload }: BringBackUserProps) {
  const [turn, setTurn] = useState(0);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setTurn((count) => count + 1);
          setOpen(true);
        }}
      >
        Bring back
      </button>
      {open && (
        <PersonDialog
          title={`Bring ${user.username} back?`}
          testId="bring-back-user"
          onCancel={() => setOpen(false)}
        >
          <BringBackAsk
            key={turn}
            user={user}
            turn={turn}
            onCancel={() => setOpen(false)}
            onBroughtBack={(answer) => {
              setOpen(false);
              onBroughtBack(answer);
            }}
            onReload={onReload}
          />
        </PersonDialog>
      )}
    </>
  );
}

interface BringBackAskProps extends BringBackUserProps {
  turn: number;
  onCancel: () => void;
}

function BringBackAsk({ user, turn, onCancel, onBroughtBack, onReload }: BringBackAskProps) {
  const read = useLoad(`bring back linked ${user.hid} ${turn}`, (signal) =>
    readLinked({ kind: "user", hid: user.hid }, signal),
  );
  const [ticked, setTicked] = useState<readonly string[]>([]);
  const [sent, setSent] = useState<ReturnType<typeof bringBackBody> | null>(null);
  const action = useAction();
  const linked = read.data;
  const offer = linked ? bringBackOffer(linked) : null;
  const refused = refusedRows(action.error?.fields ?? {}, sent);

  async function bringBack() {
    if (!linked) return;
    const body = bringBackBody(linked, ticked, user.row_version);
    setSent(body);
    const result = await action.run(() => sendBringBack(user.hid, body));
    if (result.ok) onBroughtBack(result.value);
    // A contact retired since the page was read is offered once the list is read again.
    else read.reload();
  }

  return (
    <>
      <div className="dialog-body">
        <Problem error={read.error} />
        <Problem error={action.error} shown={refused.shown} onReload={onReload} />
        {read.loading && !linked && (
          <p role="status" className="muted">
            Reading what is linked…
          </p>
        )}
        {offer && (
          <div className="person-rows" data-testid="bring-back-rows">
            <p className="person-lead">
              The account is active again, with a new access code, which is shown once. It has no
              role and no group until an Admin gives them.
            </p>
            {offer.contact && (
              <div className="person-row" data-row="contact">
                <CheckField
                  label={`Bring back the contact ${offer.contact.name}`}
                  name="linked_contact"
                  checked
                  onChange={() => {}}
                  disabled
                  hint="An account does not stand on a retired contact: the two are brought back together. To bring the account back alone, take its contact away first, under The person."
                  error={refused.rows[rowOf("contact")]}
                />
              </div>
            )}
            {offer.operators.map((operator) => (
              <div
                className="person-row"
                data-row="operator"
                data-operator={operator.hid}
                key={operator.hid}
              >
                <CheckField
                  label={`Bring back the label ${operator.label}`}
                  name={`linked_operator_${operator.hid}`}
                  checked={ticked.includes(operator.hid)}
                  onChange={(yes) =>
                    setTicked((was) =>
                      yes
                        ? [...was.filter((hid) => hid !== operator.hid), operator.hid]
                        : was.filter((hid) => hid !== operator.hid),
                    )
                  }
                  disabled={action.busy}
                  hint={`Ticked, it is on everything it was on again: ${operatorUses(operator.uses)}. Leave it unticked where that has gone to somebody else since.`}
                  error={refused.rows[rowOf("operator", operator.hid)]}
                />
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="actions">
        <button type="button" onClick={onCancel} disabled={action.busy}>
          Cancel
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => void bringBack()}
          disabled={action.busy || !linked}
        >
          Bring back
        </button>
      </p>
    </>
  );
}
