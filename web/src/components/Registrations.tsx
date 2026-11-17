// What an item or a device group is registered with: the external systems that know
// it, each with the other system's key for it and when that system last agreed. A
// record is registered from its own page. A registration is on the record it was made
// for: that of a stack is on the stack, and is not listed on its members. One that ends
// is given the status Removed and stays on record; registered again, it is the same
// record.

import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useAction, useLoad } from "../lib/hooks";
import { EVERY, useChoices, useSystems } from "../lib/lists";
import { choiceLabel, optionLabel } from "../lib/options";
import { fieldErrors } from "../lib/problems";
import { dateValue } from "../lib/sort";
import {
  type GroupRegistration,
  type Holder,
  holderFilter,
  REGISTRATION_STATUSES,
  REMOVED,
  type Registration,
  SYSTEM_KIND_LIST,
  systemPath,
  unregistered,
} from "../lib/systems";
import { useSorting } from "../lib/useSorting";
import { ConfirmButton } from "./ConfirmButton";
import { CheckField, SelectField, TextField } from "./Field";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";
import { Time } from "./Time";

interface RegistrationsProps {
  /** The record the registrations are of. */
  holder: Holder;
  /** What that record is called. */
  whose: string;
  /** What the record is, where the page has more to say of it than its name. */
  note?: string;
  /**
   * For an item: what a stack or a cluster it is a current member of is registered
   * with. It is shown beneath the item's own registrations, to be read only.
   */
  throughGroups?: readonly GroupRegistration[];
  mayEdit: boolean;
  /** Something changed: the record is read again, for what it lists itself. */
  onChanged: (text: string) => void;
}

const STATUSES_TO_SET = REGISTRATION_STATUSES.filter((status) => status.value !== REMOVED);

