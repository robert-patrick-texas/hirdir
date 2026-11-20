// The server's own measures as About says them (P-265, P-266, P-270 to P-273): the words
// of its health and of what it refuses, of each measure and of the background work,
// numbers with their units, who a request was asked by, and what is kept as it was when a
// new answer holds the same. A value the server or its host does not say is said as not
// known, never as 0.

import type { Schemas } from "../api/client";
import { formatTime } from "./format";
import { sameAnswer } from "./hooks";
import { sizeText } from "./references";
import { HEALTHS, type Health, type Refusing } from "./serverHealth";

export type Load = Schemas["Load"];
export type Measure = "response_ms" | "cpu_percent";
export type SlowRequest = Schemas["LoadSlow"];
export type ActivePerson = Schemas["LoadPerson"];

export const NOT_KNOWN = "not known";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const LISTS = ["requests", "average_ms", "high_ms", "cpu_percent", "busy"] as const;

/**
 * The answer of `GET /about/load`, where it has the shape the page draws: its parts, the
 * lists of the graph, the bands, and the rows of the slowest requests and of the people.
 * Null for anything else, as an answer from something in front of the server, which the
 * page then says it could not read, where drawing it would fail.
 */
export function loadOf(answer: unknown): Load | null {
  if (!isRecord(answer)) return null;
  const { ceiling, host, in_flight, measures, points, process, totals, because, at } = answer;
  if (![ceiling, host, in_flight, measures, points, process, totals].every(isRecord)) return null;
  if (typeof at !== "string" || !Array.isArray(because)) return null;
  const spreads = totals as Record<string, unknown>;
  if (!isRecord(spreads.response_ms) || !isRecord(spreads.cpu_percent)) return null;
  const bands = spreads.bands;
  if (!isRecord(bands) || !Array.isArray(bands.bounds_ms) || !Array.isArray(bands.counts)) {
    return null;
  }
  const lists = points as Record<string, unknown>;
  if (!LISTS.every((name) => Array.isArray(lists[name]))) return null;
  const { slowest, slowest_long, people } = answer;
  for (const rows of [slowest, slowest_long]) {
    if (!Array.isArray(rows) || !rows.every((row) => isRecord(row) && isRecord(row.who))) {
      return null;
    }
  }
  if (!Array.isArray(people) || !people.every(isRecord)) return null;
  return answer as unknown as Load;
}

/**
 * A new answer with each part that holds the same values as before being the part that
 * was there, and the answer that was there where every part is: what is drawn from a
 * part is then not drawn again for numbers that are the same (P-264).
 */
export function kept<T extends object>(was: T | null | undefined, next: T): T {
  if (!was) return next;
  const before = was as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  let same = Object.keys(before).length === Object.keys(next).length;
  for (const [name, value] of Object.entries(next)) {
    if (Object.hasOwn(before, name) && sameAnswer(before[name], value)) {
      out[name] = before[name];
    } else {
      out[name] = value;
      same = false;
    }
  }
  return same ? was : (out as T);
}

