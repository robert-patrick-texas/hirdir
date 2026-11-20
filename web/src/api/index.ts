// The client and the session store the whole page shares.

import { HEALTH_HEADER, healthOfHeader, serverHealth } from "../lib/serverHealth";
import { browserStorage, SESSION_KEY, SessionStore } from "../lib/session";
import { createClient } from "./client";

export type { Schemas } from "./client";
export { ApiError } from "./client";

export const sessions = new SessionStore(browserStorage());

export const api = createClient({
  baseURI: () => document.baseURI,
  fetch: (input, init) => window.fetch(input, init),
  xhr: () => new XMLHttpRequest(),
  sessions,
  // 0.9.10: every answer says the health of the server, which the menu bar shows
  // (P-270). The newest answer's word is the one on show; an answer that carries none
  // that reads, as one from something in front of the server, leaves no mark.
  onAnswer: ({ headers }) => serverHealth.set(healthOfHeader(headers.get(HEALTH_HEADER))),
});

// Signed out: what the server last said is said to nobody.
sessions.subscribe(() => {
  if (sessions.get() === null) serverHealth.set(null);
});

// Another tab signed in or out: follow it.
window.addEventListener("storage", (event) => {
  if (event.key === SESSION_KEY || event.key === null) sessions.notify();
});
