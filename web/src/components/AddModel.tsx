// 0.9.6: a model that is not in the catalog is added from New item (P-201), beneath the
// search for its catalog entry: its vendor, PID, model name, kind and type, within the
// page. The server makes the entry as the catalog page makes it, under the same role;
// on success it is chosen for the item and the keyboard goes on to the item's next field,
// and on a refusal the server's answer is shown and everything typed stays. A refusal
// because the catalog has the model already offers that entry, to be chosen with Use it,
// and its page in a new tab, so that New item and what was typed stay.

import { createContext, type KeyboardEvent, useRef, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { ApiError } from "../api/client";
import { useAction } from "../lib/hooks";
import { useChoices, useVendorOptions } from "../lib/lists";
import { CATALOG_KINDS, choiceOptions } from "../lib/options";
import { entryLabel, sawEntries } from "../lib/pick";
import { existingLead, existingPath, fieldErrors } from "../lib/problems";
import { SelectField, TextField } from "./Field";
import { Problem } from "./Problem";

type Entry = Schemas["CatalogEntryOut"];

/** Whether a catalog entry field offers to add a model that is not in the catalog. */
export const OffersNewModel = createContext(false);

// The fields of the request the part of the form below has an input for.
const FIELDS = ["vendor_hid", "pid", "model_name", "kind", "type"];

/**
 * The first field of the form after the one `from` stands in, that takes the keyboard: the
 * item's next field once its model has been chosen.
 */
export function nextField(from: HTMLElement): HTMLElement | null {
  const field = from.closest<HTMLElement>("[data-field]");
  const form = from.closest("form");
  if (!field || !form) return null;
  const inputs = form.querySelectorAll<HTMLElement>(
    "input:not([type=hidden]):not(:disabled), select:not(:disabled), textarea:not(:disabled)",
  );
  return (
    [...inputs].find(
      (input) =>
        !field.contains(input) &&
        field.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING &&
        input.getClientRects().length > 0,
    ) ?? null
  );
}

interface AddModelProps {
  /** What was typed into the search: the PID starts as it. */
  typed: string;
  /** The search found nothing for what was typed. */
  nothing: boolean;
  /** The model was added: it is the one chosen. */
  onAdded: (entry: Entry, from: HTMLElement) => void;
}

/** Add this model to the catalog: a part of the form beneath the search for an entry. */
export function AddModel({ typed, nothing, onAdded }: AddModelProps) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  if (!open) {
    return (
      <p className={nothing ? "add-model" : "add-model add-model-small"}>
        <button
          type="button"
          ref={opener}
          className={nothing ? undefined : "change-link"}
          onClick={() => setOpen(true)}
        >
          {nothing ? "Add this model to the catalog" : "Add a model to the catalog"}
        </button>
      </p>
    );
  }
  return (
    <NewModel
      typed={typed}
      onAdded={(entry, from) => {
        setOpen(false);
        onAdded(entry, from);
      }}
      onCancel={() => {
        setOpen(false);
        requestAnimationFrame(() => opener.current?.focus());
      }}
    />
  );
}

interface NewModelProps {
  typed: string;
  onAdded: (entry: Entry, from: HTMLElement) => void;
  onCancel: () => void;
}

