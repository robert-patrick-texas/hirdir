// The two forms every record page has: one that changes a record and one that makes a
// new one. Both are driven by a list of fields, and both show the server's refusal where
// it belongs: a field's message beside its input, a stale version as a clear statement
// that someone else changed the record, with an offer to read it again.

import { type FormEvent, type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
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
}

/**
 * A form that changes a record. Only the fields that were changed are sent. A stale
 * version is never sent again by the form: the reader is told, and reloads.
 */
export function EditForm<R extends { row_version: number }, B extends { row_version: number }>(
  props: EditFormProps<R, B>,
) {
  const { specs, record, hints, notes, save, onSaved, onReload, submitLabel = "Save" } = props;
  const stored = record as R & Readonly<Record<string, unknown>>;
  const [values, setValues] = useState<FormValues>(() => formOf(specs, stored));
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const names = specs.map((spec) => spec.name);
  const built = buildPatch<B>(specs, stored, values);
  const refused = fieldErrors(action.error, names).shown;
  const [form, refusedNow] = useShownRefusal();

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
    const result = await action.run(() => save(built.body));
    if (result.ok) onSaved();
    else refusedNow();
  }

  return (
    <form onSubmit={submit} className="stack" noValidate ref={form}>
      <Problem error={action.error} shown={names} onReload={onReload} />
      <FormFields
        specs={specs}
        values={values}
        onChange={change}
        errors={{ ...refused, ...found }}
        {...(hints ? { hints } : {})}
        {...(notes ? { notes } : {})}
        disabled={action.busy}
      />
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
          disabled={action.busy || built.changed.length === 0}
          onClick={() => {
            setValues(formOf(specs, stored));
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
  children?: ReactNode;
}

/** A form that makes a new record. A field left blank is not sent. */
export function CreateForm<B, R>(props: CreateFormProps<B, R>) {
  const { title, specs, start, create, onCreated, onCancel, submitLabel, labels, children } = props;
  const [values, setValues] = useState<FormValues>(() => ({ ...formOf(specs), ...start }));
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const names = specs.map((spec) => spec.name);
  const refused = fieldErrors(action.error, names).shown;
  const [form, refusedNow] = useShownRefusal();
  const headingId = `new-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  function change(name: string, value: FormValue) {
    setValues((was) => ({ ...was, [name]: value }));
    setFound((was) => {
      const { [name]: _, ...rest } = was;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildCreate<B>(specs, values);
    setFound(built.errors);
    if (Object.keys(built.errors).length > 0) {
      action.clear();
      refusedNow();
      return;
    }
    const result = await action.run(() => create(built.body));
    if (result.ok) onCreated(result.value);
    else refusedNow();
  }

  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      {children}
      <form onSubmit={submit} className="stack" noValidate ref={form}>
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
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
