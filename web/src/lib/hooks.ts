import {
  type RefObject,
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError } from "../api/client";
import { titleOf, useSite } from "./product";

/** Whatever was thrown, as an ApiError. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError({
    status: 0,
    title: "Something went wrong",
    detail: error instanceof Error ? error.message : String(error),
  });
}

export interface Loaded<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  /**
   * Read again in the background (P-183): `loading` stays as it is and what is on show
   * stays on show until the new answer comes, and a read that fails leaves it so.
   */
  refresh: () => void;
}

interface LoadState<T> {
  key: string;
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
}

/** Whether two answers of the server hold the same values, whatever objects hold them. */
export function sameAnswer(one: unknown, other: unknown): boolean {
  if (Object.is(one, other)) return true;
  if (typeof one !== "object" || typeof other !== "object" || one === null || other === null) {
    return false;
  }
  if (Array.isArray(one) || Array.isArray(other)) {
    if (!Array.isArray(one) || !Array.isArray(other) || one.length !== other.length) return false;
    return one.every((value, index) => sameAnswer(value, other[index]));
  }
  const left = one as Record<string, unknown>;
  const right = other as Record<string, unknown>;
  const names = Object.keys(left);
  if (names.length !== Object.keys(right).length) return false;
  return names.every((name) => Object.hasOwn(right, name) && sameAnswer(left[name], right[name]));
}

/** Whether what is on show is whole and is what was read again. */
function keptAsIs<T>(was: LoadState<T>, key: string, data: T): boolean {
  return was.key === key && !was.loading && was.error === null && sameAnswer(was.data, data);
}

// 0.9.10: asking again for what a busy server did not answer (P-265). A server past its
// ceiling answers a read at once that it is busy, and to try again in a few seconds.
// Nothing asks again by itself. The page offers Try again under the refusal of a read,
// and pressing it asks again for every read on the page that was so refused, since one
// busy moment refuses several: the rows of a list and the lists of choices beside it.

const askers = new Set<() => void>();
// The refusals of reads, which are the ones that can be asked again from here: a refused
// change is sent again by the form that sent it.
const reads = new WeakSet<ApiError>();

/** Hear when the person asks again. Returns the means to stop hearing. */
export function hearAskAgain(asker: () => void): () => void {
  askers.add(asker);
  return () => {
    askers.delete(asker);
  };
}

/** Ask again for every read on the page that a busy server did not answer. */
export function askAgain(): void {
  for (const asker of [...askers]) asker();
}

/** Note the failure of a read, where it is a busy server's, as one to offer Try again under. */
export function noteRead(error: ApiError): void {
  if (error.busy) reads.add(error);
}

/** Whether a failure is that of a read a busy server did not answer, which `askAgain` asks again. */
export function canAskAgain(error: ApiError | null | undefined): boolean {
  return !!error && error.busy !== null && reads.has(error);
}

/**
 * Read something from the server, and again whenever `key` changes or `reload` is called.
 * What was read stays on show while the same key is being read again.
 */
export function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>): Loaded<T> {
  const [state, setState] = useState<LoadState<T>>({
    key,
    data: undefined,
    error: null,
    loading: true,
  });
  const [turn, setTurn] = useState({ count: 0, quiet: false });
  const wanted = useMemo(() => ({ key, turn }), [key, turn]);
  const run = useEffectEvent(load);
  // What is on show, for a refresh to know whether there is anything to keep on show.
  const read = useRef<LoadState<T>>(state);
  useEffect(() => {
    read.current = state;
  }, [state]);

  useEffect(() => {
    const controller = new AbortController();
    const { key, turn } = wanted;
    const was = read.current;
    const quiet = turn.quiet && was.key === key && was.data !== undefined && !was.loading;
    if (!quiet) {
      setState((was) => ({
        key,
        data: was.key === key ? was.data : undefined,
        error: null,
        loading: true,
      }));
    }
    run(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        // Read again in the background and the same: what the page has is kept as it is,
        // so nothing that is made from it is made again (P-264).
        setState((was) =>
          quiet && keptAsIs(was, key, data) ? was : { key, data, error: null, loading: false },
        );
      },
      (error: unknown) => {
        if (controller.signal.aborted || quiet) return;
        const failure = toApiError(error);
        noteRead(failure);
        setState((was) => ({ ...was, key, error: failure, loading: false }));
      },
    );
    return () => controller.abort();
  }, [wanted]);

  const reload = useCallback(
    () => setTurn(({ count }) => ({ count: count + 1, quiet: false })),
    [],
  );
  // 0.9.10: what a busy server did not answer is asked for again when the person says so,
  // with Try again under any such refusal on the page (P-265).
  useEffect(
    () =>
      hearAskAgain(() => {
        if (read.current.error?.busy) reload();
      }),
    [reload],
  );
  const refresh = useCallback(
    () => setTurn(({ count }) => ({ count: count + 1, quiet: true })),
    [],
  );
  const current = state.key === key;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : null,
    loading: current ? state.loading : true,
    reload,
    refresh,
  };
}

