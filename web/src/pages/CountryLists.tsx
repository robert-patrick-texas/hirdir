// 0.9.18: Admin › Choices › Countries and States: the lists an address takes its country
// and its state from, read by every role and changed by an Admin alone (P-318, P-321);
// and the addresses that hold a country or a state that no list holds, each a link to its
// place, where a person chooses the value.
//
// Every rule is the server's: the order of the lists, the United States first, the codes
// kept in capitals, and what is not changed or removed while an address holds it. A
// refusal is shown in its words. What the page keeps of its own is that the United
// States' code is not offered to change, nor the United States to remove, since neither
// is ever taken.

import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { api, type Schemas } from "../api";
import { ConfirmButton } from "../components/ConfirmButton";
import { SelectField } from "../components/Field";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { FormRow, useOpeners } from "../components/RowForm";
import { SortTh } from "../components/SortTh";
import { CountriesExport } from "../components/TableExports";
import {
  type Country,
  countryName,
  type State,
  stateCounts,
  statesOf,
  UNLISTED_ID,
  type UnlistedAddress,
  US,
  unlistedFieldLabel,
  unlistedSetLabel,
} from "../lib/countries";
import { plural } from "../lib/format";
import { useAction, useLoad, useReloadOn } from "../lib/hooks";
import { useCountries, useStates } from "../lib/lists";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { levelLabel, placePath } from "../lib/places";
import { useSorting } from "../lib/useSorting";

/** The address of the list of one country's states, on this page. */
export function statesPath(country: string): string {
  return `/admin/choices?${new URLSearchParams({ list: "states", country }).toString()}`;
}

// A refusal on the code of a row names no input: its words stand as a sentence.
const ROW_LABELS = { code: "", name: "" } as const;

/** The fields of a country, in its form. The United States' code is shown, and kept. */
function countrySpecs(country: Country | null): FieldSpec[] {
  return [
    {
      name: "code",
      label: "Code",
      kind: "text",
      required: true,
      maxLength: 2,
      hint: "Its ISO 3166-1 alpha-2 code, two letters, as MX: kept in capitals. A code that an address holds is not changed.",
      ...(country?.code === US
        ? { shownAs: () => "US, which the United States keeps: it may be renamed" }
        : {}),
    },
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 100,
      hint: "As the forms of an address offer it, and as an address is shown",
    },
  ];
}

/** The fields of a state, in its form. */
const STATE_SPECS: FieldSpec[] = [
  {
    name: "code",
    label: "Code",
    kind: "text",
    required: true,
    maxLength: 3,
    hint: "The part of its ISO 3166-2 code after the hyphen, 1 to 3 letters and digits, as TX of US-TX: kept in capitals. A code that an address holds is not changed.",
  },
  {
    name: "name",
    label: "Name",
    kind: "text",
    required: true,
    maxLength: 100,
    hint: "As the forms of an address offer it, and as an address is shown",
  },
];

interface ListProps {
  mayEdit: boolean;
}

