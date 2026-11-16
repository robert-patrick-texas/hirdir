// Finding a record to add to a list being made, by searching for it: a device group to
// connect to a circuit, a circuit to put into a group. The list may be long, so it is
// never offered whole: what is typed is sent to the server as a filter of its list, and
// the first few that match are offered as buttons. Each one pressed is handed to the
// page, which gathers them and sends them all together.

import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { api } from "../api";
import { circuitLabel, circuitSearch } from "../lib/circuits";
import type { FilterNode } from "../lib/filter";
import { plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { groupTypeLabel } from "../lib/groups";
import { useLoad } from "../lib/hooks";
import { PICK_LIMIT } from "../lib/pick";
import { Problem } from "./Problem";

// How long after the last key the search is sent, in milliseconds.
const PAUSE = 300;
// The most records one search asks the server for.
const MOST_ASKED = 100;

/** One record a search offers. */
export interface Offer {
  hid: string;
  label: string;
  /** A word to say beside it: its type, that it is a draft. */
  note?: string;
}

interface SearchPickerProps {
  /** What the record is wanted for: "Add a device group". */
  label: string;
  hint: string;
  /** What is searched for, one and many: "device group", "device groups". */
  noun: [one: string, many: string];
  /** Ask the server for what matches, up to `limit`. Blank text is no search: null. */
  find: (
    typed: string,
    limit: number,
    signal: AbortSignal,
  ) => Promise<{ offers: Offer[]; total: number } | null>;
  /** Records that are not offered: those chosen already, or there already. */
  taken?: readonly string[];
  onPick: (offer: Offer) => void;
  disabled?: boolean;
}

/**
 * Find a record and choose it. It is not a form of its own, so it can stand inside one:
 * Enter in its box searches at once and submits nothing.
 */
export function SearchPicker(props: SearchPickerProps) {
  const { label, hint, noun, find, taken = [], onPick, disabled } = props;
  const id = useId();
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setAsked(typed), PAUSE);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const searching = asked.trim() !== "";
  const limit = Math.min(PICK_LIMIT + taken.length, MOST_ASKED);
  const found = useLoad(`pick ${noun[0]} ${limit} ${asked.trim()}`, (signal) =>
    find(asked, limit, signal),
  );

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    // Inside another form, Enter would send that form: it searches instead.
    event.preventDefault();
    setAsked(typed);
  }

  const offers = found.data
    ? found.data.offers.filter((offer) => !taken.includes(offer.hid)).slice(0, PICK_LIMIT)
    : [];
  const more = found.data ? found.data.total - found.data.offers.length : 0;
  const capital = noun[1].charAt(0).toUpperCase() + noun[1].slice(1);
  return (
    <div className="picker">
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <input
          id={id}
          type="search"
          value={typed}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          autoCapitalize="none"
          aria-describedby={`${id}-hint`}
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={keyDown}
        />
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      </div>
      <Problem error={found.error} />
      <div role="status" aria-live="polite">
        {searching && found.data && offers.length === 0 && (
          <p className="muted">
            {found.data.total === 0
              ? `No ${noun[0]} matches.`
              : `Every ${noun[0]} that matches is taken.`}
          </p>
        )}
        {searching && found.loading && !found.data && (
          <p className="muted loading-late">Searching…</p>
        )}
      </div>
      {offers.length > 0 && (
        <ul className="pick-results" aria-label={`${capital} that match`}>
          {offers.map((offer) => (
            <li key={offer.hid}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  onPick(offer);
                  setTyped("");
                  setAsked("");
                }}
              >
                {offer.label}
              </button>
              {offer.note && <span className="muted"> {offer.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {offers.length > 0 && more > 0 && (
        <p className="hint">
          {plural(more, `more ${noun[0]}`, `more ${noun[1]}`)} {more === 1 ? "matches" : "match"}.
          Type more to narrow them down.
        </p>
      )}
    </div>
  );
}

/** The device groups whose name holds what was typed, drafts among them. */
export async function findGroups(typed: string, limit: number, signal: AbortSignal) {
  const value = typed.trim().slice(0, 200);
  if (value === "") return null;
  const filter: FilterNode = { field: "name", op: "contains", value };
  const page = await api.request("post", "/api/v1/device-groups/query", {
    body: queryBody({
      filter,
      sort: ["name"],
      limit,
      offset: 0,
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
  return {
    offers: page.items.map((group) => ({
      hid: group.hid,
      label: group.name,
      note: [groupTypeLabel(group.type), group.record_status === "draft" ? "draft" : ""]
        .filter(Boolean)
        .join(", "),
    })),
    total: page.total,
  };
}

/**
 * The circuits whose name, enterprise ID or a carrier's number holds what was typed,
 * drafts among them. A retired circuit is put into no group, so it is not offered.
 */
export async function findCircuits(typed: string, limit: number, signal: AbortSignal) {
  const filter = circuitSearch(typed);
  if (filter === null) return null;
  const page = await api.request("post", "/api/v1/circuits/query", {
    body: {
      ...queryBody({
        filter,
        sort: ["name"],
        limit,
        offset: 0,
        include_archived: false,
        include_drafts: true,
      }),
      fields: ["name", "enterprise_circuit_id", "record_status", "speed"],
    },
    signal,
  });
  return {
    offers: page.items.map((circuit) => ({
      hid: circuit.hid,
      label: circuitLabel(circuit),
      note: [circuit.speed ?? "", circuit.record_status === "draft" ? "draft" : ""]
        .filter(Boolean)
        .join(", "),
    })),
    total: page.total,
  };
}