/**
 * Read again when the person comes back to the tab, while `active` (P-183): a search on
 * show, or a list a page read whole when it opened. Nothing is asked while the tab is
 * hidden, nor of what is not on show.
 */
export function useReloadOnReturn(reload: () => void, active = true): void {
  useEffect(() => {
    if (!active) return;
    const back = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [active, reload]);
}

/**
 * Read something again whenever `changed` is another value than it was. What was read
 * stays on show meanwhile, so that a page does not go blank after every change made on it.
 */
export function useReloadOn(changed: string | number, reload: () => void): void {
  const seen = useRef(changed);
  useEffect(() => {
    if (seen.current === changed) return;
    seen.current = changed;
    reload();
  }, [changed, reload]);
}

/** What a field that finds a record by what is typed has asked the server for. */
export interface Asked {
  /** The text asked for, as typed. */
  asked: string;
  /** How many times the same text was asked for again: a reason to read it again. */
  again: number;
  /** Ask now, as Enter does, for what is typed. */
  askNow: () => void;
  /** Ask for nothing, as when a record was chosen and the box emptied. */
  forget: () => void;
}

/**
 * What a search field asks for once `text` is asked for: other text is a new search, the
 * same text is the same search asked again, and blank is no search, asked again or not.
 */
export function askedNext(
  was: { asked: string; again: number },
  text: string,
): { asked: string; again: number } {
  if (text.trim() === "" && was.asked.trim() === "") return was;
  // Text that differs, if only by a space at its end, is not the same text asked again:
  // the key of the search says whether it is another search.
  if (was.asked !== text) return { asked: text, again: was.again };
  return { asked: text, again: was.again + 1 };
}

/**
 * The text a search field asks for: what is typed, once the typing pauses for `pause`
 * milliseconds or Enter is pressed. Asking for the same text again, by Enter or by typing
 * it again, counts in `again`, which the field reads again on (P-183): the key of what
 * it reads is the same, so it would not be asked for otherwise.
 */
export function useAsked(typed: string, pause = 300): Asked {
  const [state, setState] = useState({ asked: "", again: 0 });
  const timer = useRef<number | undefined>(undefined);

  const ask = useCallback((text: string) => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    setState((was) => askedNext(was, text));
  }, []);

  useEffect(() => {
    timer.current = window.setTimeout(() => ask(typed), pause);
    return () => window.clearTimeout(timer.current);
  }, [typed, pause, ask]);

  const askNow = useCallback(() => ask(typed), [ask, typed]);
  const forget = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    setState((was) => ({ asked: "", again: was.again }));
  }, []);
  return {
    asked: state.asked,
    again: state.again,
    askNow,
    forget,
  };
}

/** What is heard of a change sent to the server through `useAction`. */
export type Heard = "sent" | "done" | "refused";

const hearers = new Set<(heard: Heard) => void>();

/**
 * Hear of every change sent from the page on show (P-182): that it was sent, and that it
 * was done or refused. "done" is told once the code that sent the change has had its
 * answer and said what it says of it, so that a hearer then finds that said. Returns
 * the means to stop hearing.
 */
export function hearChanges(hearer: (heard: Heard) => void): () => void {
  hearers.add(hearer);
  return () => {
    hearers.delete(hearer);
  };
}

function tell(heard: Heard): void {
  for (const hearer of [...hearers]) hearer(heard);
}

export interface Action {
  busy: boolean;
  error: ApiError | null;
  /** Run a change. Returns its answer, or undefined when the server refused it. */
  run: <T>(change: () => Promise<T>) => Promise<{ ok: true; value: T } | { ok: false }>;
  clear: () => void;
}

/** Track one change being sent to the server: whether it is under way, and how it failed. */
export function useAction(): Action {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback<Action["run"]>(async (change) => {
    setBusy(true);
    setError(null);
    tell("sent");
    try {
      const value = await change();
      // After the sender has gone on from its answer, and set what the page says of it.
      window.setTimeout(() => tell("done"), 0);
      return { ok: true, value };
    } catch (thrown) {
      setError(toApiError(thrown));
      tell("refused");
      return { ok: false };
    } finally {
      setBusy(false);
    }
  }, []);
  const clear = useCallback(() => setError(null), []);
  return { busy, error, run, clear };
}

/** Name the page in the browser's title bar, with the name the site gives the product. */
export function useTitle(title: string): void {
  const { productName } = useSite();
  useEffect(() => {
    document.title = titleOf(title, productName);
  }, [title, productName]);
}

/**
 * 0.9.5: what a picker found is brought into the window when it arrives for the box being
 * typed in, so that the buttons that stay at the foot of the window do not cover it
 * (P-190): only as far as it needs, and the padding of the page keeps it above them.
 * `found` is the answer, a new one each time one arrives.
 */
export function useFoundInView(
  list: RefObject<HTMLElement | null>,
  box: RefObject<HTMLElement | null>,
  found: unknown,
): void {
  useEffect(() => {
    if (found === undefined || found === null) return;
    if (!list.current || !box.current || document.activeElement !== box.current) return;
    list.current.scrollIntoView({ block: "nearest" });
  }, [list, box, found]);
}
