// The server's own measures, on About, for everyone signed in (P-265, P-266, P-270 to
// P-273): its health in words, what it refuses and why, with the ceiling in force; the
// percentiles of the time of an answer over the last ten minutes beside the lowest, the
// average and the highest, and the requests counted by band of time; how the requests
// were answered; what is in flight; one graph; the process and its host; whether the
// background work is being done; the slowest requests; and who is active, and what each
// met.
//
// A person watches this while the server is in trouble, so watching it is cheap: one
// request of `GET /about/load` every five seconds while the page is in front, none while
// it is hidden, one at once on coming back, and never two at a time (`lib/watch.ts`).
// What is read is kept here and nowhere above, so nothing else of About is drawn again
// by the clock; each part below is drawn again only when its own numbers are other than
// they were, since a part that holds the same in a new answer is kept as it is (P-264),
// and a row of a table only when that row is another. The tables whose length changes,
// the slowest requests and the people, come last, so that a row more or less moves
// nothing that is read above them.

import { Fragment, memo, useEffect, useState } from "react";
import { api } from "../api";
import { ApiError } from "../api/client";
import { useAuth } from "../auth";
import { plural } from "../lib/format";
import { sameAnswer, toApiError } from "../lib/hooks";
import {
  type ActivePerson,
  bandCount,
  becauseWords,
  bytesText,
  clockText,
  countText,
  healthOfLoad,
  kept,
  type Load,
  loadAverageText,
  loadOf,
  type Measure,
  msText,
  noCeiling,
  percentText,
  personKey,
  requestText,
  type SlowRequest,
  stillAnswered,
  waitText,
  whoWords,
  whyNothingRefused,
  workerWords,
} from "../lib/load";
import { sentence } from "../lib/problems";
import { allows } from "../lib/roles";
import { bandHealth, bandLabels, healthWords, speedWords } from "../lib/serverHealth";
import { watchEvery } from "../lib/watch";
import { HealthShape } from "./HealthMark";
import { LoadGraph } from "./LoadGraph";
import { Problem } from "./Problem";
import { Time } from "./Time";
import { ValueLink } from "./ValueLink";

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
  { measure: "response_ms", name: "How long requests take: the 95th percentile" },
  { measure: "cpu_percent", name: "Processor time the server uses, of one processor" },
];

