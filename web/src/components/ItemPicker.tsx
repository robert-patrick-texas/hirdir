import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { api, type Schemas } from "../api";
import type { FilterNode } from "../lib/filter";
import { plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useLoad } from "../lib/hooks";
import { itemSearch, offered, PICK_LIMIT, pickLabel } from "../lib/pick";
import { Problem } from "./Problem";

type Item = Schemas["ItemOut"];

// How long after the last key the search is sent, in milliseconds.
const PAUSE = 300;
// The most items one search asks the server for.
const MOST_ASKED = 100;

interface ItemPickerProps {
  /** What the item is wanted for: "Put it in", "Add a member". */
  label: string;
  hint?: string;
  /** Narrow the search, as to major items. */
  only?: FilterNode | null;
  /** Items that are not offered: the item itself, or ones chosen already. */
  taken?: readonly string[];
  onPick: (item: Item) => void;
  disabled?: boolean;
}

/**
 * Find an item and choose it. What is typed is sent to the server as a filter of the
 * item list, by name, serial number or asset tag, and the first few that match are
 * offered as buttons. Drafts are offered too; retired and archived items are not.
 *
 * It is not a form of its own, so it can stand inside one: Enter in its box searches at
 * once and submits nothing.
 */
export function ItemPicker({
  label,
  hint,
  only = null,
  taken = [],
  onPick,
  disabled,
}: ItemPickerProps) {
  const id = useId();
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setAsked(typed), PAUSE);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const filter = itemSearch(asked, only);
  const found = useLoad(`pick ${JSON.stringify(filter)}`, async (signal) => {
    if (filter === null) return null;
    return api.request("post", "/api/v1/items/query", {
      body: queryBody({
        filter,
        sort: ["name"],
        // A few more than are offered, to make up for those that are taken already.
        limit: Math.min(PICK_LIMIT + taken.length, MOST_ASKED),
        offset: 0,
        include_archived: false,
        include_drafts: true,
      }),
      signal,
    });
  });

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    // Inside another form, Enter would send that form: it searches instead.
    event.preventDefault();
    setAsked(typed);
  }

  const items = found.data ? offered(found.data.items, taken).slice(0, PICK_LIMIT) : [];
  const more = found.data ? found.data.total - found.data.items.length : 0;
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
          {hint ?? "Type a part of its name, serial number or asset tag."}
        </p>
      </div>
      <Problem error={found.error} />
      <div role="status" aria-live="polite">
        {filter !== null && found.data && items.length === 0 && (
          <p className="muted">
            {found.data.total === 0 ? "No item matches." : "Every item that matches is taken."}
          </p>
        )}
        {filter !== null && found.loading && !found.data && (
          <p className="muted loading-late">Searching…</p>
        )}
      </div>
      {items.length > 0 && (
        <ul className="pick-results" aria-label="Items that match">
          {items.map((item) => (
            <li key={item.hid}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  onPick(item);
                  setTyped("");
                  setAsked("");
                }}
              >
                {pickLabel(item)}
              </button>
              {item.record_status === "draft" && <span className="badge">Draft</span>}
              {!item.is_major && <span className="muted"> minor item</span>}
            </li>
          ))}
        </ul>
      )}
      {items.length > 0 && more > 0 && (
        <p className="hint">
          {plural(more, "more item")} {more === 1 ? "matches" : "match"}. Type more to narrow them
          down.
        </p>
      )}
    </div>
  );
}
