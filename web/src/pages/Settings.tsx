import { type FormEvent, Fragment, type ReactNode, useEffect, useState } from "react";
import { api, type Schemas } from "../api";
import { CheckGroupField, RadioGroupField, SelectField, TextField } from "../components/Field";
// 0.8.0: the kept reports and their check (P-157).
import { KeptAnswers } from "../components/KeptAnswers";
import { Notice, Problem } from "../components/Problem";
import { FormRow, type Openers, useOpeners } from "../components/RowForm";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { setZone } from "../lib/format";
import { formatsOf, OFFERED_PATTERNS, patternSample, setFormats, tidier } from "../lib/formats";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { END_OF_LIFE_DATES } from "../lib/lifecycleReports";
import { CATALOG_KINDS } from "../lib/options";
import type { Option } from "../lib/patch";
import { site, siteOfSettings } from "../lib/product";
import {
  FLAG_OPTIONS,
  listValue,
  movedUp,
  type SettingRead,
  settingFormat,
  settingInput,
  settingStart,
  settingText,
  settingValue,
  splitSettings,
  withExtension,
  withPattern,
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
  // 0.9.3: the Change button of a setting takes the focus back once its form has closed,
  // or once the setting was returned to its default from its row; after a change, once
  // the settings have been read again (P-171).
  const openers = useOpeners(settings, reset.busy);
  const { settings: own, fixed } = splitSettings(settings.data ?? []);

  // 0.9.2: the name of the product and whom the sign-in page lists, as the settings read
  // last say: a change shows on this page at once, in the menu bar and the title, and on
  // the sign-in page when this Admin signs out (P-168, P-169).
  // 0.9.18: and the formats of what is typed or pasted, which every box follows (P-322).
  useEffect(() => {
    if (!settings.data) return;
    site.update(siteOfSettings(settings.data));
    setFormats(formatsOf(settings.data));
  }, [settings.data]);

  /** Close the form that is open, if any, and give the focus back to the setting's Change. */
  function close(key: string, reading = false) {
    setOpen(null);
    openers.closed(key, reading);
  }

  function changed(key: string, text: string) {
    setDone(text);
    close(key, true);
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
    changed(
      setting.key,
      `${setting.key} is at its default again: ${shownValue(setting, setting.default)}.`,
    );
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
              opener={openers.opener}
              onOpen={(key) => {
                setDone("");
                openers.forget();
                setOpen(key);
              }}
              onDefault={toDefault}
              form={(setting) => (
                <SettingForm
                  key={`${setting.key} ${setting.row_version}`}
                  setting={setting}
                  onChanged={(text) => changed(setting.key, text)}
                  onDefault={() => toDefault(setting)}
                  onClose={() => close(setting.key)}
                  onReload={settings.reload}
                />
              )}
            />
          </section>
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

/** The columns of the table of settings, which the row of an open form spans. */
const SETTING_COLUMNS = 8;

interface SettingsTableProps {
  settings: readonly Setting[];
  busy: boolean;
  /** The setting whose form is open beneath its row, if any. */
  open: string | null;
  /** The ref of the Change button of a setting, which the focus goes back to. */
  opener: Openers["opener"];
  onOpen: (key: string) => void;
  onDefault: (setting: Setting) => void;
  /** The form of a setting, shown beneath its row while it is open. */
  form: (setting: Setting) => ReactNode;
}

/**
 * The settings, sorted by their headers: the table holds all of them. 0.9.3: the form of
 * the setting that is open is a row of its own beneath the setting's row, one cell across
 * every column, so that the setting, its value and what it is for stay in view above it
 * and the page stays where it was; and when the form closes, the focus is on that
 * setting's Change button again. The table fits a window 1280 pixels wide: a long name
 * breaks after an underscore, and the two buttons of a row stand one above the other
 * (P-171).
 */
function SettingsTable(props: SettingsTableProps) {
  const { settings, busy, open, opener, onOpen, onDefault, form } = props;
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
      <table data-testid="settings" className="settings-table">
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
            <Fragment key={setting.key}>
              <tr data-setting={setting.key} data-default={setting.is_default ? "true" : "false"}>
                <th scope="row" className="mono">
                  <Breakable name={setting.key} />
                </th>
                <td className="held" data-testid={`value-${setting.key}`}>
                  <Shown setting={setting} value={setting.value} />
                </td>
                <td className="held" data-testid={`default-${setting.key}`}>
                  <Shown setting={setting} value={setting.default} />
                </td>
                <td data-testid={`standing-${setting.key}`}>
                  {setting.is_default ? (
                    "At its default"
                  ) : (
                    <span className="badge badge-plain">Set here</span>
                  )}
                </td>
                <td className="prose">{setting.meaning}</td>
                <td className="prose">{setting.accepts || <span className="muted">—</span>}</td>
                <td>
                  {setting.updated_at ? (
                    <Time at={setting.updated_at} />
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="row-actions stacked">
                  <button
                    type="button"
                    ref={opener(setting.key)}
                    aria-label={`Change ${setting.key}`}
                    aria-expanded={open === setting.key}
                    aria-controls={open === setting.key ? formId(setting.key) : undefined}
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
              {open === setting.key && (
                <FormRow of={setting.key} columns={SETTING_COLUMNS}>
                  {form(setting)}
                </FormRow>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The name of a setting, which may break after each underscore where its column is
 * narrow, and nowhere else: it is read and copied whole.
 */
function Breakable({ name }: { name: string }) {
  // Each part is known by where it starts in the name, and each but the last is followed
  // by its underscore and a place to break.
  const parts: Array<{ at: number; text: string }> = [];
  let at = 0;
  for (const text of name.split("_")) {
    parts.push({ at, text });
    at += text.length + 1;
  }
  return parts.map((part) => (
    <Fragment key={part.at}>
      {part.text}
      {part.at + part.text.length < name.length && (
        <>
          _<wbr />
        </>
      )}
    </Fragment>
  ));
}

/** The id of the form of a setting, which its Change button controls. */
function formId(key: string): string {
  return `change-${key}`;
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
  const [text, setText] = useState(() => settingStart(setting));
  const [chosen, setChosen] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  const [found, setFound] = useState("");
  // 0.9.0: a list of the extensions of files, to which another is added (P-159).
  const [extensions, setExtensions] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  // 0.9.18: the patterns a telephone number is written in, in the order tried (P-322).
  const [patterns, setPatterns] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  const action = useAction();
  const sectionId = formId(setting.key);
  const headingId = `${sectionId}-heading`;
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
        : input === "patterns"
          ? { ok: true, value: patterns }
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
    <section
      id={sectionId}
      className="panel"
      aria-labelledby={headingId}
      data-testid="setting-form"
    >
      <h3 id={headingId}>
        Change <span className="mono">{setting.key}</span>
      </h3>
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
        {input === "patterns" && (
          <PatternList
            name={setting.key}
            list={patterns}
            onChange={setPatterns}
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
        {/* 0.9.2: the first setting that is true or false (P-169). */}
        {input === "flag" && (
          <RadioGroupField
            label="New value"
            name={setting.key}
            options={FLAG_OPTIONS}
            value={text}
            onChange={setText}
            disabled={action.busy}
            hint={hint}
            error={found || action.error?.fields.value}
          />
        )}
        {input === "text" && (
          <TextField
            label="New value"
            name={setting.key}
            value={text}
            onChange={setText}
            // 0.9.18: whom to ask's number and address, as the server writes them (P-322 (4)).
            tidy={tidier(settingFormat(setting.key))}
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

interface PatternListProps {
  name: string;
  list: readonly string[];
  onChange: (list: string[]) => void;
  disabled: boolean;
  hint: string;
  error: string | undefined;
}

/**
 * 0.9.18: the patterns a telephone number is written in, as the list it is, in the order
 * they are tried (P-322 (1), (2)): each with a number written in it, moved up or removed;
 * the two patterns of P-293 added with one press each, and one of the Admin's own typed.
 * An empty list formats no number. What a pattern may be is the server's to say, and the
 * form shows its refusal as it comes.
 */
function PatternList({ name, list, onChange, disabled, hint, error }: PatternListProps) {
  const [typed, setTyped] = useState("");
  const [wrong, setWrong] = useState("");

  function add(pattern: string, own: boolean) {
    const added = withPattern(list, pattern);
    if (!added.ok) {
      setWrong(added.error);
      return;
    }
    setWrong("");
    if (own) setTyped("");
    onChange(added.list);
  }

  return (
    <fieldset className="extension-list" aria-describedby={`${name}-hint`}>
      <legend>New value</legend>
      <p className="hint" id={`${name}-hint`}>
        {hint} A number is written in the first pattern that fits its digits; one that none fits, or
        with a letter in it, is kept as typed.
      </p>
      {list.length === 0 ? (
        <p className="muted" data-testid="no-patterns">
          No pattern: every number is kept as typed.
        </p>
      ) : (
        <ol
          className="extensions"
          aria-label="The patterns, in the order tried"
          data-testid="patterns"
        >
          {list.map((pattern, place) => (
            <li key={pattern}>
              <span className="mono">{pattern}</span>{" "}
              <span className="muted">writes {patternSample(pattern)}</span>{" "}
              {place > 0 && (
                <button
                  type="button"
                  aria-label={`Move ${pattern} up`}
                  disabled={disabled}
                  onClick={() => onChange(movedUp(list, place))}
                >
                  Move up
                </button>
              )}{" "}
              <button
                type="button"
                aria-label={`Remove ${pattern}`}
                disabled={disabled}
                onClick={() => onChange(list.filter((one) => one !== pattern))}
              >
                Remove
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className="actions">
        {OFFERED_PATTERNS.map((pattern) => (
          <button
            key={pattern}
            type="button"
            aria-label={`Add ${pattern}`}
            disabled={disabled || list.includes(pattern)}
            onClick={() => add(pattern, false)}
          >
            Add <span className="mono">{pattern}</span>
          </button>
        ))}
      </p>
      <div className="cell-form">
        <TextField
          label="Add a pattern of your own"
          name={`${name}-add`}
          value={typed}
          onChange={setTyped}
          maxLength={40}
          autoComplete="off"
          hint="# for each digit; digits before the first # alone, as a country's code; spaces and + - ( ) . / between them."
          disabled={disabled}
          error={wrong || undefined}
          onKeyDown={(event) => {
            // Enter in the box adds the pattern: it does not set the list.
            if (event.key !== "Enter") return;
            event.preventDefault();
            add(typed, true);
          }}
        />
        <button type="button" onClick={() => add(typed, true)} disabled={disabled}>
          Add
        </button>
      </div>
      {error && (
        <p className="field-error" data-testid="patterns-refused">
          {error}
        </p>
      )}
    </fieldset>
  );
}
