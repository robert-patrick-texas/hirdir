// The one way the web UI talks to the server.
//
// Every request is same-origin under the page's base, carries the session as a bearer
// token, names the web UI as its client, and never sends or accepts a cookie. Errors
// arrive as RFC 9457 problem documents and are thrown as ApiError.

import { apiUrl } from "../lib/base";
import { plural } from "../lib/format";
import type { EndReason, Session } from "../lib/session";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

type Method = "get" | "post" | "put" | "patch" | "delete";
type RoutesWith<M extends Method> = {
  [P in keyof paths]: paths[P] extends Record<M, unknown> ? P : never;
}[keyof paths];
type Operation<M extends Method, P extends keyof paths> =
  paths[P] extends Record<M, infer O> ? O : never;

type PathOf<O> = O extends { parameters: { path: infer T } } ? T : never;
type QueryOf<O> = O extends { parameters: { query?: infer T } } ? NonNullable<T> : never;
type BodyOf<O> = O extends { requestBody: { content: { "application/json": infer T } } }
  ? T
  : never;
type JsonOf<R> = R extends { content: { "application/json": infer T } } ? T : undefined;
type AnswerOf<O> = O extends { responses: infer R }
  ? JsonOf<R[Extract<keyof R, 200 | 201 | 204>]>
  : never;

type Part<K extends string, T> = [T] extends [never] ? { [P in K]?: never } : { [P in K]: T };
/** A route that takes `Idempotency-Key` may be given one; no other route may. */
type KeyOf<O> = O extends { parameters: { header?: infer H } }
  ? "Idempotency-Key" extends keyof NonNullable<H>
    ? { idempotencyKey?: string }
    : { idempotencyKey?: never }
  : { idempotencyKey?: never };
type Options<O> = Part<"path", PathOf<O>> &
  Part<"body", BodyOf<O>> &
  KeyOf<O> & { query?: QueryOf<O>; signal?: AbortSignal };
type Args<O> = object extends Options<O> ? [options?: Options<O>] : [options: Options<O>];

/** The routes that take a file itself as the body of a `POST`. */
type FileRoutes = {
  [P in keyof paths]: paths[P] extends {
    post: { requestBody: { content: { "text/csv": unknown } } };
  }
    ? P
    : never;
}[keyof paths];
/** The routes that answer a `POST` with a file. */
type DownloadRoutes = {
  [P in keyof paths]: paths[P] extends {
    post: { responses: { 200: { content: { "text/csv": unknown } } } };
  }
    ? P
    : never;
}[keyof paths];

/** The kinds of file the server reads and writes. */
export type FileType = "text/csv" | "application/json";

/** A file the server sent: its content, and the name the server gave it. */
export interface Download {
  blob: Blob;
  /** The name in `Content-Disposition`, or null when the answer named none. */
  fileName: string | null;
}

interface LooseOptions {
  path?: Record<string, string | number>;
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  /** A file to send as the body, as it is, under its own content type. */
  file?: { content: Blob; type: FileType };
  idempotencyKey?: string;
  signal?: AbortSignal;
}

const STALE_TITLE = "Stale version";

/** A request the server refused, or that never reached it (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  /** What is wrong with each field of the request, by field name. */
  readonly fields: Readonly<Record<string, string>>;
  /** Seconds to wait before trying again, when the server said. */
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    title: string;
    detail?: string;
    fields?: Record<string, string>;
    retryAfter?: number | null;
  }) {
    const detail = init.detail ?? "";
    let text = detail || init.title;
    const retryAfter = init.retryAfter ?? null;
    if (init.status === 429 && retryAfter !== null) {
      text = `Too many attempts. Try again in ${plural(retryAfter, "second")}.`;
    }
    super(text);
    this.name = "ApiError";
    this.status = init.status;
    this.title = init.title;
    this.detail = detail;
    this.fields = init.fields ?? {};
    this.retryAfter = retryAfter;
  }

  /** The record changed since it was read: read it again before changing it. */
  get stale(): boolean {
    return this.status === 409 && this.title === STALE_TITLE;
  }

  /** The request was stopped by the page itself, as when the reader moved on. */
  get aborted(): boolean {
    return this.status === 0 && this.title === "Aborted";
  }
}

function retryAfterOf(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (header === null || !/^\s*\d+\s*$/.test(header)) return null;
  return Number.parseInt(header, 10);
}

/** Read the problem document of a failed response. */
export async function problemOf(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: an answer from something in front of the server, most likely.
  }
  const problem = (typeof body === "object" && body !== null ? body : {}) as Partial<
    Schemas["Problem"]
  >;
  const fields: Record<string, string> = {};
  if (Array.isArray(problem.errors)) {
    for (const item of problem.errors) {
      if (item && typeof item.field === "string" && typeof item.message === "string") {
        fields[item.field] = item.message;
      }
    }
  }
  return new ApiError({
    status: response.status,
    title:
      typeof problem.title === "string" && problem.title
        ? problem.title
        : `The server answered ${response.status}`,
    detail: typeof problem.detail === "string" ? problem.detail : "",
    fields,
    retryAfter: retryAfterOf(response),
  });
}

