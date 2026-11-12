// The session: the token the server issued and when it ends, kept in localStorage.
// Nothing here reads or writes a cookie.

export const SESSION_KEY = "hirdir.session";

export interface Session {
  token: string;
  expires_at: string;
}

/** Why there is no session any more. */
export type EndReason = "signed-out" | "ended";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Read a stored session. Anything malformed or past its expiry is no session. */
export function parseSession(raw: string | null, now: number): Session | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const { token, expires_at } = value as Record<string, unknown>;
  if (typeof token !== "string" || token === "" || typeof expires_at !== "string") return null;
  const expires = Date.parse(expires_at);
  if (Number.isNaN(expires) || expires <= now) return null;
  return { token, expires_at };
}

/** A store that forgets everything when the page goes, for when localStorage is refused. */
export function memoryStorage(): Store {
  const items = new Map<string, string>();
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => {
      items.set(key, value);
    },
    removeItem: (key) => {
      items.delete(key);
    },
  };
}

/** The browser's localStorage, or a memory store when the browser refuses it. */
export function browserStorage(): Store {
  try {
    const storage = window.localStorage;
    storage.getItem(SESSION_KEY);
    return storage;
  } catch {
    return memoryStorage();
  }
}

export class SessionStore {
  /** Why the last session went, for the sign-in page to say. */
  endReason: EndReason | null = null;

  private storage: Store;
  private readonly now: () => number;
  private readonly listeners = new Set<() => void>();
  private raw: string | null = null;
  private parsed: Session | null = null;

  constructor(storage: Store, now: () => number = Date.now) {
    this.storage = storage;
    this.now = now;
  }

  /** The session, or null when there is none or it is past its expiry. */
  get = (): Session | null => {
    const raw = this.read();
    if (raw !== this.raw) {
      // Parsed once for each stored value, so callers get the same object back.
      this.raw = raw;
      this.parsed = parseSession(raw, this.now());
    }
    if (this.parsed && Date.parse(this.parsed.expires_at) <= this.now()) return null;
    return this.parsed;
  };

  /** Keep the token and its expiry, and nothing else of what the server answered. */
  set(session: Session): void {
    const text = JSON.stringify({ token: session.token, expires_at: session.expires_at });
    try {
      this.storage.setItem(SESSION_KEY, text);
    } catch {
      // Storage is full or refused: the session then lasts until the page is closed.
      this.storage = memoryStorage();
      this.storage.setItem(SESSION_KEY, text);
    }
    this.endReason = null;
    this.notify();
  }

  /** Forget the session. */
  clear(reason: EndReason): void {
    if (this.read() !== null) this.endReason = reason;
    try {
      this.storage.removeItem(SESSION_KEY);
    } catch {
      // Nothing could be stored, so nothing is left behind.
    }
    this.notify();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Tell everyone to look again, as when another tab signed in or out. */
  notify(): void {
    for (const listener of [...this.listeners]) listener();
  }

  private read(): string | null {
    try {
      return this.storage.getItem(SESSION_KEY);
    } catch {
      return null;
    }
  }
}
