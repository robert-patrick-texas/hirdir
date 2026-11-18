// 0.9.6: what is typed into a form after its Save, while the page reads the record again,
// is kept (P-202). A field the person has changed since the form last took the record
// keeps what was typed; every other field takes what the record now has. The next save
// goes with the version of the record as it was read, so that it is not refused as stale.

import { type FieldSpec, type FormValue, type FormValues, formOf } from "./patch";

type Stored = Readonly<Record<string, unknown>>;

function same(a: FormValue | undefined, b: FormValue | undefined): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((entry, at) => entry === b[at]);
  }
  return a === b;
}

/** The fields that hold something other than what the form took the record as. */
export function touched(
  specs: readonly FieldSpec[],
  taken: FormValues,
  values: FormValues,
): string[] {
  return specs.map((spec) => spec.name).filter((name) => !same(taken[name], values[name]));
}

/**
 * The values of a form once the record has been read again: what the person changed since
 * `taken` stays, and every other field is filled from the record as it now is.
 */
export function carryTyped(
  specs: readonly FieldSpec[],
  taken: FormValues,
  values: FormValues,
  record: Stored,
): FormValues {
  const fresh = formOf(specs, record);
  for (const name of touched(specs, taken, values)) {
    const typed = values[name];
    if (typed !== undefined) fresh[name] = typed;
  }
  return fresh;
}

/**
 * The fields whose typed value is kept over a value someone else saved meanwhile: changed
 * by the person since `taken`, changed in the record read again since `taken` too, and to
 * something other than what was typed. Saving replaces what the record now has, and the
 * person is told so under each of them.
 */
export function changedMeanwhile(
  specs: readonly FieldSpec[],
  taken: FormValues,
  values: FormValues,
  record: Stored,
): string[] {
  const fresh = formOf(specs, record);
  return touched(specs, taken, values).filter(
    (name) => !same(fresh[name], taken[name]) && !same(fresh[name], values[name]),
  );
}

/** What a field holds, in the words the form shows it in: a choice by its label. */
function shown(spec: FieldSpec, value: FormValue | undefined): string {
  const label = (one: string) => spec.options?.find((option) => option.value === one)?.label ?? one;
  if (value === undefined || value === "") return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(label).join(", ");
  if (spec.kind === "tristate") return value === "true" ? "Yes" : value === "false" ? "No" : value;
  return label(value);
}

/** What is said under a kept field whose value someone else changed meanwhile. */
export function meanwhileNote(spec: FieldSpec, value: FormValue | undefined): string {
  const now = shown(spec, value);
  return now === ""
    ? "Emptied meanwhile by someone else; saving replaces that."
    : `Changed meanwhile to “${now}”; saving replaces it.`;
}

/**
 * The record as a save left it, before the page has read it again: what was sent, over
 * the record as it was, with the version the server answered. Without a version in the
 * answer there is nothing to go on, and the record stays as it was.
 */
export function savedRecord<R extends { row_version: number }>(
  record: R,
  body: Readonly<Record<string, unknown>>,
  answer: unknown,
): R {
  const version =
    answer !== null && typeof answer === "object" && "row_version" in answer
      ? (answer as { row_version: unknown }).row_version
      : undefined;
  if (typeof version !== "number") return record;
  return { ...record, ...body, row_version: version };
}

/** What a form held when it went, kept for the form that takes its place (P-202). */
export interface Left {
  /** The record as the form last took it, and the values it filled the form with. */
  record: Stored & { row_version: number };
  taken: FormValues;
  /** What the form held. */
  values: FormValues;
  /** The fields kept over a value someone else saved meanwhile. */
  meanwhile: readonly string[];
  at: number;
}

// How long what a form held is kept for the form that takes its place, in milliseconds:
// a busy server reads the record again late.
const KEPT_FOR = 120_000;

const left = new Map<string, Left>();

/** What a form that has saved holds now, for a form that may take its place. */
export function leave(key: string, held: Left): void {
  left.set(key, held);
}

/**
 * What the form that went before held, if it was of the same record, saved, and the
 * record read now is no older than the one it held.
 */
export function peekLeft(key: string, record: { row_version: number }, now: number): Left | null {
  const held = left.get(key);
  if (!held) return null;
  if (now - held.at > KEPT_FOR || record.row_version < held.record.row_version) return null;
  return held;
}

/** What the form before held has been taken by the one in its place. */
export function forgetLeft(key: string): void {
  left.delete(key);
}
