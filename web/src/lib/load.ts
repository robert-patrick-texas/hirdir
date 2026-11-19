// The server's own measures as About says them (P-265, P-266): the words of each state,
// of each measure and of the background work, numbers with their units, and what is kept
// as it was when a new answer holds the same. A value the server or its host does not
// say is said as not known, never as 0.

import type { Schemas } from "../api/client";
import { formatTime } from "./format";
import { sameAnswer } from "./hooks";
import { sizeText } from "./references";

export type Load = Schemas["Load"];
export type Measure = "response_ms" | "cpu_percent";

export const NOT_KNOWN = "not known";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const LISTS = ["requests", "average_ms", "high_ms", "cpu_percent", "busy"] as const;

/**
 * The answer of `GET /about/load`, where it has the shape the page draws: its parts, and
 * the lists of the graph. Null for anything else, as an answer from something in front of
 * the server, which the page then says it could not read, where drawing it would fail.
 */
export function loadOf(answer: unknown): Load | null {
  if (!isRecord(answer)) return null;
  const { ceiling, host, in_flight, measures, points, process, totals, because, at } = answer;
  if (![ceiling, host, in_flight, measures, points, process, totals].every(isRecord)) return null;
  if (typeof at !== "string" || !Array.isArray(because)) return null;
  const spreads = totals as Record<string, unknown>;
  if (!isRecord(spreads.response_ms) || !isRecord(spreads.cpu_percent)) return null;
  const lists = points as Record<string, unknown>;
  if (!LISTS.every((name) => Array.isArray(lists[name]))) return null;
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

export interface StateWords {
  /** The state in a word or two. */
  name: string;
  /** What the server does while it is so. */
  what: string;
}

const STATES: Readonly<Record<string, StateWords>> = {
  ok: { name: "Not busy", what: "Every request is answered." },
  busy: {
    name: "Busy",
    what: "Lists, reports, exports and previews are answered at once that the server is busy, until it eases. Everything else is answered, and every change is stored.",
  },
  very_busy: {
    name: "Very busy",
    what: "Everything that only reads is answered at once that the server is busy, until it eases. Sign-ins are taken and every change is stored.",
  },
};

/** What a state of the server is called, and what the server does in it. */
export function stateWords(state: unknown): StateWords {
  if (typeof state === "string" && Object.hasOwn(STATES, state)) {
    const words = STATES[state];
    if (words) return words;
  }
  return { name: "Not known", what: "The server did not say whether it is busy." };
}

const MEASURES: Readonly<Record<Measure, string>> = {
  response_ms: "how long requests take",
  cpu_percent: "the share of one processor it uses",
};

/** What a measure of the ceiling is called in a sentence. */
export function measureWords(measure: Measure): string {
  return MEASURES[measure];
}

/** Why the server is busy: the measures that are past their ceiling, in words. */
export function becauseWords(because: readonly unknown[]): string {
  const named = (["response_ms", "cpu_percent"] as const)
    .filter((measure) => because.includes(measure))
    .map(measureWords);
  if (named.length === 0) return "";
  return `Past its ceiling: ${named.join(", and ")}.`;
}

/** Whether no ceiling is in force: neither measure is looked at. */
export function noCeiling(ceiling: Load["ceiling"]): boolean {
  return !(ceiling.response_ms > 0) && !(ceiling.cpu_percent > 0);
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
