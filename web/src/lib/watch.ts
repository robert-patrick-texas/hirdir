// Asking the server for the same thing again and again, cheaply (P-266): one request
// every so often while the page that shows it is in front, none while it is hidden, one
// at once on coming back, and never two at a time. About watches the server's own
// measures with it, and a person watches About while the server is in trouble, so the
// watching must not be load of its own: a request that fails or is slow is not followed
// at once by another.
//
// Nothing here knows of React or of the browser: what asks, the clock, the timers and
// whether the page is in front are given, so the rules are tested without waiting.

export interface WatchDeps {
  /**
   * Ask once. The signal is aborted when the watch stops, or when no answer has come in
   * `giveUp` milliseconds. A promise that rejects is a request that failed.
   */
  ask: (signal: AbortSignal) => Promise<unknown>;
  /** From one request to the next, in milliseconds. */
  every: number;
  /** How long an answer is waited for, in milliseconds. */
  giveUp: number;
  /** Whether the page is in front: `document.visibilityState` is `visible`. */
  visible: () => boolean;
  now?: () => number;
  setTimer?: (run: () => void, wait: number) => unknown;
  clearTimer?: (timer: unknown) => void;
}

export interface Watch {
  /** Begin: ask now, if the page is in front. */
  start: () => void;
  /** The page came to the front or went behind: ask at once, or ask nothing more. */
  look: () => void;
  /** End: nothing more is asked, and what is asked is let go. */
  stop: () => void;
}

/**
 * How long to wait after an answer before asking again: the rest of `every` counted from
 * when the request was sent, so that requests are `every` apart; and all of `every`
 * after one that failed or took that long, so that a server in trouble is left alone
 * for as long as a well one.
 */
export function waitAfter(every: number, took: number, failed: boolean): number {
  if (failed || !(took >= 0) || took >= every) return every;
  return every - took;
}

/**
 * How long a page that reads something again by itself, as a job that is being applied,
 * waits after an answer: as long as it usually does, and after the answer of a busy
 * server at least as long as that answer says to (P-265), so that a server that asked
 * to be left alone for five seconds is.
 */
export function waitAsTold(
  usual: number,
  error: { busy: unknown; retryAfter: number | null } | null,
): number {
  if (!error?.busy || error.retryAfter === null || !(error.retryAfter > 0)) return usual;
  return Math.max(usual, error.retryAfter * 1000);
}

export function watchEvery(deps: WatchDeps): Watch {
  const now = deps.now ?? (() => Date.now());
  const setTimer = deps.setTimer ?? ((run, wait) => setTimeout(run, wait));
  const clearTimer =
    deps.clearTimer ?? ((timer) => clearTimeout(timer as ReturnType<typeof setTimeout>));
  // The request that is out, if one is: there is never a second.
  let asking: AbortController | null = null;
  let next: unknown;
  let stopped = false;

  function forgetNext(): void {
    if (next !== undefined) clearTimer(next);
    next = undefined;
  }

  function ask(): void {
    forgetNext();
    if (stopped || asking || !deps.visible()) return;
    const controller = new AbortController();
    asking = controller;
    const sent = now();
    const tooLong = setTimer(() => controller.abort(), deps.giveUp);
    const ended = (failed: boolean) => {
      clearTimer(tooLong);
      if (asking === controller) asking = null;
      // Hidden meanwhile: coming back asks. Stopped: nothing asks.
      if (stopped || !deps.visible()) return;
      forgetNext();
      next = setTimer(ask, waitAfter(deps.every, now() - sent, failed));
    };
    let answer: Promise<unknown>;
    try {
      answer = deps.ask(controller.signal);
    } catch (thrown) {
      answer = Promise.reject(thrown);
    }
    answer.then(
      () => ended(false),
      () => ended(true),
    );
  }

  return {
    start: ask,
    look() {
      if (stopped) return;
      if (deps.visible()) ask();
      else forgetNext();
    },
    stop() {
      stopped = true;
      forgetNext();
      asking?.abort();
      asking = null;
    },
  };
}