export interface ClientDeps {
  /** The page's base URI, read when a request is made. */
  baseURI: () => string;
  fetch: (input: string, init: RequestInit) => Promise<Response>;
  sessions: {
    get: () => Session | null;
    clear: (reason: EndReason) => void;
  };
}

/**
 * The file name of a `Content-Disposition` header, or null when it names none. A name
 * is only ever a name: anything that looks like a path is cut down to its last part.
 */
export function fileNameOf(disposition: string | null): string | null {
  if (!disposition) return null;
  let name = "";
  const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  if (extended?.[1]) {
    try {
      name = decodeURIComponent(extended[1].trim());
    } catch {
      // Not percent-encoded as it says: the plain name, if there is one, will do.
    }
  }
  if (name === "") {
    const plain = /filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]+))/i.exec(disposition);
    name = (plain?.[1]?.replace(/\\(.)/g, "$1") ?? plain?.[2] ?? "").trim();
  }
  name = name.split(/[\\/]/).pop() ?? "";
  return name === "" || name === "." || name === ".." ? null : name;
}

export interface Client {
  /** Call a route of the contract. The route, its parameters and its answer are typed by it. */
  request<M extends Method, P extends RoutesWith<M>>(
    method: M,
    route: P,
    ...args: Args<Operation<M, P>>
  ): Promise<AnswerOf<Operation<M, P>>>;

  /**
   * Send a file to a route that takes one as its body: the file itself, under its own
   * content type, with everything else about it in the URL. It is not a form upload.
   */
  upload<P extends FileRoutes>(
    route: P,
    options: {
      file: Blob;
      type: FileType;
      query?: QueryOf<Operation<"post", P>>;
      idempotencyKey?: string;
      signal?: AbortSignal;
    },
  ): Promise<AnswerOf<Operation<"post", P>>>;

  /**
   * Fetch a file from a route that answers with one. It is fetched like everything
   * else, with the bearer token and no cookie, and handed over to be saved or read.
   */
  download<P extends DownloadRoutes>(
    route: P,
    options: { body: BodyOf<Operation<"post", P>>; signal?: AbortSignal },
  ): Promise<Download>;
}

export function createClient(deps: ClientDeps): Client {
  /** Send a request and return the answer, or throw what the server refused it with. */
  async function exchange(
    method: string,
    route: string,
    options: LooseOptions,
    accept = "application/json",
  ): Promise<Response> {
    const session = deps.sessions.get();
    const headers: Record<string, string> = {
      Accept: accept,
      "X-Hirdir-Client": "web",
    };
    if (session) headers.Authorization = `Bearer ${session.token}`;
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    const init: RequestInit = {
      method: method.toUpperCase(),
      headers,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    };
    if (options.file !== undefined) {
      headers["Content-Type"] = options.file.type;
      init.body = options.file.content;
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (options.signal) init.signal = options.signal;

    let response: Response;
    try {
      const url = apiUrl(deps.baseURI(), route, options.path, options.query);
      response = await deps.fetch(url, init);
    } catch {
      if (options.signal?.aborted) throw new ApiError({ status: 0, title: "Aborted" });
      throw new ApiError({
        status: 0,
        title: "No answer",
        detail: "The server could not be reached. Check the connection and try again.",
      });
    }
    if (response.status === 401) {
      // The session is no longer good. Forgetting it brings the sign-in page back.
      const problem = await problemOf(response);
      if (session) deps.sessions.clear("ended");
      throw problem;
    }
    if (!response.ok) throw await problemOf(response);
    return response;
  }

  function unreadable(response: Response): ApiError {
    return new ApiError({
      status: response.status,
      title: "Unreadable answer",
      detail: "The server's answer could not be read.",
    });
  }

  async function send(method: string, route: string, options: LooseOptions): Promise<unknown> {
    const response = await exchange(method, route, options);
    if (response.status === 204) return undefined;
    try {
      return await response.json();
    } catch {
      throw unreadable(response);
    }
  }

  async function download(route: string, options: LooseOptions): Promise<Download> {
    const response = await exchange("post", route, options, "text/csv, application/json");
    try {
      return {
        blob: await response.blob(),
        fileName: fileNameOf(response.headers.get("Content-Disposition")),
      };
    } catch {
      // The answer began and then broke off, as when the connection was lost.
      if (options.signal?.aborted) throw new ApiError({ status: 0, title: "Aborted" });
      throw unreadable(response);
    }
  }

  return {
    request: ((method: string, route: string, options: LooseOptions = {}) =>
      send(method, route, options)) as Client["request"],
    upload: ((route: string, options: { file: Blob; type: FileType } & LooseOptions) => {
      const { file, type, ...rest } = options;
      return send("post", route, { ...rest, file: { content: file, type } });
    }) as Client["upload"],
    download: ((route: string, options: LooseOptions) =>
      download(route, options)) as Client["download"],
  };
}
