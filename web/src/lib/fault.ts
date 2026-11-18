// 0.9.7: a page that cannot be drawn says so, and offers to load again (P-230).
//
// What is said of a fault, and the text of it that the page shows and copies for whoever
// is asked about it. The fault is written to the browser's console and sent nowhere.

/** A part of the web page, the file of one of its pages, that could not be fetched. */
export class PartNotFetched extends Error {
  constructor(cause: unknown) {
    super(
      `A part of the page could not be fetched: ${cause instanceof Error ? cause.message : String(cause)}`,
      { cause },
    );
    this.name = "PartNotFetched";
  }
}

/** Fetch a part of the page, a rejection of it said as a `PartNotFetched`. */
export function part<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((thrown: unknown) => {
      throw thrown instanceof PartNotFetched ? thrown : new PartNotFetched(thrown);
    });
}

// What browsers say of a module that could not be fetched: Chromium, Firefox, Safari, and
// the build's own preloading of a page's stylesheet.
const NOT_FETCHED = [
  /failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /importing a module script failed/i,
  /unable to preload css/i,
];

/** Whether the fault is a part of the page that could not be fetched. */
export function isMissingPart(error: unknown): boolean {
  if (error instanceof PartNotFetched) return true;
  if (error instanceof Error && error.name === "PartNotFetched") return true;
  const message = error instanceof Error ? error.message : String(error);
  return NOT_FETCHED.some((pattern) => pattern.test(message));
}

export interface FaultFacts {
  error: unknown;
  /** Where in the page it happened, as React says it. */
  componentStack?: string | null | undefined;
  /** The address of the page. */
  address: string;
  /** The version the page was built as. */
  version: string;
  /** When it happened. */
  at: Date;
}

/** The text of a fault, to be read out or pasted to whoever is asked about it. */
export function faultText(facts: FaultFacts): string {
  const { error } = facts;
  const said =
    error instanceof Error ? `${error.name}: ${error.message}` : `Thrown: ${String(error)}`;
  const lines = [
    said,
    `Page: ${facts.address}`,
    `Web page version: ${facts.version}`,
    `At: ${facts.at.toISOString()}`,
  ];
  const stack = error instanceof Error ? error.stack : undefined;
  if (stack) lines.push("", stack.trim());
  const where = facts.componentStack?.trim();
  if (where) lines.push("", "Drawn in:", where);
  return lines.join("\n");
}
