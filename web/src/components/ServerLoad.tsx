// The server's own measures, on About, for everyone signed in (P-265, P-266): whether it
// is busy and by which measure, with the ceiling in force; the lowest, the average and
// the highest time of an answer and share of the processor over the last ten minutes;
// how the requests were answered; what is in flight; the process and its host; whether
// the background work is being done; and one graph.
//
// A person watches this while the server is in trouble, so watching it is cheap: one
// request of `GET /about/load` every five seconds while the page is in front, none while
// it is hidden, one at once on coming back, and never two at a time (`lib/watch.ts`).
// What is read is kept here and nowhere above, so nothing else of About is drawn again
// by the clock; each part below is drawn again only when its own numbers are other than
// they were, since a part that holds the same in a new answer is kept as it is (P-264).

import { memo, useEffect, useState } from "react";
import { api } from "../api";
import { ApiError } from "../api/client";
import { toApiError } from "../lib/hooks";
import {
  becauseWords,
  bytesText,
  clockText,
  countText,
  kept,
  type Load,
  loadAverageText,
  loadOf,
  type Measure,
  msText,
  noCeiling,
  percentText,
  stateWords,
  waitText,
  workerWords,
} from "../lib/load";
import { sentence } from "../lib/problems";
import { watchEvery } from "../lib/watch";
import { LoadGraph } from "./LoadGraph";
import { Problem } from "./Problem";
import { Time } from "./Time";

/** From one request to the next, and how long an answer is waited for, in milliseconds. */
const EVERY_MS = 5000;
const GIVE_UP_MS = 15_000;

interface Watched {
  /** The last answer that was read, which stays on show while a later request fails. */
  load: Load | null;
  /** The last request, where it failed: when, by this browser's clock, and how. */
  failed: { at: number; error: ApiError } | null;
}

/** What went wrong with a request, as the page says it. */
function failureOf(thrown: unknown): ApiError {
  const error = toApiError(thrown);
  if (!error.aborted) return error;
  return new ApiError({
    status: 0,
    title: "No answer",
    detail: `The server did not answer in ${GIVE_UP_MS / 1000} seconds.`,
  });
}

/** The server's measures, read again every five seconds while the page is in front. */
function useServerLoad(): Watched {
  const [watched, setWatched] = useState<Watched>({ load: null, failed: null });
  useEffect(() => {
    let gone = false;
    const watch = watchEvery({
      every: EVERY_MS,
      giveUp: GIVE_UP_MS,
      visible: () => document.visibilityState === "visible",
      ask: async (signal) => {
        try {
          const load = loadOf(await api.request("get", "/api/v1/about/load", { signal }));
          if (!load) {
            throw new ApiError({
              status: 0,
              title: "Unreadable answer",
              detail: "The server's answer could not be read.",
            });
          }
          if (!gone) setWatched((was) => ({ load: kept(was.load, load), failed: null }));
        } catch (thrown) {
          if (!gone) {
            setWatched((was) => ({
              load: was.load,
              failed: { at: Date.now(), error: failureOf(thrown) },
            }));
          }
          throw thrown;
        }
      },
    });
    const look = () => watch.look();
    document.addEventListener("visibilitychange", look);
    watch.start();
    return () => {
      gone = true;
      document.removeEventListener("visibilitychange", look);
      watch.stop();
    };
  }, []);
  return watched;
}

/** Since when the numbers are, and where the last request failed, that it did. */
function Since({ at, failed }: { at: string; failed: Watched["failed"] }) {
  if (failed) {
    return (
      <p className="alert alert-error" data-testid="load-since" data-stale="true">
        The server's measures could not be read at {clockText(failed.at)}:{" "}
        {sentence(failed.error.message)} These are the numbers of {clockText(at)}.
      </p>
    );
  }
  return (
    <p className="muted" data-testid="load-since" data-stale="false" data-at={at}>
      Read at {clockText(at)}, and again every {EVERY_MS / 1000} seconds while this page is in
      front.
    </p>
  );
}

