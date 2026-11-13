import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { type ApiError, api } from "../api";
import { useAuth } from "../auth";
import { SelectField } from "../components/Field";
import { Pager } from "../components/Pager";
import { ApplyPreview, JobCounts, PreviewRows } from "../components/Preview";
import { Problem } from "../components/Problem";
import { Time } from "../components/Time";
import { toApiError, useLoad, useTitle } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import {
  ENTITIES,
  entityLabel,
  fileIdentity,
  fileType,
  guessEntity,
  isEntity,
  MODES,
  type Mode,
  modeLabel,
  previewQuery,
} from "../lib/imports";
import { countsText, type Job, type Preview, type StaleRow, statusLabel } from "../lib/preview";
import { fieldErrors } from "../lib/problems";
import { allows } from "../lib/roles";
import type { Entity } from "../lib/transfer";

const JOBS_PAGE = 20;

/** A file as it was sent for a preview, kept while the page is open to send it again. */
interface Sent {
  file: File;
  entity: Entity | "";
  mode: Mode | "";
  preview: Preview;
}

/**
 * Import: choose a file, see what it would do, apply it, and look at what was imported
 * before. A preview has an address of its own, `/import/<hid>`, so it can be come back to.
 */
export function Import() {
  const { hid = "" } = useParams();
  useTitle("Import");
  const { user } = useAuth();
  const navigate = useNavigate();
  const keys = useRef(new Keys());
  const [sent, setSent] = useState<Sent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [jobsTurn, setJobsTurn] = useState(0);
  const mayImport = allows(user.role, "inventory");

  /** Send a file to be previewed, and show the preview it becomes. */
  async function preview(file: File, entity: Entity | "", mode: Mode | "") {
    const type = fileType(file);
    if (type === null) {
      setError(
        toApiError(new Error("Choose a CSV file or a JSON file: its name ends in .csv or .json.")),
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // A file that was changed or moved after it was chosen cannot be read any more.
      // The browser says so when the file is touched; without this it would read as if
      // the server could not be reached.
      await file.slice(0, 1).arrayBuffer();
    } catch {
      setError(toApiError(new Error("The file can no longer be read. Choose it again.")));
      setBusy(false);
      return;
    }
    try {
      const made = await withKey(keys.current, fileIdentity(file, entity, mode), (idempotencyKey) =>
        api.upload("/api/v1/imports/preview", {
          file,
          type,
          query: previewQuery(entity, mode, file.name),
          idempotencyKey,
        }),
      );
      setSent({ file, entity, mode, preview: made });
      setJobsTurn((turn) => turn + 1);
      navigate(`/import/${encodeURIComponent(made.job.hid)}`);
    } catch (thrown) {
      setError(toApiError(thrown));
    } finally {
      setBusy(false);
    }
  }

  const mine = sent && sent.preview.job.hid === hid ? sent : null;
  return (
    <>
      <h1>Import</h1>
      {mayImport ? (
        <Upload busy={busy} error={error} onPreview={preview} />
      ) : (
        <p className="muted">
          Importing needs the Inventory role. The imports that were made are listed below.
        </p>
      )}
      {hid && (
        <OneJob
          key={hid}
          hid={hid}
          sent={mine}
          busy={busy}
          onChanged={() => setJobsTurn((turn) => turn + 1)}
          again={mine ? () => preview(mine.file, mine.entity, mine.mode) : undefined}
        />
      )}
      <PastJobs turn={jobsTurn} current={hid} />
    </>
  );
}

interface UploadProps {
  busy: boolean;
  error: ApiError | null;
  onPreview: (file: File, entity: Entity | "", mode: Mode | "") => void;
}

/** The form that sends a file: the file, the records it holds and the mode beside it. */
function Upload({ busy, error, onPreview }: UploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [entity, setEntity] = useState<Entity | "">("");
  const [mode, setMode] = useState<Mode | "">("");
  const known = ["entity", "mode"];
  const refused = fieldErrors(error, known).shown;

  function choose(chosen: File | null) {
    setFile(chosen);
    if (chosen && entity === "") setEntity(guessEntity(chosen.name));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (file) onPreview(file, entity, mode);
  }

  return (
    <section className="panel" aria-labelledby="import-file">
      <h2 id="import-file">Preview a file</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={error} shown={known} />
        <div className="fields">
          <div className="field">
            <label htmlFor="import-file-input">File</label>
            <input
              id="import-file-input"
              name="file"
              type="file"
              accept=".csv,.json,text/csv,application/json"
              disabled={busy}
              aria-describedby="import-file-hint"
              onChange={(event) => choose(event.target.files?.[0] ?? null)}
            />
            <p className="hint" id="import-file-hint">
              CSV with a header row, or JSON in its envelope. At most 20 MB and 100,000 rows.
            </p>
          </div>
          <SelectField
            label="Records"
            name="entity"
            value={entity}
            onChange={(next) => setEntity(isEntity(next) ? next : "")}
            disabled={busy}
            error={refused.entity}
            hint="What the file holds. A JSON file may say so itself."
          >
            <option value="">As the file says</option>
            {ENTITIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Mode"
            name="mode"
            value={mode}
            onChange={(next) => setMode(next === "create" || next === "upsert" ? next : "")}
            disabled={busy}
            error={refused.mode}
            hint="Create only refuses a row whose record exists already. Nothing is ever deleted."
          >
            <option value="">Create and update, or as a JSON file says</option>
            {MODES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={busy || !file}>
            Preview
          </button>
          {busy && (
            <span role="status" className="muted loading-late">
              Reading the file…
            </span>
          )}
        </p>
        <p className="hint">
          A preview changes nothing. It shows what every row would do, and is applied from there.
        </p>
      </form>
    </section>
  );
}

interface OneJobProps {
  hid: string;
  /** The file this preview was made from, when it was made on this page. */
  sent: Sent | null;
  busy: boolean;
  /** The job was applied, or failed: the list of jobs is out of date. */
  onChanged: () => void;
  again: (() => void) | undefined;
}

/** One stored preview: what it is, what it would do or did, and the button to apply it. */
function OneJob({ hid, sent, busy, onChanged, again }: OneJobProps) {
  const [turn, setTurn] = useState(0);
  const [stale, setStale] = useState<StaleRow[]>([]);
  const loaded = useLoad(`import ${hid}`, (signal) =>
    api.request("get", "/api/v1/imports/{hid}", { path: { hid }, signal }),
  );
  // The answer of the preview is shown at once; the job as the server has it follows.
  const job: Job | undefined = loaded.data ?? sent?.preview.job;
  const bulk = job?.source === "bulk";

  function changed() {
    setTurn((count) => count + 1);
    loaded.reload();
    onChanged();
  }

  return (
    <section aria-labelledby="import-job" data-testid="import-job" data-status={job?.status}>
      <h2 id="import-job">
        {job ? (bulk ? "Bulk edit" : `Preview of ${job.file_name ?? "a file"}`) : "Preview"}
      </h2>
      <Problem error={loaded.error} />
      {loaded.loading && !job && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {job && (
        <>
          <dl className="facts">
            <dt>Records</dt>
            <dd>{entityLabel(job.entity)}</dd>
            <dt>Mode</dt>
            <dd>{modeLabel(job.mode)}</dd>
            <dt>Status</dt>
            <dd data-testid="import-status">{statusLabel(job)}</dd>
            <dt>Made</dt>
            <dd>
              <Time at={job.created_at} /> by {job.created_by_name ?? "an account that is gone"}
            </dd>
            {job.applied_at && (
              <>
                <dt>Applied</dt>
                <dd>
                  <Time at={job.applied_at} />
                </dd>
              </>
            )}
            <dt>HID</dt>
            <dd className="mono">{job.hid}</dd>
          </dl>
          <JobCounts job={job} />
          <ApplyPreview
            job={job}
            noun={bulk ? ["item", "items"] : ["row", "rows"]}
            busy={busy}
            onApplied={changed}
            onOutOfDate={(rows) => {
              setStale(rows);
              changed();
            }}
            again={again}
            againHint={
              bulk
                ? "Make the bulk edit again from the grid of items."
                : "Choose the file again above to make a new preview."
            }
          />
          <PreviewRows job={job} preview={sent?.preview} stale={stale} turn={turn} />
        </>
      )}
    </section>
  );
}

/** The previews that were made, newest first: files, or bulk edits. */
function PastJobs({ turn, current }: { turn: number; current: string }) {
  const [source, setSource] = useState<Job["source"]>("file");
  const [offset, setOffset] = useState(0);
  const jobs = useLoad(`imports ${source} ${offset} ${turn}`, (signal) =>
    api.request("get", "/api/v1/imports", {
      query: { source, limit: JOBS_PAGE, offset },
      signal,
    }),
  );
  const items = jobs.data?.items ?? [];

  return (
    <section aria-labelledby="import-jobs">
      <h2 id="import-jobs">Past imports</h2>
      <div className="inline">
        <SelectField
          label="Show"
          name="source"
          value={source}
          onChange={(next) => {
            setSource(next === "bulk" ? "bulk" : "file");
            setOffset(0);
          }}
        >
          <option value="file">Imports of files</option>
          <option value="bulk">Bulk edits</option>
        </SelectField>
      </div>
      <Problem error={jobs.error} />
      {jobs.loading && !jobs.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {jobs.data && (
        <>
          <div className="scroll">
            <table data-testid="import-jobs">
              <caption className="visually-hidden">
                {source === "bulk" ? "Bulk edits" : "Imports of files"}, newest first
              </caption>
              <thead>
                <tr>
                  <th scope="col">Made</th>
                  <th scope="col">{source === "bulk" ? "Preview" : "File"}</th>
                  <th scope="col">Records</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Status</th>
                  <th scope="col">Rows</th>
                  <th scope="col">By</th>
                </tr>
              </thead>
              <tbody>
                {items.map((job) => (
                  <tr key={job.hid} aria-current={job.hid === current ? "true" : undefined}>
                    <td className="nowrap">
                      <Time at={job.created_at} />
                    </td>
                    <th scope="row">
                      <Link to={`/import/${encodeURIComponent(job.hid)}`}>
                        {job.file_name || (source === "bulk" ? "Bulk edit" : "A file with no name")}
                      </Link>
                      <span className="hid mono">{job.hid}</span>
                    </th>
                    <td>{entityLabel(job.entity)}</td>
                    <td>{modeLabel(job.mode)}</td>
                    <td>{statusLabel(job)}</td>
                    <td>{countsText(job)}</td>
                    <td>{job.created_by_name ?? <span className="muted">—</span>}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
                      {source === "bulk"
                        ? "No bulk edit has been previewed."
                        : "No file has been previewed."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={jobs.data.total}
            limit={JOBS_PAGE}
            offset={offset}
            noun={source === "bulk" ? "bulk edits" : "imports"}
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}
