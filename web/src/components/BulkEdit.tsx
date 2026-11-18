// Bulk edit: one change to many items, shown before it is made.
//
// The form names the fields to change. The server works out what that does to each item
// and stores it as a preview, with before and after for every row. Nothing changes
// until the preview is applied. The apply goes on in the background, as an import's
// does: an item that somebody has changed in the meantime is left as it is, and named,
// and the rest are changed.

import { type FormEvent, useMemo, useRef, useState } from "react";
import { type ApiError, api, type Schemas } from "../api";
import {
  type BulkField,
  type BulkLine,
  buildBulk,
  bulkIdentity,
  bulkRows,
  CATALOG_ENTRY,
  type EntryRef,
  LIFECYCLE_STATE,
} from "../lib/bulk";
import { plural } from "../lib/format";
import { CONDITION_LIST, OBSERVED_CHOICES } from "../lib/health";
import { toApiError } from "../lib/hooks";
import { Keys, withKey } from "../lib/idempotency";
import { useOwnerOptions, useTags } from "../lib/lists";
import { choiceOptions, SETTABLE_STATUSES } from "../lib/options";
import type { FormValue, Option } from "../lib/patch";
import { entrySeen } from "../lib/pick";
import type { Preview } from "../lib/preview";
import { fieldErrors } from "../lib/problems";
import { type Chosen, chosenCount, type GridView } from "../lib/transfer";
import { useJob } from "../lib/useJob";
import { CheckField, CheckGroupField, SelectField } from "./Field";
import { FormFields } from "./FormFields";
import { ApplyCounts, ApplyPreview, JobCounts, LeftOutOf, PreviewRows } from "./Preview";
import { Problem } from "./Problem";

type Choice = Schemas["ChoiceOut"];

const DISPOSITIONS: readonly Option[] = ["Staging", "Production", "Spare", "Excess"].map(
  (value) => ({ value, label: value }),
);
const DAYS: ReadonlyArray<[name: string, label: string]> = [
  ["procured_on", "Procured"],
  ["delivered_on", "Delivered"],
  ["in_service_on", "In service"],
  ["warranty_start", "Warranty start"],
  ["warranty_end", "Warranty end"],
];
const AMOUNTS: ReadonlyArray<[name: string, label: string]> = [
  ["est_value", "Estimated value"],
  ["support_weight", "Support weight"],
  ["annual_support_cost", "Annual support cost"],
];
const LAST_DAYS: ReadonlyArray<[name: string, label: string]> = [
  ["end_of_sale", "End of sale"],
  ["end_of_sw_support", "End of software support"],
  ["end_of_hw_support", "End of hardware support"],
  ["ldos", "Last day of support (LDoS)"],
];
const INHERITS = "Cleared, it inherits from the catalog entry again";

/**
 * The fields a bulk edit may change: what an import may set, less the fields that tell
 * one item from another. Each is named as a column of an import.
 */
