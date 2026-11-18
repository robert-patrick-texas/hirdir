// 0.9.6: a page that has made a record says that it was created, with its name as a link
// to it (P-204), in the region a page answers in, which stays in view (P-182). A create
// that goes on to the record's own page takes the words with it, in the state of the
// history entry: Back and Forward bring them again with that page, and nothing else does.

import { useEffect, useEffectEvent, useMemo, useState } from "react";
import { Link, useLocation } from "react-router";
import { hearChanges } from "../lib/hooks";

/** A record just made: what kind it is, what it is called, and where its page is. */
export interface Made {
  kind: string;
  name: string;
  to: string;
}

/** The state of the history entry of a page reached by a create, to say so there. */
export function createdState(made: Made): { created: Made } {
  return { created: made };
}

function madeOf(state: unknown): Made | null {
  if (typeof state !== "object" || state === null || !("created" in state)) return null;
  const { created } = state as { created: unknown };
  if (typeof created !== "object" || created === null) return null;
  const { kind, name, to } = created as Record<string, unknown>;
  return typeof kind === "string" && typeof name === "string" && typeof to === "string"
    ? { kind, name, to }
    : null;
}

/** The record a create made, as the page it went on to was reached with. */
export function useCreated(): Made | null {
  const { state } = useLocation();
  // The same record for as long as the page is on the same entry of the history.
  return useMemo(() => madeOf(state), [state]);
}

/**
 * "<Kind> <name> was created.", the name a link to the record. The words are taken away
 * while the next change is sent, as the page's other answers are.
 */
export function Created({ made }: { made: Made | null }) {
  const [away, setAway] = useState<Made | null>(null);
  const heard = useEffectEvent((what: "sent" | "done" | "refused") => {
    if (what === "sent") setAway(made);
  });
  useEffect(() => hearChanges(heard), []);
  const shown = made !== null && away !== made ? made : null;
  return (
    <div className="live" role="status" aria-live="polite">
      {shown && (
        <p className="alert alert-ok">
          {shown.kind} <Link to={shown.to}>{shown.name}</Link> was created.
        </p>
      )}
    </div>
  );
}
