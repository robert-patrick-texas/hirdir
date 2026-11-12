import { describe, expect, it, vi } from "vitest";
import { memoryStorage, parseSession, SESSION_KEY, SessionStore } from "./session";

const NOW = Date.parse("2026-03-01T12:00:00Z");
const LATER = "2026-03-02T00:00:00Z";
const EARLIER = "2026-03-01T11:59:59Z";

function stored(value: unknown): string {
  return JSON.stringify(value);
}

describe("parseSession", () => {
  it("reads a session that has not ended", () => {
    expect(parseSession(stored({ token: "t", expires_at: LATER }), NOW)).toEqual({
      token: "t",
      expires_at: LATER,
    });
  });

  it("keeps only the token and the expiry", () => {
    const raw = stored({ token: "t", expires_at: LATER, user: { username: "vera" } });
    expect(parseSession(raw, NOW)).toEqual({ token: "t", expires_at: LATER });
  });

  it("treats a session past its expiry as absent", () => {
    expect(parseSession(stored({ token: "t", expires_at: EARLIER }), NOW)).toBeNull();
    const exactly = new Date(NOW).toISOString();
    expect(parseSession(stored({ token: "t", expires_at: exactly }), NOW)).toBeNull();
  });

  it("treats anything malformed as absent", () => {
    for (const raw of [
      null,
      "",
      "not json",
      "null",
      "[]",
      '"text"',
      stored({ token: "t" }),
      stored({ expires_at: LATER }),
      stored({ token: "", expires_at: LATER }),
      stored({ token: 7, expires_at: LATER }),
      stored({ token: "t", expires_at: "some day" }),
    ]) {
      expect(parseSession(raw, NOW)).toBeNull();
    }
  });
});

describe("SessionStore", () => {
  it("keeps the session under hirdir.session", () => {
    const storage = memoryStorage();
    const store = new SessionStore(storage, () => NOW);
    expect(SESSION_KEY).toBe("hirdir.session");
    expect(store.get()).toBeNull();
    store.set({ token: "t", expires_at: LATER });
    expect(JSON.parse(storage.getItem("hirdir.session") ?? "")).toEqual({
      token: "t",
      expires_at: LATER,
    });
    expect(store.get()).toEqual({ token: "t", expires_at: LATER });
  });

  it("does not store the user that came with the sign-in answer", () => {
    const storage = memoryStorage();
    const store = new SessionStore(storage, () => NOW);
    const answer = { token: "t", expires_at: LATER, user: { username: "vera" } };
    store.set(answer);
    expect(storage.getItem(SESSION_KEY)).not.toContain("vera");
  });

  it("finds a session stored before the page was loaded", () => {
    const storage = memoryStorage();
    storage.setItem(SESSION_KEY, stored({ token: "kept", expires_at: LATER }));
    expect(new SessionStore(storage, () => NOW).get()?.token).toBe("kept");
  });

  it("gives the same object back until the stored value changes", () => {
    const store = new SessionStore(memoryStorage(), () => NOW);
    store.set({ token: "t", expires_at: LATER });
    expect(store.get()).toBe(store.get());
  });

  it("stops giving a session once its expiry passes", () => {
    let now = NOW;
    const store = new SessionStore(memoryStorage(), () => now);
    store.set({ token: "t", expires_at: LATER });
    expect(store.get()).not.toBeNull();
    now = Date.parse(LATER);
    expect(store.get()).toBeNull();
  });

  it("clears the stored session and says why", () => {
    const storage = memoryStorage();
    const store = new SessionStore(storage, () => NOW);
    store.set({ token: "t", expires_at: LATER });
    expect(store.endReason).toBeNull();
    store.clear("ended");
    expect(storage.getItem(SESSION_KEY)).toBeNull();
    expect(store.get()).toBeNull();
    expect(store.endReason).toBe("ended");
    store.set({ token: "u", expires_at: LATER });
    expect(store.endReason).toBeNull();
  });

  it("gives no reason when there was no session to end", () => {
    const store = new SessionStore(memoryStorage(), () => NOW);
    store.clear("ended");
    expect(store.endReason).toBeNull();
  });

  it("tells subscribers when the session is set or cleared, until they leave", () => {
    const store = new SessionStore(memoryStorage(), () => NOW);
    const listener = vi.fn();
    const leave = store.subscribe(listener);
    store.set({ token: "t", expires_at: LATER });
    store.clear("signed-out");
    expect(listener).toHaveBeenCalledTimes(2);
    leave();
    store.set({ token: "t", expires_at: LATER });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("sees a change made by another tab", () => {
    const storage = memoryStorage();
    const store = new SessionStore(storage, () => NOW);
    store.set({ token: "t", expires_at: LATER });
    storage.removeItem(SESSION_KEY);
    expect(store.get()).toBeNull();
    storage.setItem(SESSION_KEY, stored({ token: "other", expires_at: LATER }));
    expect(store.get()?.token).toBe("other");
  });

  it("keeps the session for the life of the page when storage refuses to write", () => {
    const storage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("refused");
      },
      removeItem: () => {},
    };
    const store = new SessionStore(storage, () => NOW);
    store.set({ token: "t", expires_at: LATER });
    expect(store.get()?.token).toBe("t");
    store.clear("signed-out");
    expect(store.get()).toBeNull();
  });
});