/** The registrations of one item or one device group, and the forms that change them. */
export function Registrations(props: RegistrationsProps) {
  const { holder, whose, note, throughGroups = [], mayEdit, onChanged } = props;
  const filter = holderFilter(holder);
  const [turn, setTurn] = useState(0);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const action = useAction();
  // 0.9.3: a system's kind by its label in the list, which a site may have changed (P-170).
  const choices = useChoices();
  const kindOf = (kind: string) => choiceLabel(choices.data, SYSTEM_KIND_LIST, kind);
  const found = useLoad(`registrations ${filter} ${turn}`, (signal) =>
    api.request("get", "/api/v1/registrations", { query: { filter, limit: EVERY }, signal }),
  );
  const rows = found.data?.items ?? [];
  const sorting = useSorting(rows, {
    system: (row) => row.system.name,
    kind: (row) => kindOf(row.system.kind),
    external_id: (row) => row.external_id,
    status: (row) => optionLabel(REGISTRATION_STATUSES, row.status),
    confirmed: (row) => dateValue(row.confirmed_at),
  });
  const open = rows.find((row) => row.hid === editing) ?? null;

  function changed(text: string) {
    setAdding(false);
    setEditing(null);
    setTurn((count) => count + 1);
    onChanged(text);
  }

  async function patch(row: Registration, body: Record<string, unknown>, done: string) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/registrations/{hid}", {
        path: { hid: row.hid },
        body: { row_version: row.row_version, ...body },
      }),
    );
    if (result.ok) changed(done);
  }

  return (
    <section aria-labelledby="registrations">
      <h2 id="registrations">Registered with</h2>
      {note && <p className="hint">{note}</p>}
      <Problem error={found.error} />
      <Problem error={action.error} onReload={() => setTurn((count) => count + 1)} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {found.data && rows.length === 0 && (
        <p className="muted" data-testid="no-registrations">
          {throughGroups.length > 0
            ? `${whose} has no registration of its own.`
            : `${whose} is registered with no external system.`}
        </p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="registrations">
            <caption className="visually-hidden">
              The external systems {whose} is registered with
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="system">
                  System
                </SortTh>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="external_id">
                  Its key there
                </SortTh>
                <SortTh sort={sorting} column="status">
                  Status
                </SortTh>
                <SortTh sort={sorting} column="confirmed">
                  Confirmed
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((row) => {
                const removed = row.status === REMOVED;
                return (
                  <tr
                    key={row.hid}
                    data-system={row.system.name}
                    data-status={row.status}
                    className={removed ? "muted" : undefined}
                  >
                    <th scope="row">
                      <Link to={systemPath(row.system_hid)}>{row.system.name}</Link>
                    </th>
                    <td>{kindOf(row.system.kind)}</td>
                    <td className="mono">{row.external_id || <span className="muted">—</span>}</td>
                    <td>{optionLabel(REGISTRATION_STATUSES, row.status)}</td>
                    <td className="nowrap">
                      <Time at={row.confirmed_at} />
                    </td>
                    {mayEdit && (
                      <td className="row-actions">
                        {!removed && (
                          <button
                            type="button"
                            disabled={action.busy}
                            aria-label={`${row.system.name} confirmed it now`}
                            onClick={() =>
                              patch(
                                row,
                                { confirmed_at: new Date().toISOString() },
                                `${row.system.name} confirmed ${whose}, now.`,
                              )
                            }
                          >
                            Confirmed now
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={action.busy}
                          aria-label={`Change the registration with ${row.system.name}`}
                          onClick={() => {
                            setAdding(false);
                            setEditing(row.hid);
                          }}
                        >
                          Change
                        </button>
                        {removed ? (
                          <button
                            type="button"
                            disabled={action.busy}
                            aria-label={`Register with ${row.system.name} again`}
                            onClick={() =>
                              patch(
                                row,
                                { status: "registered" },
                                `${whose} is registered with ${row.system.name} again: it is the same registration.`,
                              )
                            }
                          >
                            Register again
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={action.busy}
                            aria-label={`Remove the registration with ${row.system.name}`}
                            onClick={() =>
                              patch(
                                row,
                                { status: REMOVED },
                                `The registration of ${whose} with ${row.system.name} has the status Removed. It stays on record.`,
                              )
                            }
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && open && (
        <ChangeRegistration
          key={`${open.hid} ${open.row_version}`}
          registration={open}
          onSaved={() => changed(`The registration with ${open.system.name} was saved.`)}
          onRemoved={() =>
            changed(
              `The registration of ${whose} with ${open.system.name} was removed. The audit trail holds what it was.`,
            )
          }
          onReload={() => setTurn((count) => count + 1)}
          onClose={() => setEditing(null)}
        />
      )}
      {mayEdit && !adding && (
        <p className="actions">
          <button
            type="button"
            onClick={() => {
              setEditing(null);
              setAdding(true);
            }}
          >
            Register with a system
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <Register
          holder={holder}
          whose={whose}
          taken={rows}
          onCancel={() => setAdding(false)}
          onRegistered={(system) => changed(`${whose} is registered with ${system}.`)}
        />
      )}
      <ThroughGroups registrations={throughGroups} whose={whose} kindOf={kindOf} />
    </section>
  );
}

interface RegisterProps {
  holder: Holder;
  whose: string;
  /** The registrations the record has: with each of those systems it is registered once. */
  taken: readonly Registration[];
  onCancel: () => void;
  onRegistered: (system: string) => void;
}

function Register({ holder, whose, taken, onCancel, onRegistered }: RegisterProps) {
  const systems = useSystems();
  const [system, setSystem] = useState("");
  const [externalId, setExternalId] = useState("");
  const [status, setStatus] = useState("registered");
  const [confirmed, setConfirmed] = useState(false);
  const action = useAction();
  const known = ["system_hid", "external_id", "status", "confirmed_at"];
  const refused = fieldErrors(action.error, known).shown;
  const offered = unregistered(systems.data ?? [], taken);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      api.request("post", "/api/v1/registrations", {
        body: {
          ...holder,
          system_hid: system,
          status: status === "pending" ? "pending" : "registered",
          ...(externalId.trim() === "" ? {} : { external_id: externalId.trim() }),
          ...(confirmed ? { confirmed_at: new Date().toISOString() } : {}),
        },
      }),
    );
    if (result.ok) onRegistered(result.value.system.name);
  }

  return (
    <section className="panel" aria-labelledby="register" data-testid="register">
      <h3 id="register">Register {whose} with a system</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem
          error={action.error ?? systems.error}
          shown={known}
          labels={{ item_hid: "", group_hid: "" }}
        />
        <div className="fields">
          <SelectField
            label="External system"
            name="system_hid"
            value={system}
            onChange={setSystem}
            disabled={action.busy}
            required
            error={refused.system_hid}
            hint={
              systems.data && offered.length === 0
                ? "There is no system left that it is not registered with. The systems are under External systems."
                : "A record is registered with one system once. A registration that was removed is registered again on its own row."
            }
          >
            <option value="">Choose a system</option>
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Its key there"
            name="external_id"
            value={externalId}
            onChange={setExternalId}
            disabled={action.busy}
            maxLength={200}
            autoComplete="off"
            error={refused.external_id}
            hint="What the other system calls it: a node ID, a device ID."
          />
          <SelectField
            label="Status"
            name="status"
            value={status}
            onChange={setStatus}
            disabled={action.busy}
            error={refused.status}
          >
            {STATUSES_TO_SET.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <CheckField
            label="The system confirmed it just now"
            name="confirmed_now"
            checked={confirmed}
            onChange={setConfirmed}
            disabled={action.busy}
            error={refused.confirmed_at}
            hint="Records this moment as when the other system last agreed. Left off, nobody has said yet."
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || system === ""}>
            Register
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

interface ChangeRegistrationProps {
  registration: Registration;
  onSaved: () => void;
  /** The registration was removed outright, as a mistake. */
  onRemoved: () => void;
  onReload: () => void;
  onClose: () => void;
}

/**
 * Change the key and the status of one registration, or remove one that was a mistake.
 * Its system and its record stay.
 */
export function ChangeRegistration(props: ChangeRegistrationProps) {
  const { registration, onSaved, onRemoved, onReload, onClose } = props;
  const [externalId, setExternalId] = useState(registration.external_id ?? "");
  const [status, setStatus] = useState<string>(registration.status);
  const action = useAction();
  const known = ["external_id", "status"];
  const refused = fieldErrors(action.error, known).shown;
  const key = externalId.trim();
  const unchanged = key === (registration.external_id ?? "") && status === registration.status;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      api.request("patch", "/api/v1/registrations/{hid}", {
        path: { hid: registration.hid },
        body: {
          row_version: registration.row_version,
          ...(key === (registration.external_id ?? "") ? {} : { external_id: key || null }),
          ...(status === registration.status ? {} : { status: status as Registration["status"] }),
        },
      }),
    );
    if (result.ok) onSaved();
  }

  async function remove() {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/registrations/{hid}", { path: { hid: registration.hid } }),
    );
    if (result.ok) onRemoved();
  }

  return (
    <section
      className="panel"
      aria-labelledby="change-registration"
      data-testid="change-registration"
    >
      <h3 id="change-registration">The registration with {registration.system.name}</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} onReload={onReload} />
        <div className="fields">
          <TextField
            label="Its key there"
            name="external_id"
            value={externalId}
            onChange={setExternalId}
            disabled={action.busy}
            maxLength={200}
            autoComplete="off"
            error={refused.external_id}
          />
          <SelectField
            label="Status"
            name="status"
            value={status}
            onChange={setStatus}
            disabled={action.busy}
            error={refused.status}
            hint="A registration that ends is given the status Removed, and stays on record."
          >
            {REGISTRATION_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || unchanged}>
            Save
          </button>
          <button type="button" onClick={onClose} disabled={action.busy}>
            Cancel
          </button>
          <ConfirmButton
            label="Remove as a mistake"
            title={`Remove the registration with ${registration.system.name}?`}
            confirmLabel="Remove the registration"
            onConfirm={remove}
            disabled={action.busy}
          >
            <p>
              Removing is for a registration that was a mistake, as one made with the wrong system:
              it is gone, and the audit trail holds what it was. A registration that was true and
              has ended is given the status Removed instead, and stays on record.
            </p>
          </ConfirmButton>
        </p>
      </form>
    </section>
  );
}

interface ThroughGroupsProps {
  /** What a stack or a cluster the item is a current member of is registered with. */
  registrations: readonly GroupRegistration[];
  whose: string;
  /** A kind of system by its label. */
  kindOf: (kind: string) => string;
}

/**
 * What the stack or the cluster an item is a member of is registered with: to be read
 * here, so that nobody takes a member for a device no tool knows, and changed on the
 * page of the group. Nothing is shown for an item that is in no such group.
 */
export function ThroughGroups({ registrations, whose, kindOf }: ThroughGroupsProps) {
  const sorting = useSorting(registrations, {
    group: (row) => row.group.name,
    system: (row) => row.system.name,
    kind: (row) => kindOf(row.system.kind),
    external_id: (row) => row.external_id,
    status: (row) => optionLabel(REGISTRATION_STATUSES, row.status),
    confirmed: (row) => dateValue(row.confirmed_at),
  });
  if (registrations.length === 0) return null;
  return (
    <section aria-labelledby="group-registrations">
      <h3 id="group-registrations">Through its stack or cluster</h3>
      <p className="hint">
        What a group that {whose} is a member of is registered with, as one device. These are the
        registrations of the group: they are changed on its page.
      </p>
      <div className="scroll">
        <table data-testid="group-registrations">
          <caption className="visually-hidden">
            What the groups {whose} is a member of are registered with
          </caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="group">
                Group
              </SortTh>
              <SortTh sort={sorting} column="system">
                System
              </SortTh>
              <SortTh sort={sorting} column="kind">
                Kind
              </SortTh>
              <SortTh sort={sorting} column="external_id">
                Its key there
              </SortTh>
              <SortTh sort={sorting} column="status">
                Status
              </SortTh>
              <SortTh sort={sorting} column="confirmed">
                Confirmed
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((row) => (
              <tr
                key={row.hid}
                data-system={row.system.name}
                data-group={row.group.name}
                data-status={row.status}
                className={row.status === REMOVED ? "muted" : undefined}
              >
                <th scope="row">
                  <Link to={`/groups/${encodeURIComponent(row.group.hid)}`}>{row.group.name}</Link>
                </th>
                <td>
                  <Link to={systemPath(row.system_hid)}>{row.system.name}</Link>
                </td>
                <td>{kindOf(row.system.kind)}</td>
                <td className="mono">{row.external_id || <span className="muted">—</span>}</td>
                <td>{optionLabel(REGISTRATION_STATUSES, row.status)}</td>
                <td className="nowrap">
                  <Time at={row.confirmed_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
