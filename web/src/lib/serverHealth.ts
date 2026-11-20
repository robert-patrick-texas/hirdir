// The health of the server, as every page shows it (P-270 to P-272): one of four words,
// green, yellow, orange and red, with what the server refuses. Every answer of the API
// carries both in `X-Hirdir-Health`, and the mark in the menu bar shows what the newest
// answer said. It is read from the answers the page gets anyway: nothing here asks the
// server anything, and nothing here runs by the clock.
//
// The words are of speed where nothing is refused, and say busy only where something
// is: red with nothing refused is one slow answer on a quiet server, which is slow and
// not busy (P-272).

export type Health = "good" | "slow" | "very_slow" | "busy";
export type Refusing = "nothing" | "long" | "reads";

export interface ServerHealth {
  health: Health;
  refusing: Refusing;
}

/** The four, from the best: the level of a band of time is its place among them. */
export const HEALTHS: readonly Health[] = ["good", "slow", "very_slow", "busy"];
const REFUSINGS: readonly Refusing[] = ["nothing", "long", "reads"];

/** The header every answer of the API carries. */
export const HEALTH_HEADER = "X-Hirdir-Health";

/**
 * What `X-Hirdir-Health: busy; refusing=nothing` says: both words, in that form. Null
 * for no header, as on an answer from something in front of the server, and for one of
 * any other form or with a word this page does not know: there is then no mark.
 */
export function healthOfHeader(header: unknown): ServerHealth | null {
  if (typeof header !== "string") return null;
  const found = /^\s*([a-z_]+)\s*;\s*refusing\s*=\s*([a-z_]+)\s*$/.exec(header);
  if (!found) return null;
  const health = HEALTHS.find((one) => one === found[1]);
  const refusing = REFUSINGS.find((one) => one === found[2]);
  return health && refusing ? { health, refusing } : null;
}

const SPEED: Readonly<Record<Health, string>> = {
  good: "Answers are quick",
  slow: "Answers are slow",
  very_slow: "Answers are very slow",
  busy: "Answers are slower than the server's ceiling",
};

const REFUSED: Readonly<Record<Exclude<Refusing, "nothing">, string>> = {
  long: "The server is busy: reports, exports and previews are not answered for now",
  reads: "The server is busy: lists and everything else that only reads are not answered for now",
};

/** How quick answers are, in words of speed. */
export function speedWords(health: Health): string {
  return `${SPEED[health]}.`;
}

/** What a busy server refuses, in words; null where it refuses nothing. */
export function refusedWords(refusing: Refusing): string | null {
  return refusing === "nothing" ? null : `${REFUSED[refusing]}.`;
}

/**
 * The health in one sentence, as the mark says it: of speed where nothing is refused,
 * and that the server is busy, with what it does not answer, only where something is.
 */
export function healthWords({ health, refusing }: ServerHealth): string {
  return refusedWords(refusing) ?? speedWords(health);
}

/**
 * What pointing at the mark shows: the health in its sentence; where answers are very
 * slow or past the ceiling and nothing is refused for it, that nothing is, which is true
 * whatever the reason, and About says the reason; and that About has the measures.
 */
export function healthTitle(said: ServerHealth): string {
  const slowUnrefused =
    said.refusing === "nothing" && (said.health === "very_slow" || said.health === "busy");
  return `${healthWords(said)}${slowUnrefused ? " Nothing is refused." : ""} About shows the server's measures.`;
}

// ---- the newest answer's word, held in one place ---------------------------------------

let newest: ServerHealth | null = null;
const listeners = new Set<() => void>();

/**
 * What the newest answer of the server said of its health, for the mark to show. Whoever
 * shows it subscribes, and is told only when the word or what is refused is another, so
 * an answer that says the same draws nothing again.
 */
export const serverHealth = {
  get: (): ServerHealth | null => newest,
  /** Take what an answer said: null where it said nothing that reads. */
  set(next: ServerHealth | null): void {
    if (next?.health === newest?.health && next?.refusing === newest?.refusing) return;
    newest = next;
    for (const listener of [...listeners]) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};

// ---- the bands of time -----------------------------------------------------------------

/** A length of time as a number and its unit: whole seconds where it is, else milliseconds. */
function span(ms: number): { amount: string; unit: "ms" | "second" } {
  if (ms >= 1000 && ms % 100 === 0) {
    return { amount: (ms / 1000).toLocaleString("en-US"), unit: "second" };
  }
  return { amount: ms.toLocaleString("en-US", { maximumFractionDigits: 1 }), unit: "ms" };
}

function withUnit({ amount, unit }: { amount: string; unit: "ms" | "second" }): string {
  if (unit === "ms") return `${amount} ms`;
  return amount === "1" ? "1 second" : `${amount} seconds`;
}

/**
 * The names of the bands that some bounds part, from the bounds themselves: of
 * `[1000, 2000, 3000]`, "Under 1 second", "1 to 2 seconds", "2 to 3 seconds" and "Over 3
 * seconds". One more name than there are bounds; none for bounds that are no numbers.
 */
export function bandLabels(bounds: unknown): string[] {
  if (!Array.isArray(bounds) || bounds.length === 0) return [];
  if (!bounds.every((one) => typeof one === "number" && Number.isFinite(one) && one >= 0)) {
    return [];
  }
  const spans = (bounds as number[]).map(span);
  const labels = [`Under ${withUnit(spans[0] ?? { amount: "0", unit: "ms" })}`];
  for (let place = 1; place < spans.length; place += 1) {
    const from = spans[place - 1];
    const to = spans[place];
    if (!from || !to) continue;
    labels.push(
      from.unit === to.unit
        ? `${from.amount} to ${withUnit(to)}`
        : `${withUnit(from)} to ${withUnit(to)}`,
    );
  }
  const last = spans.at(-1);
  if (last) labels.push(`Over ${withUnit(last)}`);
  return labels;
}

/**
 * The level of a band, for its colour and its shape: the four bands are the four words
 * of the health in their order. A band past the fourth, should there be one, is the worst.
 */
export function bandHealth(place: number): Health {
  return HEALTHS[Math.max(0, Math.min(place, HEALTHS.length - 1))] ?? "busy";
}