/** The health in words, what is refused and why, and the two measures with their ceilings. */
const Health = memo(function Health({
  health,
  refusing,
  because,
  ceiling,
  measures,
}: Pick<Load, "health" | "refusing" | "because" | "ceiling" | "measures">) {
  const said = healthOfLoad({ health, refusing });
  const few = whyNothingRefused({ health, refusing, ceiling });
  const now = (measure: Measure) =>
    measure === "response_ms"
      ? msText(measures.response_ms, "no request to read it from")
      : percentText(measures.cpu_percent);
  const limit = (measure: Measure) => {
    if (!(ceiling[measure] > 0)) return "not looked at";
    return measure === "response_ms" ? msText(ceiling[measure]) : percentText(ceiling[measure]);
  };
  return (
    <>
      {/* Said aloud when the health becomes another: the words are the same until then. */}
      <div role="status">
        <p
          className={`alert ${said && said.health === "good" && said.refusing === "nothing" ? "alert-ok" : "alert-warn"}`}
          data-testid="load-health"
          data-health={health}
          data-refusing={refusing}
        >
          {said ? (
            <>
              <HealthShape health={said.health} />{" "}
              <strong data-testid="load-health-words">{healthWords(said)}</strong>
              {said.refusing !== "nothing" &&
                ` ${speedWords(said.health)} ${stillAnswered(said.refusing)}`}
            </>
          ) : (
            <strong>The server did not say how it is.</strong>
          )}
          {becauseWords(because) && ` ${becauseWords(because)}`}
          {few && <span data-testid="load-few"> {few}</span>}
          {noCeiling(ceiling) && (
            <span data-testid="load-no-ceiling">
              {" "}
              No ceiling is set: the server refuses nothing, however slow it is.
            </span>
          )}
        </p>
      </div>
      <div className="scroll">
        <table className="load-table" data-testid="load-measures">
          <thead>
            <tr>
              <th scope="col">
                What the health is read from, over the last {ceiling.over_seconds} seconds
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
                <Fragment key={measure}>
                  <tr data-measure={measure} data-past={past}>
                    <th scope="row">
                      {name}
                      {measure === "response_ms" && (
                        <span className="muted" data-testid="load-measured">
                          {" "}
                          of {plural(measures.requests, "request")}
                        </span>
                      )}
                      {past && <span className="badge">The health stands on it</span>}
                    </th>
                    <td className="number" data-testid={`load-now-${measure}`}>
                      {now(measure)}
                    </td>
                    <td className="number" data-testid={`load-ceiling-${measure}`}>
                      {limit(measure)}
                    </td>
                  </tr>
                  {/* What is refused is decided by the reads alone, where there are enough
                      of them: a read is never refused for a change that was slow (P-272). */}
                  {measure === "response_ms" && (
                    <tr data-measure="reads_ms">
                      <th scope="row">
                        Of the reads alone
                        <span className="muted" data-testid="load-reads">
                          {" "}
                          of {countText(measures.reads)}: what is refused is decided by these, with{" "}
                          {countText(ceiling.fewest_requests)} or more
                        </span>
                      </th>
                      <td className="number" data-testid="load-now-reads_ms">
                        {msText(measures.reads_ms, "no read to read it from")}
                      </td>
                      <td className="number">{limit(measure)}</td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
});

/** The heading of a band of time: the shape and colour of its level, and its name from its bounds. */
function BandHeads({ labels }: { labels: readonly string[] }) {
  return (
    <>
      {labels.map((label, place) => (
        <th key={label} scope="col" className="number load-band" data-band={place}>
          <HealthShape health={bandHealth(place)} /> {label}
        </th>
      ))}
    </>
  );
}

/** The last ten minutes: the times, the bands, and how requests were answered. */
const Totals = memo(function Totals({
  totals,
  inFlight,
}: {
  totals: Load["totals"];
  inFlight: Load["in_flight"];
}) {
  const times = totals.response_ms;
  const shares = totals.cpu_percent;
  const labels = bandLabels(totals.bands.bounds_ms);
  const none = "no answer yet";
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
              <th scope="col" className="number">
                <abbr title="The 50th percentile, the median: half the requests took no longer">
                  p50
                </abbr>
              </th>
              <th scope="col" className="number">
                <abbr title="The 95th percentile: 95 requests in 100 took no longer">p95</abbr>
              </th>
              <th scope="col" className="number">
                <abbr title="The 99th percentile: 99 requests in 100 took no longer">p99</abbr>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr data-measure="response_ms">
              <th scope="row">Time of an answer</th>
              <td className="number">{msText(times.low, none)}</td>
              <td className="number">{msText(times.average, none)}</td>
              <td className="number">{msText(times.high, none)}</td>
              <td className="number" data-testid="load-p50">
                {msText(times.p50, none)}
              </td>
              <td className="number" data-testid="load-p95">
                {msText(times.p95, none)}
              </td>
              <td className="number" data-testid="load-p99">
                {msText(times.p99, none)}
              </td>
            </tr>
            <tr data-measure="cpu_percent">
              <th scope="row">Processor time, of one processor</th>
              <td className="number">{percentText(shares.low, "not known yet")}</td>
              <td className="number">{percentText(shares.average, "not known yet")}</td>
              <td className="number">{percentText(shares.high, "not known yet")}</td>
              <td colSpan={3} className="muted number">
                —
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted">
        The lowest, the average and the highest are of every answer. The percentiles are of the
        reads and the changes: reports, exports and previews, which are long by nature, are in none.
      </p>
      {labels.length > 0 && (
        <div className="scroll">
          <table className="load-table" data-testid="load-bands">
            <thead>
              <tr>
                <th scope="col">Reads and changes, by how long each took</th>
                <BandHeads labels={labels} />
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Requests in the last ten minutes</th>
                {labels.map((label, place) => (
                  <td key={label} className="number" data-testid={`load-band-${place}`}>
                    {countText(bandCount(totals.bands.counts, place))}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
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

/**
 * Who asked: the username, as a link to the account for an Admin and as text for anyone
 * else, as the audit trail names who made a change (P-240); a service token said as one;
 * and the rows that are of no one account in words.
 */
function Who({ who, admin }: { who: Parameters<typeof whoWords>[0]; admin: boolean }) {
  const { name, hid, note } = whoWords(who);
  return (
    <>
      {hid ? (
        <ValueLink kind="user" hid={hid} admin={admin}>
          {name}
        </ValueLink>
      ) : (
        name
      )}
      {note && <span className="muted"> ({note})</span>}
    </>
  );
}

/** One of the slowest requests. It is drawn again only when it is another. */
const SlowRow = memo(
  function SlowRow({ row, admin }: { row: SlowRequest; admin: boolean }) {
    return (
      <tr data-request={row.request_id}>
        <td>{clockText(row.at)}</td>
        <td data-testid="load-slow-who">
          <Who who={row.who} admin={admin} />
        </td>
        <td className="mono" data-testid="load-slow-request">
          {requestText(row)}
        </td>
        <td className="number">{msText(row.ms)}</td>
        <td className="number">{countText(row.status)}</td>
        <td>
          {/* One click takes the whole of it, to be copied and looked for in the log. */}
          <code className="load-request-id" data-testid="load-slow-id">
            {row.request_id}
          </code>
        </td>
      </tr>
    );
  },
  (was, now) => was.admin === now.admin && sameAnswer(was.row, now.row),
);

/** A table of slow requests, the slowest first, or that there is none. */
const Slowest = memo(function Slowest({
  rows,
  admin,
  testId,
  none,
}: {
  rows: readonly SlowRequest[];
  admin: boolean;
  testId: string;
  none: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="muted" data-testid={`${testId}-none`}>
        {none}
      </p>
    );
  }
  return (
    <div className="scroll">
      <table className="load-table" data-testid={testId}>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Who</th>
            <th scope="col">Request</th>
            <th scope="col" className="number">
              Time
            </th>
            <th scope="col" className="number">
              Status
            </th>
            <th scope="col">Request ID</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <SlowRow key={row.request_id} row={row} admin={admin} />
          ))}
        </tbody>
      </table>
    </div>
  );
});

/** One of the people. It is drawn again only when what it met is other than it was. */
const PersonRow = memo(
  function PersonRow({
    person,
    bands,
    admin,
  }: {
    person: ActivePerson;
    bands: number;
    admin: boolean;
  }) {
    return (
      <tr data-person={person.username ?? person.kind} data-kind={person.kind}>
        <th scope="row" data-testid="load-person-name">
          <Who who={person} admin={admin} />
        </th>
        <td className="number">{countText(person.requests)}</td>
        {Array.from({ length: bands }, (_, place) => place).map((place) => (
          <td key={place} className="number" data-band={place}>
            {countText(bandCount(person.bands, place))}
          </td>
        ))}
        <td className="number">{msText(person.slowest_ms, "none")}</td>
        <td className="number">{countText(person.busy)}</td>
        <td className="number">{countText(person.failed)}</td>
        <td>{clockText(person.last_at)}</td>
      </tr>
    );
  },
  (was, now) =>
    was.admin === now.admin && was.bands === now.bands && sameAnswer(was.person, now.person),
);

/** Who asked anything in the ten minutes, and what each met, whoever had it worst first. */
const People = memo(function People({
  people,
  bounds,
  admin,
}: {
  people: readonly ActivePerson[];
  bounds: readonly number[];
  admin: boolean;
}) {
  const labels = bandLabels(bounds);
  if (people.length === 0) {
    return (
      <p className="muted" data-testid="load-people-none">
        Nobody asked anything in the last ten minutes.
      </p>
    );
  }
  return (
    <div className="scroll">
      <table className="load-table wrap-heads" data-testid="load-people">
        <thead>
          <tr>
            <th scope="col">Who</th>
            <th scope="col" className="number">
              Requests
            </th>
            <BandHeads labels={labels} />
            <th scope="col" className="number">
              Slowest
            </th>
            <th scope="col" className="number">
              Answered as busy
            </th>
            <th scope="col" className="number">
              Failed
            </th>
            <th scope="col">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {people.map((person) => (
            <PersonRow
              key={personKey(person)}
              person={person}
              bands={labels.length}
              admin={admin}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
});

/** The server's own measures, and the graph of its last ten minutes. */
export function ServerLoad() {
  const { load, failed } = useServerLoad();
  const { user } = useAuth();
  const admin = allows(user.role, "admin");
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
          <Health
            health={load.health}
            refusing={load.refusing}
            because={load.because}
            ceiling={load.ceiling}
            measures={load.measures}
          />
          <h3 id="server-load-window">The last ten minutes</h3>
          <Totals totals={load.totals} inFlight={load.in_flight} />
          <LoadGraph
            points={load.points}
            ceiling={load.ceiling}
            bounds={load.totals.bands.bounds_ms}
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
          <h3 id="server-load-slowest">The slowest requests</h3>
          <p className="muted">
            The slowest reads and changes of the last ten minutes, the slowest first: each by its
            route, never by what was asked for. The request ID finds it in the server's log.
          </p>
          <Slowest
            rows={load.slowest}
            admin={admin}
            testId="load-slowest"
            none="No read or change was answered in the last ten minutes."
          />
          <h4 id="server-load-long">Long by nature</h4>
          <p className="muted">
            The slowest reports, exports and previews. They take long by what they are, and are in
            neither the health nor the percentiles.
          </p>
          <Slowest
            rows={load.slowest_long}
            admin={admin}
            testId="load-slowest-long"
            none="No report, export or preview was answered in the last ten minutes."
          />
          <h3 id="server-load-people">Who is active</h3>
          <p className="muted">
            Everyone who asked anything in the last ten minutes, and what each met, whoever had it
            worst first.
          </p>
          <People people={load.people} bounds={load.totals.bands.bounds_ms} admin={admin} />
        </>
      )}
    </section>
  );
}
