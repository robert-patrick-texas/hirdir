import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { TextField } from "../components/Field";
import { Pager, toOffset } from "../components/Pager";
import { Problem } from "../components/Problem";
import { Time } from "../components/Time";
import { formatChanges } from "../lib/format";
import { useLoad, useTitle } from "../lib/hooks";

const PAGE = 50;

// Suggestions for the filters: what this release writes to the trail. The server matches
// whatever is typed, so a value not listed here can still be asked for.
const ACTIONS = [
  "add_member",
  "create",
  "delete",
  "grant_role",
  "remove_member",
  "retire",
  "revoke",
  "revoke_role",
  "set_access_code",
  "sign_in",
  "sign_in_delayed",
  "sign_in_failed",
  "sign_out_everywhere",
  "transition",
  "update",
];
const RECORD_TYPES = [
  "catalog_entry",
  "choice",
  "contact",
  "contact_assignment",
  "item",
  "lifecycle_rule",
  "location",
  "owner",
  "owner_member",
  "region",
  "service_token",
  "setting",
  "site",
  "tag",
  "user",
  "user_group",
  "vendor",
];

function suggestions(known: readonly string[], seen: ReadonlyArray<string>): string[] {
  return [...new Set([...known, ...seen.filter(Boolean)])].sort();
}

/** Give each line a key of its own, even when two lines read the same. */
function keyed(lines: readonly string[]): Array<{ key: string; line: string }> {
  const counts = new Map<string, number>();
  return lines.map((line) => {
    const count = (counts.get(line) ?? 0) + 1;
    counts.set(line, count);
    return { key: `${count} ${line}`, line };
  });
}

/** The audit trail, newest first. */
export function Audit() {
  useTitle("Audit");
  const [params, setParams] = useSearchParams();
  const action = params.get("action") ?? "";
  const recordType = params.get("record_type") ?? "";
  const offset = toOffset(params.get("offset"));
  const [wantedAction, setWantedAction] = useState(action);
  const [wantedType, setWantedType] = useState(recordType);
  const events = useLoad(`audit ${offset} ${action} ${recordType}`, (signal) =>
    api.request("get", "/api/v1/audit-events", {
      query: { action, record_type: recordType, limit: PAGE, offset },
      signal,
    }),
  );
  const items = events.data?.items ?? [];

  function show(next: { action: string; recordType: string; offset: number }) {
    const wanted = new URLSearchParams();
    if (next.action) wanted.set("action", next.action);
    if (next.recordType) wanted.set("record_type", next.recordType);
    if (next.offset > 0) wanted.set("offset", String(next.offset));
    setParams(wanted);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    show({ action: wantedAction.trim(), recordType: wantedType.trim(), offset: 0 });
  }

  function clear() {
    setWantedAction("");
    setWantedType("");
    show({ action: "", recordType: "", offset: 0 });
  }

  return (
    <>
      <h1>Audit</h1>
      <form onSubmit={submit} className="inline">
        <TextField
          label="Action"
          name="action"
          value={wantedAction}
          onChange={setWantedAction}
          list="audit-actions"
          autoComplete="off"
        />
        <datalist id="audit-actions">
          {suggestions(
            ACTIONS,
            items.map((item) => item.action),
          ).map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <TextField
          label="Record type"
          name="record_type"
          value={wantedType}
          onChange={setWantedType}
          list="audit-record-types"
          autoComplete="off"
        />
        <datalist id="audit-record-types">
          {suggestions(
            RECORD_TYPES,
            items.map((item) => item.record_type),
          ).map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <button type="submit">Filter</button>
        <button
          type="button"
          onClick={clear}
          disabled={!action && !recordType && !wantedAction && !wantedType}
        >
          Clear
        </button>
      </form>

      <Problem error={events.error} />
      {events.loading && !events.data && <p role="status">Loading…</p>}
      {events.data && (
        <>
          <div className="scroll">
            <table className="audit">
              <caption className="visually-hidden">Audit events, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Who</th>
                  <th scope="col">Via</th>
                  <th scope="col">Action</th>
                  <th scope="col">Record type</th>
                  <th scope="col">What changed</th>
                </tr>
              </thead>
              <tbody>
                {items.map((event) => {
                  const changes = formatChanges(event.changes);
                  return (
                    <tr key={event.hid}>
                      <td className="nowrap">
                        <Time at={event.at} />
                      </td>
                      <td>{event.actor_name ?? <span className="muted">—</span>}</td>
                      <td>{event.via}</td>
                      <td>{event.action}</td>
                      <td>
                        {event.record_type}
                        {event.record_hid && <span className="hid mono">{event.record_hid}</span>}
                      </td>
                      <td>
                        {changes.length > 0 && (
                          <ul className="changes">
                            {keyed(changes).map(({ key, line }) => (
                              <li key={key}>{line}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">
                      {action || recordType
                        ? "No event matches the filter."
                        : "There are no events."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={events.data.total}
            limit={PAGE}
            offset={offset}
            noun="events"
            onChange={(next) => show({ action, recordType, offset: next })}
          />
        </>
      )}
    </>
  );
}