const MEASURE_NAMES: ReadonlyArray<{ measure: Measure; name: string }> = [
  { measure: "response_ms", name: "How long requests take: the median" },
  { measure: "cpu_percent", name: "Share of one processor the server uses" },
];

/** Whether the server is busy, by which measure, and the ceiling in force. */
const State = memo(function State({
  state,
  because,
  ceiling,
  measures,
}: Pick<Load, "state" | "because" | "ceiling" | "measures">) {
  const words = stateWords(state);
  const why = becauseWords(because);
  const now = (measure: Measure) =>
    measure === "response_ms"
      ? msText(measures.response_ms, "too few requests to say")
      : percentText(measures.cpu_percent);
  const limit = (measure: Measure) => {
    if (!(ceiling[measure] > 0)) return "not looked at";
    return measure === "response_ms" ? msText(ceiling[measure]) : percentText(ceiling[measure]);
  };
  return (
    <>
      {/* Said aloud when the state becomes another: the words are the same until then. */}
      <div role="status">
        <p
          className={`alert ${state === "ok" ? "alert-ok" : "alert-warn"}`}
          data-testid="load-state"
          data-state={state}
        >
          <strong>{words.name}.</strong> {words.what}
          {why && ` ${why}`}
          {noCeiling(ceiling) &&
            " No ceiling is set: the server refuses nothing, however busy it is."}
        </p>
      </div>
      <div className="scroll">
        <table className="load-table" data-testid="load-measures">
          <thead>
            <tr>
              <th scope="col">
                What the ceiling reads, over the last {ceiling.over_seconds} seconds
              </th>
              <th scope="col" className="number">
                Now
              </th>
              <th scope="col" className="number">
                Ceiling
              </th>
            </tr>
          </thead>
          <tbody>
            {MEASURE_NAMES.map(({ measure, name }) => {
              const past = because.includes(measure);
              return (
                <tr key={measure} data-measure={measure} data-past={past}>
                  <th scope="row">
                    {name}
                    {past && <span className="badge">Past its ceiling</span>}
                  </th>
                  <td className="number" data-testid={`load-now-${measure}`}>
                    {now(measure)}
                  </td>
                  <td className="number" data-testid={`load-ceiling-${measure}`}>
                    {limit(measure)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
});

/** The last ten minutes: the spread of the two measures, and how requests were answered. */
const Totals = memo(function Totals({
  totals,
  inFlight,
}: {
  totals: Load["totals"];
  inFlight: Load["in_flight"];
}) {
  const times = totals.response_ms;
  const shares = totals.cpu_percent;
  return (
    <>
      <div className="scroll">
        <table className="load-table" data-testid="load-spread">
          <thead>
            <tr>
              <th scope="col">Over the last ten minutes</th>
              <th scope="col" className="number">
                Lowest
              </th>
              <th scope="col" className="number">
                Average
              </th>
              <th scope="col" className="number">
                Highest
              </th>
            </tr>
          </thead>
          <tbody>
            <tr data-measure="response_ms">
              <th scope="row">Time of an answer</th>
              <td className="number">{msText(times.low, "no answer yet")}</td>
              <td className="number">{msText(times.average, "no answer yet")}</td>
              <td className="number">{msText(times.high, "no answer yet")}</td>
            </tr>
            <tr data-measure="cpu_percent">
              <th scope="row">Share of one processor</th>
              <td className="number">{percentText(shares.low, "not known yet")}</td>
              <td className="number">{percentText(shares.average, "not known yet")}</td>
              <td className="number">{percentText(shares.high, "not known yet")}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <dl className="facts load-facts" data-testid="load-requests">
        <dt>Requests answered</dt>
        <dd data-testid="load-count-requests">{countText(totals.requests)}</dd>
        <dt>Answered well</dt>
        <dd data-testid="load-count-ok">{countText(totals.ok)}</dd>
        <dt>Not taken as asked</dt>
        <dd data-testid="load-count-not-accepted">{countText(totals.not_accepted)}</dd>
        <dt>Failed</dt>
        <dd data-testid="load-count-failed">{countText(totals.failed)}</dd>
        <dt>Answered as busy</dt>
        <dd data-testid="load-count-busy">{countText(totals.busy)}</dd>
        <dt>In flight now</dt>
        <dd data-testid="load-in-flight">{countText(inFlight.count)}</dd>
        <dt>The oldest has waited</dt>
        <dd data-testid="load-oldest">{waitText(inFlight.oldest_ms, "none is in flight")}</dd>
      </dl>
    </>
  );
});

/** An amount of the whole it is part of, `2.8 GB of 7.5 GB`, where both are known. */
function ofWhole(part: number | null, whole: number | null): string {
  const said = bytesText(part);
  return part === null || whole === null ? said : `${said} of ${bytesText(whole)}`;
}

/** The server's process, its host, and whether the background work is being done. */
const Host = memo(function Host({
  host,
  process,
  worker,
  startedAt,
}: {
  host: Load["host"];
  process: Load["process"];
  worker: Load["worker"];
  startedAt: string;
}) {
  const work = workerWords(worker);
  return (
    <dl className="facts load-facts" data-testid="load-host">
      <dt>Server started</dt>
      <dd>
        <Time at={startedAt} />
      </dd>
      <dt>Memory of the server's process</dt>
      <dd data-testid="load-process-memory">{bytesText(process.memory_bytes)}</dd>
      <dt>Memory of the host, used</dt>
      <dd data-testid="load-memory-used">
        {ofWhole(host.memory_used_bytes, host.memory_total_bytes)}
      </dd>
      <dt>Memory of the host, free</dt>
      <dd data-testid="load-memory-free">{bytesText(host.memory_free_bytes)}</dd>
      <dt>Space free where the inventory is kept</dt>
      <dd data-testid="load-disk-free">{ofWhole(host.disk_free_bytes, host.disk_total_bytes)}</dd>
      <dt>Processors of the host</dt>
      <dd data-testid="load-processors">{countText(host.processors)}</dd>
      <dt>Load of the host over the last minute</dt>
      <dd data-testid="load-average">{loadAverageText(host.load_1m)}</dd>
      <dt>Background work</dt>
      <dd data-testid="load-worker" data-worker={worker}>
        {work.notice ? <strong>{work.text}</strong> : work.text}
      </dd>
    </dl>
  );
});

/** The server's own measures, and the graph of its last ten minutes. */
export function ServerLoad() {
  const { load, failed } = useServerLoad();
  return (
    <section aria-labelledby="server-load" data-testid="load">
      <h2 id="server-load">The server's own measures</h2>
      {!load && !failed && <p role="status">Loading…</p>}
      {!load && <Problem error={failed?.error ?? null} />}
      {load && (
        <>
          <Since at={load.at} failed={failed} />
          {workerWords(load.worker).notice && (
            <p className="alert alert-warn" data-testid="load-worker-stopped">
              <strong>The background work is not running.</strong> Imports and bulk edits wait to be
              applied until it is started.
            </p>
          )}
          <State
            state={load.state}
            because={load.because}
            ceiling={load.ceiling}
            measures={load.measures}
          />
          <h3 id="server-load-window">The last ten minutes</h3>
          <Totals totals={load.totals} inFlight={load.in_flight} />
          <LoadGraph
            points={load.points}
            ceiling={load.ceiling}
            windowSeconds={load.window_seconds}
            stepSeconds={load.step_seconds}
          />
          <h3 id="server-load-host">The server and its host</h3>
          <Host
            host={load.host}
            process={load.process}
            worker={load.worker}
            startedAt={load.started_at}
          />
        </>
      )}
    </section>
  );
}
