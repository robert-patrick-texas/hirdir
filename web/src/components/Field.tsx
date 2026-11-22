import {
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";

interface FieldProps {
  label: string;
  /** The server's message about this field, if it refused it. */
  error?: string | undefined;
  hint?: string;
}

interface TextFieldProps extends FieldProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password" | "email" | "search" | "datetime-local" | "date";
  required?: boolean;
  disabled?: boolean;
  maxLength?: number;
  autoComplete?: string;
  inputMode?: "text" | "numeric" | "decimal";
  placeholder?: string;
  inputRef?: Ref<HTMLInputElement>;
  /** The id of a <datalist> of suggestions. */
  list?: string;
  /** A key pressed in the box: as Enter, to add what was typed rather than send the form. */
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  /**
   * 0.9.18: what a format makes of what the box holds (P-322 (7)): a telephone number in
   * its pattern, an email address in lower case, a person's name in Title Case. It is
   * applied as the person leaves the box, or presses Enter in it, having typed in it, and
   * as something is pasted into it, never at each key; and, once it has changed what was
   * typed, not again unless something is pasted again, so that the person's own
   * correction stands.
   */
  tidy?: ((value: string) => string) | undefined;
}

function describedBy(...ids: Array<string | false | undefined>): string | undefined {
  const present = ids.filter(Boolean);
  return present.length > 0 ? present.join(" ") : undefined;
}

/** Give a ref the node, whichever kind of ref it is. */
function assign<T>(ref: Ref<T> | undefined, node: T | null): void {
  if (typeof ref === "function") ref(node);
  else if (ref) ref.current = node;
}

/** What is pasted, as one line: the line breaks at its ends dropped, those within it spaces. */
function oneLine(pasted: string): string {
  return pasted.replace(/^[\r\n]+|[\r\n]+$/g, "").replace(/\r\n|\r|\n/g, " ");
}

/** What the box says of a value longer than its field takes, or nothing. */
function tooLong(value: string, maxLength: number | undefined): string | undefined {
  const length = [...value].length;
  if (maxLength === undefined || length <= maxLength) return undefined;
  return `At most ${maxLength} characters: this has ${length}.`;
}

export function TextField(props: TextFieldProps) {
  const id = useId();
  const {
    label,
    error,
    hint,
    onChange,
    type = "text",
    inputRef,
    tidy,
    onKeyDown,
    ...input
  } = props;
  const { value, maxLength } = props;
  const box = useRef<HTMLInputElement | null>(null);
  const setBox = useCallback(
    (node: HTMLInputElement | null) => {
      box.current = node;
      assign(inputRef, node);
    },
    [inputRef],
  );
  // 0.9.18: whether the person has typed in the box, and whether a format has tidied it,
  // while the form is open; a box emptied, as by Undo changes or the next of a run, starts
  // again (P-322 (7)).
  const typed = useRef(false);
  const tidiedOnce = useRef(false);
  useEffect(() => {
    if (value !== "") return;
    typed.current = false;
    tidiedOnce.current = false;
  }, [value]);
  // Where the caret goes once a paste the box took itself is shown.
  const caret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const at = caret.current;
    if (at === null || !box.current) return;
    caret.current = null;
    if (box.current === document.activeElement) box.current.setSelectionRange(at, at);
  });

  /**
   * The format applied to what was typed, until it has once changed it: what the person
   * then changes of it stands.
   */
  function tidyTyped(): void {
    if (!tidy || !typed.current || tidiedOnce.current) return;
    const next = tidy(value);
    if (next === value) return;
    tidiedOnce.current = true;
    onChange(next);
  }

  /**
   * 0.9.18: pasting is never hindered (P-293): what is pasted is taken whole, even past
   * the most the field takes, which the box then says and the server refuses; and a box
   * with a format is tidied at once. Otherwise the browser pastes as it does.
   */
  function paste(event: ClipboardEvent<HTMLInputElement>): void {
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd ?? start;
    // A box that has no caret to speak of, as one for a day, is left to the browser.
    if (start === null || end === null) return;
    const pasted = oneLine(event.clipboardData.getData("text/plain"));
    const whole = target.value.slice(0, start) + pasted + target.value.slice(end);
    const cut = maxLength !== undefined && whole.length > maxLength;
    if (!tidy && !cut) return;
    event.preventDefault();
    typed.current = true;
    const next = tidy ? tidy(whole) : whole;
    if (next !== whole) tidiedOnce.current = true;
    caret.current = next === whole ? start + pasted.length : next.length;
    onChange(next);
  }

  const said = error ?? tooLong(value, maxLength);
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {props.required && <span className="required"> (required)</span>}
      </label>
      <input
        {...input}
        id={id}
        type={type}
        ref={setBox}
        spellCheck={false}
        autoCapitalize="none"
        aria-invalid={said ? true : undefined}
        aria-describedby={describedBy(hint && `${id}-hint`, said && `${id}-error`)}
        onChange={(event) => {
          typed.current = true;
          onChange(event.target.value);
        }}
        onBlur={tidyTyped}
        onPaste={paste}
        onKeyDown={(event) => {
          // Enter sends a form without leaving the box: what was typed is tidied first,
          // so that what is sent is what is shown.
          if (event.key === "Enter" && !event.nativeEvent.isComposing) flushSync(tidyTyped);
          onKeyDown?.(event);
        }}
      />
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {said && (
        <p className="field-error" id={`${id}-error`}>
          {said}
        </p>
      )}
    </div>
  );
}

