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
type Options<O> = Part<"path", PathOf<O>> &
  Part<"body", BodyOf<O>> & { query?: QueryOf<O>; signal?: AbortSignal };
type Args<O> = object extends Options<O> ? [options?: Options<O>] : [options: Options<O>];

interface LooseOptions {
  path?: Record<string, string | number>;
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
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

export interface Client {
  /** Call a route of the contract. The route, its parameters and its answer are typed by it. */
  request<M extends Method, P extends RoutesWith<M>>(
    method: M,
    route: P,
    ...args: Args<Operation<M, P>>
  ): Promise<AnswerOf<Operation<M, P>>>;
}

export function createClient(deps: ClientDeps): Client {
  async function send(method: string, route: string, options: LooseOptions): Promise<unknown> {
    const session = deps.sessions.get();
    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-Hirdir-Client": "web",
    };
    if (session) headers.Authorization = `Bearer ${session.token}`;
    const init: RequestInit = {
      method: method.toUpperCase(),
      headers,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    };
    if (options.body !== undefined) {
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
    if (response.status === 204) return undefined;
    try {
      return await response.json();
    } catch {
      throw new ApiError({
        status: response.status,
        title: "Unreadable answer",
        detail: "The server's answer could not be read.",
      });
    }
  }

  return {
    request: ((method: string, route: string, options: LooseOptions = {}) =>
      send(method, route, options)) as Client["request"],
  };
}
