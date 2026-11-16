// The two ways of the client that carry a reference file: sent as the body of a request,
// saying how far it has got, and fetched as a file.

import { describe, expect, it, vi } from "vitest";
import { memoryStorage, SessionStore } from "../lib/session";
import { ApiError, type ClientDeps, createClient, type Progress } from "./client";

const BASE = "https://inventory.example/hirdir/";
const LATER = "2999-01-01T00:00:00Z";
const UPLOADS = "https://inventory.example/hirdir/api/v1/reference-files";

type Listener = (event: { loaded: number; total: number; lengthComputable: boolean }) => void;

/** An XMLHttpRequest that answers as it is told, and records what it was sent. */
class FakeRequest {
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  withCredentials = true;
  responseType = "";
  status = 0;
  statusText = "";
  responseText = "";
  responseURL = "";
  answerHeaders = "";
  aborted = false;
  private readonly listeners = new Map<string, Array<() => void>>();
  private readonly progress: Listener[] = [];
  readonly upload = {
    addEventListener: (_: string, listener: Listener) => this.progress.push(listener),
  };

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  addEventListener(name: string, listener: () => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  getAllResponseHeaders() {
    return this.answerHeaders;
  }

  send(body: unknown) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
    this.fire("abort");
  }

  /** How much of the body has gone. */
  sent(loaded: number, total: number) {
    for (const listener of this.progress) listener({ loaded, total, lengthComputable: true });
  }

  /** The server's answer. */
  answer(status: number, body: unknown, url = this.url) {
    this.status = status;
    this.responseText = body === null ? "" : JSON.stringify(body);
    this.responseURL = url;
    this.answerHeaders = "Content-Type: application/json\r\nCache-Control: no-store\r\n";
    this.fire("load");
  }

  fire(name: string) {
    for (const listener of this.listeners.get(name) ?? []) listener();
  }
}

function setup() {
  const sessions = new SessionStore(memoryStorage());
  sessions.set({ token: "token-1", expires_at: LATER });
  const made: FakeRequest[] = [];
  const fetch = vi.fn<ClientDeps["fetch"]>();
  const client = createClient({
    baseURI: () => BASE,
    fetch,
    xhr: () => {
      const request = new FakeRequest();
      made.push(request);
      return request as unknown as XMLHttpRequest;
    },
    sessions,
  });
  return { client, made, fetch, sessions };
}

/** Wait for the client to have made its request. */
async function made(list: FakeRequest[]): Promise<FakeRequest> {
  await vi.waitFor(() => expect(list.length).toBeGreaterThan(0));
  const request = list[0];
  if (!request) throw new Error("no request was made");
  return request;
}

const REFERENCE = { hid: "ref-1", title: "Floor plan", form: "file" };

