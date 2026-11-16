import { type FormEvent, useState } from "react";
import { api, type Schemas } from "../api";
import { CheckGroupField, SelectField, TextField } from "../components/Field";
// 0.8.0: the kept reports and their check (P-157).
import { KeptAnswers } from "../components/KeptAnswers";
import { Notice, Problem } from "../components/Problem";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { setZone } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { END_OF_LIFE_DATES } from "../lib/lifecycleReports";
import { CATALOG_KINDS } from "../lib/options";
import type { Option } from "../lib/patch";
import {
  listValue,
  type SettingRead,
  settingInput,
  settingText,
  settingValue,
  splitSettings,
  withExtension,
} from "../lib/settings";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";

type Setting = Schemas["SettingOut"];

/**
 * What people call each option of a setting that is chosen from a list, where the page
 * knows a better name than the value itself: the kinds of the catalog, the four dates of
 * the end-of-life report. Any other option is shown as it is.
 */
const OPTION_LABELS: Readonly<Record<string, readonly Option[]>> = {
  count_kinds: CATALOG_KINDS,
  end_of_life_date: END_OF_LIFE_DATES,
  // 0.8.0: the side a new circuit's cost and support weight count at (P-150).
  circuit_cost_side: [
    { value: "a", label: "A side" },
    { value: "z", label: "Z side" },
  ],
};

function optionsOf(setting: Setting): Option[] {
  const named = OPTION_LABELS[setting.key] ?? [];
  return (setting.options ?? []).map((value) => ({
    value,
    label: named.find((option) => option.value === value)?.label ?? value,
  }));
}

/** A value as the page shows it: an option by its name, where it has one. */
function shownValue(setting: Setting, value: unknown): string {
  // 0.8.0: a default or a minimum of support weight is blank unless an Admin sets one (P-155).
  if (value === null) return "blank";
  const named = OPTION_LABELS[setting.key];
  if (!named) return settingText(value);
  const name = (one: unknown) =>
    named.find((option) => option.value === one)?.label ?? settingText(one);
  return Array.isArray(value) ? value.map(name).join(", ") : name(value);
}

/**
 * Admin → Settings: the settings of the inventory, each with its value, its default,
 * what it is for and what it takes, and whether it is at its default, which one button
 * returns it to; and beneath them the values that are fixed in the code, each with what
 * it limits and why it is fixed, which no request changes.
 */
export function Settings() {
  useTitle("Settings");
  const settings = useLoad("settings", (signal) =>
    api.request("get", "/api/v1/settings", { signal }),
  );
  const [done, setDone] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const reset = useAction();
  const { settings: own, fixed } = splitSettings(settings.data ?? []);
  const opened = own.find((setting) => setting.key === open) ?? null;

  function changed(text: string) {
    setDone(text);
    setOpen(null);
    settings.reload();
  }

  async function toDefault(setting: Setting) {
    setDone("");
    const result = await reset.run(() =>
      api.request("put", "/api/v1/settings/{key}", {
        path: { key: setting.key },
        body: { row_version: setting.row_version, value: null },
      }),
    );
    if (!result.ok) return;
    // The times on every page follow this setting from now on.
    if (setting.key === "time_zone") setZone(setting.default);
    changed(`${setting.key} is at its default again: ${shownValue(setting, setting.default)}.`);
  }

  return (
    <>
      <AdminNav />
      <h1>Settings</h1>
      <p>
        What a site may adjust without a new release. Each setting has a default that the
        application holds: a setting that has been given a value keeps it until it is returned to
        its default. A change is audited, and is in every backup. What belongs to the host and the
        service, the address it listens on, the database and the length of a session, is in the
        configuration file instead, which <span className="mono">hirdir admin config</span> writes
        in full.
      </p>
      <Problem error={settings.error} />
      <Problem error={reset.error} onReload={settings.reload} />
      <Notice text={done} />
      {settings.loading && !settings.data && <p role="status">Loading…</p>}
      {settings.data && (
        <>
          <section aria-labelledby="inventory-settings">
            <h2 id="inventory-settings">The settings of the inventory</h2>
            <SettingsTable
              settings={own}
              busy={reset.busy}
              open={open}
              onOpen={(key) => {
                setDone("");
                setOpen(key);
              }}
              onDefault={toDefault}
            />
          </section>
          {opened && (
            <SettingForm
              key={`${opened.key} ${opened.row_version}`}
              setting={opened}
              onChanged={changed}
              onDefault={() => toDefault(opened)}
              onClose={() => setOpen(null)}
              onReload={settings.reload}
            />
          )}
          <section aria-labelledby="fixed-values">
            <h2 id="fixed-values">Fixed in the code</h2>
            <p className="hint">
              These are listed so that every value the application works by can be read in one
              place. What was decided is the same for every site, and the limits protect the
              service. No request changes them.
            </p>
            <FixedTable fixed={fixed} />
          </section>
        </>
      )}
      {/* 0.8.0: what is kept of the long reports, and the check of it (P-157). */}
      <KeptAnswers />
    </>
  );
}

