import { describe, expect, it, vi } from "vitest";
import { memoryStorage, SESSION_KEY, SessionStore } from "../lib/session";
import { ApiError, type ClientDeps, createClient } from "./client";

const BASE = "https://inventory.example/hirdir/";
const LATER = "2999-01-01T00:00:00Z";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function problem(
  status: number,
  title: string,
  detail = "",
  errors: Array<{ field: string; message: string }> = [],
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ type: "about:blank", title, status, detail, errors }), {
    status,
    headers: { "Content-Type": "application/problem+json", ...headers },
  });
}

function setup(answer: () => Response | Promise<Response>, signedIn = true) {
  const storage = memoryStorage();
  const sessions = new SessionStore(storage);
  if (signedIn) sessions.set({ token: "token-1", expires_at: LATER });
  const fetch = vi.fn<ClientDeps["fetch"]>(async () => answer());
  const client = createClient({ baseURI: () => BASE, fetch, sessions });
  return { client, fetch, sessions, storage };
}

async function thrownBy(run: () => Promise<unknown>): Promise<ApiError> {
  try {
    await run();
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("nothing was thrown");
}

describe("requests", () => {
  it("go to the API under the base, as the web client, with the bearer token and no cookies", async () => {
    const { client, fetch } = setup(() =>
      json(200, {
        name: "hirdir",
        version: "0.1.0",
        python: "3",
        sqlite: "3",
        schema_revision: null,
      }),
    );
    const about = await client.request("get", "/api/v1/about");
    expect(about.version).toBe("0.1.0");
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe("https://inventory.example/hirdir/api/v1/about");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("omit");
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer token-1",
      "X-Hirdir-Client": "web",
    });
    expect(init?.body).toBeUndefined();
  });

  it("send no Authorization header without a session", async () => {
    const { client, fetch } = setup(
      () => json(200, { token: "t", expires_at: LATER, user: {} }),
      false,
    );
    await client.request("post", "/api/v1/auth/sign-in", {
      body: { username: "vera", access_code: "code" },
    });
    const init = fetch.mock.calls[0]?.[1];
    expect(init?.headers).not.toHaveProperty("Authorization");
    expect(init?.headers).toMatchObject({
      "X-Hirdir-Client": "web",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(init?.body))).toEqual({ username: "vera", access_code: "code" });
  });

  it("fill the path and the query", async () => {
    const { client, fetch } = setup(() =>
      json(200, { items: [], total: 0, limit: 50, offset: 50 }),
    );
    await client.request("get", "/api/v1/users", { query: { q: "ve ra", limit: 50, offset: 50 } });
    expect(fetch.mock.calls[0]?.[0]).toBe(
      "https://inventory.example/hirdir/api/v1/users?q=ve+ra&limit=50&offset=50",
    );
    await client.request("get", "/api/v1/users/{hid}", { path: { hid: "u-1" } });
    expect(fetch.mock.calls[1]?.[0]).toBe("https://inventory.example/hirdir/api/v1/users/u-1");
  });

  it("answer undefined for 204", async () => {
    const { client } = setup(() => new Response(null, { status: 204 }));
    await expect(
      client.request("post", "/api/v1/auth/sign-out-everywhere"),
    ).resolves.toBeUndefined();
  });

  it("treat a session past its expiry as absent", async () => {
    const storage = memoryStorage();
    storage.setItem(
      SESSION_KEY,
      JSON.stringify({ token: "old", expires_at: "2001-01-01T00:00:00Z" }),
    );
    const sessions = new SessionStore(storage);
    const fetch = vi.fn<ClientDeps["fetch"]>(async () => json(200, {}));
    const client = createClient({ baseURI: () => BASE, fetch, sessions });
    await client.request("get", "/api/v1/about");
    expect(fetch.mock.calls[0]?.[1].headers).not.toHaveProperty("Authorization");
  });
});

describe("401", () => {
  it("clears the stored session, tells subscribers, and throws the problem", async () => {
    const { client, sessions, storage } = setup(() =>
      problem(401, "Not signed in", "sign in to continue"),
    );
    const listener = vi.fn();
    sessions.subscribe(listener);
    const error = await thrownBy(() => client.request("get", "/api/v1/auth/me"));
    expect(error.status).toBe(401);
    expect(error.title).toBe("Not signed in");
    expect(error.message).toBe("sign in to continue");
    expect(storage.getItem(SESSION_KEY)).toBeNull();
    expect(sessions.get()).toBeNull();
    expect(sessions.endReason).toBe("ended");
    expect(listener).toHaveBeenCalled();
  });

  it("on signing in is a refusal, not the end of a session", async () => {
    const { client, sessions } = setup(
      () => problem(401, "Sign-in refused", "the username or access code was not accepted"),
      false,
    );
    const error = await thrownBy(() =>
      client.request("post", "/api/v1/auth/sign-in", {
        body: { username: "vera", access_code: "wrong" },
      }),
    );
    expect(error.status).toBe(401);
    expect(error.message).toBe("the username or access code was not accepted");
    expect(sessions.endReason).toBeNull();
  });
});

