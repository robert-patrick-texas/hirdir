// 0.9.7: a page that cannot be drawn says so, and offers to load again (P-230).
//
// What is said of a fault, and the text of it that the page shows and copies for whoever
// is asked about it. The fault is written to the browser's console and sent nowhere.

import { type ComponentType, createElement, lazy } from "react";

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

// The parts whose fetch failed, each with what makes it be fetched anew.
const failedParts = new Set<() => void>();

/**
 * A page that is a part of its own, as `lazy` makes one, save that a fetch that failed is
 * tried again the next time the page is opened. `lazy` keeps a rejection for good, so the
 * part is made anew, though only when the fault is cleared by a move to a page: never
 * while it is drawn, where a part that stays missing would be fetched again and again.
 */
export function retriedPart<C extends ComponentType<never>>(
  load: () => Promise<{ default: C }>,
): C {
  const make = () =>
    lazy(
      () =>
        load().catch((thrown: unknown) => {
          failedParts.add(reset);
          throw thrown;
        }) as unknown as Promise<{ default: ComponentType<object> }>,
    );
  const held: HeldPart = { current: make() };
  const reset = () => {
    held.current = make();
  };
  return DrawnPart.bind(held) as unknown as C;
}

/** What a part draws now: the one made last. */
interface HeldPart {
  current: ComponentType<object>;
}

/** A part, drawn as the one it holds now; bound to what it holds by `retriedPart`. */
function DrawnPart(this: HeldPart, props: object) {
  return createElement(this.current, props);
}

/** Make every part that could not be fetched be fetched anew when it is next opened. */
export function retryFailedParts(): void {
  for (const reset of failedParts) reset();
  failedParts.clear();
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