/** Admin › Choices › Countries: every country, the United States first, then by name. */
export function CountriesList({ mayEdit }: ListProps) {
  const countries = useCountries();
  const states = useStates();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState("");
  const [done, setDone] = useState("");
  // Counts the changes made here, so that the addresses not in the lists are read again.
  const [turn, setTurn] = useState(0);
  const action = useAction();
  const rows = countries.data ?? [];
  const counts = stateCounts(states.data ?? []);
  const sorting = useSorting(rows, {
    code: (country) => country.code,
    name: (country) => country.name,
    states: (country) => counts.get(country.code) ?? 0,
  });
  const openers = useOpeners(countries);
  const columns = mayEdit ? 4 : 3;

  function close(hid: string, reading = false) {
    setEditing("");
    openers.closed(hid, reading);
  }

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    countries.reload();
    states.reload();
  }

  async function remove(country: Country) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/countries/{hid}", { path: { hid: country.hid } }),
    );
    if (result.ok) {
      const gone = counts.get(country.code) ?? 0;
      changed(
        gone > 0
          ? `${country.name} was removed, with its ${plural(gone, "state")}.`
          : `${country.name} was removed.`,
      );
    }
  }

  return (
    <>
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            className="primary"
            onClick={() => {
              setDone("");
              setAdding(true);
            }}
          >
            New country
          </button>
        </p>
      )}
      {adding && (
        <CreateForm<Schemas["CountryCreate"], Country>
          title="New country"
          specs={countrySpecs(null)}
          create={(body) => api.request("post", "/api/v1/countries", { body })}
          onCreated={(country) => {
            setAdding(false);
            changed(`${country.name} was added, as ${country.code}.`);
          }}
          onCancel={() => setAdding(false)}
          submitLabel="Add country"
        />
      )}
      <Problem error={countries.error} />
      <Problem error={states.error} />
      <Problem error={action.error} labels={ROW_LABELS} />
      <Notice text={done} />
      {countries.loading && !countries.data && <p role="status">Loading…</p>}
      {countries.data && sorting.state !== null && (
        <p className="actions">
          <button type="button" onClick={sorting.reset}>
            Back to the order of the list
          </button>
        </p>
      )}
      {countries.data && (
        <div className="scroll">
          <table data-testid="countries">
            <caption className="visually-hidden">
              The countries, the United States first, then by name
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="code">
                  Code
                </SortTh>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                <SortTh sort={sorting} column="states">
                  States
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((country) => {
                const count = counts.get(country.code) ?? 0;
                return (
                  <Fragment key={country.hid}>
                    <tr data-country={country.code}>
                      <th scope="row" className="mono">
                        {country.code}
                      </th>
                      <td>{country.name}</td>
                      <td>
                        <Link
                          className="value-link"
                          to={statesPath(country.code)}
                          aria-label={`The states of ${country.name}: ${count === 0 ? "none" : plural(count, "state")}`}
                        >
                          {count === 0 ? "None" : plural(count, "state")}
                        </Link>
                      </td>
                      {mayEdit && (
                        <td className="row-actions">
                          <button
                            type="button"
                            ref={openers.opener(country.hid)}
                            onClick={() => {
                              setDone("");
                              action.clear();
                              openers.forget();
                              setEditing(country.hid);
                            }}
                            aria-label={`Edit ${country.name}`}
                            aria-expanded={editing === country.hid}
                          >
                            Edit
                          </button>
                          {country.code === US ? (
                            <span className="muted" data-testid="us-stays">
                              Always first, and not removed
                            </span>
                          ) : (
                            <ConfirmButton
                              label="Remove"
                              hiddenLabel={country.name}
                              title={`Remove ${country.name}?`}
                              confirmLabel="Remove country"
                              onConfirm={() => remove(country)}
                              disabled={action.busy}
                            >
                              <p>
                                {count === 0
                                  ? "It has no states."
                                  : count === 1
                                    ? "Its one state is removed with it, in the same change."
                                    : `Its ${plural(count, "state")} are removed with it, in the same change.`}{" "}
                                A country that an address holds, or one of whose states an address
                                holds, is not removed: the server refuses, and names the first place
                                that holds it.
                              </p>
                            </ConfirmButton>
                          )}
                        </td>
                      )}
                    </tr>
                    {mayEdit && editing === country.hid && (
                      <FormRow of={country.code} columns={columns}>
                        <RowEdit
                          title={`The country ${country.name}`}
                          testId="country-form"
                          specs={countrySpecs(country)}
                          record={country}
                          save={(body) =>
                            api.request("patch", "/api/v1/countries/{hid}", {
                              path: { hid: country.hid },
                              body,
                            })
                          }
                          onSaved={() => {
                            close(country.hid, true);
                            changed(`${country.name} was saved.`);
                          }}
                          onClose={() => close(country.hid)}
                          onReload={countries.reload}
                        />
                      </FormRow>
                    )}
                  </Fragment>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={columns} className="muted">
                    There are no countries.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <CountriesExport mayEdit={mayEdit} />
      <UnlistedAddresses
        turn={turn}
        ready={countries.data !== undefined && states.data !== undefined}
      />
    </>
  );
}

interface StatesListProps extends ListProps {
  /** The code of the country whose states are shown; blank is the United States. */
  country: string;
  onCountry: (code: string) => void;
}

/** Admin › Choices › States: the states of one country, by name, the United States' at first. */
export function StatesList({ mayEdit, country, onCountry }: StatesListProps) {
  const countries = useCountries();
  const states = useStates();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState("");
  const [done, setDone] = useState("");
  const [turn, setTurn] = useState(0);
  const action = useAction();
  const known = countries.data ?? [];
  // A country the list does not hold, as one removed meanwhile, is the United States.
  const code = known.some((one) => one.code === country) ? country : US;
  const name = countryName(known, code);
  const rows = statesOf(states.data ?? [], code);
  const sorting = useSorting(rows, {
    code: (state) => state.code,
    name: (state) => state.name,
  });
  const openers = useOpeners(states);
  const columns = mayEdit ? 3 : 2;

  function close(hid: string, reading = false) {
    setEditing("");
    openers.closed(hid, reading);
  }

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    states.reload();
  }

  async function remove(state: State) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/states/{hid}", { path: { hid: state.hid } }),
    );
    if (result.ok) changed(`${state.name} was removed.`);
  }

  return (
    <>
      <div className="inline">
        <SelectField
          label="Country"
          name="country"
          value={code}
          onChange={(next) => {
            setDone("");
            setAdding(false);
            setEditing("");
            action.clear();
            onCountry(next);
          }}
        >
          {known.length === 0 && <option value={code}>{code}</option>}
          {known.map((one) => (
            <option key={one.hid} value={one.code}>
              {one.name}
            </option>
          ))}
        </SelectField>
      </div>
      {mayEdit && !adding && countries.data && (
        <p className="actions">
          <button
            type="button"
            className="primary"
            onClick={() => {
              setDone("");
              setAdding(true);
            }}
          >
            New state of {name}
          </button>
        </p>
      )}
      {adding && (
        <CreateForm<Omit<Schemas["StateCreate"], "country">, State>
          key={code}
          title={`New state of ${name}`}
          specs={STATE_SPECS}
          create={(body) =>
            api.request("post", "/api/v1/states", { body: { ...body, country: code } })
          }
          onCreated={(state) => {
            setAdding(false);
            changed(`${state.name} was added to ${name}, as ${state.code}.`);
          }}
          onCancel={() => setAdding(false)}
          submitLabel="Add state"
          labels={{ country: "Country" }}
        />
      )}
      <Problem error={countries.error} />
      <Problem error={states.error} />
      <Problem error={action.error} labels={ROW_LABELS} />
      <Notice text={done} />
      {states.loading && !states.data && <p role="status">Loading…</p>}
      {states.data && (
        <div className="scroll">
          <table data-testid="states" data-country={code}>
            <caption className="visually-hidden">The states of {name}, by name</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="code">
                  Code
                </SortTh>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((state) => (
                <Fragment key={state.hid}>
                  <tr data-state={state.code}>
                    <th scope="row" className="mono">
                      {state.code}
                    </th>
                    <td>{state.name}</td>
                    {mayEdit && (
                      <td className="row-actions">
                        <button
                          type="button"
                          ref={openers.opener(state.hid)}
                          onClick={() => {
                            setDone("");
                            action.clear();
                            openers.forget();
                            setEditing(state.hid);
                          }}
                          aria-label={`Edit ${state.name}`}
                          aria-expanded={editing === state.hid}
                        >
                          Edit
                        </button>
                        <ConfirmButton
                          label="Remove"
                          hiddenLabel={state.name}
                          title={`Remove ${state.name}?`}
                          confirmLabel="Remove state"
                          onConfirm={() => remove(state)}
                          disabled={action.busy}
                        >
                          <p>
                            A state that an address holds is not removed: the server refuses, and
                            names the first place that holds it.
                          </p>
                        </ConfirmButton>
                      </td>
                    )}
                  </tr>
                  {mayEdit && editing === state.hid && (
                    <FormRow of={state.code} columns={columns}>
                      <RowEdit
                        title={`The state ${state.name} of ${name}`}
                        testId="state-form"
                        specs={STATE_SPECS}
                        record={state}
                        save={(body) =>
                          api.request("patch", "/api/v1/states/{hid}", {
                            path: { hid: state.hid },
                            body,
                          })
                        }
                        onSaved={() => {
                          close(state.hid, true);
                          changed(`${state.name} was saved.`);
                        }}
                        onClose={() => close(state.hid)}
                        onReload={states.reload}
                      />
                    </FormRow>
                  )}
                </Fragment>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={columns} className="muted" data-testid="no-states">
                    {name} has no states listed: the state of an address there is typed as text.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <CountriesExport mayEdit={mayEdit} />
      <UnlistedAddresses
        turn={turn}
        ready={countries.data !== undefined && states.data !== undefined}
      />
    </>
  );
}

interface RowEditProps<R extends { hid: string; row_version: number }> {
  title: string;
  testId: string;
  specs: readonly FieldSpec[];
  record: R;
  save: (body: { row_version: number; code?: string | null; name?: string | null }) => Promise<R>;
  onSaved: () => void;
  onClose: () => void;
  onReload: () => void;
}

/** The form of one country or one state, beneath its row: its code and its name. */
function RowEdit<R extends { hid: string; row_version: number }>(props: RowEditProps<R>) {
  const { title, testId, specs, record, save, onSaved, onClose, onReload } = props;
  const heading = `edit-${testId}`;
  return (
    <section className="panel" aria-labelledby={heading} data-testid={testId}>
      <h2 id={heading}>{title}</h2>
      <EditForm<R, { row_version: number; code?: string | null; name?: string | null }>
        key={`${record.hid} ${record.row_version}`}
        specs={specs}
        record={record}
        save={save}
        onSaved={onSaved}
        onReload={onReload}
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}

// The addresses not in the lists are read a hundred to a page, as the server pages them.
const UNLISTED_PAGE = 100;

/**
 * Where the address names the addresses not in the lists, as the link of the Import page
 * does, the window is brought to their heading and the keyboard put on it: once for each
 * address, when the page above it and the list itself have come, so that rows drawn
 * above do not move it away again.
 */
function useToUnlisted(ready: boolean) {
  const { hash, key } = useLocation();
  const done = useRef("");
  useEffect(() => {
    if (!ready || done.current === key || hash !== `#${UNLISTED_ID}`) return;
    const heading = document.getElementById(UNLISTED_ID);
    if (!heading) return;
    done.current = key;
    heading.scrollIntoView({ block: "start" });
    heading.focus({ preventScroll: true });
  }, [hash, key, ready]);
}

/**
 * The addresses that hold a country or a state that no list holds, as the upgrade to
 * 0.9.18 kept them: each a link to its place, whose Details offer the lists to choose
 * from (P-321 (7)). Read again whenever `turn` changes, as after a change of the lists.
 * `ready` says that what stands above it on the page has come.
 */
export function UnlistedAddresses({ turn, ready }: { turn: number; ready: boolean }) {
  const [offset, setOffset] = useState(0);
  const unlisted = useLoad(`unlisted addresses ${offset}`, (signal) =>
    api.request("get", "/api/v1/places/unlisted-addresses", {
      query: { limit: UNLISTED_PAGE, offset },
      signal,
    }),
  );
  useReloadOn(turn, unlisted.reload);
  const page = unlisted.data;
  useToUnlisted(ready && page !== undefined);
  return (
    <section aria-labelledby={UNLISTED_ID} data-testid="unlisted-addresses">
      <h2 id={UNLISTED_ID} tabIndex={-1}>
        Addresses not in the lists
      </h2>
      <p className="hint">
        Each country and state of an address that no list holds, as it was typed before the lists
        were kept: the retired places and the drafts among them. Open a place and choose the country
        or the state it is from the lists in its Details. A value that a list holds once it is added
        there leaves this list too.
      </p>
      <Problem error={unlisted.error} />
      {unlisted.loading && !page && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {page && page.total === 0 && (
        <p className="muted" data-testid="unlisted-none">
          Every address holds a country and a state of the lists.
        </p>
      )}
      {page && page.total > 0 && (
        <>
          <div className="scroll">
            <table>
              <caption className="visually-hidden">
                The countries and states of addresses that no list holds, by the path of the place
              </caption>
              <thead>
                <tr>
                  <th scope="col">Place</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Address</th>
                  <th scope="col">Field</th>
                  <th scope="col">Value</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row: UnlistedAddress) => (
                  <tr
                    key={`${row.hid} ${row.field}`}
                    data-hid={row.hid}
                    data-field={row.field}
                    data-testid="unlisted-row"
                  >
                    <th scope="row">
                      <Link to={placePath(row.level, row.hid)}>{row.path}</Link>
                      {row.record_status !== "active" && (
                        <span className="badge">
                          {optionLabel(RECORD_STATUSES, row.record_status)}
                        </span>
                      )}
                    </th>
                    <td>{levelLabel(row.level)}</td>
                    <td>{unlistedSetLabel(row.set)}</td>
                    <td>{unlistedFieldLabel(row.field)}</td>
                    <td data-testid="unlisted-value">{row.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page.total > UNLISTED_PAGE && (
            <Pager
              total={page.total}
              limit={UNLISTED_PAGE}
              offset={offset}
              noun="values not in the lists"
              onChange={setOffset}
            />
          )}
        </>
      )}
    </section>
  );
}
