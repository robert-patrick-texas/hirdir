// The two forms every record page has: one that changes a record and one that makes a
// new one. Both are driven by a list of fields, and both show the server's refusal where
// it belongs: a field's message beside its input, a stale version as a clear statement
// that someone else changed the record, with an offer to read it again.

import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";
import { useAction } from "../lib/hooks";
import {
  buildCreate,
  buildPatch,
  type FieldSpec,
  type FormValue,
  type FormValues,
  formOf,
} from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { carryTyped, forgetLeft, leave, peekLeft, savedRecord } from "../lib/typedAfterSave";
import { FormFields } from "./FormFields";
import { Problem } from "./Problem";

/**
 * Bring a refusal to the reader. A form can be longer than the window, with its button at
 * the bottom: the first input that was refused is given the focus, and a refusal that is
 * about no input, such as a stale version, is scrolled into view.
 */
function useShownRefusal(): [RefObject<HTMLFormElement | null>, () => void] {
  const form = useRef<HTMLFormElement>(null);
  const [refusals, setRefusals] = useState(0);
  useEffect(() => {
    if (refusals === 0 || !form.current) return;
    const input = form.current.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (input) input.focus();
    else form.current.querySelector(".alert-error")?.scrollIntoView({ block: "nearest" });
  }, [refusals]);
  return [form, () => setRefusals((count) => count + 1)];
}

interface EditFormProps<R, B> {
  specs: readonly FieldSpec[];
  /** The record as it was read. Its `row_version` goes with the change. */
  record: R;
  hints?: Readonly<Record<string, string>>;
  /** Something to read above a field, by its name: what applies before anything is typed. */
  notes?: Readonly<Record<string, ReactNode>>;
  /** Send the change: the version and the fields that differ, and nothing else. */
  save: (body: B) => Promise<unknown>;
  /** The change was taken. */
  onSaved: () => void;
  /** Read the record again, as when someone else has changed it. */
  onReload: () => void;
  submitLabel?: string;
  /** What the page calls a field the server may refuse and the form has no input for. */
  labels?: Readonly<Record<string, string>>;
}

/**
 * A form that changes a record. Only the fields that were changed are sent. A stale
 * version is never sent again by the form: the reader is told, and reloads.
 *
 * 0.9.6: what is typed after a save, while the page reads the record again, stays
 * (P-202). The form compares what it holds with the record as it last took it: after a
 * save that is the record as saved, with the version the server answered, so that the
 * next save is not refused as stale; once the page has read the record again, a field
 * the person has changed keeps what was typed and the others take what was read. A page
 * that makes a new form for the record it read again, by a `key` with its version, is
 * handed what the form before it held.
 */