function known(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** A number to a tenth at the most, with the separator of thousands: `1,234.5`. */
export function tenth(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/** A time in milliseconds, `12.3 ms`, or `none` where there is no such time. */
export function msText(value: unknown, none: string = NOT_KNOWN): string {
  return known(value) ? `${tenth(value)} ms` : none;
}

/** A share in percent, `12.5%`, or `none` where there is no such share. */
export function percentText(value: unknown, none: string = NOT_KNOWN): string {
  return known(value) ? `${tenth(value)}%` : none;
}

/** A count, `1,234`, or that it is not known. */
export function countText(value: unknown): string {
  return known(value) ? Math.round(value).toLocaleString("en-US") : NOT_KNOWN;
}

/** A size, `1.4 GB`, or that it is not known. */
export function bytesText(value: unknown): string {
  return known(value) && value >= 0 ? sizeText(value) : NOT_KNOWN;
}

/** A load average, `0.42`, or that it is not known. */
export function loadAverageText(value: unknown): string {
  return known(value)
    ? value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : NOT_KNOWN;
}

/** How long something has waited: `240 ms`, or `3.2 seconds` from a second up. */
export function waitText(value: unknown, none: string = NOT_KNOWN): string {
  if (!known(value)) return none;
  const whole = Math.round(value);
  if (whole < 1000) return `${tenth(whole)} ms`;
  const seconds = tenth(whole / 1000);
  return seconds === "1" ? "1 second" : `${seconds} seconds`;
}

/** The time of day of a moment, with the zone's short name: `14:05:09 EST`. */
export function clockText(at: string | number | null | undefined, zone?: string): string {
  if (at === null || at === undefined || at === "") return NOT_KNOWN;
  const moment = new Date(at);
  if (Number.isNaN(moment.getTime())) return NOT_KNOWN;
  const whole = formatTime(moment.toISOString(), zone);
  return whole.slice(whole.indexOf(" ") + 1);
}

/** The hour and minute of a moment, as the axis of the graph names it: `14:05`. */
export function minuteText(at: number, zone?: string): string {
  const clock = clockText(at, zone);
  return clock === NOT_KNOWN ? "" : clock.slice(0, 5);
}

/** The health and what is refused, as an answer says them, or null where it says neither that reads. */
export function healthOfLoad(load: {
  health?: unknown;
  refusing?: unknown;
}): { health: Health; refusing: Refusing } | null {
  const health = HEALTHS.find((one) => one === load.health);
  const refusing = (["nothing", "long", "reads"] as const).find((one) => one === load.refusing);
  return health && refusing ? { health, refusing } : null;
}

const MEASURES: Readonly<Record<Measure, string>> = {
  response_ms: "how long requests take",
  cpu_percent: "the processor time the server uses",
};

/** What a measure of the ceiling is called in a sentence. */
export function measureWords(measure: Measure): string {
  return MEASURES[measure];
}

/** What the health stands on: the measures the server names, in words. */
export function becauseWords(because: readonly unknown[]): string {
  const named = (["response_ms", "cpu_percent"] as const)
    .filter((measure) => because.includes(measure))
    .map(measureWords);
  if (named.length === 0) return "";
  return `It is read from ${named.join(", and from ")}.`;
}

/** Whether no ceiling is in force: neither measure is looked at. */
export function noCeiling(ceiling: Pick<Load["ceiling"], "response_ms" | "cpu_percent">): boolean {
  return !(ceiling.response_ms > 0) && !(ceiling.cpu_percent > 0);
}

/**
 * Why a server whose answers are very slow, or past the ceiling, refuses nothing for it
 * (P-272). What is refused is decided by the reads, where there are enough of them to
 * be load: so either it is changes that are slow, or the reads are too few, and the
 * page says the one thing that is true of both. Where no ceiling is set for time, it
 * says that. Blank where the server does refuse, and where its answers are quicker.
 */
export function whyNothingRefused(load: Pick<Load, "health" | "refusing" | "ceiling">): string {
  if (load.refusing !== "nothing") return "";
  if (load.health !== "very_slow" && load.health !== "busy") return "";
  if (!(load.ceiling.response_ms > 0)) {
    return "Nothing is refused for it: no ceiling is set for how long requests take.";
  }
  return "Nothing is refused for it: it is not the reads that are slow, or there are too few of them for it to be load.";
}

/** What a busy server still answers, said beside what it refuses. */
export function stillAnswered(refusing: unknown): string {
  if (refusing === "long") return "Everything else is answered, and every change is stored.";
  if (refusing === "reads") return "Sign-ins are taken and every change is stored.";
  return "";
}

/** The method and the route of a request, as one: `GET /api/v1/items/{hid}`. */
export function requestText(row: Pick<SlowRequest, "method" | "route">): string {
  const method = typeof row.method === "string" ? row.method : "";
  return [method, typeof row.route === "string" ? row.route : "a path that no route answers"]
    .filter(Boolean)
    .join(" ");
}

export interface WhoWords {
  /** The username, or what the row is of where it is of no one account. */
  name: string;
  /** The account's HID, where the name is an account's, for a link to it. */
  hid: string | null;
  /** What is said after the name: that the account is a service token. */
  note: string;
}

/** Who asked, as the tables of About name them: a person, a service token, or the rest. */
export function whoWords(who: { kind?: unknown; hid?: unknown; username?: unknown }): WhoWords {
  const username = typeof who.username === "string" && who.username !== "" ? who.username : null;
  const hid = typeof who.hid === "string" && who.hid !== "" ? who.hid : null;
  switch (who.kind) {
    case "person":
      return { name: username ?? NOT_KNOWN, hid: username ? hid : null, note: "" };
    case "service":
      return {
        name: username ?? "A service token",
        hid: username ? hid : null,
        note: username ? "service token" : "",
      };
    case "unnamed":
      return { name: "Nobody named: not signed in, or signing in", hid: null, note: "" };
    case "others":
      return { name: "Everyone else, counted together", hid: null, note: "" };
    default:
      return { name: username ?? NOT_KNOWN, hid: null, note: "" };
  }
}

/** What tells one row of the people from another: the kind, and the account where there is one. */
export function personKey(person: { kind?: unknown; hid?: unknown }): string {
  return `${String(person.kind)} ${typeof person.hid === "string" ? person.hid : ""}`;
}

/** A count of the bands of a row, in its place, or 0 where the row has none there. */
export function bandCount(counts: unknown, place: number): number {
  const count = Array.isArray(counts) ? counts[place] : undefined;
  return typeof count === "number" && Number.isFinite(count) ? count : 0;
}

export interface WorkerWords {
  text: string;
  /** Said so that it is noticed: the work waits. */
  notice: boolean;
}

/** Whether the background work is being done, in words (P-267). */
export function workerWords(worker: unknown): WorkerWords {
  switch (worker) {
    case "running":
      return { text: "Running, as a process of its own.", notice: false };
    case "in_process":
      return { text: "Done by the server itself.", notice: false };
    case "not_running":
      return {
        text: "Not running. Imports and bulk edits wait to be applied, and nothing is done by the clock, until it is started.",
        notice: true,
      };
    default:
      return { text: NOT_KNOWN, notice: false };
  }
}
