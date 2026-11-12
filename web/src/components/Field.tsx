import { type ReactNode, type Ref, useId } from "react";

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
  type?: "text" | "password" | "email" | "search" | "datetime-local";
  required?: boolean;
  disabled?: boolean;
  maxLength?: number;
  autoComplete?: string;
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

export function CheckField({ label, error, hint, onChange, ...input }: CheckFieldProps) {
  const id = useId();
  return (
    <div className="field field-check">
      <input
        {...input}
        id={id}
        type="checkbox"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
        onChange={(event) => onChange(event.target.checked)}
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
