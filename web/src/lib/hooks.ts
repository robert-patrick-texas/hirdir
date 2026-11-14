import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { ApiError } from "../api/client";

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
}

interface LoadState<T> {
  key: string;
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
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
  const [turn, setTurn] = useState(0);
  const wanted = useMemo(() => ({ key, turn }), [key, turn]);
  const run = useEffectEvent(load);

  useEffect(() => {
    const controller = new AbortController();
    const { key } = wanted;
    setState((was) => ({
      key,
      data: was.key === key ? was.data : undefined,
      error: null,
      loading: true,
    }));
    run(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ key, data, error: null, loading: false });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState((was) => ({ ...was, key, error: toApiError(error), loading: false }));
      },
    );
    return () => controller.abort();
  }, [wanted]);

  const reload = useCallback(() => setTurn((count) => count + 1), []);
  const current = state.key === key;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : null,
    loading: current ? state.loading : true,
    reload,
  };
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
    try {
      return { ok: true, value: await change() };
    } catch (thrown) {
      setError(toApiError(thrown));
      return { ok: false };
    } finally {
      setBusy(false);
    }
  }, []);
  const clear = useCallback(() => setError(null), []);
  return { busy, error, run, clear };
}

/** Name the page in the browser's title bar. */
export function useTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} · hirdir` : "hirdir";
  }, [title]);
}
