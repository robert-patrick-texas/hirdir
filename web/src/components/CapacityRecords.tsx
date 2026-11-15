// The capacity balance over time: the server records it by itself each Monday, and a
// person may record it again at any time, which replaces the record of that week. A
// saved week's demand and supply may be corrected, with a note that says why, and a
// record that was a mistake is removed. The trend is drawn from the records, and the
// records are listed beneath it, a page at a time, as the server sorts them.

import { type FormEvent, useRef, useState } from "react";
import { api, type Schemas } from "../api";
import { measureText } from "../lib/capacity";
import { useAction, useLoad } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import { EVERY } from "../lib/lists";
import { canonicalDecimal } from "../lib/patch";
import { fieldErrors } from "../lib/problems";
import { CAPACITY_RECORDS_SORT } from "../lib/tableSorts";
import type { CapacityRecord } from "../lib/trend";
import { useServerSort } from "../lib/useServerSort";
import { TrendGraph } from "./CapacityTrend";
import { ConfirmButton } from "./ConfirmButton";
import { TextAreaField, TextField } from "./Field";
import { Pager } from "./Pager";
import { Notice, Problem } from "./Problem";
import { SortTh } from "./SortTh";
import { Time } from "./Time";

const RECORDS_PAGE = 20;

interface CapacityTrendProps {
  /** Whether the reader may record, correct and remove: the Inventory role. */
  mayEdit: boolean;
}

/** Capacity → the balance over time: the graph, recording it now, and the records. */
export function CapacityTrend({ mayEdit }: CapacityTrendProps) {
  const [turn, setTurn] = useState(0);
  const [done, setDone] = useState("");
  // The graph has every week, the latest of them if there are ever more than a page.
  const trend = useLoad(`capacity-trend ${turn}`, (signal) =>
    api.request("get", "/api/v1/capacity-records", {
      query: { sort: ["-week_of"], limit: EVERY },
      signal,
    }),
  );

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
  }

  return (
    <section aria-labelledby="capacity-trend" data-testid="capacity-trend">
      <h2 id="capacity-trend">The balance over time</h2>
      <p>
        The server records the balance of the whole installation by itself each Monday just after
        midnight, one record to a week. Recorded again by hand, it replaces that week&apos;s record,
        so a change made in the course of a week shows in its point. A week&apos;s demand and supply
        may be corrected, with a note that says why.
      </p>
      <Notice text={done} />
      <Problem error={trend.error} />
      {trend.loading && !trend.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {trend.data && <TrendGraph records={trend.data.items} />}
      {mayEdit && <RecordNow onRecorded={changed} />}
      <Records mayEdit={mayEdit} turn={turn} onChanged={changed} />
    </section>
  );
}

/** Record the balance as it is now, in place of this week's record. */
function RecordNow({ onRecorded }: { onRecorded: (text: string) => void }) {
  const [note, setNote] = useState("");
  const action = useAction();
  const keys = useRef(new Keys());
  const refused = fieldErrors(action.error, ["note"]).shown;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = { note: note.trim() === "" ? null : note.trim() };
    const result = await action.run(() =>
      withKey(keys.current, `record ${body.note ?? ""}`, (idempotencyKey) =>
        api.request("post", "/api/v1/capacity-records", { body, idempotencyKey }),
      ),
    );
    if (result.ok) {
      setNote("");
      onRecorded(`The balance was recorded for the week of ${result.value.week_of}.`);
    }
  }

  return (
    <form onSubmit={submit} className="panel stack" noValidate aria-label="Record the balance">
      <Problem error={action.error} shown={["note"]} />
      <div className="inline">
        <TextField
          label="Note"
          name="record-note"
          value={note}
          onChange={setNote}
          maxLength={2000}
          error={refused.note}
          hint="Optional: why it is recorded again, as a contractor who started this week."
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Record the balance now
          </button>
        </p>
      </div>
    </form>
  );
}

// The headers of the records' table, by the names the sort fields have.
const COLUMNS: ReadonlyArray<[column: string, label: string, number: boolean]> = [
  ["week", "Week of", false],
  ["recorded", "Recorded", false],
  ["demand", "Demand", true],
  ["supply", "Supply", true],
  ["balance", "Balance", true],
  ["coverage", "Coverage", true],
  ["drafts_demand", "Demand with drafts", true],
  ["drafts_supply", "Supply with drafts", true],
  ["drafts_balance", "Balance with drafts", true],
  ["drafts_coverage", "Coverage with drafts", true],
  ["adjusted", "Corrected", false],
  ["note", "Note", false],
];

