// A stored preview on a page: its counts, its rows with what each would change, and the
// button that applies it. An import of a file and a bulk edit are previews of the same
// kind, so both pages show them with what is here. An apply goes on in the background:
// the page shows how far it has got, and once it has ended, what it applied and the rows
// it left out, each with why. 0.9.19: a preview of more than a hundred rows is worked in
// the background too, and followed as an apply is, until it is shown (P-325).

import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { type ApiError, api } from "../api";
import { useAuth } from "../auth";
import { plural } from "../lib/format";
import { toApiError, useLoad } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import {
  appliedLabel,
  appliedText,
  applyBegun,
  changeText,
  firstPage,
  hasPreview,
  isOutcome,
  isPreviewing,
  isWorking,
  type Job,
  type LeftOut,
  leftOutCount,
  leftOutQuery,
  type Outcome,
  outcomeLabel,
  outcomeOptions,
  type Preview,
  type PreviewRow,
  previewedText,
  previewFailed,
  previewingText,
  progressText,
  ROWS_PAGE,
  reasonText,
  recordPath,
  refusedAtApply,
  rowsQuery,
  stoppedText,
} from "../lib/preview";
import { allows } from "../lib/roles";
import type { SortColumns } from "../lib/sort";
import { PREVIEW_ROWS_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";
import { SelectField } from "./Field";
import { Pager } from "./Pager";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

/** Give each line a key of its own, even when two lines read the same. */
function keyed(lines: readonly string[]): Array<{ key: string; line: string }> {
  const counts = new Map<string, number>();
  return lines.map((line) => {
    const count = (counts.get(line) ?? 0) + 1;
    counts.set(line, count);
    return { key: `${count} ${line}`, line };
  });
}

/**
 * The order the rows of a job are in until a header is clicked: a file's, or for a bulk
 * edit, which no file is behind, that of the items it changes (P-204).
 */
function inOrder(job: Job): string {
  return job.source === "bulk" ? "in the order of the items" : "in the order of the file";
}

/**
 * How many rows of a job the preview found to create, to update, unchanged and rejected.
 * 0.9.6: a bulk edit creates nothing, and does not say it would (P-204). 0.9.19: nothing
 * while it is being previewed, or when its preview failed (P-325).
 */
export function JobCounts({ job }: { job: Job }) {
  if (!hasPreview(job)) return null;
  const all: Array<[name: string, label: string, count: number]> = [
    ["created", "To create", job.created],
    ["updated", "To update", job.updated],
    ["unchanged", "Unchanged", job.unchanged],
    ["rejected", "Rejected", job.rejected],
  ];
  const counts = job.source === "bulk" ? all.filter(([name]) => name !== "created") : all;
  const said = counts.map(([, label, count]) => `${count} ${label.toLowerCase()}`).join(", ");
  return (
    <dl className="counts" data-testid="preview-counts" aria-label={`As previewed: ${said}`}>
      {counts.map(([name, label, count]) => (
        <div key={name} data-count={name} className={count > 0 ? undefined : "muted"}>
          <dt>{label}</dt>
          <dd>{count}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * What the apply has done so far: how many rows it has worked of all of them, how many
 * it applied, how many it left out as changed since the preview, and how many it refused.
 */
export function ApplyCounts({ job }: { job: Job }) {
  if (!applyBegun(job)) return null;
  const counts: Array<[name: string, label: string, count: number]> = [
    ["applied", "Applied", job.applied],
    ["stale", "Changed since the preview", job.stale],
    ["refused", "Refused", refusedAtApply(job)],
  ];
  return (
    <dl className="counts" data-testid="apply-counts" aria-label="What the apply did">
      <div data-count="worked">
        <dt>Worked</dt>
        <dd>
          {job.rows_done} <span className="muted">of {job.row_count}</span>
        </dd>
      </div>
      {counts.map(([name, label, count]) => (
        <div key={name} data-count={name} className={count > 0 ? undefined : "muted"}>
          <dt>{label}</dt>
          <dd>{count}</dd>
        </div>
      ))}
    </dl>
  );
}

// The columns of a preview's rows that the server does not sort by: their cells are
// composed here from lists. Each is sorted in the browser by what its cell shows, the
// lines of the cell as one text, and only while the table holds every row.
const LOCAL_COLUMNS: SortColumns<PreviewRow> = {
  changes: (row) => row.changes.map(changeText).join("; "),
  reasons: (row) =>
    [...row.applied_reasons.map(reasonText), ...row.reasons.map(reasonText), ...row.notes].join(
      "; ",
    ),
  why: (row) => row.applied_reasons.map(reasonText).join("; "),
};

interface PreviewRowsProps {
  job: Job;
  /** The answer the preview was made with, which holds the first rows already. */
  preview?: Preview | null | undefined;
  /** Change it to read the rows again, as after an apply. */
  turn?: number;
}

/**
 * The rows of a preview, a page at a time, all of them or those of one outcome. Once an
 * apply has begun, each row also says what the apply did with it. 0.9.19: none while the
 * job is being previewed, when the server lists none, or when its preview failed; once it
 * is previewed they are read, the first of them too (P-325).
 */
export function PreviewRows(props: PreviewRowsProps) {
  return hasPreview(props.job) ? <RowsOfPreview {...props} /> : null;
}

function RowsOfPreview({ job, preview, turn = 0 }: PreviewRowsProps) {
  const [outcome, setOutcome] = useState<Outcome | "">("");
  const [offset, setOffset] = useState(0);
  // The server pages the rows and sorts them, over every row and not the page on show: a
  // header asks for the rows in its order, from the first page.
  const sort = useServerSort<PreviewRow>({
    fields: PREVIEW_ROWS_SORT,
    local: LOCAL_COLUMNS,
    onChange: () => setOffset(0),
  });
  const rows = sort.held(
    useLoad(`rows ${job.hid} ${outcome} ${offset} ${turn} ${sort.param ?? ""}`, async (signal) => {
      // The rows that the preview's own answer holds are in the order of the file: they
      // serve only while the server is asked for no other order.
      const held =
        turn === 0 && sort.param === undefined ? firstPage(preview, outcome, offset) : null;
      if (held) return held;
      return api.request("get", "/api/v1/imports/{hid}/rows", {
        path: { hid: job.hid },
        query: {
          ...rowsQuery(outcome, offset),
          ...sort.query,
        },
        signal,
      });
    }),
  );
  const holdsAll = rows.data !== undefined && rows.data.items.length === rows.data.total;
  const applying = applyBegun(job);

  return (
    <section aria-labelledby={`rows-${job.hid}`}>
      <h3 id={`rows-${job.hid}`}>Rows</h3>
      <div className="inline">
        <SelectField
          label="Show"
          name="outcome"
          value={outcome}
          onChange={(next) => {
            setOutcome(isOutcome(next) ? next : "");
            setOffset(0);
          }}
        >
          {outcomeOptions(job).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <Problem error={rows.error} />
      {rows.loading && !rows.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {rows.data && (
        <>
          <div className="scroll">
            <table className="preview-rows" data-testid="preview-rows">
              <caption className="visually-hidden">
                What each row would do, {inOrder(job)} until a header is clicked
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("row", holdsAll)} column="row">
                    Row
                  </SortTh>
                  <SortTh sort={sort.header("record", holdsAll)} column="record">
                    Record
                  </SortTh>
                  <SortTh sort={sort.header("outcome", holdsAll)} column="outcome">
                    Outcome
                  </SortTh>
                  {applying && (
                    <SortTh sort={sort.header("applied", holdsAll)} column="applied">
                      Applied as
                    </SortTh>
                  )}
                  <SortTh sort={sort.header("changes", holdsAll)} column="changes">
                    Before → after
                  </SortTh>
                  <SortTh sort={sort.header("reasons", holdsAll)} column="reasons">
                    Reasons and notes
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(rows.data.items, holdsAll).map((row) => (
                  <Row key={row.row} row={row} entity={job.entity} applying={applying} />
                ))}
                {rows.data.items.length === 0 && (
                  <tr>
                    <td colSpan={applying ? 6 : 5} className="muted">
                      {outcome === "" ? "There are no rows." : "No row has this outcome."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={rows.data.total}
            limit={ROWS_PAGE}
            offset={offset}
            noun="rows"
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}

function Row({
  row,
  entity,
  applying,
}: {
  row: PreviewRow;
  entity: string;
  /** Whether the apply has begun, and the row says what it did. */
  applying: boolean;
}) {
  const path = recordPath(entity, row.record_hid);
  const stale = row.applied_outcome === "stale";
  return (
    <tr
      data-row={row.row}
      data-outcome={row.outcome}
      data-applied={row.applied_outcome ?? undefined}
      data-stale={stale ? "true" : undefined}
    >
      <td>{row.row}</td>
      <td>
        {path ? <Link to={path}>{row.key || row.record_hid}</Link> : row.key}
        {row.record_hid && <span className="hid mono">{row.record_hid}</span>}
      </td>
      <td className="nowrap">
        <span className={`outcome outcome-${row.outcome}`}>{outcomeLabel(row.outcome)}</span>
      </td>
      {applying && (
        <td className="nowrap">
          {row.applied_outcome ? (
            <span className={`outcome outcome-${row.applied_outcome}`}>
              {appliedLabel(row.applied_outcome)}
            </span>
          ) : (
            <span className="muted">Not yet</span>
          )}
        </td>
      )}
      <td>
        {row.changes.length > 0 && (
          <ul className="changes">
            {row.changes.map((change) => (
              <li key={change.field} data-field={change.field}>
                {changeText(change)}
              </li>
            ))}
          </ul>
        )}
      </td>
      <td>
        {(row.applied_reasons.length > 0 || row.reasons.length > 0 || row.notes.length > 0) && (
          <ul className="changes">
            {keyed(row.applied_reasons.map(reasonText)).map(({ key, line }) => (
              <li key={`applied ${key}`} className="reason">
                {line}
              </li>
            ))}
            {keyed(row.reasons.map(reasonText)).map(({ key, line }) => (
              <li key={`reason ${key}`} className="reason">
                {line}
              </li>
            ))}
            {keyed(row.notes).map(({ key, line }) => (
              <li key={`note ${key}`}>{line}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

const LEFT_OUT_TITLES: Readonly<Record<LeftOut, string>> = {
  stale: "Left out as changed since the preview",
  rejected: "Refused at the apply",
};

const LEFT_OUT_ABOUT: Readonly<Record<LeftOut, string>> = {
  stale:
    "Somebody changed the record of each of these rows after the preview was made, so the row was not applied, and the rest went on. A row like this is applied by previewing it again.",
  rejected:
    "The rules refused these rows when the apply came to them: a row the preview rejected and that was left out on purpose, or one that rested on a row that was not applied.",
};

interface LeftOutRowsProps {
  job: Job;
  outcome: LeftOut;
  /** Change it to read the rows again. */
  turn?: number;
}

/** The rows an apply left out of one kind, each with why, a page at a time. */
export function LeftOutRows({ job, outcome, turn = 0 }: LeftOutRowsProps) {
  const [offset, setOffset] = useState(0);
  const sort = useServerSort<PreviewRow>({
    fields: PREVIEW_ROWS_SORT,
    local: LOCAL_COLUMNS,
    onChange: () => setOffset(0),
  });
  const count = leftOutCount(job, outcome);
  const rows = sort.held(
    useLoad(
      `left out ${job.hid} ${outcome} ${offset} ${turn} ${count} ${sort.param ?? ""}`,
      (signal) =>
        api.request("get", "/api/v1/imports/{hid}/rows", {
          path: { hid: job.hid },
          query: { ...leftOutQuery(outcome, offset), ...sort.query },
          signal,
        }),
    ),
  );
  const holdsAll = rows.data !== undefined && rows.data.items.length === rows.data.total;
  const id = `left-out-${outcome}-${job.hid}`;

  return (
    <section aria-labelledby={id} data-testid={`left-out-${outcome}`}>
      <h3 id={id}>
        {LEFT_OUT_TITLES[outcome]} ({count})
      </h3>
      <p className="hint">{LEFT_OUT_ABOUT[outcome]}</p>
      <Problem error={rows.error} />
      {rows.loading && !rows.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {rows.data && (
        <>
          <div className="scroll">
            <table className="preview-rows">
              <caption className="visually-hidden">
                {LEFT_OUT_TITLES[outcome]}, {inOrder(job)} until a header is clicked
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("row", holdsAll)} column="row">
                    Row
                  </SortTh>
                  <SortTh sort={sort.header("record", holdsAll)} column="record">
                    Record
                  </SortTh>
                  <SortTh sort={sort.header("outcome", holdsAll)} column="outcome">
                    Previewed as
                  </SortTh>
                  <SortTh sort={sort.header("why", holdsAll)} column="why">
                    Why
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(rows.data.items, holdsAll).map((row) => {
                  const path = recordPath(job.entity, row.record_hid);
                  return (
                    <tr key={row.row} data-row={row.row} data-applied={outcome}>
                      <td>{row.row}</td>
                      <td>
                        {path ? <Link to={path}>{row.key || row.record_hid}</Link> : row.key}
                        {row.record_hid && <span className="hid mono">{row.record_hid}</span>}
                      </td>
                      <td className="nowrap">{outcomeLabel(row.outcome)}</td>
                      <td>
                        <ul className="changes">
                          {keyed(row.applied_reasons.map(reasonText)).map(({ key, line }) => (
                            <li key={key} className="reason">
                              {line}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  );
                })}
                {rows.data.items.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No row was left out so.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={rows.data.total}
            limit={ROWS_PAGE}
            offset={offset}
            noun="rows"
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}

/** The rows an apply that has ended left out, of each kind it left any out of. */
export function LeftOutOf({ job, turn = 0 }: { job: Job; turn?: number }) {
  if (!applyBegun(job) || isWorking(job)) return null;
  return (
    <>
      {job.stale > 0 && <LeftOutRows job={job} outcome="stale" turn={turn} />}
      {refusedAtApply(job) > 0 && <LeftOutRows job={job} outcome="rejected" turn={turn} />}
    </>
  );
}

/**
 * 0.9.19: a block that is shown while a preview or an apply goes on, and goes when it
 * ends. Where the keyboard was in it, on its link, it is not lost to the page with it:
 * it is put on the first button of the preview left, or on the preview itself (P-325).
 */
function WhileUnderWay({ testId, children }: { testId: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const block = ref.current;
    // Run as the block goes, while it is still on the page.
    return () => {
      if (!block?.contains(document.activeElement)) return;
      const box = block.closest<HTMLElement>(".apply-preview");
      requestAnimationFrame(() => {
        const now = document.activeElement;
        if (!box?.isConnected || (now !== null && now !== document.body)) return;
        const next = box.querySelector<HTMLElement>("button:not(:disabled)") ?? box;
        next.focus({ preventScroll: true });
      });
    };
  }, []);
  return (
    <div ref={ref} className="alert alert-info" data-testid={testId}>
      {children}
    </div>
  );
}

interface ApplyPreviewProps {
  job: Job;
  /** What the rows are, one and many: "row", "rows"; "item", "items". */
  noun?: [one: string, many: string];
  /** The server took the apply, or the resume: the job as it answered, to be followed. */
  onStarted: (job: Job) => void;
  /** Make the preview again from what it was made from. Left out when that is gone. */
  again?: (() => void) | undefined;
  /** What to do for a new preview, when it cannot be made from here. */
  againHint: string;
  /** Where else the preview and the apply can be followed, as the job's page among the imports. */
  followAt?: string | undefined;
  busy?: boolean;
}

/**
 * Apply a preview, and follow the apply. A preview with rejected rows is not applied as
 * it is: the reader chooses to apply the rest, or goes back. The apply goes on in the
 * background, and this says how far it has got; once it has ended, what it applied, or
 * why it stopped, with the button that resumes it. 0.9.19: a preview in the background
 * is followed here too, with nothing to apply until it has come, and a preview that
 * failed says why and is made again (P-325).
 */
export function ApplyPreview(props: ApplyPreviewProps) {
  const { job, noun = ["row", "rows"], onStarted, again, againHint, followAt } = props;
  const { user } = useAuth();
  const keys = useRef(new Keys());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const working = busy || props.busy === true;
  const rest = job.row_count - job.rejected;
  const mayApply = allows(user.role, "inventory");
  // Whether the preview was followed here to its end, which is then said, once, to
  // whoever listens: the status before is kept, and the change seen as it renders.
  const [before, setBefore] = useState(job.status);
  const [arrived, setArrived] = useState(false);
  if (before !== job.status) {
    setBefore(job.status);
    setArrived(before === "previewing");
  }

  /** Ask for the apply, or for a stopped one to go on: the answer is the job, at once. */
  async function apply(skipRejected: boolean) {
    const options = {
      path: { hid: job.hid },
      query: skipRejected ? { skip_rejected: true } : {},
    };
    setBusy(true);
    setError(null);
    try {
      const started = await withKey(
        keys.current,
        `apply ${job.hid} ${job.status} ${job.rows_done} ${skipRejected}`,
        (idempotencyKey) =>
          job.source === "bulk"
            ? api.request("post", "/api/v1/items/bulk-update/{hid}/apply", {
                ...options,
                idempotencyKey,
              })
            : api.request("post", "/api/v1/imports/{hid}/apply", { ...options, idempotencyKey }),
      );
      onStarted(started);
    } catch (thrown) {
      setError(toApiError(thrown));
    } finally {
      setBusy(false);
    }
  }

  const againButton = (label: string) =>
    again ? (
      <button type="button" onClick={again} disabled={working}>
        {label}
      </button>
    ) : null;

  return (
    <div className="apply-preview" data-testid="apply" data-status={job.status} tabIndex={-1}>
      <Problem error={error} />
      <div className="live" role="status" aria-live="polite">
        {isPreviewing(job) && (
          <WhileUnderWay testId="preview-progress">
            <p>
              <strong>Being previewed.</strong>{" "}
              <span data-testid="preview-progress-text">{previewingText(job, noun)}</span>.
            </p>
            <progress
              max={Math.max(job.row_count, 1)}
              value={job.rows_previewed}
              aria-label="How far the preview has got"
            />
            <p className="hint">
              It goes on in the background, after what was asked for before it: this page may be
              left and come back to. Nothing is offered to apply until every row is previewed.
              {followAt && (
                <>
                  {" "}
                  It is also followed on <Link to={followAt}>its page among the imports</Link>.
                </>
              )}
            </p>
          </WhileUnderWay>
        )}
        {arrived && job.status === "previewed" && (
          <p className="visually-hidden" data-testid="preview-arrived">
            {previewedText(job)}.
          </p>
        )}
        {isWorking(job) && (
          <WhileUnderWay testId="apply-progress">
            <p>
              <strong>
                {job.status === "queued" ? "Waiting to be applied, in its turn." : "Being applied."}
              </strong>{" "}
              <span data-testid="apply-progress-text">{progressText(job, noun)}</span>.
            </p>
            <progress
              max={Math.max(job.row_count, 1)}
              value={job.rows_done}
              aria-label="How far the apply has got"
            />
            <p className="hint">
              It goes on in the background: this page may be left and come back to.
              {followAt && (
                <>
                  {" "}
                  It is also followed on <Link to={followAt}>its page among the imports</Link>.
                </>
              )}
            </p>
          </WhileUnderWay>
        )}
        {job.status === "applied" && (
          <div
            className="alert alert-ok"
            data-testid="preview-applied"
            data-applied={job.applied}
            data-stale={job.stale}
            data-refused={refusedAtApply(job)}
          >
            <p>Applied: {appliedText(job, noun)}.</p>
            {job.stale > 0 && mayApply && (
              <p>
                {againButton("Preview again")}{" "}
                <span className="hint">
                  {again
                    ? "The rows changed since the preview are applied by previewing them again."
                    : againHint}
                </span>
              </p>
            )}
          </div>
        )}
      </div>
      <div className="live" aria-live="assertive" aria-atomic="true">
        {job.status === "stopped" && (
          <div className="alert alert-error" data-testid="preview-stopped">
            <p>
              <strong>The apply stopped partway.</strong>{" "}
              <span data-testid="apply-failure">
                {job.failure || "The server did not say why."}
              </span>
            </p>
            <p>
              {stoppedText(job, noun)}. What was applied stays applied. Resumed, it goes on from the
              first row it had not applied, and nothing is applied twice.
            </p>
            {mayApply ? (
              <p className="actions">
                <button
                  type="button"
                  className="primary"
                  onClick={() => apply(false)}
                  disabled={working}
                >
                  Resume the apply
                </button>
              </p>
            ) : (
              <p className="muted">Resuming it needs the Inventory role.</p>
            )}
          </div>
        )}
        {job.status === "failed" && (
          <div
            className="alert alert-error"
            data-testid="preview-failed"
            data-whole={previewFailed(job) ? "false" : "true"}
          >
            {previewFailed(job) ? (
              // 0.9.19: a preview that failed in the background kept nothing (P-325).
              <p>
                <strong>The preview failed, and nothing was applied.</strong>{" "}
                <span data-testid="preview-failure">
                  {job.failure || "The server did not say why."}
                </span>
              </p>
            ) : (
              <p>
                <strong>Nothing was applied.</strong>{" "}
                {job.failure || "A record was changed after this preview was made."}
              </p>
            )}
            {mayApply && <p>{againButton("Preview again") ?? againHint}</p>}
          </div>
        )}
      </div>
      {job.status === "previewed" &&
        (!mayApply ? (
          <p className="muted">This preview has not been applied.</p>
        ) : job.rejected > 0 ? (
          <div className="alert alert-info">
            <p>
              <strong>{plural(job.rejected, noun[0], noun[1])} rejected.</strong> A preview with
              rejected rows is not applied as it is. Correct them and preview again, or apply the
              rest and leave them out.
            </p>
            <p className="actions">
              <button
                type="button"
                className="primary"
                onClick={() => apply(true)}
                disabled={working || rest === 0}
              >
                Apply the other {plural(rest, noun[0], noun[1])}
              </button>
            </p>
          </div>
        ) : (
          <p className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => apply(false)}
              disabled={working}
            >
              Apply {plural(job.row_count, noun[0], noun[1])}
            </button>
          </p>
        ))}
    </div>
  );
}
