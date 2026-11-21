import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { SelectField, TextField } from "../components/Field";
import { Pager, toOffset } from "../components/Pager";
import { Problem } from "../components/Problem";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { ValueLink } from "../components/ValueLink";
import { actorLabel, deletedRecords, isDeleted } from "../lib/audit";
import { formatChanges } from "../lib/format";
import { useLoad, useTitle } from "../lib/hooks";
import { kindPath } from "../lib/preview";
import { allows } from "../lib/roles";
import { AUDIT_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";

const PAGE = 50;
// The most users the server lists at once.
const EVERY_USER = 1000;

type AuditEvent = Schemas["AuditEventOut"];

// Suggestions for the filters: what this release writes to the trail. The server matches
// whatever is typed, so a value not listed here can still be asked for.
const ACTIONS = [
  "add_member",
  "create",
  "delete",
  "export",
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
  "address",
  "catalog_entry",
  "choice",
  "contact",
  "contact_assignment",
  "device_group",
  "device_group_member",
  "inventory",
  "item",
  "item_replacement",
  "lifecycle_rule",
  "location",
  "network",
  "operator",
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

/** The audit trail, newest first until a header is clicked. */
export function Audit() {
  useTitle("Audit");
  const { user } = useAuth();
  const admin = allows(user.role, "admin");
  const [params, setParams] = useSearchParams();
  const action = params.get("action") ?? "";
  const recordType = params.get("record_type") ?? "";
  // 0.9.14: who acted, by the HID of the account, kept in the address (P-296).
  const actor = params.get("actor_hid") ?? "";
  const offset = toOffset(params.get("offset"));
  const [wantedAction, setWantedAction] = useState(action);
  const [wantedType, setWantedType] = useState(recordType);
  const [wantedActor, setWantedActor] = useState(actor);
  // The accounts an Admin chooses from, the retired among them, marked: what an account
  // did is still in the trail after it has left. The list of users is an Admin's.
  const actors = useLoad(`audit actors ${admin}`, async (signal) =>
    admin
      ? (
          await api.request("get", "/api/v1/users", {
            query: { retired: "yes", limit: EVERY_USER },
            signal,
          })
        ).items
      : [],
  );
  // The server pages the trail and sorts it, over every event and not the page on show:
  // a header asks for the trail in its order, from the first page. What changed is
  // composed here and is no field of the server's sort: its header sorts in the browser,
  // and only while the page holds every event there is.
  const sort = useServerSort<AuditEvent>({
    fields: AUDIT_SORT,
    local: { changes: (event) => formatChanges(event.changes).join("\n") },
    onChange: () => {
      if (offset > 0) show({ action, recordType, actor, offset: 0 });
    },
  });
  const events = sort.held(
    useLoad(`audit ${offset} ${action} ${recordType} ${actor} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/audit-events", {
        query: {
          action,
          record_type: recordType,
          ...(actor ? { actor_hid: actor } : {}),
          ...sort.query,
          limit: PAGE,
          offset,
        },
        signal,
      }),
    ),
  );
  const items = events.data?.items ?? [];
  const holdsAll = events.data ? events.data.total === items.length : false;
  // 0.9.8: a record that an event on show deleted is named as text, by each of its events
  // (P-240). One deleted in an event not on show is a link, to a page that says so.
  const gone = deletedRecords(items);

  function show(next: { action: string; recordType: string; actor: string; offset: number }) {
    const wanted = new URLSearchParams();
    if (next.action) wanted.set("action", next.action);
    if (next.recordType) wanted.set("record_type", next.recordType);
    if (next.actor) wanted.set("actor_hid", next.actor);
    if (next.offset > 0) wanted.set("offset", String(next.offset));
    setParams(wanted);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    show({
      action: wantedAction.trim(),
      recordType: wantedType.trim(),
      actor: wantedActor,
      offset: 0,
    });
  }

  function clear() {
    setWantedAction("");
    setWantedType("");
    setWantedActor("");
    show({ action: "", recordType: "", actor: "", offset: 0 });
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
        {/* 0.9.14: who acted, for an Admin, a retired account among them, marked (P-296). */}
        {admin && (
          <SelectField label="Who" name="actor_hid" value={wantedActor} onChange={setWantedActor}>
            <option value="">Anybody</option>
            {/* An account in the address that the list does not hold is still the choice. */}
            {wantedActor && !actors.data?.some((user) => user.hid === wantedActor) && (
              <option value={wantedActor}>{wantedActor}</option>
            )}
            {(actors.data ?? []).map((user) => (
              <option key={user.hid} value={user.hid}>
                {actorLabel(user)}
              </option>
            ))}
          </SelectField>
        )}
        <button type="submit">Filter</button>
        <button
          type="button"
          onClick={clear}
          disabled={
            !action && !recordType && !actor && !wantedAction && !wantedType && !wantedActor
          }
        >
          Clear
        </button>
      </form>

      <Problem error={actors.error} />
      <Problem error={events.error} />
      {events.loading && !events.data && <p role="status">Loading…</p>}
      {events.data && (
        <>
          <div className="scroll">
            <table className="audit">
              <caption className="visually-hidden">
                Audit events, newest first until a header is clicked
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("time", holdsAll)} column="time">
                    Time
                  </SortTh>
                  <SortTh sort={sort.header("who", holdsAll)} column="who">
                    Who
                  </SortTh>
                  <SortTh sort={sort.header("via", holdsAll)} column="via">
                    Via
                  </SortTh>
                  <SortTh sort={sort.header("action", holdsAll)} column="action">
                    Action
                  </SortTh>
                  <SortTh sort={sort.header("record_type", holdsAll)} column="record_type">
                    Record type
                  </SortTh>
                  <SortTh sort={sort.header("changes", holdsAll)} column="changes">
                    What changed
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(items, holdsAll).map((event) => {
                  const changes = formatChanges(event.changes);
                  const deleted = isDeleted(gone, event);
                  const page = deleted
                    ? null
                    : kindPath(event.record_type, event.record_hid, admin);
                  return (
                    <tr key={event.hid}>
                      <td className="nowrap">
                        <Time at={event.at} />
                      </td>
                      <td>
                        {/* The user who did it: an Admin opens the user's page (P-240). */}
                        {event.actor_name ? (
                          <ValueLink kind="user" hid={event.actor_hid} admin={admin}>
                            {event.actor_name}
                          </ValueLink>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>{event.via}</td>
                      <td>{event.action}</td>
                      <td>
                        {event.record_type}
                        {event.record_hid && (
                          <span className="hid mono">
                            {page ? <Link to={page}>{event.record_hid}</Link> : event.record_hid}
                          </span>
                        )}
                        {deleted && <span className="muted"> · deleted</span>}
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
            onChange={(next) => show({ action, recordType, actor, offset: next })}
          />
        </>
      )}
    </>
  );
}
