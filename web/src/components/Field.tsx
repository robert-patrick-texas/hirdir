import { type ReactNode, type Ref, useEffect, useId, useState } from "react";

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
}

function describedBy(...ids: Array<string | false | undefined>): string | undefined {
  const present = ids.filter(Boolean);
  return present.length > 0 ? present.join(" ") : undefined;
}

export function TextField(props: TextFieldProps) {
  const id = useId();
  const { label, error, hint, onChange, type = "text", inputRef, ...input } = props;
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
        ref={inputRef}
        spellCheck={false}
        autoCapitalize="none"
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
