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
// 202 is the answer of a route that has taken work to do in the background, as an apply
// of an import: its body is the job, as the contract says.
type AnswerOf<O> = O extends { responses: infer R }
  ? JsonOf<R[Extract<keyof R, 200 | 201 | 202 | 204>]>
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
/**
 * What a download is given: its body where the route takes one, and none where it does
 * not; and, since 0.9.14, what the route takes in its address, as `POST /users/export`
 * takes `retired` (P-296).
 */
type DownloadOptions<O> = Part<"body", BodyOf<O>> & { query?: QueryOf<O>; signal?: AbortSignal };
type DownloadArgs<O> =
  object extends DownloadOptions<O>
    ? [options?: DownloadOptions<O>]
    : [options: DownloadOptions<O>];

/** The routes that take a file itself as the body of a `POST`. */
type FileRoutes = {
  [P in keyof paths]: paths[P] extends {
    post: { requestBody: { content: { "text/csv": unknown } } };
  }
    ? P
    : never;
}[keyof paths];
/**
 * The routes that answer a `POST` with a file: an export, or, since 0.9.13, the zip of
 * every table (P-286).
 */
type DownloadRoutes = {
  [P in keyof paths]: paths[P] extends {
    post: { responses: { 200: { content: { "text/csv": unknown } } } };
  }
    ? P
    : paths[P] extends { post: { responses: { 200: { content: { "application/zip": unknown } } } } }
      ? P
      : never;
}[keyof paths];

/**
 * The routes that take a file of any kind as the body of a request, as a reference file
 * is (P-162): the file itself, with everything else about it in the URL.
 */
type BinaryRoutes<M extends "post" | "put"> = {
  [P in keyof paths]: paths[P] extends Record<
    M,
    { requestBody: { content: { "application/octet-stream": unknown } } }
  >
    ? P
    : never;
}[keyof paths];
/** What a file sent as the body of a request is sent with. */
type FileOptions<O> = Part<"path", PathOf<O>> & {
  query?: QueryOf<O>;
  file: Blob;
  onProgress?: (progress: Progress) => void;
  signal?: AbortSignal;
};
/** The routes that answer a `GET` with a file: the content of a reference. */
type ContentRoutes = {
  [P in keyof paths]: paths[P] extends {
    get: { responses: { 200: { content: { "application/octet-stream": unknown } } } };
  }
    ? P
    : never;
}[keyof paths];

/** The kinds of file the server reads and writes. */
export type FileType = "text/csv" | "application/json";

/** How much of a file has been sent, in bytes. */
export interface Progress {
  sent: number;
  total: number;
}

/** A file the server sent: its content, and the name the server gave it. */
export interface Download {
  blob: Blob;
  /** The name in `Content-Disposition`, or null when the answer named none. */
  fileName: string | null;
}

interface LooseOptions {
  path?: Record<string, string | number>;
  query?: Record<string, string | number | boolean | readonly string[] | null | undefined>;
  body?: unknown;
  /** A file to send as the body, as it is, under its own content type. */
  file?: { content: Blob; type: FileType };
  idempotencyKey?: string;
  signal?: AbortSignal;
}

const STALE_TITLE = "Stale version";

/** The record that already has the value a change was refused for (P-207). */
export type ExistingRecord = Schemas["ProblemRecord"];

/** 0.9.7: the deletion of a record a 404 is for, when, by whom and why (P-227). */
export type DeletedRecord = Schemas["ProblemDeleted"];

/**
 * 0.9.10: what a server past its ceiling says of itself where it does not take a request
 * (P-265, P-271): its health, by which measure, and what it refuses. Only its `503`
 * holds one.
 */
export type BusyServer = Schemas["ProblemBusy"];

/**
 * What the page says of a request a busy server did not take, with the seconds of
 * `Retry-After` where the answer names them. They are the words of the failure itself,
 * so every place that says why a request failed says them, and no page has its own.
 */
export function busyWords(retryAfter: number | null): string {
  const when =
    retryAfter !== null && retryAfter > 0 ? `in ${plural(retryAfter, "second")}` : "shortly";
  return `The server is busy and did not answer this. Try again ${when}.`;
}

