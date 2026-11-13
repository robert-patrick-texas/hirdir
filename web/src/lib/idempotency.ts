// Idempotency keys: so that a request sent again after its answer was lost is not
// carried out a second time.
//
// The server keeps the answer to a `POST` that succeeded under the key it came with,
// and gives that answer again to the same request with the same key. So a request keeps
// its key for as long as it has had no answer, and takes a new one once it has: asking
// for the same thing again on purpose, as in "preview again", is then a new request.

import { ApiError } from "../api/client";

/** A key nobody else will choose: 32 hex digits. */
export function newKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The keys of the requests that have been sent and not yet answered. */
export class Keys {
  private readonly held = new Map<string, string>();
  private readonly make: () => string;

  constructor(make: () => string = newKey) {
    this.make = make;
  }

  /** The key to send a request with: the one it was last sent with, if that got no answer. */
  of(request: string): string {
    let key = this.held.get(request);
    if (key === undefined) {
      key = this.make();
      this.held.set(request, key);
    }
    return key;
  }

  /** The request was answered, with a yes or a no. The next one like it is a new request. */
  answered(request: string): void {
    this.held.delete(request);
  }
}

/** True for a failure that leaves it unknown whether the server carried the request out. */
function unanswered(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status >= 500);
}

/**
 * Send a request with its key. `request` says what is asked for, in any words that are
 * the same when the same thing is asked again. When no answer comes, the key is kept
 * for the next attempt.
 */
export async function withKey<T>(
  keys: Keys,
  request: string,
  send: (key: string) => Promise<T>,
): Promise<T> {
  const key = keys.of(request);
  try {
    const answer = await send(key);
    keys.answered(request);
    return answer;
  } catch (error) {
    if (!unanswered(error)) keys.answered(request);
    throw error;
  }
}