describe("a file sent as the body of a request", () => {
  it("goes as itself, with the bearer token and no cookie, and says how far it has got", async () => {
    const { client, made: requests } = setup();
    const file = new Blob(["%PDF-1.7 plan"], { type: "application/pdf" });
    const seen: Progress[] = [];
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: {
        title: "Floor plan",
        kind: "floor_plan",
        file_name: "b1-floor-2.pdf",
        attach_to: ["loc-1", "loc-2"],
      },
      file,
      onProgress: (progress) => seen.push(progress),
    });
    const request = await made(requests);
    expect(request.method).toBe("POST");
    const url = new URL(request.url);
    expect(`${url.origin}${url.pathname}`).toBe(UPLOADS);
    expect(url.searchParams.get("file_name")).toBe("b1-floor-2.pdf");
    expect(url.searchParams.getAll("attach_to")).toEqual(["loc-1", "loc-2"]);
    expect(request.withCredentials).toBe(false);
    expect(request.headers).toEqual({
      Accept: "application/json",
      "X-Hirdir-Client": "web",
      Authorization: "Bearer token-1",
      "Content-Type": "application/octet-stream",
    });
    expect(request.body).toBe(file);
    request.sent(5, 13);
    request.sent(13, 13);
    request.answer(201, REFERENCE);
    expect(await sending).toEqual(REFERENCE);
    expect(seen).toEqual([
      { sent: 5, total: 13 },
      { sent: 13, total: 13 },
    ]);
  });

  it("is a new edition with its name and the version it replaces", async () => {
    const { client, made: requests } = setup();
    const sending = client.sendFile("put", "/api/v1/reference-files/{hid}/content", {
      path: { hid: "ref 1" },
      query: { file_name: "admin-2027.pdf", row_version: 3 },
      file: new Blob(["%PDF-1.7"]),
    });
    const request = await made(requests);
    expect(request.method).toBe("PUT");
    const url = new URL(request.url);
    expect(url.pathname).toBe("/hirdir/api/v1/reference-files/ref%201/content");
    expect(url.searchParams.get("row_version")).toBe("3");
    request.answer(200, REFERENCE);
    expect(await sending).toEqual(REFERENCE);
  });

  it("is refused with what the server said", async () => {
    const { client, made: requests } = setup();
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: { title: "Big", kind: "other", file_name: "big.zip", attach_to: ["loc-1"] },
      file: new Blob(["PK"]),
    });
    const request = await made(requests);
    request.answer(413, {
      type: "about:blank",
      title: "Too large",
      status: 413,
      detail: "a reference file is at most 100 MB",
      errors: [{ field: "file", message: "too large" }],
    });
    const error = await sending.catch((thrown: unknown) => thrown);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(413);
    expect((error as ApiError).detail).toBe("a reference file is at most 100 MB");
    expect((error as ApiError).fields).toEqual({ file: "too large" });
  });

  it("ends the session on a 401, as every request does", async () => {
    const { client, made: requests, sessions } = setup();
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: { title: "A", kind: "other", file_name: "a.pdf", attach_to: ["loc-1"] },
      file: new Blob(["%PDF-"]),
    });
    (await made(requests)).answer(401, { title: "Not signed in", status: 401 });
    await sending.catch(() => undefined);
    expect(sessions.get()).toBeNull();
  });

  it("takes an answer from anywhere else than where it was sent for no answer", async () => {
    const { client, made: requests } = setup();
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: { title: "A", kind: "other", file_name: "a.pdf", attach_to: ["loc-1"] },
      file: new Blob(["%PDF-"]),
    });
    (await made(requests)).answer(200, REFERENCE, "https://elsewhere.example/upload");
    const error = (await sending.catch((thrown: unknown) => thrown)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.title).toBe("No answer");
  });

  it("is stopped when the page stops it", async () => {
    const { client, made: requests } = setup();
    const stop = new AbortController();
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: { title: "A", kind: "other", file_name: "a.pdf", attach_to: ["loc-1"] },
      file: new Blob(["%PDF-"]),
      signal: stop.signal,
    });
    const request = await made(requests);
    stop.abort();
    const error = (await sending.catch((thrown: unknown) => thrown)) as ApiError;
    expect(request.aborted).toBe(true);
    expect(error.aborted).toBe(true);
  });

  it("is no answer when the connection fails", async () => {
    const { client, made: requests } = setup();
    const sending = client.sendFile("post", "/api/v1/reference-files", {
      query: { title: "A", kind: "other", file_name: "a.pdf", attach_to: ["loc-1"] },
      file: new Blob(["%PDF-"]),
    });
    (await made(requests)).fire("error");
    const error = (await sending.catch((thrown: unknown) => thrown)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.detail).toMatch(/could not be reached/);
  });
});

describe("a file fetched", () => {
  it("is asked for with the token and no cookie, and comes with its name", async () => {
    const { client, fetch } = setup();
    fetch.mockResolvedValue(
      new Response("%PDF-1.7", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition":
            "attachment; filename=\"b1-floor-2.pdf\"; filename*=UTF-8''b1-floor-2.pdf",
        },
      }),
    );
    const got = await client.content("/api/v1/reference-files/{hid}/content", {
      path: { hid: "ref-1" },
    });
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe("https://inventory.example/hirdir/api/v1/reference-files/ref-1/content");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("omit");
    expect(init?.headers).toMatchObject({ Authorization: "Bearer token-1" });
    expect(got.fileName).toBe("b1-floor-2.pdf");
    expect(await got.blob.text()).toBe("%PDF-1.7");
  });

  it("is refused with what the server said, as content missing after a restore", async () => {
    const { client, fetch } = setup();
    fetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          title: "Not found",
          status: 404,
          detail: "the content of Floor plan is missing from the store",
        }),
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    const error = (await client
      .content("/api/v1/reference-files/{hid}/content", { path: { hid: "ref-1" } })
      .catch((thrown: unknown) => thrown)) as ApiError;
    expect(error.status).toBe(404);
    expect(error.message).toMatch(/missing from the store/);
  });
});
