// Forms and what they send. A form is filled from a record; a save sends only the fields
// that were changed, with the version the record was read at. A blank is sent as null,
// which clears a field and makes one that inherits do so again. An amount is sent as the
// text that was typed: it never passes through a JavaScript number.

export type FieldKind =
  /** One line of text. */
  | "text"
  /** Several lines of text. */
  | "longtext"
  /** A whole number. */
  | "integer"
  /** A date, as YYYY-MM-DD. */
  | "date"
  /** A decimal amount, kept as text. `places` is how many it may have after the point. */
  | "decimal"
  /** Yes or no. */
  | "boolean"
  /** Yes, no or blank. */
  | "tristate"
  /** One of a list of values, or blank. */
  | "choice"
  /** A list of text, one to a line. */
  | "lines"
  /** A set of labels, in no order. */
  | "set"
  /** A location, found by searching for it. What the form holds is its HID. */
  | "location"
  /** A contact, found by searching for it by name or email. What the form holds is its HID. */
  | "contact"
  /** An operator, found by its label or by the person behind it. What the form holds is its HID. */
  | "operator";

export interface Option {
  value: string;
  label: string;
  /** A heading to group the option under. */
  group?: string;
  /**
   * What there is to say of the option once it is chosen, shown beneath the field: of an
   * owner outside the team, that it is one, and its reason.
   */
  note?: string;
}

export interface FieldSpec {
  name: string;
  label: string;
  kind: FieldKind;
  /** For a decimal: the most digits after the point. */
  places?: number;
  hint?: string;
  required?: boolean;
  maxLength?: number;
  /**
   * For a choice or a set: what may be chosen. For a location: the ones the form already
   * knows what to call, such as the one the record has, each by its HID with its path.
   */
  options?: readonly Option[];
  /**
   * For a choice, or for yes or no: the text of the blank option. Left out, there is
   * none. For a location: what to say while none is chosen.
   */
  blank?: string;
  /** A heading to put above this field, which starts a new group of fields. */
  heading?: string;
  /**
   * Whether the form asks for this field, given what it holds now: the reason for an
   * exception is asked for only while the owner chosen is outside the team. A field that
   * is not asked for is not shown, and nothing of it is sent.
   */
  when?: (values: FormValues) => boolean;
  /**
   * For a field with `when`: while the form does not ask for it, a value the record
   * holds is cleared with the change, in the same request. So a shipping address is
   * cleared as "deliveries go to the street address" is ticked, which the server would
   * refuse beside one.
   */
  clearedWhenNotAsked?: boolean;
}

export type FormValue = string | boolean | string[];
export type FormValues = Record<string, FormValue>;

/**
 * What is said beneath a field: the hint the record gives it, or else its own, and after
 * that what the option that is chosen has to say of itself, as an owner outside the team
 * says that it is one. Nothing at all is undefined.
 */
export function hintOf(
  spec: FieldSpec,
  value: FormValue | undefined,
  given?: string,
): string | undefined {
  const chosen =
    spec.kind === "choice" && typeof value === "string" && value !== ""
      ? spec.options?.find((option) => option.value === value)?.note
      : undefined;
  return [given ?? spec.hint, chosen].filter(Boolean).join(" ") || undefined;
}

/** Whether a form asks for a field, given what the form holds now. */
export function asked(spec: FieldSpec, values: FormValues): boolean {
  return spec.when === undefined || spec.when(values);
}

type Stored = Readonly<Record<string, unknown>>;

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : String(value);
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map((entry) => String(entry)) : [];
}

/** The value a form field starts with, for a record or for nothing. */
function initial(spec: FieldSpec, stored: unknown): FormValue {
  switch (spec.kind) {
    case "boolean":
      return stored === true;
    case "tristate":
      return stored === true ? "true" : stored === false ? "false" : "";
    case "lines":
      return list(stored).join("\n");
    case "set":
      return list(stored);
    default:
      return text(stored);
  }
}

/** Fill a form from a record. With no record, every field starts blank. */
export function formOf(specs: readonly FieldSpec[], record: Stored | null = null): FormValues {
  const values: FormValues = {};
  for (const spec of specs) values[spec.name] = initial(spec, record?.[spec.name]);
  return values;
}

/** A decimal without the zeros that say nothing: `18000.00` and `018000` are `18000`. */
export function canonicalDecimal(value: string): string {
  const [whole = "", fraction = ""] = value.trim().split(".");
  const digits = whole.replace(/^0+(?=\d)/, "");
  const rest = fraction.replace(/0+$/, "");
  return rest === "" ? digits : `${digits}.${rest}`;
}