interface SettingsTableProps {
  settings: readonly Setting[];
  busy: boolean;
  /** The setting whose form is open beneath the table, if any. */
  open: string | null;
  onOpen: (key: string) => void;
  onDefault: (setting: Setting) => void;
}

/** The settings, sorted by their headers: the table holds all of them. */
function SettingsTable({ settings, busy, open, onOpen, onDefault }: SettingsTableProps) {
  const sorting = useSorting(settings, {
    key: (setting) => setting.key,
    // A blank value is sorted last, as every blank is.
    value: (setting) => (setting.value === null ? null : shownValue(setting, setting.value)),
    default: (setting) => (setting.default === null ? null : shownValue(setting, setting.default)),
    standing: (setting) => (setting.is_default ? "At its default" : "Set here"),
    meaning: (setting) => setting.meaning,
    accepts: (setting) => setting.accepts,
    changed: (setting) => dateValue(setting.updated_at),
  });
  return (
    <div className="scroll">
      <table data-testid="settings">
        <caption className="visually-hidden">
          The settings of the inventory, each with its value in force and its default
        </caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="key">
              Setting
            </SortTh>
            <SortTh sort={sorting} column="value">
              Value in force
            </SortTh>
            <SortTh sort={sorting} column="default">
              Default
            </SortTh>
            <SortTh sort={sorting} column="standing">
              At its default
            </SortTh>
            <SortTh sort={sorting} column="meaning">
              What it is for
            </SortTh>
            <SortTh sort={sorting} column="accepts">
              What it takes
            </SortTh>
            <SortTh sort={sorting} column="changed">
              Changed
            </SortTh>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((setting) => (
            <tr
              key={setting.key}
              data-setting={setting.key}
              data-default={setting.is_default ? "true" : "false"}
            >
              <th scope="row" className="mono">
                {setting.key}
              </th>
              <td data-testid={`value-${setting.key}`}>
                <Shown setting={setting} value={setting.value} />
              </td>
              <td data-testid={`default-${setting.key}`}>
                <Shown setting={setting} value={setting.default} />
              </td>
              <td data-testid={`standing-${setting.key}`}>
                {setting.is_default ? (
                  "At its default"
                ) : (
                  <span className="badge badge-plain">Set here</span>
                )}
              </td>
              <td>{setting.meaning}</td>
              <td>{setting.accepts || <span className="muted">—</span>}</td>
              <td className="nowrap">
                {setting.updated_at ? (
                  <Time at={setting.updated_at} />
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="row-actions">
                <button
                  type="button"
                  aria-label={`Change ${setting.key}`}
                  aria-pressed={open === setting.key}
                  disabled={busy}
                  onClick={() => onOpen(setting.key)}
                >
                  Change
                </button>
                <button
                  type="button"
                  aria-label={`Return ${setting.key} to its default`}
                  disabled={busy || setting.is_default}
                  onClick={() => onDefault(setting)}
                >
                  Return to its default
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A value in the table: a blank one is said to be blank, lighter. */
function Shown({ setting, value }: { setting: Setting; value: unknown }) {
  if (value === null) return <span className="muted">Blank</span>;
  return shownValue(setting, value) || <span className="muted">—</span>;
}

/** The values fixed in the code, sorted by their headers. Nothing here is changed. */
function FixedTable({ fixed }: { fixed: readonly Setting[] }) {
  const sorting = useSorting(fixed, {
    key: (one) => one.key,
    value: (one) => settingText(one.value),
    meaning: (one) => one.meaning,
    reason: (one) => one.reason,
    decision: (one) => one.decision,
  });
  if (fixed.length === 0) return <p className="muted">The server lists no fixed value.</p>;
  return (
    <div className="scroll">
      <table data-testid="fixed-values">
        <caption className="visually-hidden">
          The values fixed in the code, each with what it limits and why it is fixed
        </caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="key">
              Value
            </SortTh>
            <SortTh sort={sorting} column="value">
              Is
            </SortTh>
            <SortTh sort={sorting} column="meaning">
              What it limits
            </SortTh>
            <SortTh sort={sorting} column="reason">
              Why it is fixed
            </SortTh>
            <SortTh sort={sorting} column="decision">
              Decision
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((one) => (
            <tr key={one.key} data-fixed={one.key}>
              <th scope="row" className="mono">
                {one.key}
              </th>
              <td data-testid={`fixed-${one.key}`}>
                {settingText(one.value) || <span className="muted">—</span>}
              </td>
              <td>{one.meaning}</td>
              <td>{one.reason || <span className="muted">—</span>}</td>
              <td>{one.decision || <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface SettingFormProps {
  setting: Setting;
  onChanged: (text: string) => void;
  onDefault: () => void;
  onClose: () => void;
  onReload: () => void;
}

/**
 * Give a setting another value: ticked from its options where it is a list, chosen from
 * them where it is one of a list, and typed otherwise. The server says what it takes,
 * and refuses anything else, saying so.
 */
function SettingForm({ setting, onChanged, onDefault, onClose, onReload }: SettingFormProps) {
  const input = settingInput(setting);
  const options = optionsOf(setting);
  const [text, setText] = useState(() => settingText(setting.value));
  const [chosen, setChosen] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  const [found, setFound] = useState("");
  // 0.9.0: a list of the extensions of files, to which another is added (P-159).
  const [extensions, setExtensions] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  const action = useAction();
  const headingId = `change-${setting.key}`;
  const hint = [
    setting.accepts ? `It takes ${setting.accepts}.` : "",
    `The default is ${shownValue(setting, setting.default)}.`,
  ]
    .filter(Boolean)
    .join(" ");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const wanted: SettingRead =
      input === "extensions"
        ? { ok: true, value: extensions }
        : input === "set"
          ? listValue(
              chosen,
              options.map((option) => option.value),
            )
          : settingValue(setting, text);
    if (!wanted.ok) {
      setFound(wanted.error);
      action.clear();
      return;
    }
    setFound("");
    const result = await action.run(() =>
      api.request("put", "/api/v1/settings/{key}", {
        path: { key: setting.key },
        body: { row_version: setting.row_version, value: wanted.value },
      }),
    );
    if (!result.ok) return;
    // The times on every page follow this setting from now on.
    if (setting.key === "time_zone") setZone(result.value.value ?? setting.default);
    onChanged(`${setting.key} was set to ${shownValue(setting, result.value.value)}.`);
  }

  return (
    <section className="panel" aria-labelledby={headingId} data-testid="setting-form">
      <h2 id={headingId}>
        Change <span className="mono">{setting.key}</span>
      </h2>
      <p>{setting.meaning}</p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["value"]} onReload={onReload} />
        {input === "extensions" && (
          <ExtensionList
            name={setting.key}
            list={extensions}
            onChange={setExtensions}
            disabled={action.busy}
            hint={hint}
            error={found || action.error?.fields.value}
          />
        )}
        {input === "set" && (
          <CheckGroupField
            label="New value"
            name={setting.key}
            options={options}
            value={chosen}
            onChange={setChosen}
            disabled={action.busy}
            hint={hint}
            error={found || action.error?.fields.value}
          />
        )}
        {input === "choice" && (
          <SelectField
            label="New value"
            name={setting.key}
            value={text}
            onChange={setText}
            disabled={action.busy}
            hint={hint}
            error={found || action.error?.fields.value}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
        )}
        {input === "text" && (
          <TextField
            label="New value"
            name={setting.key}
            value={text}
            onChange={setText}
            autoComplete="off"
            disabled={action.busy}
            hint={hint}
            error={found || action.error?.fields.value}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Set
          </button>
          <button type="button" disabled={action.busy || setting.is_default} onClick={onDefault}>
            Return to its default
          </button>
          <button type="button" disabled={action.busy} onClick={onClose}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

interface ExtensionListProps {
  name: string;
  list: readonly string[];
  onChange: (list: string[]) => void;
  disabled: boolean;
  hint: string;
  error: string | undefined;
}

/**
 * 0.9.0: the extensions of the files a reference may be, as the list it is: one removed,
 * another added (P-159). What an extension may be is the server's to say, and the form
 * shows its refusal as it comes.
 */
function ExtensionList({ name, list, onChange, disabled, hint, error }: ExtensionListProps) {
  const [typed, setTyped] = useState("");
  const [wrong, setWrong] = useState("");

  function add() {
    const added = withExtension(list, typed);
    if (!added.ok) {
      setWrong(added.error);
      return;
    }
    setWrong("");
    setTyped("");
    onChange(added.list);
  }

  return (
    <fieldset className="extension-list" aria-describedby={`${name}-hint`}>
      <legend>New value</legend>
      <p className="hint" id={`${name}-hint`}>
        {hint}
      </p>
      {list.length === 0 ? (
        <p className="muted">No extension: no file may be uploaded.</p>
      ) : (
        <ul className="extensions" aria-label="The extensions it takes" data-testid="extensions">
          {list.map((extension) => (
            <li key={extension}>
              <span className="mono">{extension}</span>{" "}
              <button
                type="button"
                aria-label={`Remove ${extension}`}
                disabled={disabled}
                onClick={() => onChange(list.filter((one) => one !== extension))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="cell-form">
        <TextField
          label="Add an extension"
          name={`${name}-add`}
          value={typed}
          onChange={setTyped}
          maxLength={20}
          autoComplete="off"
          disabled={disabled}
          error={wrong || undefined}
          onKeyDown={(event) => {
            // Enter in the box adds the extension: it does not set the list.
            if (event.key !== "Enter") return;
            event.preventDefault();
            add();
          }}
        />
        <button type="button" onClick={add} disabled={disabled}>
          Add
        </button>
      </div>
      {error && (
        <p className="field-error" data-testid="extensions-refused">
          {error}
        </p>
      )}
    </fieldset>
  );
}