export function EditForm<R extends { row_version: number }, B extends { row_version: number }>(
  props: EditFormProps<R, B>,
) {
  const { specs, record, hints, notes, save, onSaved, onReload, submitLabel = "Save" } = props;
  const { labels } = props;
  const stored = record as R & Readonly<Record<string, unknown>>;
  const names = specs.map((spec) => spec.name);
  const hid = typeof stored.hid === "string" ? stored.hid : null;
  const leftKey = hid === null ? null : `${hid} ${names.join(" ")}`;
  // The record the form compares with, and the values it filled the form with from it.
  const [base, setBase] = useState<{ record: R; taken: FormValues }>(() => ({
    record,
    taken: formOf(specs, stored),
  }));
  const [values, setValues] = useState<FormValues>(() => {
    const held = leftKey === null ? null : peekLeft(leftKey, record, Date.now());
    const taken = formOf(specs, stored);
    return held ? carryTyped(specs, held.taken, held.values, stored) : taken;
  });
  // The record as the page last gave it, to see when it has been read again.
  const [given, setGiven] = useState(`${hid} ${record.row_version}`);
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const built = buildPatch<B>(specs, base.record as R & Readonly<Record<string, unknown>>, values);
  const refused = fieldErrors(action.error, names).shown;
  const [form, refusedNow] = useShownRefusal();

  // The page read the record again: what was typed since the form took it stays.
  const now = `${hid} ${record.row_version}`;
  if (now !== given) {
    setGiven(now);
    if ((base.record as { hid?: unknown }).hid !== hid) {
      setBase({ record, taken: formOf(specs, stored) });
      setValues(formOf(specs, stored));
    } else if (record.row_version >= base.record.row_version) {
      setBase({ record, taken: formOf(specs, stored) });
      setValues(carryTyped(specs, base.taken, values, stored));
    }
  }

  // Once it has saved, what the form holds is kept for a form of the same record that
  // takes its place: the page makes that one as it renders, before this one has gone.
  const saved = useRef(false);
  useEffect(() => {
    if (leftKey !== null) forgetLeft(leftKey);
  }, [leftKey]);
  useEffect(() => {
    if (leftKey === null || !saved.current) return;
    const record = base.record as R & Readonly<Record<string, unknown>>;
    leave(leftKey, { record, taken: base.taken, values, at: Date.now() });
  });

  function change(name: string, value: FormValue) {
    setValues((was) => ({ ...was, [name]: value }));
    setFound((was) => {
      const { [name]: _, ...rest } = was;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFound(built.errors);
    if (Object.keys(built.errors).length > 0) {
      action.clear();
      refusedNow();
      return;
    }
    const sent = values;
    const result = await action.run(() => save(built.body));
    if (result.ok) {
      saved.current = true;
      const after = savedRecord(base.record, built.body, result.value);
      if (after !== base.record) setBase({ record: after, taken: sent });
      onSaved();
    } else refusedNow();
  }
  return (
    <form onSubmit={submit} className="stack" noValidate ref={form}>
      <Problem
        error={action.error}
        shown={names}
        onReload={onReload}
        {...(labels ? { labels } : {})}
      />
      <FormFields
        specs={specs}
        values={values}
        onChange={change}
        errors={{ ...refused, ...found }}
        {...(hints ? { hints } : {})}
        {...(notes ? { notes } : {})}
        disabled={action.busy}
      />
      {/* 0.9.5: at the foot of the window while the form runs on below it (P-190). */}
      <p className="actions form-foot">
        <button
          type="submit"
          className="primary"
          disabled={action.busy || built.changed.length === 0}
        >
          {submitLabel}
        </button>
        <button
          type="button"
          disabled={action.busy || built.changed.length === 0}
          onClick={() => {
            setValues(base.taken);
            setFound({});
            action.clear();
          }}
        >
          Undo changes
        </button>
      </p>
    </form>
  );
}

// How long after a press of a button a form that opens is taken to be opened by it, in
// milliseconds: a form may wait for the lists it offers, which a busy server sends late.
const OPENED_WAIT = 10_000;

/**
 * The last press of a button, to tell a form opened by a press from one a page shows open
 * as it loads, which begins at its top (P-167). Any click, of a link as well, takes the
 * place of the one before; a press on another page is not this page's.
 */
let pressed: { at: number; path: string; button: Element } | null = null;

if (typeof document !== "undefined") {
  document.addEventListener(
    "click",
    (event) => {
      const button = event.target instanceof Element ? event.target.closest("button") : null;
      pressed = button ? { at: performance.now(), path: window.location.pathname, button } : null;
    },
    true,
  );
}

/**
 * Whether a form that has just opened was opened by the press of a button outside it, a
 * moment before, on this page. The press is used up: it opens one form.
 */
function openedByPress(form: Element): boolean {
  const press = pressed;
  if (!press) return false;
  if (performance.now() - press.at > OPENED_WAIT) return false;
  if (press.path !== window.location.pathname || form.contains(press.button)) return false;
  pressed = null;
  return true;
}

/**
 * A form opened by a press comes into the window and its first field takes the keyboard
 * (P-190): the whole form where it fits in the window, and from its heading where not.
 */
function bringIntoView(section: HTMLElement): void {
  const heading = section.querySelector<HTMLElement>("h2, h3");
  if (section.getBoundingClientRect().height <= window.innerHeight) {
    section.scrollIntoView({ block: "nearest" });
  } else {
    (heading ?? section).scrollIntoView({ block: "start" });
  }
  firstField(section)?.focus({ preventScroll: true });
}

/**
 * A form, its section, opened by a press comes into the window with the keyboard in its
 * first field (P-190): for every form opened by a button New, those built here and those
 * written by hand, as New group's.
 */
export function useOpenedIntoView(section: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    if (section.current && openedByPress(section.current)) bringIntoView(section.current);
  }, [section]);
}

// The boxes in which Enter sends the form they stand in.
const SENDS_ON_ENTER = new Set(["text", "search", "email", "tel", "url", "number", "password"]);

/**
 * Once a record has been made by the second button, Enter in a box of the form sends it
 * as that button (P-192): a run of items, a scanner's Enter after each serial number, is
 * not ended by the first button, which leaves the form. A box that takes Enter for itself,
 * as a picker that searches, has said so first, and is left to it.
 */
function enterAsAnother(event: KeyboardEvent<HTMLFormElement>): void {
  if (event.key !== "Enter" || event.defaultPrevented || event.nativeEvent.isComposing) return;
  if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
  const box = event.target;
  if (!(box instanceof HTMLInputElement) || !SENDS_ON_ENTER.has(box.type)) return;
  const button = event.currentTarget.querySelector<HTMLButtonElement>("button[data-another]");
  if (!button || button.disabled) return;
  event.preventDefault();
  event.currentTarget.requestSubmit(button);
}

