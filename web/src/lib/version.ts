// 0.9.7: a page older than the server says that a new version is installed (P-231).
//
// The page knows the version it was built as, from web/package.json when it was built.
// It asks the server what is running, `GET /about`, on coming back to its tab, at a
// change of page when it last asked more than five minutes before, and when a page could
// not be drawn. Where the two differ, the notice stands until the page is loaded again:
// nothing here ever loads the page by itself, and nothing makes the notice go. A request
// that fails, or an answer without a version, says nothing.

/** The version this page was built as. */
export const BUILT_AS: string = __HIRDIR_VERSION__;

/** How long a change of page waits before it asks again, in milliseconds. */
export const ASK_AFTER = 5 * 60 * 1000;

/** The version the server answered, where it is another than the page's; else null. */
export function otherVersion(built: string, answer: unknown): string | null {
  if (typeof answer !== "object" || answer === null) return null;
  const version = (answer as { version?: unknown }).version;
  if (typeof version !== "string") return null;
  const running = version.trim();
  return running !== "" && running !== built ? running : null;
}

/** Whether a change of page asks again, when it last asked at `last`. */
export function dueToAsk(last: number, now: number): boolean {
  return now - last > ASK_AFTER;
}

type Listener = () => void;

export interface VersionDeps {
  /** Ask the server what is running; a rejection is taken as no answer. */
  ask: () => Promise<unknown>;
  /** Whether someone is signed in: nobody else is told what is running. */
  signedIn: () => boolean;
  now: () => number;
}

/** What the page knows of the version running on the server. */
export class VersionStore {
  private running: string | null = null;
  private asking = false;
  private last: number;
  private readonly listeners = new Set<Listener>();

  constructor(
    private readonly built: string,
    private readonly deps: VersionDeps,
  ) {
    // The page was served a moment ago, by the server that runs now.
    this.last = deps.now();
  }

  /** The version installed since the page was loaded, or null. It never goes back. */
  get = (): string | null => this.running;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Ask now, unless a question is on its way or the answer is known. */
  check = async (): Promise<void> => {
    if (this.running !== null || this.asking || !this.deps.signedIn()) return;
    this.asking = true;
    this.last = this.deps.now();
    try {
      const other = otherVersion(this.built, await this.deps.ask());
      if (other !== null) {
        this.running = other;
        for (const listener of this.listeners) listener();
      }
    } catch {
      // A request that fails says nothing.
    } finally {
      this.asking = false;
    }
  };

  /** At a change of page: ask where the last question is older than five minutes. */
  checkIfDue = (): void => {
    if (dueToAsk(this.last, this.deps.now())) void this.check();
  };
}