interface RecordsProps {
  mayEdit: boolean;
  turn: number;
  onChanged: (text: string) => void;
}

// The order of the table until a header is clicked: the latest week first, where the
// route by itself, as the graph reads it, gives the oldest first.
const NEWEST_FIRST = ["-week_of"];

/** The records, a page at a time, the newest week first until a header is clicked. */
function Records({ mayEdit, turn, onChanged }: RecordsProps) {
  const [offset, setOffset] = useState(0);
  const [correcting, setCorrecting] = useState<CapacityRecord | null>(null);
  const removing = useAction();
  const sort = useServerSort<CapacityRecord>({
    fields: CAPACITY_RECORDS_SORT,
    onChange: () => setOffset(0),
  });
  const records = sort.held(
    useLoad(`capacity-records ${offset} ${turn} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/capacity-records", {
        query: { sort: sort.query.sort ?? NEWEST_FIRST, limit: RECORDS_PAGE, offset },
        signal,
      }),
    ),
  );
  const items = records.data?.items ?? [];
  const holdsAll = records.data ? records.data.total === items.length : false;

  async function remove(record: CapacityRecord) {
    const result = await removing.run(() =>
      api.request("delete", "/api/v1/capacity-records/{hid}", { path: { hid: record.hid } }),
    );
    if (result.ok) {
      if (correcting?.hid === record.hid) setCorrecting(null);
      onChanged(`The record of the week of ${record.week_of} was removed.`);
    }
  }

  return (
    <section aria-labelledby="capacity-records">
      <h3 id="capacity-records">The records, week by week</h3>
      <Problem error={records.error ?? removing.error} />
      {records.loading && !records.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {records.data && (
        <>
          <div className="scroll">
            <table data-testid="capacity-records">
              <caption className="visually-hidden">
                The records of the balance, the newest week first until a header is clicked, in
                resource units
              </caption>
              <thead>
                <tr>
                  {COLUMNS.map(([column, label, number]) => (
                    <SortTh
                      key={column}
                      sort={sort.header(column, holdsAll)}
                      column={column}
                      {...(number ? { className: "number" } : {})}
                    >
                      {label}
                    </SortTh>
                  ))}
                  {mayEdit && (
                    <th scope="col">
                      <span className="visually-hidden">Change</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {sort.arrange(items, holdsAll).map((record) => (
                  <tr
                    key={record.hid}
                    data-week={record.week_of}
                    data-adjusted={record.adjusted ? "true" : "false"}
                    aria-current={correcting?.hid === record.hid ? "true" : undefined}
                  >
                    <th scope="row" className="nowrap">
                      {record.week_of}
                    </th>
                    <td className="nowrap">
                      <Time at={record.recorded_at} />
                    </td>
                    <Figures view={record.active} which="active" />
                    <Figures view={record.with_drafts} which="drafts" />
                    <td data-testid="record-adjusted">
                      {record.adjusted ? <span className="badge">Corrected</span> : "No"}
                    </td>
                    <td data-testid="record-note">
                      {record.note || <span className="muted">—</span>}
                    </td>
                    {mayEdit && (
                      <td className="nowrap">
                        <button
                          type="button"
                          onClick={() => setCorrecting(record)}
                          disabled={removing.busy}
                        >
                          Correct
                        </button>{" "}
                        <ConfirmButton
                          label="Remove"
                          title={`Remove the record of the week of ${record.week_of}?`}
                          confirmLabel="Remove the record"
                          onConfirm={() => remove(record)}
                          disabled={removing.busy}
                        >
                          <p>
                            A record that was a mistake is removed outright. The audit trail keeps
                            what it was. The server records a week again by itself only on the
                            Monday that begins it, or when it starts in a week that has none.
                          </p>
                        </ConfirmButton>
                      </td>
                    )}
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length + (mayEdit ? 1 : 0)} className="muted">
                      No week has been recorded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={records.data.total}
            limit={RECORDS_PAGE}
            offset={offset}
            noun="weeks"
            onChange={setOffset}
          />
        </>
      )}
      {mayEdit && correcting && (
        <Correct
          key={`${correcting.hid} ${correcting.row_version}`}
          record={correcting}
          onCancel={() => setCorrecting(null)}
          onReload={() => {
            setCorrecting(null);
            records.reload();
          }}
          onCorrected={(record) => {
            setCorrecting(null);
            onChanged(`The figures of the week of ${record.week_of} were corrected.`);
          }}
        />
      )}
    </section>
  );
}

function Figures({ view, which }: { view: Schemas["CapacityRecordView"]; which: string }) {
  return (
    <>
      <td className="number" data-testid={`record-${which}-demand`} data-value={view.demand}>
        {measureText(view.demand, "units")}
      </td>
      <td className="number" data-testid={`record-${which}-supply`} data-value={view.supply}>
        {measureText(view.supply, "units")}
      </td>
      <td className="number" data-testid={`record-${which}-balance`} data-value={view.balance}>
        {measureText(view.balance, "units")}
      </td>
      <td className="number">{measureText(view.coverage_pct, "percent")}</td>
    </>
  );
}

// The figures a correction may change, by the name of their field in the request.
const CORRECTED = [
  ["active", "demand", "Demand"],
  ["active", "supply", "Supply"],
  ["with_drafts", "demand", "Demand with drafts"],
  ["with_drafts", "supply", "Supply with drafts"],
] as const;

type Figure = (typeof CORRECTED)[number];

function key([view, name]: Figure): string {
  return `${view}.${name}`;
}

/** A correction of a week's demand and supply, in each view, with the note that says why. */
function Correct(props: {
  record: CapacityRecord;
  onCancel: () => void;
  onCorrected: (record: CapacityRecord) => void;
  /** Read the records again, as when somebody else changed this one. */
  onReload: () => void;
}) {
  const { record, onCancel, onCorrected, onReload } = props;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(CORRECTED.map((figure) => [key(figure), record[figure[0]][figure[1]]])),
  );
  // A correction says why it is made, in a note of its own.
  const [note, setNote] = useState("");
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  const names = [...CORRECTED.map(key), ...CORRECTED.map(([view]) => view), "note"];
  const refused = { ...fieldErrors(action.error, names).shown, ...found };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const wrong: Record<string, string> = {};
    const body: Schemas["CapacityRecordPatch"] = {
      row_version: record.row_version,
      note: note.trim(),
    };
    for (const figure of CORRECTED) {
      const [view, name] = figure;
      const typed = (values[key(figure)] ?? "").trim();
      if (!/^\d+(\.\d{1,2})?$/.test(typed)) {
        wrong[key(figure)] =
          "A number that is not negative, with at most 2 digits after the point.";
        continue;
      }
      if (canonicalDecimal(typed) === canonicalDecimal(record[view][name])) continue;
      body[view] = { ...body[view], [name]: typed };
    }
    setFound(wrong);
    if (Object.keys(wrong).length > 0) return;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/capacity-records/{hid}", {
        path: { hid: record.hid },
        body,
      }),
    );
    if (result.ok) onCorrected(result.value);
  }

  const id = `correct-${record.hid}`;
  return (
    <section className="panel" aria-labelledby={id} data-testid="correct-record">
      <h3 id={id}>Correct the week of {record.week_of}</h3>
      <p className="hint">
        A correction changes the demand and the supply, the totals, and nothing else: the parts stay
        as they were recorded, and the balance and the coverage are worked out from the two figures.
        Recorded again, the week is worked out anew and is no longer corrected.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={names} onReload={onReload} />
        <div className="fields">
          {CORRECTED.map((figure) => (
            <TextField
              key={key(figure)}
              label={figure[2]}
              name={key(figure)}
              value={values[key(figure)] ?? ""}
              onChange={(next) => {
                setValues((was) => ({ ...was, [key(figure)]: next }));
                setFound((was) => {
                  const { [key(figure)]: _, ...rest } = was;
                  return rest;
                });
              }}
              inputMode="decimal"
              autoComplete="off"
              error={refused[key(figure)] ?? refused[figure[0]]}
              hint={`As recorded: ${measureText(record[figure[0]][figure[1]], "units")}`}
            />
          ))}
          <TextAreaField
            label="Why the figures are corrected"
            name="note"
            value={note}
            onChange={setNote}
            required
            maxLength={2000}
            error={refused.note}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Correct the figures
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
