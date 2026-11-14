import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { plural } from "../lib/format";
import { useLoad } from "../lib/hooks";
import type { Option } from "../lib/patch";
import { Problem } from "./Problem";

// How long after the last key the search is sent, in milliseconds.
const PAUSE = 300;

/** What a search found: the first few that match, and how many match in all. */
export interface Found {
  options: Array<Option & { draft?: boolean }>;
  total: number;
}

export interface PickFieldProps {
  label: string;
  name: string;
  /** The HID of the record chosen, or blank for none. */
  value: string;
  onChange: (hid: string) => void;
  /** Records the form already knows what to call, such as the one the record has. */
  known?: readonly Option[];
  /** What to say while none is chosen: "No location". */
  blank?: string;
  hint?: string;
  error?: string | undefined;
  disabled?: boolean;
}

interface SearchProps extends PickFieldProps {
  /** What is searched for, one and many: "location", "locations". */
  noun: [one: string, many: string];
  /** How to search, as a sentence beneath the box. */
  how: string;
  /** Ask the server for what matches. Blank text is no search, and answers null. */
  find: (typed: string, signal: AbortSignal) => Promise<Found | null>;
}

/**
 * A field of a form that holds one record of a list too long to offer whole, chosen by
 * searching for it: a location, a contact. What is typed is sent to the server as a
 * filter of the list, and the first few that match are offered as buttons. What the form
 * holds is the HID of the one chosen.
 *
 * The field stands inside a form: Enter in its box searches at once and submits nothing.
 */
export function PickField(props: SearchProps) {
  const { label, name, value, onChange, known = [], blank = "None", hint, error, disabled } = props;
  const { noun, how, find } = props;
  const id = useId();
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");
  // What the reader chose here, so that it can be called by its name at once.
  const [picked, setPicked] = useState<Option | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setAsked(typed), PAUSE);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const searching = asked.trim() !== "";
  const found = useLoad(`pick ${noun[0]} ${asked.trim()}`, (signal) => find(asked, signal));

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    // Inside a form, Enter would send the form: it searches instead.
    event.preventDefault();
    setAsked(typed);
  }

  function choose(option: Option | null) {
    setPicked(option);
    onChange(option?.value ?? "");
    setTyped("");
    setAsked("");
  }

  const chosen =
    value === ""
      ? ""
      : picked?.value === value
        ? picked.label
        : (known.find((option) => option.value === value)?.label ?? value);
  const options = found.data?.options ?? [];
  const more = found.data ? found.data.total - options.length : 0;
  const described = [`${id}-chosen`, `${id}-hint`, error ? `${id}-error` : ""]
    .filter(Boolean)
    .join(" ");
  const many = noun[1].charAt(0).toUpperCase() + noun[1].slice(1);

  return (
    <div className="field place-field" data-field={name}>
      <label htmlFor={id}>{label}</label>
      <p className="place-chosen" id={`${id}-chosen`}>
        <span data-testid={`chosen-${name}`} className={chosen ? undefined : "muted"}>
          {chosen || blank}
        </span>
        {chosen && (
          <button type="button" onClick={() => choose(null)} disabled={disabled}>
            Clear<span className="visually-hidden"> the {label.toLowerCase()}</span>
          </button>
        )}
      </p>
      <input
        id={id}
        type="search"
        name={name}
        value={typed}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
        autoCapitalize="none"
        placeholder={chosen ? "Search for another" : "Search"}
        aria-invalid={error ? true : undefined}
        aria-describedby={described}
        onChange={(event) => setTyped(event.target.value)}
        onKeyDown={keyDown}
      />
      <p className="hint" id={`${id}-hint`}>
        {hint ? `${hint} ` : ""}
        {how}
      </p>
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
      <Problem error={found.error} />
      <div role="status" aria-live="polite">
        {searching && found.data && options.length === 0 && (
          <p className="muted">No {noun[0]} matches.</p>
        )}
        {searching && found.loading && !found.data && (
          <p className="muted loading-late">Searching…</p>
        )}
      </div>
      {options.length > 0 && (
        <ul className="pick-results" aria-label={`${many} that match`}>
          {options.map((option) => (
            <li key={option.value}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => choose({ value: option.value, label: option.label })}
              >
                {option.label}
              </button>
              {option.draft && <span className="badge">Draft</span>}
            </li>
          ))}
        </ul>
      )}
      {options.length > 0 && more > 0 && (
        <p className="hint">
          {plural(more, `more ${noun[0]}`)} {more === 1 ? "matches" : "match"}. Type more to narrow
          them down.
        </p>
      )}
    </div>
  );
}