/** The few fields a catalog entry needs, within the item's form: no form of its own. */
function NewModel({ typed, onAdded, onCancel }: NewModelProps) {
  const vendors = useVendorOptions();
  const choices = useChoices();
  const [vendor, setVendor] = useState("");
  const [pid, setPid] = useState(typed);
  const [model, setModel] = useState("");
  const [kind, setKind] = useState("hardware");
  const [type, setType] = useState("");
  const action = useAction();
  const group = useRef<HTMLFieldSetElement>(null);
  const refused = fieldErrors(action.error, FIELDS).shown;
  const missing: Record<string, string> = {};
  const [tried, setTried] = useState(false);
  if (tried && vendor === "") missing.vendor_hid = "Choose the vendor.";
  if (tried && pid.trim() === "") missing.pid = "Give the PID.";
  const errors = { ...refused, ...missing };
  // The catalog has the model already: that entry is offered, and the refusal says the
  // rest without its link, which would leave the page.
  const error = action.error;
  const existing =
    error && !error.stale && error.existing?.record_type === "catalog_entry"
      ? error.existing
      : null;
  const existingTo = existing ? existingPath(existing) : null;
  const said =
    error && existing
      ? new ApiError({
          status: error.status,
          title: error.title,
          detail: error.detail,
          fields: { ...error.fields },
          retryAfter: error.retryAfter,
        })
      : error;

  async function use(hid: string) {
    const result = await action.run(() =>
      api.request("get", "/api/v1/catalog-entries/{hid}", { path: { hid } }),
    );
    if (result.ok && group.current) {
      sawEntries([result.value]);
      onAdded(result.value, group.current);
    }
  }

  async function add() {
    setTried(true);
    if (vendor === "" || pid.trim() === "") return;
    const body: Schemas["CatalogEntryCreate"] = {
      vendor_hid: vendor,
      pid: pid.trim(),
      kind,
      ...(model.trim() ? { model_name: model.trim() } : {}),
      ...(type ? { type } : {}),
    };
    const result = await action.run(() => api.request("post", "/api/v1/catalog-entries", { body }));
    if (result.ok && group.current) {
      sawEntries([result.value]);
      onAdded(result.value, group.current);
    }
  }

  // Enter in a box of this part adds the model, and does not send the item's form.
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    void add();
  }

  return (
    <fieldset className="panel add-model-form" ref={group}>
      <legend>Add a model to the catalog</legend>
      <Problem error={said} shown={FIELDS} />
      {existing && (
        <p>
          {existingLead(existing)}{" "}
          {existingTo ? (
            <Link to={existingTo} target="_blank" rel="noreferrer">
              {existing.label}
              <span className="visually-hidden"> (opens in a new tab)</span>
            </Link>
          ) : (
            <strong>{existing.label}</strong>
          )}{" "}
          <button type="button" onClick={() => void use(existing.hid)} disabled={action.busy}>
            Use it
          </button>
        </p>
      )}
      <Problem error={vendors.error ?? choices.error} />
      <SelectField
        label="Vendor"
        name="new-model-vendor"
        value={vendor}
        onChange={setVendor}
        required
        disabled={action.busy}
        error={errors.vendor_hid}
      >
        <option value="">{vendors.loading ? "Loading…" : "Choose a vendor"}</option>
        {(vendors.data ?? []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </SelectField>
      <TextField
        label="PID"
        name="new-model-pid"
        value={pid}
        onChange={setPid}
        required
        maxLength={100}
        disabled={action.busy}
        error={errors.pid}
        hint="The product ID as the vendor writes it"
        onKeyDown={keyDown}
      />
      <TextField
        label="Model name"
        name="new-model-name"
        value={model}
        onChange={setModel}
        maxLength={200}
        disabled={action.busy}
        error={errors.model_name}
        onKeyDown={keyDown}
      />
      <SelectField
        label="Kind"
        name="new-model-kind"
        value={kind}
        onChange={setKind}
        disabled={action.busy}
        error={errors.kind}
      >
        {CATALOG_KINDS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="Type"
        name="new-model-type"
        value={type}
        onChange={setType}
        disabled={action.busy}
        error={errors.type}
      >
        <option value="">No type</option>
        {choiceOptions(choices.data, "catalog_type").map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </SelectField>
      <p className="actions">
        <button type="button" className="primary" onClick={() => void add()} disabled={action.busy}>
          Add to the catalog
        </button>
        <button type="button" onClick={onCancel} disabled={action.busy}>
          Cancel
        </button>
      </p>
      <p className="hint">
        The rest of what the catalog holds of the model, its dates and amounts, is filled in on its
        page in the catalog.
      </p>
    </fieldset>
  );
}

/** What a catalog entry just added is called in the field that chose it. */
export function addedOption(entry: Entry): { value: string; label: string } {
  return { value: entry.hid, label: entryLabel(entry) };
}
