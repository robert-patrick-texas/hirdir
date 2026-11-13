import { type FormEvent, useState } from "react";
import { api, type Schemas } from "../api";
import { CheckGroupField, TextField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { AdminNav } from "../components/Shell";
import { Time } from "../components/Time";
import { formatValue } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { stateNames } from "../lib/lifecycle";
import { useRules } from "../lib/lists";
import { CATALOG_KINDS } from "../lib/options";
import type { Option } from "../lib/patch";
import { settingText, settingValue } from "../lib/settings";

type Setting = Schemas["SettingOut"];

/** Admin → Settings: the installation-wide values, each with its default. */
export function Settings() {
  useTitle("Settings");
  const settings = useLoad("settings", (signal) =>
    api.request("get", "/api/v1/settings", { signal }),
  );
  const rules = useRules();
  const [done, setDone] = useState("");
  const states = stateNames(rules.data ?? []).map((state) => ({ value: state, label: state }));

  return (
    <>
      <AdminNav />
      <h1>Settings</h1>
      <p>
        Each setting has a default. A setting that has been given a value keeps it until it is
        reset, which returns it to the default.
      </p>
      <Problem error={settings.error ?? rules.error} />
      <Notice text={done} />
      {settings.loading && !settings.data && <p role="status">Loading…</p>}
      {settings.data?.map((setting) => (
        <SettingForm
          key={`${setting.key} ${setting.row_version}`}
          setting={setting}
          options={
            setting.key === "count_kinds"
              ? CATALOG_KINDS
              : setting.key.endsWith("_states")
                ? states
                : null
          }
          onChanged={(text) => {
            setDone(text);
            settings.reload();
          }}
          onReload={settings.reload}
        />
      ))}
    </>
  );
}

interface SettingFormProps {
  setting: Setting;
  /** For a setting that is a set of values: what may be chosen. */
  options: readonly Option[] | null;
  onChanged: (text: string) => void;
  onReload: () => void;
}

function SettingForm({ setting, options, onChanged, onReload }: SettingFormProps) {
  const isList = Array.isArray(setting.value);
  const [text, setText] = useState(() => settingText(setting.value));
  const [chosen, setChosen] = useState<string[]>(() =>
    Array.isArray(setting.value) ? setting.value.map(String) : [],
  );
  const [found, setFound] = useState("");
  const action = useAction();
  const headingId = `setting-${setting.key}`;

  async function put(value: unknown, done: string) {
    const result = await action.run(() =>
      api.request("put", "/api/v1/settings/{key}", {
        path: { key: setting.key },
        body: { row_version: setting.row_version, value },
      }),
    );
    if (result.ok) onChanged(done);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const wanted = isList ? { ok: true as const, value: chosen } : settingValue(setting, text);
    if (!wanted.ok) {
      setFound(wanted.error);
      action.clear();
      return;
    }
    setFound("");
    await put(wanted.value, `${setting.key} was set.`);
  }

  return (
    <section className="panel setting" aria-labelledby={headingId}>
      <h2 id={headingId} className="mono">
        {setting.key}
      </h2>
      <p>{setting.meaning}</p>
      <dl className="facts">
        <dt>Default</dt>
        <dd>{settingText(setting.default) || formatValue(setting.default)}</dd>
        <dt>Value in force</dt>
        <dd data-testid={`value-${setting.key}`}>
          {settingText(setting.value) || formatValue(setting.value)}
          <span className="muted"> · {setting.is_default ? "the default" : "set here"}</span>
        </dd>
        {setting.updated_at && (
          <>
            <dt>Changed</dt>
            <dd>
              <Time at={setting.updated_at} />
            </dd>
          </>
        )}
      </dl>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={["value"]} onReload={onReload} />
        {isList ? (
          <CheckGroupField
            label="New value"
            name={setting.key}
            options={
              options ??
              (setting.default as unknown[]).map(String).map((value) => ({ value, label: value }))
            }
            value={chosen}
            onChange={setChosen}
            error={found || action.error?.fields.value}
          />
        ) : (
          <TextField
            label="New value"
            name={setting.key}
            value={text}
            onChange={setText}
            autoComplete="off"
            error={found || action.error?.fields.value}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Set
          </button>
          <button
            type="button"
            disabled={action.busy || setting.is_default}
            onClick={() => put(null, `${setting.key} was reset to its default.`)}
          >
            Reset to default
          </button>
        </p>
      </form>
    </section>
  );
}
