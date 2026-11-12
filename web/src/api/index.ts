// The client and the session store the whole page shares.

import { browserStorage, SESSION_KEY, SessionStore } from "../lib/session";
import { createClient } from "./client";

export type { Schemas } from "./client";
export { ApiError } from "./client";

export const sessions = new SessionStore(browserStorage());

export const api = createClient({
  baseURI: () => document.baseURI,
  fetch: (input, init) => window.fetch(input, init),
  sessions,
});

// Another tab signed in or out: follow it.
window.addEventListener("storage", (event) => {
  if (event.key === SESSION_KEY || event.key === null) sessions.notify();
});
