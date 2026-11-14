// A stored preview on a page: its counts, its rows with what each would change, and the
// button that applies it. An import of a file and a bulk edit are previews of the same
// kind, so both pages show them with what is here.

import { useRef, useState } from "react";
import { Link } from "react-router";
import { type ApiError, api } from "../api";
import { useAuth } from "../auth";
import { plural } from "../lib/format";
import { toApiError, useLoad } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import {
  changeText,
  countsText,
  firstPage,
  isOutcome,
  isOutOfDate,
  type Job,
  type Outcome,
  outcomeLabel,
  outcomeOptions,
  type Preview,
  type PreviewRow,
  ROWS_PAGE,
  reasonText,
  recordPath,
  rowsQuery,
  type StaleRow,
  staleRows,
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

/** How many rows of a job create, update, change nothing and are rejected. */
export function JobCounts({ job }: { job: Job }) {
  const done = job.status === "applied";
  const counts: Array<[name: string, label: string, count: number]> = [
    ["created", done ? "Created" : "To create", job.created],
    ["updated", done ? "Updated" : "To update", job.updated],
    ["unchanged", "Unchanged", job.unchanged],
    ["rejected", "Rejected", job.rejected],
  ];
  return (
    <dl className="counts" data-testid="preview-counts" aria-label={countsText(job)}>
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
  reasons: (row) => [...row.reasons.map(reasonText), ...row.notes].join("; "),
};

interface PreviewRowsProps {
  job: Job;
  /** The answer the preview was made with, which holds the first rows already. */
  preview?: Preview | null | undefined;
  /** The rows that stood in the way of an apply, to be marked. */
  stale?: readonly StaleRow[];
  /** Change it to read the rows again, as after an apply. */
  turn?: number;
}

/** The rows of a preview, a page at a time, all of them or those of one outcome. */
export function PreviewRows({ job, preview, stale = [], turn = 0 }: PreviewRowsProps) {
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
  const inTheWay = new Map(stale.map((entry) => [entry.row, entry.message]));
  const holdsAll = rows.data !== undefined && rows.data.items.length === rows.data.total;

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
                What each row would do, in the order of the file until a header is clicked
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
                  <Row key={row.row} row={row} entity={job.entity} stale={inTheWay.get(row.row)} />
                ))}
                {rows.data.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
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
  stale,
}: {
  row: PreviewRow;
  entity: string;
  stale: string | undefined;
}) {
  const path = recordPath(entity, row.record_hid);
  return (
    <tr data-row={row.row} data-outcome={row.outcome} data-stale={stale ? "true" : undefined}>
      <td>{row.row}</td>
      <td>
        {path ? <Link to={path}>{row.key || row.record_hid}</Link> : row.key}
        {row.record_hid && <span className="hid mono">{row.record_hid}</span>}
      </td>
      <td className="nowrap">
        <span className={`outcome outcome-${row.outcome}`}>{outcomeLabel(row.outcome)}</span>
        {stale && <span className="badge">Changed since</span>}
      </td>
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
        {(row.reasons.length > 0 || row.notes.length > 0) && (
          <ul className="changes">
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

interface ApplyPreviewProps {
  job: Job;
  /** What the rows are, one and many: "row", "rows"; "item", "items". */
  noun?: [one: string, many: string];
  /** The apply went through. The job is as it is now. */
  onApplied: (job: Job) => void;
  /** The apply was refused because records changed. The job has failed, and these rows were in the way. */
  onOutOfDate: (rows: StaleRow[]) => void;
  /** Make the preview again from what it was made from. Left out when that is gone. */
  again?: (() => void) | undefined;
  /** What to do for a new preview, when it cannot be made from here. */
  againHint: string;
  busy?: boolean;
}

/**
 * Apply a preview. A preview with rejected rows is not applied as it is: the reader
 * chooses to apply the rest, or goes back. When a record has changed since the preview
 * was made, nothing is applied, and the rows in the way are named.
 */
export function ApplyPreview(props: ApplyPreviewProps) {
  const { job, noun = ["row", "rows"], onApplied, onOutOfDate, again, againHint } = props;
  const { user } = useAuth();
  const keys = useRef(new Keys());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [applied, setApplied] = useState(false);
  const stale = staleRows(error);
  const outOfDate = isOutOfDate(error);
  const working = busy || props.busy === true;
  const rest = job.row_count - job.rejected;

  async function apply(skipRejected: boolean) {
    const options = {
      path: { hid: job.hid },
      query: skipRejected ? { skip_rejected: true } : {},
    };
    setBusy(true);
    setError(null);
    try {
      const done = await withKey(
        keys.current,
        `apply ${job.hid} ${skipRejected}`,
        (idempotencyKey) =>
          job.source === "bulk"
            ? api.request("post", "/api/v1/items/bulk-update/{hid}/apply", {
                ...options,
                idempotencyKey,
              })
            : api.request("post", "/api/v1/imports/{hid}/apply", { ...options, idempotencyKey }),
      );
      setApplied(true);
      onApplied(done);
    } catch (thrown) {
      const refusal = toApiError(thrown);
      setError(refusal);
      // The job has failed on the server: the page reads it again, and marks the rows.
      if (isOutOfDate(refusal)) onOutOfDate(staleRows(refusal));
    } finally {
      setBusy(false);
    }
  }

  const failed = job.status === "failed" || outOfDate;
  return (
    <div className="apply-preview">
      <Problem error={outOfDate ? null : error} />
      <div className="live" aria-live="assertive" aria-atomic="true">
        {failed && (
          <div className="alert alert-error" data-testid="preview-out-of-date">
            <p>
              <strong>Nothing was applied.</strong>{" "}
              {stale.length > 0
                ? "A record was changed by somebody after this preview was made. The rows in the way:"
                : job.failure || "A record was changed after this preview was made."}
            </p>
            {stale.length > 0 && (
              <ul>
                {stale.map((entry) => (
                  <li key={entry.row} data-row={entry.row}>
                    {entry.message}
                  </li>
                ))}
              </ul>
            )}
            {allows(user.role, "inventory") &&
              (again ? (
                <p>
                  <button type="button" className="primary" onClick={again} disabled={working}>
                    Preview again
                  </button>
                </p>
              ) : (
                <p>{againHint}</p>
              ))}
          </div>
        )}
      </div>
      <div className="live" role="status" aria-live="polite">
        {(applied || job.status === "applied") && (
          <p className="alert alert-ok" data-testid="preview-applied">
            Applied: {countsText({ ...job, status: "applied" })}.
          </p>
        )}
      </div>
      {job.status === "previewed" &&
        !outOfDate &&
        !applied &&
        (!allows(user.role, "inventory") ? (
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
