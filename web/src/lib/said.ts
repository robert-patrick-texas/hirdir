// What a live region says, and when (0.9.19, the review of P-325).
//
// A live region is heard when what it holds changes, and not when it comes onto the page
// already holding it: so it comes empty, and is given its words a moment later. What is
// under way as the page opens, a preview or an apply in its turn or being worked, is
// said so; what had ended before, a preview previewed, an apply applied, a failure, is
// not said again to whoever comes back to it, until something else is to be said.

import { useEffect, useState } from "react";

/** How long a live region holds nothing after it comes onto the page, in milliseconds. */
export const SAY_AFTER_MS = 400;

export interface Saying {
  /** The region has been on the page long enough to be heard. */
  ready: boolean;
  /** What it was to say as it came. */
  first: string;
  /** Whether what it is to say has been other than `first` since. */
  changed: boolean;
}

/**
 * What the region holds: nothing until it is ready; then `text`, unless `text` is what
 * the region was to say as it came and that was not to be said (`sayFirst` false).
 */
export function announced(
  text: string,
  sayFirst: boolean,
  { ready, first, changed }: Saying,
): string {
  if (!ready) return "";
  if (!sayFirst && !changed && text === first) return "";
  return text;
}

/**
 * The words for a live region: `text` as it changes, said once each time it does;
 * `sayFirst` says whether what it is as the region comes is said too.
 */
export function useSaid(text: string, sayFirst: boolean): string {
  const [first] = useState(text);
  const [ready, setReady] = useState(false);
  const [changed, setChanged] = useState(false);
  if (!changed && text !== first) setChanged(true);
  useEffect(() => {
    const timer = setTimeout(() => setReady(true), SAY_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  return announced(text, sayFirst, { ready, first, changed: changed || text !== first });
}
