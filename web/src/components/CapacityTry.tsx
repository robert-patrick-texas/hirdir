// 0.8.0: Try, the what-if of the capacity report (P-141, P-156). Other defaults and
// minimums, another weight one engineer carries, another stack discount, and staff lines
// changed, left out and added, worked out by the server beside the balance in force.
// Nothing is saved and nothing is audited; an Admin who agrees the estimate saves the
// settings tried, one audited change each. A staff line tried is never saved.

import { type FormEvent, useMemo, useState } from "react";
import { api, type Schemas } from "../api";
import type { ApiError } from "../api/client";
import { STAFF } from "../lib/capacity";
import {
  type AddedLine,
  FIGURE_KEYS,
  type FigureKey,
  type Figures,
  figureHint,
  figureLabel,
  figuresOf,
  type StaffLineTry,
  settingsToSave,
  staffFields,
  staffLinesOf,
  type TryAnswer,
  type TryRequest,
  triedText,
  tryRequest,
} from "../lib/capacityTry";
import { toApiError, useAction, useLoad } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { fieldErrors, sentence } from "../lib/problems";
import { decimalValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";
import { TriedBeside } from "./CapacityParts";
import { CheckField, TextField } from "./Field";
import { Notice, Problem } from "./Problem";
import { SortTh } from "./SortTh";

type Setting = Schemas["SettingOut"];

/** The staff lines that add and are there, drafts among them: what a Try may change. */
function useTriedLines() {
  return useLoad("capacity-try-staff-lines", async (signal) => {
    const page = await api.request("get", "/api/v1/capacity-lines", {
      query: {
        filter: `side:eq:supply category:eq:${STAFF} effect:eq:add`,
        include_drafts: true,
        sort: ["name"],
        limit: EVERY,
      },
      signal,
    });
    return page.items;
  });
}

/** What became of one setting an Admin saved from a Try. */
interface Saved {
  key: FigureKey;
  value: string | null;
  ok: boolean;
  message: string;
}

interface CapacityTryProps {
  /** The settings in force, as `GET /settings` gives them. */
  settings: readonly Setting[];
  /** Whether the person may save the settings tried: an Admin. */
  maySave: boolean;
  /** Settings were saved: the balance in force and the settings are read again. */
  onSaved: () => void;
}

/**
 * The Try panel: each figure prefilled with the one in force, the staff lines with their
 * quantities to change and a box to leave each out, rows to add, and the balance tried
 * beside the one in force once it is tried.
 */
export function CapacityTry({ settings, maySave, onSaved }: CapacityTryProps) {
  const inForce = useMemo(() => figuresOf(settings), [settings]);
  const lines = useTriedLines();
  // What the last save did: it outlives the form, which starts again from the settings
  // once they are saved and read again.
  const [saved, setSaved] = useState<Saved[]>([]);
  return (
    <section aria-labelledby="capacity-try" data-testid="capacity-try" className="panel">
      <h2 id="capacity-try">Try</h2>
      <p>
        What would other figures give? Change the defaults and minimums of the support weight, the
        weight one engineer carries or the stack discount, change, leave out or add staff lines, and
        Try: the balance they would give is shown beside the balance in force. Nothing is saved and
        nothing is written to the audit trail.
      </p>
      <Problem error={lines.error} />
      <SavedList saved={saved} />
      {lines.loading && !lines.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {lines.data && (
        <TryForm
          key={JSON.stringify(inForce)}
          inForce={inForce}
          staff={staffLinesOf(lines.data)}
          maySave={maySave}
          onSaving={() => setSaved([])}
          onSaved={(done) => {
            setSaved(done);
            if (done.some((one) => one.ok)) onSaved();
          }}
        />
      )}
    </section>
  );
}

interface TryFormProps {
  inForce: Figures;
  staff: StaffLineTry[];
  maySave: boolean;
  onSaving: () => void;
  /** What became of each setting that was to be saved. */
  onSaved: (saved: Saved[]) => void;
}

function TryForm({ inForce, staff, maySave, onSaving, onSaved }: TryFormProps) {
  const [figures, setFigures] = useState<Figures>(inForce);
  const [lines, setLines] = useState<StaffLineTry[]>(staff);
  const [added, setAdded] = useState<AddedLine[]>([]);
  const [nextId, setNextId] = useState(1);
  const [answer, setAnswer] = useState<{ value: TryAnswer; sent: string } | null>(null);
  const [asked, setAsked] = useState<TryRequest | null>(null);
  const trying = useAction();
  const [saving, setSaving] = useState(false);
  const request = tryRequest(figures, inForce, lines, added);
  const sentNow = JSON.stringify(request.body);

  // The server's message of each input, by the field it names: a figure by its key, a
  // staff line by its place in the request that was refused. What it says of a line left
  // out, which has no input of its own, is listed above the form.
  const known = useMemo(() => {
    const names: string[] = [...FIGURE_KEYS];
    for (let place = 0; place < (asked?.changed.length ?? 0); place += 1) {
      names.push(`staff.change.${place}.quantity`, `staff.change.${place}.units_each`);
      names.push(`staff.change.${place}`);
    }
    for (let place = 0; place < (asked?.added.length ?? 0); place += 1) {
      names.push(`staff.add.${place}.name`, `staff.add.${place}.quantity`);
      names.push(`staff.add.${place}.units_each`);
    }
    return names;
  }, [asked]);
  const refused = fieldErrors(trying.error, known).shown;
  const where = asked ? staffFields(asked) : null;
  // What is said of a changed line as a whole, that it is retired, is said by its quantity.
  const changeError = (hid: string, field: "quantity" | "units_each") => {
    const place = where?.change.get(hid);
    if (place === undefined) return undefined;
    const whole = field === "quantity" ? refused[`staff.change.${place}`] : undefined;
    return refused[`staff.change.${place}.${field}`] ?? whole;
  };
  const addError = (id: number, field: "name" | "quantity" | "units_each") => {
    const place = where?.add.get(id);
    return place === undefined ? undefined : refused[`staff.add.${place}.${field}`];
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    onSaving();
    setAsked(request);
    const result = await trying.run(() =>
      api.request("post", "/api/v1/reports/capacity/try", { body: request.body }),
    );
    if (result.ok) setAnswer({ value: result.value, sent: sentNow });
  }

  function startAgain() {
    setFigures(inForce);
    setLines(staff);
    setAdded([]);
    setAnswer(null);
    setAsked(null);
    onSaving();
    trying.clear();
  }

  /** Save each setting the Try changed, one after another, at the value tried. */
  async function save(value: TryAnswer) {
    const wanted = settingsToSave(value.parameters);
    setSaving(true);
    onSaving();
    const done: Saved[] = [];
    try {
      // The versions are read now, so that a setting another Admin changed meanwhile is
      // refused as stale rather than written over.
      const now = await api.request("get", "/api/v1/settings", {});
      for (const one of wanted) {
        const setting = now.find((candidate) => candidate.key === one.key);
        try {
          await api.request("put", "/api/v1/settings/{key}", {
            path: { key: one.key },
            body: { row_version: setting?.row_version ?? 0, value: one.value },
          });
          done.push({ ...one, ok: true, message: "" });
        } catch (thrown) {
          done.push({ ...one, ok: false, message: refusalText(toApiError(thrown)) });
        }
      }
    } catch (thrown) {
      const message = refusalText(toApiError(thrown));
      for (const one of wanted) done.push({ ...one, ok: false, message });
    } finally {
      setSaving(false);
    }
    onSaved(done);
  }

  const stale = answer !== null && answer.sent !== sentNow;
  const toSave = answer ? settingsToSave(answer.value.parameters) : [];
  const busy = trying.busy || saving;

  return (
    <>
      <form onSubmit={submit} className="stack" noValidate data-testid="try-form">
        <Problem
          error={trying.error}
          shown={Object.keys(refused)}
          labels={{
            staff: "Staff lines",
            // A line left out is named by the message itself.
            ...Object.fromEntries(lines.map((_, place) => [`staff.leave_out.${place}`, ""])),
          }}
        />
        <fieldset>
          <legend>The figures</legend>
          <div className="fields">
            {FIGURE_KEYS.map((key) => (
              <TextField
                key={key}
                label={figureLabel(key)}
                name={key}
                value={figures[key]}
                onChange={(next) => setFigures((was) => ({ ...was, [key]: next }))}
                inputMode="decimal"
                autoComplete="off"
                disabled={busy}
                hint={`${figureHint(key)} In force: ${inForce[key] || "blank"}.`}
                error={refused[key]}
              />
            ))}
          </div>
        </fieldset>
        <StaffLines lines={lines} busy={busy} onChange={setLines} error={changeError} />
        <AddedLines
          added={added}
          busy={busy}
          onChange={setAdded}
          onAdd={() => {
            setAdded((was) => [...was, { id: nextId, name: "", quantity: "1", unitsEach: "1" }]);
            setNextId((id) => id + 1);
          }}
          error={addError}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={busy}>
            Try
          </button>
          <button type="button" disabled={busy} onClick={startAgain}>
            Start again from what is in force
          </button>
        </p>
      </form>
      {trying.busy && (
        <p role="status" className="muted loading-late">
          Working it out…
        </p>
      )}
      {answer && (
        <section aria-labelledby="capacity-tried" data-testid="try-answer">
          <h3 id="capacity-tried">The balance tried</h3>
          {stale && (
            <p className="warning" data-testid="try-stale">
              The figures or the staff lines were changed since this was tried: Try again to see
              what they give.
            </p>
          )}
          <TriedBeside inForce={answer.value.in_force} tried={answer.value.tried} />
          <TriedStaff value={answer.value} />
          <section aria-labelledby="capacity-save" data-testid="try-save">
            <h4 id="capacity-save">Saving the settings tried</h4>
            {toSave.length === 0 ? (
              <p className="muted">
                Every setting tried is the one in force: there is no setting to save.
              </p>
            ) : (
              <p>
                The settings tried that are not the ones in force:{" "}
                <span data-testid="try-changed">
                  {toSave.map((one) => `${one.key} at ${triedText(one.key, one.value)}`).join(", ")}
                </span>
                .
              </p>
            )}
            {maySave && toSave.length > 0 && (
              <p className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy || stale}
                  onClick={() => save(answer.value)}
                >
                  Save these settings
                </button>
                <span className="hint">
                  Each is saved as a change of its own, and audited. A staff line tried is not
                  saved: enter it under Lines to keep it.
                </span>
              </p>
            )}
            {!maySave && (
              <p className="hint">
                An Admin saves the settings once an estimate is agreed. A staff line tried is not
                saved: it is entered under Lines to keep it.
              </p>
            )}
            {saving && (
              <p role="status" className="muted">
                Saving…
              </p>
            )}
          </section>
        </section>
      )}
    </>
  );
}

function refusalText(error: ApiError): string {
  const fields = Object.values(error.fields);
  if (error.stale) return "Another change was made to it meanwhile: read the page again.";
  return sentence([error.message, ...fields].filter(Boolean).join(": "));
}

/** Which settings were saved and which were refused, each with why. */
function SavedList({ saved }: { saved: readonly Saved[] }) {
  if (saved.length === 0) return null;
  const good = saved.filter((one) => one.ok);
  const bad = saved.filter((one) => !one.ok);
  return (
    <div data-testid="try-saved">
      <Notice
        text={
          good.length > 0
            ? `Saved: ${good.map((one) => `${one.key} at ${triedText(one.key, one.value)}`).join(", ")}.`
            : ""
        }
      />
      {bad.length > 0 && (
        <div className="alert alert-error" data-testid="try-refused">
          <p>
            <strong>Not saved:</strong>
          </p>
          <ul>
            {bad.map((one) => (
              <li key={one.key} data-setting={one.key}>
                <span className="mono">{one.key}</span>: {one.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The staff lines as they were tried: added, changed and left out, by name. */
function TriedStaff({ value }: { value: TryAnswer }) {
  const { add, change, leave_out: leftOut } = value.parameters.staff;
  if (add.length + change.length + leftOut.length === 0) return null;
  return (
    <div data-testid="tried-staff">
      <h4>The staff lines tried</h4>
      <ul className="plain-list">
        {add.map((line) => (
          <li key={`add ${line.name}`} data-tried="add">
            Added: {line.name}, {line.quantity} × {line.units_each} = {line.units} units
          </li>
        ))}
        {change.map((line) => (
          <li key={`change ${line.hid}`} data-tried="change">
            Changed: {line.name}, {line.quantity} × {line.units_each} = {line.units} units
          </li>
        ))}
        {leftOut.map((line) => (
          <li key={`out ${line.hid}`} data-tried="leave_out">
            Left out: {line.name}
          </li>
        ))}
      </ul>
      <p className="hint">
        A staff line tried, changed or added, counts as active and in date in both views. A line
        that multiplies works on a changed line as it is tried, on none that is left out, and on no
        line that is added, since it names the lines it works on.
      </p>
    </div>
  );
}

interface StaffLinesProps {
  lines: StaffLineTry[];
  busy: boolean;
  onChange: (lines: StaffLineTry[]) => void;
  error: (hid: string, field: "quantity" | "units_each") => string | undefined;
}

/** The staff lines that are there: each with its quantity and units to change, and a box to leave it out. */
function StaffLines({ lines, busy, onChange, error }: StaffLinesProps) {
  const sorting = useSorting(lines, {
    name: (line) => line.name,
    standing: (line) => line.standing,
    quantity: (line) => decimalValue(line.triedQuantity),
    units_each: (line) => decimalValue(line.triedUnitsEach),
    leave_out: (line) => (line.leaveOut ? "Left out" : null),
  });
  const put = (hid: string, change: Partial<StaffLineTry>) =>
    onChange(lines.map((line) => (line.hid === hid ? { ...line, ...change } : line)));
  return (
    <fieldset>
      <legend>The staff lines</legend>
      {lines.length === 0 ? (
        <p className="muted">There is no staff line that adds: add one to try below.</p>
      ) : (
        <div className="scroll">
          <table data-testid="try-staff">
            <caption className="visually-hidden">
              The staff lines, each with its quantity and units of one to try, and whether to leave
              it out
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Line
                </SortTh>
                <SortTh sort={sorting} column="standing">
                  Counts now
                </SortTh>
                <SortTh sort={sorting} column="quantity">
                  Quantity
                </SortTh>
                <SortTh sort={sorting} column="units_each">
                  Units each
                </SortTh>
                <SortTh sort={sorting} column="leave_out">
                  Leave out
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((line) => (
                <tr key={line.hid} data-line={line.name}>
                  <th scope="row">{line.name}</th>
                  <td>
                    {line.standing === "active"
                      ? "Yes"
                      : line.standing === "draft"
                        ? "With the drafts: a draft"
                        : "No: out of date"}
                  </td>
                  <td>
                    <TextField
                      label={`Quantity of ${line.name}`}
                      name={`quantity-${line.hid}`}
                      value={line.triedQuantity}
                      onChange={(next) => put(line.hid, { triedQuantity: next })}
                      inputMode="decimal"
                      autoComplete="off"
                      disabled={busy || line.leaveOut}
                      error={error(line.hid, "quantity")}
                    />
                  </td>
                  <td>
                    <TextField
                      label={`Units each of ${line.name}`}
                      name={`units-${line.hid}`}
                      value={line.triedUnitsEach}
                      onChange={(next) => put(line.hid, { triedUnitsEach: next })}
                      inputMode="decimal"
                      autoComplete="off"
                      disabled={busy || line.leaveOut}
                      error={error(line.hid, "units_each")}
                    />
                  </td>
                  <td>
                    <CheckField
                      label={`Leave out ${line.name}`}
                      name={`leave-out-${line.hid}`}
                      checked={line.leaveOut}
                      onChange={(on) => put(line.hid, { leaveOut: on })}
                      disabled={busy}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </fieldset>
  );
}

interface AddedLinesProps {
  added: AddedLine[];
  busy: boolean;
  onChange: (added: AddedLine[]) => void;
  onAdd: () => void;
  error: (id: number, field: "name" | "quantity" | "units_each") => string | undefined;
}

/** Staff lines that are not there, tried as if they were: a name, a quantity and the units of one. */
function AddedLines({ added, busy, onChange, onAdd, error }: AddedLinesProps) {
  const sorting = useSorting(added, {
    name: (row) => row.name,
    quantity: (row) => decimalValue(row.quantity),
    units_each: (row) => decimalValue(row.unitsEach),
  });
  const put = (id: number, change: Partial<AddedLine>) =>
    onChange(added.map((row) => (row.id === id ? { ...row, ...change } : row)));
  return (
    <fieldset>
      <legend>Staff lines to add</legend>
      {added.length > 0 && (
        <div className="scroll">
          <table data-testid="try-added">
            <caption className="visually-hidden">Staff lines to try as if they were there</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                <SortTh sort={sorting} column="quantity">
                  Quantity
                </SortTh>
                <SortTh sort={sorting} column="units_each">
                  Units each
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => (
                <tr key={row.id} data-added={row.id}>
                  <td>
                    <TextField
                      label={`Name of added line ${row.id}`}
                      name={`added-name-${row.id}`}
                      value={row.name}
                      onChange={(next) => put(row.id, { name: next })}
                      autoComplete="off"
                      maxLength={200}
                      disabled={busy}
                      error={error(row.id, "name")}
                    />
                  </td>
                  <td>
                    <TextField
                      label={`Quantity of added line ${row.id}`}
                      name={`added-quantity-${row.id}`}
                      value={row.quantity}
                      onChange={(next) => put(row.id, { quantity: next })}
                      inputMode="decimal"
                      autoComplete="off"
                      disabled={busy}
                      error={error(row.id, "quantity")}
                    />
                  </td>
                  <td>
                    <TextField
                      label={`Units each of added line ${row.id}`}
                      name={`added-units-${row.id}`}
                      value={row.unitsEach}
                      onChange={(next) => put(row.id, { unitsEach: next })}
                      inputMode="decimal"
                      autoComplete="off"
                      disabled={busy}
                      error={error(row.id, "units_each")}
                    />
                  </td>
                  <td className="row-actions">
                    <button
                      type="button"
                      disabled={busy}
                      aria-label={`Take out added line ${row.id}`}
                      onClick={() => onChange(added.filter((one) => one.id !== row.id))}
                    >
                      Take out
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="actions">
        <button type="button" disabled={busy} onClick={onAdd}>
          Add a staff line to try
        </button>
        <span className="hint">
          A line added here is tried, never saved: one that is to stay is entered under Lines.
        </span>
      </p>
    </fieldset>
  );
}
