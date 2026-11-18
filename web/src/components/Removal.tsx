// 0.9.7: the rows ticked retired at once by the Inventory role (P-228), and those that
// were a mistake deleted by an Admin (P-227), from a list, from the records an import
// made (P-234) and from a record's page. Each asks first and says how many; a deletion
// shows what the server's dry run answers, and needs a reason. The server holds the
// roles and every rule: the page only offers the buttons to the roles that may.

import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad } from "../lib/hooks";
import {
  countOf,
  type DeletedMany,
  type Dependent,
  deletedText,
  dependentKind,
  dependentPath,
  type RemovalKind,
  type RetiredMany,
  reasonGiven,
  removalPath,
  retiredText,
  retireQuestion,
  stayTicked,
  tooManyText,
} from "../lib/removal";
import { allows } from "../lib/roles";
import type { Chosen } from "../lib/transfer";
import { TextAreaField } from "./Field";
import type { GridAction } from "./grid/DataGrid";
import { Problem } from "./Problem";

/** What is asked: to retire or to delete these records. */
export interface Asked {
  what: "retire" | "delete";
  hids: readonly string[];
}

/** What a request did, as its answer says. */
export type Outcome =
  | { what: "retire"; answer: RetiredMany }
  | { what: "delete"; answer: DeletedMany };

function retire(kind: RemovalKind, hids: readonly string[]): Promise<RetiredMany> {
  const body = { hids: [...hids] };
  return kind === "item"
    ? api.request("post", "/api/v1/items/retire", { body })
    : api.request("post", "/api/v1/device-groups/retire", { body });
}

function remove(
  kind: RemovalKind,
  hids: readonly string[],
  reason: string | null,
  dryRun: boolean,
  signal?: AbortSignal,
): Promise<DeletedMany> {
  const body = { hids: [...hids], reason, dry_run: dryRun };
  return kind === "item"
    ? api.request("post", "/api/v1/items/delete", { body, ...(signal ? { signal } : {}) })
    : api.request("post", "/api/v1/device-groups/delete", { body, ...(signal ? { signal } : {}) });
}

interface RemovalDialogProps {
  kind: RemovalKind;
  asked: Asked;
  onDone: (outcome: Outcome) => void;
  onCancel: () => void;
}

/** The question before a Retire or a Delete, in a modal dialog open from the start. */
export function RemovalDialog({ kind, asked, onDone, onCancel }: RemovalDialogProps) {
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
      aria-labelledby="removal-title"
      className="removal-dialog"
      data-testid="removal-dialog"
      onCancel={onCancel}
    >
      {asked.what === "retire" ? (
        <RetireAsk kind={kind} hids={asked.hids} onDone={onDone} onCancel={onCancel} />
      ) : (
        <DeleteAsk kind={kind} hids={asked.hids} onDone={onDone} onCancel={onCancel} />
      )}
    </dialog>
  );
}

interface AskProps {
  kind: RemovalKind;
  hids: readonly string[];
  onDone: (outcome: Outcome) => void;
  onCancel: () => void;
}

function RetireAsk({ kind, hids, onDone, onCancel }: AskProps) {
  const action = useAction();
  async function go() {
    const result = await action.run(() => retire(kind, hids));
    if (result.ok) onDone({ what: "retire", answer: result.value });
  }
  return (
    <>
      <h2 id="removal-title">{retireQuestion(kind, hids.length)}</h2>
      <div className="dialog-body">
        <Problem error={action.error} />
        <p>
          {kind === "item"
            ? "Each is retired as its own page retires it: it stays in the inventory, is left out of counts and default views, and its memberships of groups end today."
            : "Each is retired as its own page retires it: its current memberships end today, and its record and past memberships are kept."}{" "}
          A retired record is shown again with Include archived on, and brought back on its page.
        </p>
      </div>
      <p className="actions">
        <button type="button" onClick={onCancel} disabled={action.busy}>
          Cancel
        </button>
        <button type="button" className="danger" onClick={go} disabled={action.busy}>
          Retire {countOf(kind, hids.length)}
        </button>
      </p>
    </>
  );
}

