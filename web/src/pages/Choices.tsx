import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, SelectField, TextField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { AdminNav } from "../components/Shell";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { CHOICE_LISTS, optionLabel } from "../lib/options";
import { reordered } from "../lib/reorder";
import { allows } from "../lib/roles";

type Choice = Schemas["ChoiceOut"];

/** Admin → Choices: the editable lists that some fields take their values from. */
export function Choices() {
  useTitle("Choices");
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const [params, setParams] = useSearchParams();
  const wanted = params.get("list") ?? "";
  const list = CHOICE_LISTS.some((known) => known.value === wanted) ? wanted : "catalog_type";
  const choices = useLoad(`choices ${list}`, (signal) =>
    api.request("get", "/api/v1/choices", { query: { list }, signal }),
  );
  const [done, setDone] = useState("");
  const action = useAction();
  const rows = choices.data ?? [];

  function changed(text: string) {
    setDone(text);
    choices.reload();
  }

  /** Move one value a place up or down, by giving the list an order with room in it. */
  async function move(choice: Choice, by: -1 | 1) {
    setDone("");
    const result = await action.run(async () => {
      for (const change of reordered(rows, choice.hid, by)) {
        await api.request("patch", "/api/v1/choices/{hid}", {
          path: { hid: change.hid },
          body: { row_version: change.row_version, sort: change.sort },
        });
      }
    });
    // Read the list again either way: after a refusal part of the order may have changed.
    choices.reload();
    if (result.ok) setDone(`${choice.value} was moved.`);
  }

  async function remove(choice: Choice) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/choices/{hid}", { path: { hid: choice.hid } }),
    );
    if (result.ok) changed(`${choice.value} was removed.`);
  }

  return (
    <>
      <AdminNav />
      <h1>Choices</h1>
      <p>
        The values a field offers. A value is what is stored on a record; its label is what people
        read. A value in use cannot be removed, only made inactive: it is then no longer offered,
        and the records that hold it keep it.
      </p>
      <div className="inline">
        <SelectField
          label="List"
          name="list"
          value={list}
          onChange={(next) => {
            setDone("");
            action.clear();
            setParams(next === "catalog_type" ? {} : { list: next });
          }}
        >
          {CHOICE_LISTS.map((known) => (
            <option key={known.value} value={known.value}>
              {known.label}
            </option>
          ))}
        </SelectField>
      </div>

      <Problem error={choices.error} />
      <Problem error={action.error} onReload={choices.reload} />
      <Notice text={done} />
      {choices.loading && !choices.data && <p role="status">Loading…</p>}
      {choices.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">
              The values of {optionLabel(CHOICE_LISTS, list)}, in their order
            </caption>
            <thead>
              <tr>
                <th scope="col">Value</th>
                <th scope="col">Label</th>
                <th scope="col">Offered</th>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((choice, place) => (
                <tr key={choice.hid} className={choice.active ? undefined : "dim"}>
                  <th scope="row" className="mono">
                    {choice.value}
                  </th>
                  {mayEdit ? (
                    <ChoiceRow
                      key={`${choice.hid} ${choice.row_version}`}
                      choice={choice}
                      onChanged={changed}
                      onReload={choices.reload}
                    />
                  ) : (
                    <>
                      <td>{choice.label}</td>
                      <td>{choice.active ? "Yes" : "No"}</td>
                    </>
                  )}
                  {mayEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        disabled={action.busy || place === 0}
                        onClick={() => move(choice, -1)}
                        aria-label={`Move ${choice.value} up`}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        disabled={action.busy || place === rows.length - 1}
                        onClick={() => move(choice, 1)}
                        aria-label={`Move ${choice.value} down`}
                      >
                        Down
                      </button>
                      <ConfirmButton
                        label="Remove"
                        title={`Remove ${choice.value}?`}
                        confirmLabel="Remove value"
                        onConfirm={() => remove(choice)}
                        disabled={action.busy}
                      >
                        <p>
                          A value that a record still holds is not removed: the server refuses, and
                          the value can be made inactive instead.
                        </p>
                      </ConfirmButton>
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={mayEdit ? 4 : 3} className="muted">
                    This list has no values.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && (
        <NewChoice
          key={list}
          list={list}
          after={rows.reduce((highest, choice) => Math.max(highest, choice.sort), 0)}
          onCreated={(choice) => changed(`${choice.value} was added.`)}
        />
      )}
    </>
  );
}

interface ChoiceRowProps {
  choice: Choice;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** The cells of one value that can be changed: its label, and whether it is offered. */
function ChoiceRow({ choice, onChanged, onReload }: ChoiceRowProps) {
  const [label, setLabel] = useState(choice.label);
  const [active, setActive] = useState(choice.active);
  const action = useAction();
  const dirty = label.trim() !== choice.label || active !== choice.active;

  async function save() {
    // Only what changed is sent, with the version this row was read at.
    const body: Schemas["ChoicePatch"] = { row_version: choice.row_version };
    if (label.trim() !== choice.label) body.label = label.trim();
    if (active !== choice.active) body.active = active;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/choices/{hid}", { path: { hid: choice.hid }, body }),
    );
    if (result.ok) onChanged(`${choice.value} was saved.`);
  }

  return (
    <>
      <td>
        <Problem error={action.error} shown={["label", "active"]} onReload={onReload} />
        <div className="cell-form">
          <TextField
            label={`Label of ${choice.value}`}
            name={`label-${choice.hid}`}
            value={label}
            onChange={setLabel}
            maxLength={100}
            autoComplete="off"
            error={action.error?.fields.label}
          />
          <button type="button" onClick={save} disabled={action.busy || !dirty}>
            Save
          </button>
        </div>
      </td>
      <td>
        <CheckField
          label={`Offer ${choice.value}`}
          name={`active-${choice.hid}`}
          checked={active}
          onChange={setActive}
          error={action.error?.fields.active}
        />
      </td>
    </>
  );
}

interface NewChoiceProps {
  list: string;
  /** The highest place in the order so far: a new value goes after it. */
  after: number;
  onCreated: (choice: Choice) => void;
}

function NewChoice({ list, after, onCreated }: NewChoiceProps) {
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["ChoiceCreate"] = {
      list,
      value: value.trim(),
      label: label.trim(),
      sort: after + 10,
    };
    const result = await action.run(() => api.request("post", "/api/v1/choices", { body }));
    if (!result.ok) return;
    setValue("");
    setLabel("");
    onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-choice">
      <h2 id="new-choice">New value</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["value", "label", "list"]} />
        <div className="fields">
          <TextField
            label="Value"
            name="value"
            value={value}
            onChange={setValue}
            required
            maxLength={40}
            autoComplete="off"
            hint="Lower-case letters, digits, hyphens and underscores. It cannot be changed later."
            error={fields.value ?? fields.list}
          />
          <TextField
            label="Label"
            name="label"
            value={label}
            onChange={setLabel}
            maxLength={100}
            autoComplete="off"
            hint="What people read. Left blank, the value itself."
            error={fields.label}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || value.trim() === ""}>
            Add value
          </button>
        </p>
      </form>
    </section>
  );
}