/** A request the server refused, or that never reached it (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  /** What is wrong with each field of the request, by field name. */
  readonly fields: Readonly<Record<string, string>>;
  /** Seconds to wait before trying again, when the server said. */
  readonly retryAfter: number | null;
  /** The record that has the value already, where the server named one. */
  readonly existing: ExistingRecord | null;
  /** On a 404 for a record an Admin deleted: when, by whom and why. */
  readonly deleted: DeletedRecord | null;
  /**
   * 0.9.8: on a 409 for a record that others stand on, those records, as the items that
   * run on a stack or a cluster refused retirement (P-247). Empty on every other.
   */
  readonly dependsOn: readonly ExistingRecord[];
  /**
   * 0.9.10: on the 503 of a server past its ceiling, what it says of itself (P-265).
   * Null on every other, the 503 of a change that waited for another among them.
   */
  readonly busy: BusyServer | null;

  constructor(init: {
    status: number;
    title: string;
    detail?: string;
    fields?: Record<string, string>;
    retryAfter?: number | null;
    existing?: ExistingRecord | null;
    deleted?: DeletedRecord | null;
    dependsOn?: readonly ExistingRecord[];
    busy?: BusyServer | null;
  }) {
    const detail = init.detail ?? "";
    let text = detail || init.title;
    const busy = init.busy ?? null;
    // The header says how long to wait, and the problem repeats it for an answer that
    // came through something that dropped the header.
    const retryAfter = init.retryAfter ?? busy?.retry_after ?? null;
    if (init.status === 429 && retryAfter !== null) {
      text = `Too many attempts. Try again in ${plural(retryAfter, "second")}.`;
    }
    if (busy) text = busyWords(retryAfter);
    super(text);
    this.name = "ApiError";
    this.status = init.status;
    this.title = init.title;
    this.detail = detail;
    this.fields = init.fields ?? {};
    this.retryAfter = retryAfter;
    this.existing = init.existing ?? null;
    this.deleted = init.deleted ?? null;
    this.dependsOn = init.dependsOn ?? [];
    this.busy = busy;
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
    existing: existingOf(problem.existing),
    deleted: deletedOf(problem.deleted),
    dependsOn: Array.isArray(problem.depends_on)
      ? problem.depends_on.flatMap((one) => {
          const record = existingOf(one);
          return record ? [record] : [];
        })
      : [],
    busy: response.status === 503 ? busyOf(problem.busy) : null,
  });
}

const BUSY_MEASURES: readonly string[] = ["response_ms", "cpu_percent"];

/**
 * What a busy server says of itself in its 503, where it says what it refuses: the
 * reports, exports and previews (`long`), or every read (`reads`). Its health is orange
 * at the least, and red where the answer does not say.
 */
function busyOf(given: unknown): BusyServer | null {
  if (typeof given !== "object" || given === null) return null;
  const { health, because, refusing, retry_after } = given as Partial<BusyServer>;
  if (refusing !== "long" && refusing !== "reads") return null;
  return {
    health: health === "very_slow" ? health : "busy",
    because: Array.isArray(because)
      ? because.filter((measure) => BUSY_MEASURES.includes(measure))
      : [],
    refusing,
    retry_after:
      typeof retry_after === "number" && Number.isFinite(retry_after) && retry_after >= 0
        ? retry_after
        : 0,
  };
}

/** The deletion a 404 tells of, where it tells of one whole. */
function deletedOf(given: unknown): DeletedRecord | null {
  if (typeof given !== "object" || given === null) return null;
  const { at, actor_hid, actor_name, reason } = given as Partial<DeletedRecord>;
  if (typeof at !== "string") return null;
  return {
    at,
    actor_hid: typeof actor_hid === "string" ? actor_hid : null,
    actor_name: typeof actor_name === "string" ? actor_name : null,
    reason: typeof reason === "string" ? reason : null,
  };
}

/** The record a problem names as having the value already, where it names one whole. */
function existingOf(given: unknown): ExistingRecord | null {
  if (typeof given !== "object" || given === null) return null;
  const { hid, record_type, label } = given as Partial<ExistingRecord>;
  if (typeof hid !== "string" || typeof record_type !== "string" || typeof label !== "string") {
    return null;
  }
  return { hid, record_type, label };
}

export interface ClientDeps {
  /** The page's base URI, read when a request is made. */
  baseURI: () => string;
  fetch: (input: string, init: RequestInit) => Promise<Response>;
  /**
   * A new XMLHttpRequest, for the one kind of request that says how far it has got: the
   * upload of a reference file. `fetch` cannot tell how much of a body it has sent.
   */
  xhr?: () => XMLHttpRequest;
  sessions: {
    get: () => Session | null;
    clear: (reason: EndReason) => void;
  };
  /**
   * 0.9.10: told of every answer of the server, good or refused, as it arrives: its
   * status and its headers. It is where something every answer carries in a header is
   * read, once, for every kind of request. Nothing is told of a request that had no
   * answer. What it throws is not the request's failure, and is let go.
   */
  onAnswer?: (answer: { status: number; headers: Headers }) => void;
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
   * else, with the bearer token and no cookie, and handed over to be saved or read. A
   * route that takes no body, as `POST /users/export`, is given none (review X5).
   */
  download<P extends DownloadRoutes>(
    route: P,
    ...args: DownloadArgs<Operation<"post", P>>
  ): Promise<Download>;

  /**
   * Send a file of any kind as the body of a route that takes one, as a reference file
   * is sent, saying as it goes how much of it has been sent. It is sent as every request
   * is, with the bearer token, and the answer is read as every answer is.
   */
  sendFile<P extends BinaryRoutes<"post">>(
    method: "post",
    route: P,
    options: FileOptions<Operation<"post", P>>,
  ): Promise<AnswerOf<Operation<"post", P>>>;
  sendFile<P extends BinaryRoutes<"put">>(
    method: "put",
    route: P,
    options: FileOptions<Operation<"put", P>>,
  ): Promise<AnswerOf<Operation<"put", P>>>;