function DeleteAsk({ kind, hids, onDone, onCancel }: AskProps) {
  const action = useAction();
  const [reason, setReason] = useState("");
  // What the deletion would do, as the server judges it now: nothing is changed by it.
  const dry = useLoad(`delete dry run ${kind} ${hids.join(" ")}`, (signal) =>
    remove(kind, hids, null, true, signal),
  );
  const answer = dry.data;
  const count = answer?.deleted.length ?? 0;
  async function go() {
    const result = await action.run(() => remove(kind, hids, reason.trim(), false));
    if (result.ok) onDone({ what: "delete", answer: result.value });
  }
  return (
    <>
      <h2 id="removal-title">Delete {countOf(kind, hids.length)}?</h2>
      <div className="dialog-body">
        <Problem error={dry.error} />
        <Problem error={action.error} shown={["reason"]} />
        {dry.loading && !answer && (
          <p role="status" className="muted">
            Asking the server what would be deleted…
          </p>
        )}
        {answer && (
          <div data-testid="delete-dry-run">
            <DeletedAnswer kind={kind} answer={answer} />
            {/* Where nothing can be deleted, nothing is offered: only Close. */}
            {count > 0 && (
              <p>
                A deletion cannot be undone. Each is kept in the audit trail, with the record as it
                was, who deleted it, when, and the reason.
              </p>
            )}
            {count > 0 && (
              <TextAreaField
                label="Reason"
                name="reason"
                value={reason}
                onChange={setReason}
                required
                rows={2}
                maxLength={2000}
                disabled={action.busy}
                error={action.error?.fields.reason}
                hint="Why they should never have been, as a wrong file of a day."
              />
            )}
          </div>
        )}
      </div>
      <p className="actions">
        <button type="button" onClick={onCancel} disabled={action.busy}>
          {answer && count === 0 ? "Close" : "Cancel"}
        </button>
        {!(answer && count === 0) && (
          <button
            type="button"
            className="danger"
            onClick={go}
            disabled={action.busy || !answer || !reasonGiven(reason)}
          >
            {answer ? `Delete ${countOf(kind, count)}` : "Delete"}
          </button>
        )}
      </p>
    </>
  );
}

/** A record of the answer, as a link to its page, or plain words where it is gone. */
function RecordLink({
  kind,
  record,
  gone,
}: {
  kind: RemovalKind;
  record: { hid: string; label: string };
  gone: boolean;
}) {
  return gone ? (
    <strong>{record.label}</strong>
  ) : (
    <Link to={removalPath(kind, record.hid)}>{record.label}</Link>
  );
}

function DependentLink({ dependent }: { dependent: Dependent }) {
  const to = dependentPath(dependent);
  return (
    <>
      {dependentKind(dependent)} {to ? <Link to={to}>{dependent.label}</Link> : dependent.label}
    </>
  );
}