function lines(value: FormValue): string[] {
  return text(value)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

function sameSet(one: readonly string[], other: readonly string[]): boolean {
  if (one.length !== other.length) return false;
  const have = new Set(one);
  return other.every((entry) => have.has(entry));
}

export type Read = { value: unknown } | { error: string };

/** What a form field holds, in the form the server takes it. A blank is null. */
export function read(spec: FieldSpec, value: FormValue | undefined): Read {
  switch (spec.kind) {
    case "boolean":
      return { value: value === true };
    case "tristate":
      return { value: value === "true" ? true : value === "false" ? false : null };
    case "lines":
      return { value: lines(value ?? "") };
    case "set":
      return { value: Array.isArray(value) ? [...value] : [] };
    default:
  }
  const typed = text(value).trim();
  if (typed === "") return { value: null };
  if (spec.kind === "integer") {
    if (!/^\d{1,15}$/.test(typed)) return { error: "A whole number, with digits only." };
    return { value: Number.parseInt(typed, 10) };
  }
  if (spec.kind === "decimal") {
    const places = spec.places ?? 2;
    if (!new RegExp(`^\\d+(\\.\\d{1,${places}})?$`).test(typed)) {
      return {
        error: `A number that is not negative, with at most ${places} digits after the point.`,
      };
    }
    return { value: typed };
  }
  if (spec.kind === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(typed)) {
    return { error: "A date, as YYYY-MM-DD." };
  }
  return { value: typed };
}

function unchanged(spec: FieldSpec, stored: unknown, wanted: unknown): boolean {
  switch (spec.kind) {
    case "boolean":
      return (stored === true) === wanted;
    case "lines":
      return JSON.stringify(list(stored)) === JSON.stringify(wanted);
    case "set":
      return sameSet(list(stored), wanted as string[]);
    case "decimal":
      if (typeof stored === "string" && typeof wanted === "string") {
        return canonicalDecimal(stored) === canonicalDecimal(wanted);
      }
      break;
    default:
  }
  const was = stored === undefined || stored === "" ? null : stored;
  return was === wanted;
}

export interface Built<T> {
  body: T;
  /** The names of the fields the body changes or sets. */
  changed: string[];
  /** What is wrong with a field, found before anything was sent. */
  errors: Record<string, string>;
}

/**
 * The body of a `PATCH`: the version the record was read at and the fields that differ
 * from it, and nothing else. A field left as it was is left out, so that it is left alone.
 */
export function buildPatch<T extends { row_version: number }>(
  specs: readonly FieldSpec[],
  record: Stored & { row_version: number },
  values: FormValues,
): Built<T> {
  const body: Record<string, unknown> = { row_version: record.row_version };
  const changed: string[] = [];
  const errors: Record<string, string> = {};
  for (const spec of specs) {
    if (!asked(spec, values)) {
      const held = record[spec.name];
      if (spec.clearedWhenNotAsked && held !== null && held !== undefined && held !== "") {
        body[spec.name] = null;
        changed.push(spec.name);
      }
      continue;
    }
    const result = read(spec, values[spec.name]);
    if ("error" in result) {
      // What was typed cannot be sent. If it is what the form started with, it is no change.
      if (text(values[spec.name]).trim() !== text(record[spec.name])) {
        errors[spec.name] = result.error;
      }
      continue;
    }
    if (unchanged(spec, record[spec.name], result.value)) continue;
    body[spec.name] = result.value;
    changed.push(spec.name);
  }
  return { body: body as T, changed, errors };
}

/**
 * The body of a `POST` that creates: the fields that were given a value. A blank is left
 * out, so that the server's own default stands.
 */
export function buildCreate<T>(specs: readonly FieldSpec[], values: FormValues): Built<T> {
  const body: Record<string, unknown> = {};
  const changed: string[] = [];
  const errors: Record<string, string> = {};
  for (const spec of specs) {
    if (!asked(spec, values)) continue;
    const result = read(spec, values[spec.name]);
    if ("error" in result) {
      errors[spec.name] = result.error;
      continue;
    }
    const { value } = result;
    const blank = value === null || value === false || (Array.isArray(value) && value.length === 0);
    if (blank) {
      if (spec.required) errors[spec.name] = "Must not be blank.";
      continue;
    }
    body[spec.name] = value;
    changed.push(spec.name);
  }
  return { body: body as T, changed, errors };
}
