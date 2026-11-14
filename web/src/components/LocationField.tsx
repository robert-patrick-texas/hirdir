import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { api } from "../api";
import { plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useLoad } from "../lib/hooks";
import type { Option } from "../lib/patch";
import { PICK_LIMIT } from "../lib/pick";
import { locationSearch } from "../lib/places";
import { Problem } from "./Problem";

// How long after the last key the search is sent, in milliseconds.
const PAUSE = 300;

interface LocationFieldProps {
  label: string;
  name: string;
  /** The HID of the location chosen, or blank for none. */
  value: string;
  onChange: (hid: string) => void;
  /** Locations the form already knows what to call, such as the one the record has. */
  known?: readonly Option[];
  /** What to say while none is chosen: "No location". */
  blank?: string;
  hint?: string;
  error?: string | undefined;
  disabled?: boolean;
}

/**
 * A field of a form that holds a location, chosen by searching for it. A site may have
 * thousands of locations, so they are never listed whole: what is typed is sent to the
 * server as a filter of the list of locations, and the first few that match are offered,
 * each by its path. Drafts are offered too; retired locations are not.
 *
 * The field stands inside a form: Enter in its box searches at once and submits nothing.
 */
export function LocationField(props: LocationFieldProps) {
  const { label, name, value, onChange, known = [], blank = "None", hint, error, disabled } = props;
  const id = useId();
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");
  // What the reader chose here, so that it can be called by its path at once.
  const [picked, setPicked] = useState<Option | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setAsked(typed), PAUSE);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const filter = locationSearch(asked);
  const found = useLoad(`pick-location ${JSON.stringify(filter)}`, async (signal) => {
    if (filter === null) return null;
    return api.request("post", "/api/v1/locations/query", {
      body: queryBody({
        filter,
        sort: ["site.name", "name"],
        limit: PICK_LIMIT,
        offset: 0,
        include_archived: false,
        include_drafts: true,
      }),
      signal,
    });
  });

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
  const locations = found.data?.items ?? [];
  const more = found.data ? found.data.total - locations.length : 0;
  const described = [`${id}-chosen`, `${id}-hint`, error ? `${id}-error` : ""]
    .filter(Boolean)
    .join(" ");

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
        To choose one, type a part of its name or code, or of the name of its site, of the region of
        that site or of the location it is in.
      </p>
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
      <Problem error={found.error} />
      <div role="status" aria-live="polite">
        {filter !== null && found.data && locations.length === 0 && (
          <p className="muted">No location matches.</p>
        )}
        {filter !== null && found.loading && !found.data && (
          <p className="muted loading-late">Searching…</p>
        )}
      </div>
      {locations.length > 0 && (
        <ul className="pick-results" aria-label="Locations that match">
          {locations.map((location) => (
            <li key={location.hid}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => choose({ value: location.hid, label: location.path })}
              >
                {location.path}
              </button>
              {location.record_status === "draft" && <span className="badge">Draft</span>}
            </li>
          ))}
        </ul>
      )}
      {locations.length > 0 && more > 0 && (
        <p className="hint">
          {plural(more, "more location")} {more === 1 ? "matches" : "match"}. Type more to narrow
          them down.
        </p>
      )}
    </div>
  );
}