/** What a deletion did, or would do: what is deleted, and each refused with what is in its way. */
function DeletedAnswer({
  kind,
  answer,
  ticked = true,
}: {
  kind: RemovalKind;
  answer: DeletedMany;
  ticked?: boolean;
}) {
  return (
    <>
      <p data-testid="delete-said">{deletedText(kind, answer, ticked)}</p>
      {answer.refused.length > 0 && (
        <ul className="removal-refused" data-testid="delete-refused">
          {answer.refused.map((one) => (
            <li key={one.hid} data-hid={one.hid}>
              <RecordLink kind={kind} record={one} gone={false} />: in its way,{" "}
              {one.depends_on.map((dependent, at) => (
                <span key={`${dependent.record_type} ${dependent.hid}`}>
                  {at > 0 && ", "}
                  <DependentLink dependent={dependent} />
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {answer.dry_run && answer.deleted.length > 0 && (
        <details>
          <summary>What will be deleted</summary>
          <ul data-testid="delete-will">
            {answer.deleted.map((one) => (
              <li key={one.hid}>
                <RecordLink kind={kind} record={one} gone={false} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

/** What the last Retire or Delete did, said where the page answers, which stays in view. */
export function RemovalOutcome({
  kind,
  outcome,
  ticked = true,
}: {
  kind: RemovalKind;
  outcome: Outcome | null;
  /** Whether rows were ticked, which those refused stay; not on a record's page. */
  ticked?: boolean;
}) {
  return (
    <div className="live" role="status" aria-live="polite">
      {outcome && (
        <div
          className={`alert ${outcome.answer.refused.length > 0 ? "alert-info" : "alert-ok"}`}
          data-testid="removal-outcome"
        >
          {outcome.what === "retire" ? (
            <>
              <p>{retiredText(kind, outcome.answer, ticked)}</p>
              {outcome.answer.refused.length > 0 && (
                <ul className="removal-refused">
                  {outcome.answer.refused.map((one) => (
                    <li key={one.hid} data-hid={one.hid}>
                      <RecordLink kind={kind} record={one} gone={false} />: {one.detail}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <DeletedAnswer kind={kind} answer={outcome.answer} ticked={ticked} />
          )}
        </div>
      )}
    </div>
  );
}

/** What a list needs to retire and delete the rows ticked: its buttons, and what follows. */
export interface TickedRemoval<T> {
  actions: GridAction<T>[];
  /** Open the question for these rows, as a list that is no grid does. */
  ask: (what: Asked["what"], hids: readonly string[]) => void;
  /** The dialog while one is asked, and what the last one did. */
  shown: ReactNode;
  /** How many have been done: the list is read again at each. */
  turn: number;
  /** The rows to tick again once it is: those refused. */
  keep: readonly string[];
}

/**
 * Retire for the rows ticked, for the Inventory role, and Delete, for an Admin, as
 * buttons of a grid: each takes particular rows, never all that match a filter.
 */
export function useTickedRemoval<T>(kind: RemovalKind): TickedRemoval<T> {
  const { user } = useAuth();
  const [asked, setAsked] = useState<Asked | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [turn, setTurn] = useState(0);
  const [keep, setKeep] = useState<readonly string[]>([]);
  function ask(what: Asked["what"], hids: readonly string[]) {
    if (hids.length === 0) return;
    setOutcome(null);
    setAsked({ what, hids });
  }
  const button = (what: Asked["what"]): GridAction<T> => ({
    label: what === "retire" ? "Retire" : "Delete",
    rowsOnly: true,
    // One request takes 1,000 at most, and the web does not split it.
    tooMany: tooManyText,
    run: (chosen: Chosen) => {
      if (chosen.kind === "rows") ask(what, chosen.hids);
    },
  });
  const actions: GridAction<T>[] = [
    ...(allows(user.role, "inventory") ? [button("retire")] : []),
    ...(allows(user.role, "admin") ? [button("delete")] : []),
  ];
  const shown = (
    <>
      <RemovalOutcome kind={kind} outcome={outcome} />
      {asked && (
        <RemovalDialog
          key={`${asked.what} ${asked.hids.join(" ")}`}
          kind={kind}
          asked={asked}
          onCancel={() => setAsked(null)}
          onDone={(done) => {
            setAsked(null);
            setOutcome(done);
            setKeep(stayTicked(done.answer));
            setTurn((count) => count + 1);
          }}
        />
      )}
    </>
  );
  return { actions, ask, shown, turn, keep };
}

/** The state of the history entry of a list reached by a deletion on a record's page. */
export function deletedState(text: string): { deleted: string } {
  return { deleted: text };
}

/** What a deletion on a record's page said, as the list it went on to was reached with. */
export function useDeletedNote(): string {
  const { state } = useLocation();
  if (typeof state !== "object" || state === null || !("deleted" in state)) return "";
  const { deleted } = state as { deleted: unknown };
  return typeof deleted === "string" ? deleted : "";
}

interface DeleteRecordProps {
  kind: RemovalKind;
  hid: string;
  name: string;
}

/**
 * Delete, for an Admin, on the page of an item or a device group (P-227): it asks with
 * what the dry run answers, and once the record is deleted the list it belongs to is
 * shown, saying so. One that is refused stays, and the page says what is in its way.
 */
export function DeleteRecord({ kind, hid, name }: DeleteRecordProps) {
  const navigate = useNavigate();
  const [asked, setAsked] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const noun = kind === "item" ? "item" : "group";
  const list = kind === "item" ? "/items" : "/groups";
  return (
    <section aria-labelledby="delete-record">
      <h2 id="delete-record">Delete</h2>
      <RemovalOutcome kind={kind} outcome={outcome} ticked={false} />
      <p>
        Deleting is for a {noun} that should never have been, as one a wrong file made: retiring is
        the way a {noun} ends. Only a {noun} that nothing else depends on is deleted, and the
        deletion is kept in the audit trail with the {noun} as it was.
      </p>
      <p className="actions">
        <button
          type="button"
          className="danger"
          onClick={() => {
            setOutcome(null);
            setAsked(true);
          }}
        >
          Delete {noun}
        </button>
      </p>
      {asked && (
        <RemovalDialog
          kind={kind}
          asked={{ what: "delete", hids: [hid] }}
          onCancel={() => setAsked(false)}
          onDone={(done) => {
            setAsked(false);
            if (done.what === "delete" && done.answer.deleted.some((one) => one.hid === hid)) {
              const text = `${noun === "item" ? "Item" : "Group"} ${name} was deleted.`;
              navigate(list, { state: deletedState(text) });
            } else setOutcome(done);
          }}
        />
      )}
    </section>
  );
}