  /**
   * Fetch the content of a route that answers a `GET` with a file, as everything else is
   * fetched, with the bearer token and no cookie, and hand it over to be shown or saved.
   */
  content<P extends ContentRoutes>(
    route: P,
    options: Part<"path", PathOf<Operation<"get", P>>> & { signal?: AbortSignal },
  ): Promise<Download>;
}

interface TransferOptions {
  path?: Record<string, string | number>;
  query?: LooseOptions["query"];
  file: Blob;
  onProgress?: (progress: Progress) => void;
  signal?: AbortSignal;
}

const NO_ANSWER = {
  status: 0,
  title: "No answer",
  detail: "The server could not be reached. Check the connection and try again.",
};

/** The headers of an XMLHttpRequest's answer, as those of a fetch are read. */
function headersOf(request: XMLHttpRequest): Headers {
  const headers = new Headers();
  for (const line of request.getAllResponseHeaders().split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon <= 0) continue;
    try {
      headers.append(line.slice(0, colon).trim(), line.slice(colon + 1).trim());
    } catch {
      // A header no fetch would hand over: nothing that is read here.
    }
  }
  return headers;
}

/** An XMLHttpRequest's answer as a Response, so that it is read as every other answer. */
function responseOf(request: XMLHttpRequest): Response {
  const empty = request.status === 204 || request.status === 205 || request.status === 304;
  return new Response(empty ? null : String(request.responseText ?? ""), {
    status: request.status,
    statusText: request.statusText,
    headers: headersOf(request),
  });
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
      throw new ApiError(NO_ANSWER);
    }
    return checked(response, session);
  }

  /** The answer, or what the server refused the request with. */
  async function checked(response: Response, session: Session | null): Promise<Response> {
    // Every answer passes here, of an upload as of any other request: see `onAnswer`.
    try {
      deps.onAnswer?.({ status: response.status, headers: response.headers });
    } catch {
      // Whoever listens failed: the answer is the request's all the same.
    }
    if (response.status === 401) {
      // The session is no longer good. Forgetting it brings the sign-in page back.
      // 0.9.14: only the session the request was sent with is forgotten. A request that
      // was on its way while the person changed their own access code is refused with
      // the session that change ended, and the one kept in its place stays (P-295).
      const problem = await problemOf(response);
      if (session && deps.sessions.get()?.token === session.token) deps.sessions.clear("ended");
      throw problem;
    }
    if (!response.ok) throw await problemOf(response);
    return response;
  }

  /**
   * Send a file as the body of a request with an XMLHttpRequest, which says how much of
   * it has gone, and read the answer as every other. It is given no cookie to send, as
   * none is ever set, and it follows no redirect: an answer from anywhere else than
   * where it was sent is taken for no answer, as `fetch` is told to.
   */
  async function transfer(
    method: string,
    route: string,
    options: TransferOptions,
  ): Promise<unknown> {
    const make = deps.xhr;
    if (!make) throw new ApiError({ ...NO_ANSWER, detail: "This page cannot send a file." });
    const session = deps.sessions.get();
    const url = apiUrl(deps.baseURI(), route, options.path, options.query);
    const { file, onProgress, signal } = options;
    const response = await new Promise<Response>((resolve, reject) => {
      if (signal?.aborted) {
        reject(new ApiError({ status: 0, title: "Aborted" }));
        return;
      }
      const request = make();
      const stop = () => request.abort();
      request.open(method.toUpperCase(), url);
      request.withCredentials = false;
      request.responseType = "text";
      request.setRequestHeader("Accept", "application/json");
      request.setRequestHeader("X-Hirdir-Client", "web");
      if (session) request.setRequestHeader("Authorization", `Bearer ${session.token}`);
      request.setRequestHeader("Content-Type", "application/octet-stream");
      request.upload.addEventListener("progress", (event) => {
        const total = event.lengthComputable ? event.total : file.size;
        onProgress?.({ sent: event.loaded, total });
      });
      request.addEventListener("load", () => {
        signal?.removeEventListener("abort", stop);
        const moved = request.responseURL !== "" && request.responseURL !== url;
        if (moved) reject(new ApiError(NO_ANSWER));
        else resolve(responseOf(request));
      });
      request.addEventListener("error", () => {
        signal?.removeEventListener("abort", stop);
        reject(new ApiError(NO_ANSWER));
      });
      request.addEventListener("abort", () => {
        reject(new ApiError({ status: 0, title: "Aborted" }));
      });
      signal?.addEventListener("abort", stop, { once: true });
      request.send(file);
    });
    await checked(response, session);
    if (response.status === 204) return undefined;
    try {
      return await response.json();
    } catch {
      throw unreadable(response);
    }
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

  async function download(
    route: string,
    options: LooseOptions,
    method = "post",
    accept = "text/csv, application/json, application/zip",
  ): Promise<Download> {
    const response = await exchange(method, route, options, accept);
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
    download: ((route: string, options: LooseOptions = {}) =>
      download(route, options)) as Client["download"],
    sendFile: ((method: string, route: string, options: TransferOptions) =>
      transfer(method, route, options)) as Client["sendFile"],
    content: ((route: string, options: LooseOptions) =>
      download(route, options, "get", "*/*")) as Client["content"],
  };
}
