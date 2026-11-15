// A stored preview, followed while it is applied in the background.
//
// An apply is answered at once, and the server works the rows beside the requests. The
// page reads the job again every moment while it is queued or applying, so that it
// shows how far the apply has got, and stops reading once it has ended. A page that is
// left and come back to reads the job afresh, and follows it again if it is still under
// way.

import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { type ApiError, api } from "../api";
import { toApiError } from "./hooks";
import { isWorking, type Job } from "./preview";

/** How long a page waits before it reads a job that is under way again, in milliseconds. */
export const POLL_MS = 1000;

export interface FollowedJob {
  /** The job as the server last answered it: undefined until it is read. */
  job: Job | undefined;
  error: ApiError | null;
  loading: boolean;
  /** Read it again now. */
  reload: () => void;
  /** The server answered an apply with the job: show it, and follow it while it works. */
  started: (job: Job) => void;
}

interface Options {
  /**
   * The job as the page has it already, as the answer of a preview holds it: shown at
   * once, and not read again until it is applied.
   */
  first?: Job | undefined;
  /** The apply ended, applied or stopped: what it changed may be read again. */
  onEnded?: (job: Job) => void;
}

interface State {
  hid: string;
  job: Job | undefined;
  error: ApiError | null;
  loading: boolean;
  /** How many answers have come, good or bad: the next read is timed from the last. */
  answers: number;
}

/** Read a job, and read it again every moment while its apply is under way. */
export function useJob(hid: string, { first, onEnded }: Options = {}): FollowedJob {
  const [state, setState] = useState<State>(() => ({
    hid,
    job: first,
    error: null,
    loading: first === undefined,
    answers: 0,
  }));
  // Each turn is one read. A page that has the job already reads it when it is applied.
  const [turn, setTurn] = useState(first === undefined ? 1 : 0);
  const ended = useEffectEvent((job: Job) => onEnded?.(job));
  const following = useRef(false);

  useEffect(() => {
    if (turn === 0) return;
    const controller = new AbortController();
    api.request("get", "/api/v1/imports/{hid}", { path: { hid }, signal: controller.signal }).then(
      (job) => {
        if (controller.signal.aborted) return;
        setState((was) => ({ hid, job, error: null, loading: false, answers: was.answers + 1 }));
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState((was) => ({
          ...was,
          hid,
          error: toApiError(error),
          loading: false,
          answers: was.answers + 1,
        }));
      },
    );
    return () => controller.abort();
  }, [hid, turn]);

  const job = state.hid === hid ? state.job : first;
  const working = job !== undefined && isWorking(job);

  // While the apply is under way, the job is read again a moment after each answer, and
  // after a read that failed too: the server may have been busy for that moment.
  // Each answer is a new state, which times the next read from itself.
  useEffect(() => {
    if (!working || state.loading) return;
    const timer = setTimeout(() => setTurn((count) => count + 1), POLL_MS);
    return () => clearTimeout(timer);
  }, [working, state]);

  // An apply that was under way and is no longer has ended, whichever way.
  useEffect(() => {
    if (job === undefined) return;
    if (isWorking(job)) {
      following.current = true;
    } else if (following.current) {
      following.current = false;
      ended(job);
    }
  }, [job]);

  const reload = useCallback(() => setTurn((count) => count + 1), []);
  const started = useCallback((given: Job) => {
    setState((was) => ({ ...was, hid: given.hid, job: given, error: null, loading: false }));
  }, []);
  return {
    job,
    error: state.hid === hid ? state.error : null,
    loading: state.hid === hid ? state.loading : first === undefined,
    reload,
    started,
  };
}