function bulkFields(
  states: readonly string[],
  owners: readonly Option[],
  conditions: readonly Option[],
): BulkField[] {
  return [
    {
      name: CATALOG_ENTRY,
      label: "Catalog entry",
      // 0.9.6: searched for, not a list of every model (P-200).
      kind: "entry",
      blank: "None chosen yet",
    },
    {
      name: "owner",
      label: "Owner",
      kind: "choice",
      blank: "Choose an owner",
      options: owners,
      clearable: true,
    },
    {
      name: "operator",
      label: "Operator",
      kind: "operator",
      blank: "None chosen",
      clearable: true,
      hint: "The label of who of the team looks after each item. Cleared, an item has the operator it has from above again: of the item it is in, of its group or of where it is.",
    },
    {
      name: "location",
      label: "Location",
      kind: "location",
      blank: "None chosen",
      clearable: true,
      hint: "Cleared, an item is where the item it is in is, or its group, and nowhere if those have no location.",
    },
    {
      name: "planned_location",
      label: "Planned location",
      kind: "planned_location",
      blank: "None chosen",
      clearable: true,
      hint: "Where the items are going, when that place is not in use yet. They stay where they are until the place is made active, and are then moved there by that change. Cleared, an item has the plan of the item it is in or of its group, if there is one.",
    },
    {
      name: LIFECYCLE_STATE,
      label: "Lifecycle state",
      kind: "choice",
      blank: "Choose a state",
      options: states.map((state) => ({ value: state, label: state })),
      hint: "Each item moves as the lifecycle rules allow. One that may not is rejected.",
    },
    {
      name: "disposition",
      label: "Disposition",
      kind: "choice",
      blank: "Choose a disposition",
      options: DISPOSITIONS,
      clearable: true,
    },
    {
      name: "expected_online",
      label: "Expected online",
      kind: "tristate",
      blank: "Choose yes or no",
      clearable: true,
    },
    {
      name: "condition",
      label: "Condition",
      kind: "choice",
      blank: "Choose a condition",
      options: conditions,
      clearable: true,
      hint: "The state of the hardware, as a person knows it. It moves no item in the lifecycle.",
    },
    {
      name: "observed_status",
      label: "Observed status",
      kind: "choice",
      blank: "Choose what is seen",
      options: OBSERVED_CHOICES,
      clearable: true,
      hint: "What was seen of each item. Cleared, the moment it was seen is cleared with it.",
    },
    { name: "quantity", label: "Quantity", kind: "integer" },
    { name: "description", label: "Description", kind: "longtext", clearable: true },
    { name: "comments", label: "Comments", kind: "longtext", clearable: true },
    ...DAYS.map(([name, label]): BulkField => ({ name, label, kind: "date", clearable: true })),
    ...AMOUNTS.map(
      ([name, label]): BulkField => ({
        name,
        label,
        kind: "decimal",
        places: 2,
        clearable: true,
        hint: INHERITS,
      }),
    ),
    ...LAST_DAYS.map(
      ([name, label]): BulkField => ({
        name,
        label,
        kind: "date",
        clearable: true,
        hint: INHERITS,
      }),
    ),
    {
      // Its own word on renewing its support (D-182): cleared, it has its model's again.
      name: "do_not_renew",
      label: "Not to be renewed",
      kind: "tristate",
      blank: "Choose yes or no",
      clearable: true,
      hint: "Yes leaves each item behind when its contract is renewed, its coverage ending with the present term. Cleared, an item has its model's word again.",
    },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      blank: "Choose a status",
      options: SETTABLE_STATUSES,
      hint: "Retiring is done on an item's own page",
    },
  ];
}

/**
 * How a file names the catalog entry a line sets, by its vendor and its PID: the entry
 * was chosen by searching for it (P-200), and the search noted what it offered.
 */
function entryRefs(lines: readonly BulkLine[]): Record<string, EntryRef> {
  const refs: Record<string, EntryRef> = {};
  for (const line of lines) {
    if (line.name !== CATALOG_ENTRY || typeof line.value !== "string") continue;
    const entry = entrySeen(line.value);
    if (entry) refs[entry.hid] = { vendor: entry.vendor.hid, pid: entry.pid };
  }
  return refs;
}

interface BulkEditProps {
  /** The rows to change: the ones selected, or all that the filter keeps. */
  rows: Chosen;
  /** The filter and the switches of the grid the rows were chosen in. */
  view: GridView;
  states: readonly string[];
  choices: readonly Choice[] | undefined;
  /** The change was applied: the grid is out of date. */
  onApplied: () => void;
  onClose: () => void;
}

