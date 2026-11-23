// Whether the background work is running, read while a job waits for it (0.9.19, the
// review of P-325, R1): a preview or an apply in its turn waits for as long as the
// process of the background work is not running, and the page says so.

import { useEffect, useState } from "react";
import { api } from "../api";

/** How long a page waits before it asks again while a job still waits, in milliseconds. */
export const WORKER_EVERY_MS = 15_000;

/**
 * `worker` of `GET /about/load`, which is kept in memory and never refused, while
 * `waiting`: asked at once, and again every so often until the job no longer waits.
 * Undefined while nothing waits, and until it is known.
 */
export function useWorker(waiting: boolean): unknown {
  const [worker, setWorker] = useState<unknown>(undefined);
  useEffect(() => {
    if (!waiting) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = () => {
      api.request("get", "/api/v1/about/load", { signal: controller.signal }).then(
        (load) => {
          if (controller.signal.aborted) return;
          setWorker(load.worker);
          timer = setTimeout(ask, WORKER_EVERY_MS);
        },
        () => {
          // Not known this time: nothing is said of it, and it is asked again later.
          if (!controller.signal.aborted) timer = setTimeout(ask, WORKER_EVERY_MS);
        },
      );
    };
    ask();
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [waiting]);
  return waiting ? worker : undefined;
}