interface CheckFieldProps extends FieldProps {
  name: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

/** How long a box shows what was chosen while the page has not yet said so itself. */
const ECHO_MS = 2000;

/**
 * What a box shows: what the page says, and, for the moment after a click, what was
 * chosen. A switch of a view is kept in the address of the page, and the address changes
 * a moment after the click: without this the box would spring back and then turn, and
 * would for that moment say the opposite of what was asked. The choice is shown until
 * the page says something else than it said at the click, and no longer than two
 * seconds, so a choice the page does not take is not shown as taken.
 */
function useEcho(checked: boolean): [boolean, (chosen: boolean) => void] {
  const [echo, setEcho] = useState<{ from: boolean; to: boolean } | null>(null);
  useEffect(() => {
    if (!echo) return;
    if (echo.from !== checked) {
      setEcho(null);
      return;
    }
    const timer = setTimeout(() => setEcho(null), ECHO_MS);
    return () => clearTimeout(timer);
  }, [echo, checked]);
  return [
    echo && echo.from === checked ? echo.to : checked,
    (chosen) => setEcho({ from: checked, to: chosen }),
  ];
}

export function CheckField({ label, error, hint, onChange, checked, ...input }: CheckFieldProps) {
  const id = useId();
  const [shown, choose] = useEcho(checked);
  return (
    <div className="field field-check">
      <input
        {...input}
        id={id}
        type="checkbox"
        checked={shown}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
        onChange={(event) => {
          choose(event.target.checked);
          onChange(event.target.checked);
        }}
      />
      <label htmlFor={id}>{label}</label>
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

interface SelectFieldProps extends FieldProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
  children: ReactNode;
}

export function SelectField(props: SelectFieldProps) {
  const id = useId();
  const { label, error, hint, onChange, children, ...select } = props;
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {props.required && <span className="required"> (required)</span>}
      </label>
      <select
        {...select}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

interface TextAreaFieldProps extends FieldProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  required?: boolean;
  disabled?: boolean;
  maxLength?: number;
}

export function TextAreaField(props: TextAreaFieldProps) {
  const id = useId();
  const { label, error, hint, onChange, rows = 3, ...area } = props;
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {props.required && <span className="required"> (required)</span>}
      </label>
      <textarea
        {...area}
        id={id}
        rows={rows}
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

interface CheckGroupFieldProps extends FieldProps {
  name: string;
  /** What may be ticked. */
  options: ReadonlyArray<{ value: string; label: string }>;
  /** What is ticked. */
  value: readonly string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
  /** What to say when there is nothing to tick. */
  empty?: string;
}

/** A set of tick boxes under one heading: any number of a list of values. */
export function CheckGroupField(props: CheckGroupFieldProps) {
  const id = useId();
  const { label, error, hint, name, options, value, onChange, disabled, empty } = props;
  return (
    <fieldset
      className="field check-group"
      aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
    >
      <legend>{label}</legend>
      {options.length === 0 && <p className="muted">{empty ?? "There is nothing to choose."}</p>}
      {options.map((option, place) => (
        <span className="choice" key={option.value}>
          <input
            id={`${id}-${place}`}
            type="checkbox"
            name={name}
            value={option.value}
            checked={value.includes(option.value)}
            disabled={disabled}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...value.filter((entry) => entry !== option.value), option.value]
                  : value.filter((entry) => entry !== option.value),
              )
            }
          />
          <label htmlFor={`${id}-${place}`}>{option.label}</label>
        </span>
      ))}
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </fieldset>
  );
}

interface RadioGroupFieldProps extends FieldProps {
  name: string;
  /** What may be chosen. */
  options: ReadonlyArray<{ value: string; label: string }>;
  /** What is chosen. */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/** One of a few values under one heading, each on show: Yes or No. */
export function RadioGroupField(props: RadioGroupFieldProps) {
  const id = useId();
  const { label, error, hint, name, options, value, onChange, disabled } = props;
  return (
    <fieldset
      className="field check-group"
      aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
    >
      <legend>{label}</legend>
      {options.map((option, place) => (
        <span className="choice" key={option.value}>
          <input
            id={`${id}-${place}`}
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={disabled}
            onChange={() => onChange(option.value)}
          />
          <label htmlFor={`${id}-${place}`}>{option.label}</label>
        </span>
      ))}
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </fieldset>
  );
}