describe("429", () => {
  it("carries the seconds of Retry-After and says them", async () => {
    const { client } = setup(
      () =>
        problem(429, "Too many attempts", "wait before trying again", [], { "Retry-After": "37" }),
      false,
    );
    const error = await thrownBy(() =>
      client.request("post", "/api/v1/auth/sign-in", {
        body: { username: "vera", access_code: "wrong" },
      }),
    );
    expect(error.status).toBe(429);
    expect(error.retryAfter).toBe(37);
    expect(error.message).toBe("Too many attempts. Try again in 37 seconds.");
  });

  it("says one second in the singular", async () => {
    const { client } = setup(() =>
      problem(429, "Too many attempts", "", [], { "Retry-After": "1" }),
    );
    const error = await thrownBy(() => client.request("get", "/api/v1/about"));
    expect(error.message).toBe("Too many attempts. Try again in 1 second.");
  });

  it("falls back to the detail when Retry-After is missing or not a number of seconds", async () => {
    const cases: Array<Record<string, string>> = [
      {},
      { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" },
    ];
    for (const headers of cases) {
      const { client } = setup(() =>
        problem(429, "Too many attempts", "wait a while", [], headers),
      );
      const error = await thrownBy(() => client.request("get", "/api/v1/about"));
      expect(error.retryAfter).toBeNull();
      expect(error.message).toBe("wait a while");
    }
  });
});

describe("problem documents", () => {
  it("give the detail as the message and the field messages by field", async () => {
    const { client } = setup(() =>
      problem(422, "Invalid input", "the username is not acceptable", [
        { field: "username", message: "1 to 64 letters, digits, dots, hyphens or underscores" },
        { field: "email", message: "too long" },
      ]),
    );
    const error = await thrownBy(() =>
      client.request("post", "/api/v1/users", { body: { username: "no good" } }),
    );
    expect(error.status).toBe(422);
    expect(error.title).toBe("Invalid input");
    expect(error.detail).toBe("the username is not acceptable");
    expect(error.message).toBe("the username is not acceptable");
    expect(error.fields).toEqual({
      username: "1 to 64 letters, digits, dots, hyphens or underscores",
      email: "too long",
    });
    expect(error.stale).toBe(false);
  });

  it("mark 409 Stale version as stale, and no other 409", async () => {
    const stale = setup(() => problem(409, "Stale version", "the record has changed"));
    const first = await thrownBy(() =>
      stale.client.request("patch", "/api/v1/users/{hid}", {
        path: { hid: "u-1" },
        body: { row_version: 1 },
      }),
    );
    expect(first.stale).toBe(true);

    const conflict = setup(() =>
      problem(409, "Conflict", "this would leave no Admin who can sign in"),
    );
    const second = await thrownBy(() =>
      conflict.client.request("delete", "/api/v1/role-grants/{hid}", { path: { hid: "g-1" } }),
    );
    expect(second.stale).toBe(false);
    expect(second.message).toBe("this would leave no Admin who can sign in");
  });

  it("fall back to the title when there is no detail", async () => {
    const { client } = setup(() => problem(404, "Not Found"));
    const error = await thrownBy(() => client.request("get", "/api/v1/about"));
    expect(error.message).toBe("Not Found");
    expect(error.fields).toEqual({});
  });

  it("leave the session alone for errors other than 401", async () => {
    const { client, sessions } = setup(() =>
      problem(403, "Not allowed", "this needs the admin role"),
    );
    await thrownBy(() => client.request("get", "/api/v1/users"));
    expect(sessions.get()?.token).toBe("token-1");
  });

  it("cope with an error that is not JSON", async () => {
    const { client } = setup(
      () =>
        new Response("<html>Bad Gateway</html>", {
          status: 502,
          headers: { "Content-Type": "text/html" },
        }),
    );
    const error = await thrownBy(() => client.request("get", "/api/v1/about"));
    expect(error.status).toBe(502);
    expect(error.message).toBe("The server answered 502");
  });

  it("cope with a problem document of the wrong shape", async () => {
    const { client } = setup(() =>
      json(500, { title: 7, detail: ["x"], errors: [{ field: 1 }, null, "x"] }),
    );
    const error = await thrownBy(() => client.request("get", "/api/v1/about"));
    expect(error.message).toBe("The server answered 500");
    expect(error.fields).toEqual({});
  });
});

describe("no answer", () => {
  it("is an ApiError with status 0 and leaves the session alone", async () => {
    const { client, sessions } = setup(() => {
      throw new TypeError("network down");
    });
    const error = await thrownBy(() => client.request("get", "/api/v1/about"));
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/could not be reached/);
    expect(error.aborted).toBe(false);
    expect(sessions.get()).not.toBeNull();
  });

  it("is marked aborted when the page stopped the request itself", async () => {
    const controller = new AbortController();
    const { client } = setup(() => {
      controller.abort();
      throw new DOMException("stopped", "AbortError");
    });
    const error = await thrownBy(() =>
      client.request("get", "/api/v1/about", { signal: controller.signal }),
    );
    expect(error.aborted).toBe(true);
  });
});