/** The first field of a form that takes the keyboard. */
function firstField(within: HTMLElement): HTMLElement | null {
  const fields = within.querySelectorAll<HTMLElement>(
    "form input:not([type=hidden]):not(:disabled), form select:not(:disabled), form textarea:not(:disabled)",
  );
  return [...fields].find((field) => field.getClientRects().length > 0) ?? null;
}

interface CreateFormProps<B, R> {
  /** The heading of the form. */
  title: string;
  specs: readonly FieldSpec[];
  /** Values to start with. */
  start?: FormValues;
  create: (body: B) => Promise<R>;
  onCreated: (record: R) => void;
  onCancel: () => void;
  submitLabel: string;
  /** What to call a field of the request that the form has no input for, in a refusal. */
  labels?: Readonly<Record<string, string>>;
  /** Something to read above a field, by its name: what applies before anything is typed. */
  notes?: Readonly<Record<string, ReactNode>>;
  /** A second button, which makes the record and keeps the form open for the next. */
  another?: Another<R>;
  children?: ReactNode;
}

/**
 * Make another like it (P-192): the record is made, and the form stays open with what the
 * next one shares, the rest blank and the keyboard in the field named first.
 */
export interface Another<R> {
  label: string;
  /** The fields the next record shares, which keep what was typed. */
  keep: readonly string[];
  /** The field that takes the keyboard for the next one. */
  focus: string;
  /** The record was made, and the form is open for the next. */
  onCreated: (record: R) => void;
}

/** A form that makes a new record. A field left blank is not sent. */
export function CreateForm<B, R>(props: CreateFormProps<B, R>) {
  const { title, specs, start, create, onCreated, onCancel, submitLabel, labels, children } = props;
  const { another } = props;
  const [values, setValues] = useState<FormValues>(() => ({ ...formOf(specs), ...start }));
  // How many were made by the second button: each puts the keyboard in its field.
  const [again, setAgain] = useState(0);
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const names = specs.map((spec) => spec.name);
  const refused = fieldErrors(action.error, names).shown;
  const [form, refusedNow] = useShownRefusal();
  const headingId = `new-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const section = useRef<HTMLElement>(null);

  // Opened by a press, the form comes into the window with the keyboard in it (P-190).
  useOpenedIntoView(section);

  const focus = another?.focus;
  useEffect(() => {
    if (again > 0 && focus) form.current?.querySelector<HTMLElement>(`[name="${focus}"]`)?.focus();
  }, [again, focus, form]);

  function change(name: string, value: FormValue) {
    setValues((was) => ({ ...was, [name]: value }));
    setFound((was) => {
      const { [name]: _, ...rest } = was;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Which button sent it: Enter in a field is the first, which makes the record alone,
    // until one was made by the second, and then the second (`enterAsAnother`).
    const sender = (event.nativeEvent as SubmitEvent).submitter;
    const next = another && sender?.hasAttribute("data-another") ? another : null;
    const built = buildCreate<B>(specs, values);
    setFound(built.errors);
    if (Object.keys(built.errors).length > 0) {
      action.clear();
      refusedNow();
      return;
    }
    const result = await action.run(() => create(built.body));
    if (!result.ok) refusedNow();
    else if (!next) onCreated(result.value);
    else {
      // What the next one shares is kept; what is each one's own starts again.
      const kept = Object.fromEntries(
        next.keep.filter((name) => name in values).map((name) => [name, values[name]]),
      ) as FormValues;
      setValues({ ...formOf(specs), ...start, ...kept });
      setAgain((count) => count + 1);
      next.onCreated(result.value);
    }
  }

  return (
    <section className="panel" aria-labelledby={headingId} ref={section}>
      <h2 id={headingId}>{title}</h2>
      {children}
      <form
        onSubmit={submit}
        className="stack"
        noValidate
        ref={form}
        {...(another && again > 0 ? { onKeyDown: enterAsAnother } : {})}
      >
        <Problem error={action.error} shown={names} {...(labels ? { labels } : {})} />
        <FormFields
          specs={specs}
          values={values}
          onChange={change}
          errors={{ ...refused, ...found }}
          {...(props.notes ? { notes: props.notes } : {})}
          disabled={action.busy}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            {submitLabel}
          </button>
          {another && (
            <button type="submit" data-another="" disabled={action.busy}>
              {another.label}
            </button>
          )}
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
        {another && again > 0 && (
          <p className="hint" data-testid="enter-as-another">
            Enter in a field now makes the next one as {another.label} does.
          </p>
        )}
      </form>
    </section>
  );
}