export function BulkEdit({ rows, view, states, choices, onApplied, onClose }: BulkEditProps) {
  const owners = useOwnerOptions();
  const tags = useTags();
  const keys = useRef(new Keys());
  const fields = useMemo(
    () => bulkFields(states, owners.data ?? [], choiceOptions(choices, CONDITION_LIST)),
    [states, owners.data, choices],
  );
  const labels = (tags.data ?? []).map((tag) => ({ value: tag.label, label: tag.label }));
  const reasons = choiceOptions(choices, "state_reason");

  const [lines, setLines] = useState<BulkLine[]>([]);
  const [adding, setAdding] = useState("");
  const [reason, setReason] = useState("");
  const [addTags, setAddTags] = useState<string[]>([]);
  const [removeTags, setRemoveTags] = useState<string[]>([]);
  const [found, setFound] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);

  const count = chosenCount(rows);
  // Every item the list shows: the reader set no filter, whatever a switch of the grid adds.
  const whole = rows.kind === "all" && (view.filter === null || view.unfiltered === true);
  const built = buildBulk(
    fields,
    { lines, reason, addTags, removeTags },
    bulkRows(rows, view),
    entryRefs(lines),
  );
  const names = [...lines.map((line) => line.name), "vendor", "pid", "add_tags", "remove_tags"];
  const refused = fieldErrors(error, names).shown;
  const said: Record<string, string> = { ...refused, ...found };
  const entryError = [said[CATALOG_ENTRY], refused.vendor, refused.pid].filter(Boolean).join("; ");
  if (entryError) said[CATALOG_ENTRY] = entryError;
  const unused = fields.filter((field) => !lines.some((line) => line.name === field.name));

  function forget(name: string) {
    setFound((was) => {
      const { [name]: _, ...rest } = was;
      return rest;
    });
  }

  function add() {
    const field = fields.find((candidate) => candidate.name === adding);
    if (!field) return;
    setLines((was) => [...was, { name: field.name, clear: false, value: "" }]);
    setAdding("");
  }

  function change(name: string, next: Partial<BulkLine>) {
    setLines((was) => was.map((line) => (line.name === name ? { ...line, ...next } : line)));
    forget(name);
  }

  function remove(name: string) {
    setLines((was) => was.filter((line) => line.name !== name));
    forget(name);
  }

  /** Ask the server what the change would do, and show that. */
  async function makePreview() {
    setFound(built.errors);
    if (Object.keys(built.errors).length > 0) {
      setError(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const made = await withKey(keys.current, bulkIdentity(built.body), (idempotencyKey) =>
        api.request("post", "/api/v1/items/bulk-update", { body: built.body, idempotencyKey }),
      );
      setPreview(made);
    } catch (thrown) {
      setError(toApiError(thrown));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    makePreview();
  }

  const what =
    rows.kind === "rows"
      ? `the ${plural(count, "selected item")}`
      : `all ${plural(count, "item")} that match the filter`;

  return (
    <section className="panel" aria-labelledby="bulk-edit" data-testid="bulk-edit">
      <h2 id="bulk-edit">Bulk edit</h2>
      <Problem error={owners.error ?? tags.error} />
      {!preview && (
        <form onSubmit={submit} className="stack" noValidate>
          <p>
            This changes <strong>{what}</strong>. Add each field to change. A field that is not
            added is left as it is.
          </p>
          {whole && (
            <p className="alert alert-info">
              No filter is set, so this is every item the grid shows.
            </p>
          )}
          <Problem error={error} shown={names} />
          <div className="inline">
            <SelectField
              label="Field to change"
              name="bulk-field"
              value={adding}
              onChange={setAdding}
              disabled={busy}
            >
              <option value="">Choose a field</option>
              {unused.map((field) => (
                <option key={field.name} value={field.name}>
                  {field.label}
                </option>
              ))}
            </SelectField>
            <button type="button" onClick={add} disabled={busy || adding === ""}>
              Add
            </button>
          </div>
          {lines.map((line) => {
            const field = fields.find((candidate) => candidate.name === line.name);
            if (!field) return null;
            return (
              <fieldset className="bulk-line" key={line.name} data-field={line.name}>
                <legend>{field.label}</legend>
                <div className="fields">
                  <FormFields
                    specs={[{ ...field, label: "Set to" }]}
                    values={{ [line.name]: line.clear ? "" : line.value }}
                    onChange={(_, value: FormValue) => change(line.name, { value })}
                    errors={said}
                    disabled={busy || line.clear}
                  />
                  {line.name === LIFECYCLE_STATE && (
                    <SelectField
                      label="Reason"
                      name="state_reason"
                      value={reason}
                      onChange={setReason}
                      disabled={busy}
                      hint="Recorded with each move"
                    >
                      <option value="">No reason given</option>
                      {reasons.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </SelectField>
                  )}
                </div>
                <p className="actions">
                  {field.clearable && (
                    <CheckField
                      label="Clear it instead"
                      name={`clear-${line.name}`}
                      checked={line.clear}
                      disabled={busy}
                      onChange={(clear) => change(line.name, { clear })}
                    />
                  )}
                  <button type="button" onClick={() => remove(line.name)} disabled={busy}>
                    Remove
                  </button>
                </p>
              </fieldset>
            );
          })}
          <div className="fields">
            <CheckGroupField
              label="Add tags"
              name="add_tags"
              options={labels}
              value={addTags}
              onChange={(next) => {
                setAddTags(next);
                forget("remove_tags");
              }}
              disabled={busy}
              error={said.add_tags}
              empty="There are no tags yet."
            />
            <CheckGroupField
              label="Remove tags"
              name="remove_tags"
              options={labels}
              value={removeTags}
              onChange={(next) => {
                setRemoveTags(next);
                forget("remove_tags");
              }}
              disabled={busy}
              error={said.remove_tags}
              empty="There are no tags yet."
            />
          </div>
          <p className="actions">
            <button type="submit" className="primary" disabled={busy || built.empty}>
              Preview the change
            </button>
            <button type="button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
          </p>
          <p className="hint">
            Serial number, asset tag, MAC address, name, hostname and FQDN tell one item from
            another, and are changed on an item&apos;s own page.
          </p>
        </form>
      )}
      {preview && (
        <BulkPreview
          key={preview.job.hid}
          preview={preview}
          what={what}
          busy={busy}
          error={error}
          again={makePreview}
          onApplied={onApplied}
          onChange={() => setPreview(null)}
          onClose={onClose}
        />
      )}
    </section>
  );
}

interface BulkPreviewProps {
  preview: Preview;
  /** The rows it changes, in words. */
  what: string;
  busy: boolean;
  error: ApiError | null;
  /** Make the same edit again, against the items as they are now. */
  again: () => void;
  /** The apply ended: the grid is out of date. */
  onApplied: () => void;
  /** Go back to the form, to change the edit. */
  onChange: () => void;
  onClose: () => void;
}

/**
 * A bulk edit, previewed: what it would do to each item, and the apply. The apply goes on
 * in the background and is followed here, and on its page among the imports, which the
 * panel may be closed for.
 */
function BulkPreview(props: BulkPreviewProps) {
  const { preview, what, busy, error, again, onApplied, onChange, onClose } = props;
  const [turn, setTurn] = useState(0);
  const followed = useJob(preview.job.hid, {
    first: preview.job,
    onEnded: () => {
      setTurn((was) => was + 1);
      onApplied();
    },
  });
  const job = followed.job ?? preview.job;
  const previewed = job.status === "previewed";

  return (
    <div data-testid="bulk-preview" data-status={job.status}>
      <p>
        What the change would do to <strong>{what}</strong>, row by row.{" "}
        {previewed ? "Nothing has been changed yet." : ""}
      </p>
      <JobCounts job={job} />
      <ApplyCounts job={job} />
      <ApplyPreview
        job={job}
        noun={["item", "items"]}
        busy={busy}
        onStarted={followed.started}
        again={again}
        againHint=""
        followAt={`/import/${encodeURIComponent(job.hid)}`}
      />
      <Problem error={error ?? followed.error} />
      <p className="actions">
        {previewed && (
          <button type="button" onClick={onChange} disabled={busy}>
            Change the edit
          </button>
        )}
        <button type="button" onClick={onClose} disabled={busy}>
          {previewed ? "Cancel" : "Close"}
        </button>
      </p>
      <LeftOutOf job={job} turn={turn} />
      <PreviewRows job={job} preview={preview} turn={turn} />
    </div>
  );
}
