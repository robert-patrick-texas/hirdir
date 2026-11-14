import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Addresses } from "../components/Addresses";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, TextField } from "../components/Field";
import { FormFields } from "../components/FormFields";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { MemberPicker } from "../components/MemberPicker";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { addressList, networkLabels, primaryAddress } from "../lib/addresses";
import { formatTime, itemName, plural, today } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import {
  buildMembers,
  type DeviceGroup,
  defaultRole,
  GROUP_TYPES,
  groupTypeLabel,
  MASTER,
  type Member,
  ownerDisputed,
  type PendingMember,
  roleLabel,
  roleOptions,
  rolesOf,
  stackProblem,
} from "../lib/groups";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useGroupOptions, useOwnerOptions, useTags, withCurrent } from "../lib/lists";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import {
  buildCreate,
  type FieldSpec,
  type FormValue,
  type FormValues,
  formOf,
  type Option,
} from "../lib/patch";
import { pickLabel } from "../lib/pick";
import { fieldErrors } from "../lib/problems";
import { allows } from "../lib/roles";

const MEMBERS_PAGE = 100;

function groupPath(hid: string): string {
  return `/groups/${encodeURIComponent(hid)}`;
}

function itemPath(hid: string): string {
  return `/items/${encodeURIComponent(hid)}`;
}

function Dash() {
  return <span className="muted">—</span>;
}

/**
 * The columns of the grid of device groups. The serial number, the master and the
 * number of members are read from the members as the list is asked for: the server
 * neither filters nor sorts by them.
 */
const COLUMNS: GridColumn<DeviceGroup>[] = [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (group) => group.name,
    link: true,
    width: 220,
  },
  {
    id: "type",
    header: "Type",
    kind: "choice",
    value: (group) => groupTypeLabel(group.type),
    choices: GROUP_TYPES,
    width: 160,
  },
  {
    id: "hostname",
    header: "Hostname",
    kind: "text",
    value: (group) => group.hostname,
    width: 180,
  },
  { id: "fqdn", header: "FQDN", kind: "text", value: (group) => group.fqdn, hide: true },
  {
    // For a stack, the serial number of its master.
    id: "serial_number",
    header: "Serial number",
    kind: "text",
    field: null,
    sortField: null,
    value: (group) => group.serial_number,
    mono: true,
    width: 150,
  },
  {
    id: "master",
    header: "Master",
    kind: "text",
    field: null,
    sortField: null,
    column: null,
    value: (group) => (group.master ? itemName(group.master) : ""),
    hide: true,
    width: 180,
  },
  {
    id: "member_count",
    header: "Members",
    kind: "integer",
    field: null,
    sortField: null,
    column: "members",
    value: (group) => String(group.member_count),
    numeric: true,
    width: 110,
  },
  {
    id: "owner.label",
    header: "Owner",
    kind: "text",
    value: (group) => group.owner?.label,
    width: 170,
  },
  {
    id: "parent.name",
    header: "In group",
    kind: "text",
    value: (group) => group.parent?.name,
    width: 170,
  },
  { id: "tags", header: "Tags", kind: "tags", value: (group) => group.tags.join(", "), width: 160 },
  {
    id: "mgmt_address",
    header: "Management address",
    kind: "address",
    field: null,
    sortField: null,
    value: (group) => primaryAddress(group.addresses)?.address,
    mono: true,
    hide: true,
    width: 170,
  },
  {
    id: "address",
    header: "Addresses",
    kind: "address",
    sortField: null,
    column: null,
    value: (group) => addressList(group.addresses),
    mono: true,
    hide: true,
    width: 240,
  },
  {
    id: "network.label",
    header: "Networks",
    kind: "text",
    sortField: null,
    column: null,
    value: (group) => networkLabels(group.addresses).join(", "),
    hide: true,
    width: 140,
  },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (group) => optionLabel(RECORD_STATUSES, group.record_status),
    choices: RECORD_STATUSES,
    hide: true,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (group) => formatTime(group.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (group) => group.hid,
    mono: true,
    hide: true,
  },
];

/** Groups: stacks, clusters, controller domains and other sets of items, in the grid. */
export function DeviceGroups() {
  useTitle("Groups");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);

  return (
    <>
      <h1>Groups</h1>
      {adding && (
        <NewGroup
          onCancel={() => setAdding(false)}
          onCreated={(group) => navigate(groupPath(group.hid))}
        />
      )}
      <DataGrid<DeviceGroup>
        key={startFilter ?? ""}
        id="device-groups"
        noun={["group", "groups"]}
        entity="device_groups"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("post", "/api/v1/device-groups/query", { body: queryBody(request), signal })
        }
        rowId={(group) => group.hid}
        rowLink={(group) => groupPath(group.hid)}
        dimmed={(group) => group.record_status !== "active"}
        shortFilter="type:eq:stack name:prefix:site2-"
        startFilter={startFilter}
        switches={{ archived: "Include retired", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New group
          </button>
        )}
      </DataGrid>
    </>
  );
}

/** The fields of a group that a form sets. `current` is the group being changed, if any. */
function groupSpecs(
  lists: { owners: readonly Option[]; groups: readonly Option[]; tags: readonly string[] },
  current: DeviceGroup | null,
): FieldSpec[] {
  const { owner, parent } = current ?? {};
  return [
    { name: "name", label: "Name", kind: "text", required: true, maxLength: 200 },
    {
      name: "type",
      label: "Type",
      kind: "choice",
      required: true,
      options: GROUP_TYPES,
      hint: "Not changed once the group has had a member",
    },
    {
      name: "hostname",
      label: "Hostname",
      kind: "text",
      maxLength: 255,
      hint: "A stack or a cluster answers to one name; its members usually have none",
    },
    { name: "fqdn", label: "FQDN", kind: "text", maxLength: 255 },
    {
      name: "parent_group_hid",
      label: "In group",
      kind: "choice",
      blank: "In no group",
      options: withCurrent(
        lists.groups.filter((option) => option.value !== current?.hid),
        parent ? { value: parent.hid, label: parent.name } : null,
      ),
      hint: "A cluster of controllers is nested in its controller domain",
    },
    {
      name: "owner_hid",
      label: "Owner",
      kind: "choice",
      blank: "No owner",
      options: withCurrent(lists.owners, owner ? { value: owner.hid, label: owner.label } : null),
    },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft stack may be built up one member at a time, and is not yet one managed node",
    },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...lists.tags, ...(current?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
    },
  ];
}

function useGroupLists() {
  const owners = useOwnerOptions();
  const groups = useGroupOptions();
  const tags = useTags();
  const lists = useMemo(
    () => ({
      owners: owners.data ?? [],
      groups: groups.data ?? [],
      tags: (tags.data ?? []).map((tag) => tag.label),
    }),
    [owners.data, groups.data, tags.data],
  );
  return {
    lists,
    error: owners.error ?? groups.error ?? tags.error,
    ready: !owners.loading && !groups.loading && !tags.loading,
  };
}

interface NewGroupProps {
  onCancel: () => void;
  onCreated: (group: DeviceGroup) => void;
}

/** The form for a new group: its fields, and its first members, sent as one request. */
function NewGroup({ onCancel, onCreated }: NewGroupProps) {
  const { lists, error } = useGroupLists();
  const specs = useMemo(() => groupSpecs(lists, null), [lists]);
  const [values, setValues] = useState<FormValues>(() => ({
    ...formOf(specs),
    type: "stack",
    record_status: "active",
  }));
  const [pending, setPending] = useState<PendingMember[]>([]);
  const [found, setFound] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const action = useAction();
  const names = specs.map((spec) => spec.name);
  const refused = fieldErrors(action.error, names).shown;
  const type = typeof values.type === "string" ? values.type : "stack";
  const status = typeof values.record_status === "string" ? values.record_status : "active";
  const problem = stackProblem(
    type,
    status,
    pending.map((row) => row.role),
  );

  function change(name: string, value: FormValue) {
    setValues((was) => ({ ...was, [name]: value }));
    setFound((was) => {
      const { [name]: _, ...rest } = was;
      return rest;
    });
    if (name === "type" && typeof value === "string") {
      // The roles belong to the type: a role the new type does not have becomes its usual one.
      const allowed = rolesOf(value);
      setPending((rows) =>
        rows.map((row) =>
          allowed.includes(row.role) ? row : { ...row, role: defaultRole(value) },
        ),
      );
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildCreate<Schemas["DeviceGroupCreate"]>(specs, values);
    const members = buildMembers(type, pending);
    setFound(built.errors);
    setRowErrors(members.errors);
    if (Object.keys(built.errors).length > 0 || Object.keys(members.errors).length > 0) {
      action.clear();
      return;
    }
    const body: Schemas["DeviceGroupCreate"] = {
      ...built.body,
      ...(members.members.length > 0 ? { members: members.members } : {}),
    };
    const result = await action.run(() => api.request("post", "/api/v1/device-groups", { body }));
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-group">
      <h2 id="new-group">New group</h2>
      <Problem error={error} />
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={names} />
        <FormFields
          specs={specs}
          values={values}
          onChange={change}
          errors={{ ...refused, ...found }}
          disabled={action.busy}
        />
        <fieldset className="plain">
          <legend>Its first members</legend>
          <p className="hint">
            They are added together with the group, and the group is checked as a whole. A group may
            also be made with none, and given its members later.
          </p>
          <MemberPicker
            type={type}
            pending={pending}
            onChange={setPending}
            errors={rowErrors}
            disabled={action.busy}
          />
          {problem && (
            <p className="warning" role="status" data-testid="stack-problem">
              {problem}
            </p>
          )}
        </fieldset>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Create group
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

/** Groups → one group: what it is, who is in it and was, what is nested in it, its addresses. */
export function DeviceGroupDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const group = useLoad(`device-group ${hid}`, (signal) =>
    api.request("get", "/api/v1/device-groups/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const record = group.data;
  useTitle(record ? record.name : "Group");

  function changed(text: string) {
    setDone(text);
    group.reload();
  }

  const open = mayEdit && record?.record_status !== "retired";
  return (
    <>
      <p className="crumbs">
        <Link to="/groups">Groups</Link>
      </p>
      <h1>
        {record ? record.name : "Group"}
        {record && <span className="badge badge-plain">{groupTypeLabel(record.type)}</span>}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={group.error} />
      <Notice text={done} />
      {group.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <GroupFacts group={record} />
          <Members group={record} mayEdit={open} onChanged={changed} />
          <Nested group={record} />
          <Addresses
            key={`addresses ${record.hid}`}
            holder={{ group_hid: record.hid }}
            whose={record.name}
            mayEdit={open}
          />
          {open && (
            <GroupDetails
              key={`details ${record.hid} ${record.row_version}`}
              group={record}
              onSaved={() => changed("The group was saved.")}
              onReload={group.reload}
            />
          )}
          {mayEdit && (
            <GroupStatus
              key={`status ${record.hid} ${record.row_version}`}
              group={record}
              onChanged={changed}
              onReload={group.reload}
            />
          )}
        </>
      )}
    </>
  );
}

function GroupFacts({ group }: { group: DeviceGroup }) {
  const { owner, parent, master } = group;
  const disputed = ownerDisputed(group);
  const members = `/items?filter=${encodeURIComponent(`group.hid:eq:${group.hid}`)}`;
  return (
    <section aria-labelledby="group-facts">
      <h2 id="group-facts">The group</h2>
      <dl className="facts">
        <dt>Type</dt>
        <dd>{groupTypeLabel(group.type)}</dd>
        <dt>Hostname</dt>
        <dd>{group.hostname || <Dash />}</dd>
        <dt>FQDN</dt>
        <dd>{group.fqdn || <Dash />}</dd>
        {group.type === "stack" && (
          <>
            <dt>Serial number</dt>
            <dd>
              {group.serial_number ? (
                <span className="mono" data-testid="group-serial">
                  {group.serial_number}
                </span>
              ) : (
                <Dash />
              )}
              <span className="muted"> · read from its master, and stored nowhere</span>
            </dd>
            <dt>Master</dt>
            <dd data-testid="group-master">
              {master ? <Link to={itemPath(master.hid)}>{pickLabel(master)}</Link> : <Dash />}
            </dd>
          </>
        )}
        <dt>Members</dt>
        <dd>
          <span data-testid="member-count">{plural(group.member_count, "current member")}</span>
          {group.member_count > 0 && (
            <>
              {" · "}
              <Link to={members}>in the grid of items</Link>
            </>
          )}
        </dd>
        <dt>Owner</dt>
        <dd data-testid="group-owner" data-disputed={disputed ? "true" : "false"}>
          {owner ? (
            <Link to={`/owners/${encodeURIComponent(owner.hid)}`}>{owner.label}</Link>
          ) : (
            <Dash />
          )}
          {disputed && <span className="badge">Members disagree</span>}
        </dd>
        <dt>In group</dt>
        <dd>{parent ? <Link to={groupPath(parent.hid)}>{parent.name}</Link> : <Dash />}</dd>
        <dt>Tags</dt>
        <dd>{group.tags.join(", ") || <Dash />}</dd>
        <dt>Changed</dt>
        <dd>
          <Time at={group.updated_at} />
        </dd>
        <dt>HID</dt>
        <dd className="mono">{group.hid}</dd>
      </dl>
      {disputed && (
        <p className="warning" data-testid="owner-disputed">
          The owner above is the group's own. At least one current member has another owner in
          force: see the Owner column of its members in the grid of items.
        </p>
      )}
    </section>
  );
}

interface MembersProps {
  group: DeviceGroup;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * Who is in the group, by position, and who was. Members are added several at a time,
 * a membership is ended with a date and never removed, and in a stack another member
 * is made the master by one change.
 */
function Members({ group, mayEdit, onChanged }: MembersProps) {
  const [past, setPast] = useState(false);
  const [offset, setOffset] = useState(0);
  const [turn, setTurn] = useState(0);
  const [editing, setEditing] = useState<{ hid: string; what: "change" | "end" } | null>(null);
  const [adding, setAdding] = useState(false);
  const action = useAction();
  const members = useLoad(`members ${group.hid} ${past} ${offset} ${turn}`, (signal) =>
    api.request("get", "/api/v1/device-groups/{hid}/members", {
      path: { hid: group.hid },
      query: { include_past: past, limit: MEMBERS_PAGE, offset },
      signal,
    }),
  );
  const rows = members.data?.items ?? [];
  const current = rows.filter((member) => member.left_on === null);
  // Every current member is on show: what a stack would be with more can be said early.
  const whole = offset === 0 && current.length === group.member_count;
  const open = rows.find((member) => member.hid === editing?.hid) ?? null;

  function changed(text: string) {
    setEditing(null);
    setAdding(false);
    setTurn((count) => count + 1);
    onChanged(text);
  }

  async function makeMaster(member: Member) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}/members/{member_hid}", {
        path: { hid: group.hid, member_hid: member.hid },
        body: { row_version: member.row_version, role: MASTER },
      }),
    );
    if (result.ok) changed(`${itemName(member.item)} is now the master of ${group.name}.`);
  }

  return (
    <section aria-labelledby="members">
      <h2 id="members">Members</h2>
      <div className="inline">
        <CheckField
          label="Show past memberships"
          name="include_past"
          checked={past}
          onChange={(on) => {
            setPast(on);
            setOffset(0);
          }}
        />
      </div>
      <Problem error={members.error} />
      <Problem error={action.error} onReload={() => setTurn((count) => count + 1)} />
      {members.loading && !members.data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {members.data && rows.length === 0 && (
        <p className="muted">
          {group.name} has no {past ? "" : "current "}member.
        </p>
      )}
      {rows.length > 0 && (
        <div className="scroll">
          <table data-testid="members">
            <caption className="visually-hidden">
              The members of {group.name}, by position, the current ones first
            </caption>
            <thead>
              <tr>
                <th scope="col">Position</th>
                <th scope="col">Item</th>
                <th scope="col">PID</th>
                <th scope="col">Serial number</th>
                <th scope="col">Role</th>
                <th scope="col">Joined</th>
                <th scope="col">Left</th>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((member) => {
                const name = itemName(member.item);
                const ended = member.left_on !== null;
                return (
                  <tr
                    key={member.hid}
                    data-item={member.item_hid}
                    data-role={member.role}
                    data-current={ended ? "false" : "true"}
                    className={ended ? "muted" : undefined}
                  >
                    <td>{member.position ?? <Dash />}</td>
                    <th scope="row">
                      <Link to={itemPath(member.item_hid)}>{name}</Link>
                    </th>
                    <td>{member.item.pid || <Dash />}</td>
                    <td className="mono">{member.item.serial_number || <Dash />}</td>
                    <td>{roleLabel(member.role)}</td>
                    <td className="nowrap">{member.joined_on}</td>
                    <td className="nowrap">{member.left_on ?? <Dash />}</td>
                    {mayEdit && (
                      <td className="row-actions">
                        {!ended && group.type === "stack" && member.role !== MASTER && (
                          <button
                            type="button"
                            disabled={action.busy}
                            onClick={() => makeMaster(member)}
                            aria-label={`Make ${name} the master`}
                          >
                            Make master
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={action.busy}
                          onClick={() => {
                            setAdding(false);
                            setEditing({ hid: member.hid, what: "change" });
                          }}
                          aria-label={
                            ended
                              ? `Correct the dates of ${name}`
                              : `Change the membership of ${name}`
                          }
                        >
                          {ended ? "Correct dates" : "Change"}
                        </button>
                        {!ended && (
                          <button
                            type="button"
                            disabled={action.busy}
                            onClick={() => {
                              setAdding(false);
                              setEditing({ hid: member.hid, what: "end" });
                            }}
                            aria-label={`End the membership of ${name}`}
                          >
                            End
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
      {members.data && members.data.total > MEMBERS_PAGE && (
        <Pager
          total={members.data.total}
          limit={MEMBERS_PAGE}
          offset={offset}
          noun="memberships"
          onChange={setOffset}
        />
      )}
      {mayEdit && open && editing?.what === "change" && (
        <ChangeMember
          key={`${open.hid} ${open.row_version}`}
          group={group}
          member={open}
          onSaved={() => changed(`The membership of ${itemName(open.item)} was saved.`)}
          onReload={() => setTurn((count) => count + 1)}
          onClose={() => setEditing(null)}
        />
      )}
      {mayEdit && open && editing?.what === "end" && (
        <EndMembership
          key={`${open.hid} ${open.row_version}`}
          group={group}
          member={open}
          onEnded={(day) => changed(`The membership of ${itemName(open.item)} ended on ${day}.`)}
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
            Add members
          </button>
        </p>
      )}
      {mayEdit && adding && (
        <AddMembers
          group={group}
          current={whole ? current : null}
          taken={current.map((member) => member.item_hid)}
          onCancel={() => setAdding(false)}
          onAdded={(count) => changed(`${plural(count, "member")} added to ${group.name}.`)}
        />
      )}
    </section>
  );
}

interface AddMembersProps {
  group: DeviceGroup;
  /** Every current member, when they are all known; otherwise null. */
  current: readonly Member[] | null;
  taken: readonly string[];
  onCancel: () => void;
  onAdded: (count: number) => void;
}

/** Add several members by one request, so that the group is checked once they are all in. */
function AddMembers({ group, current, taken, onCancel, onAdded }: AddMembersProps) {
  const [pending, setPending] = useState<PendingMember[]>([]);
  const [joined, setJoined] = useState("");
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const action = useAction();
  const known = ["joined_on"];
  const refused = fieldErrors(action.error, known).shown;
  const problem =
    current === null || pending.length === 0
      ? ""
      : stackProblem(group.type, group.record_status, [
          ...current.map((member) => member.role),
          ...pending.map((row) => row.role),
        ]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildMembers(group.type, pending, joined);
    setRowErrors(built.errors);
    if (Object.keys(built.errors).length > 0) {
      action.clear();
      return;
    }
    const result = await action.run(() =>
      api.request("post", "/api/v1/device-groups/{hid}/members", {
        path: { hid: group.hid },
        body: { members: built.members },
      }),
    );
    if (result.ok) onAdded(built.members.length);
  }

  return (
    <section className="panel" aria-labelledby="add-members">
      <h3 id="add-members">Add members</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} />
        <MemberPicker
          type={group.type}
          pending={pending}
          onChange={setPending}
          taken={taken}
          positions={(current ?? []).map((member) => member.position)}
          errors={rowErrors}
          disabled={action.busy}
        />
        <div className="fields">
          <TextField
            label="Joined on"
            name="joined_on"
            type="date"
            value={joined}
            onChange={setJoined}
            error={refused.joined_on}
            hint={`Left blank, today: ${today()}`}
          />
        </div>
        {problem && (
          <p className="warning" role="status" data-testid="stack-problem">
            {problem}
          </p>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || pending.length === 0}>
            {pending.length > 1 ? `Add ${pending.length} members` : "Add member"}
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

interface OneMemberProps {
  group: DeviceGroup;
  member: Member;
  onReload: () => void;
  onClose: () => void;
}

/** Change a membership: its role, its position or its dates. One that has ended keeps only its dates to correct. */
function ChangeMember({
  group,
  member,
  onSaved,
  onReload,
  onClose,
}: OneMemberProps & { onSaved: () => void }) {
  const ended = member.left_on !== null;
  const specs = useMemo<FieldSpec[]>(
    () => [
      ...(ended
        ? []
        : ([
            { name: "role", label: "Role", kind: "choice", options: roleOptions(group.type) },
            {
              name: "position",
              label: "Position",
              kind: "integer",
              hint: "The member number in a stack",
            },
          ] satisfies FieldSpec[])),
      { name: "joined_on", label: "Joined on", kind: "date" },
      ...(ended
        ? ([{ name: "left_on", label: "Left on", kind: "date" }] satisfies FieldSpec[])
        : []),
    ],
    [group.type, ended],
  );
  return (
    <section className="panel" aria-labelledby="change-member">
      <h3 id="change-member">The membership of {itemName(member.item)}</h3>
      {ended && (
        <p className="hint">
          This membership has ended: only its dates are corrected. An item that is back is added
          again, with a new membership.
        </p>
      )}
      <EditForm<Member, Schemas["MemberPatch"]>
        specs={specs}
        record={member}
        save={(body) =>
          api.request("patch", "/api/v1/device-groups/{hid}/members/{member_hid}", {
            path: { hid: group.hid, member_hid: member.hid },
            body,
          })
        }
        onSaved={onSaved}
        onReload={onReload}
        submitLabel="Save membership"
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}

/** End a membership on a day. It is kept, with its dates; nothing is removed. */
function EndMembership({
  group,
  member,
  onEnded,
  onReload,
  onClose,
}: OneMemberProps & { onEnded: (day: string) => void }) {
  const [day, setDay] = useState(() => today());
  const action = useAction();
  const known = ["left_on"];
  const refused = fieldErrors(action.error, known).shown;
  const name = itemName(member.item);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}/members/{member_hid}", {
        path: { hid: group.hid, member_hid: member.hid },
        body: { row_version: member.row_version, left_on: day },
      }),
    );
    if (result.ok) onEnded(day);
  }

  return (
    <section className="panel" aria-labelledby="end-member">
      <h3 id="end-member">End the membership of {name}</h3>
      <p className="hint">
        The membership is kept with the day it ended, and {name} is free to join again.
        {group.type === "stack" &&
          " The master does not leave a stack that has other members: make another the master first."}
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} onReload={onReload} />
        <div className="fields">
          <TextField
            label="Left on"
            name="left_on"
            type="date"
            value={day}
            onChange={setDay}
            required
            error={refused.left_on}
            hint={`Not before the day it joined, ${member.joined_on}`}
          />
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || day === ""}>
            End membership
          </button>
          <button type="button" onClick={onClose} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}

/** The groups nested directly in this one, as the cluster of controllers in its domain. */
function Nested({ group }: { group: DeviceGroup }) {
  return (
    <section aria-labelledby="nested">
      <h2 id="nested">Groups in this group</h2>
      {group.groups.length === 0 ? (
        <p className="muted">No group is nested in {group.name}.</p>
      ) : (
        <ul data-testid="nested-groups">
          {group.groups.map((inner) => (
            <li key={inner.hid}>
              <Link to={groupPath(inner.hid)}>{inner.name}</Link>
              <span className="muted"> · {groupTypeLabel(inner.type)}</span>
            </li>
          ))}
        </ul>
      )}
      {group.type === "controller_domain" && (
        <p className="hint">
          The controllers of an endpoint of this domain are its members with the role Controller,
          and the current members of every cluster nested here.
        </p>
      )}
    </section>
  );
}

interface GroupDetailsProps {
  group: DeviceGroup;
  onSaved: () => void;
  onReload: () => void;
}

function GroupDetails({ group, onSaved, onReload }: GroupDetailsProps) {
  const { lists, error, ready } = useGroupLists();
  const specs = useMemo(() => groupSpecs(lists, group), [lists, group]);
  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <Problem error={error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && (
        <EditForm<DeviceGroup, Schemas["DeviceGroupPatch"]>
          specs={specs}
          record={group}
          save={(body) =>
            api.request("patch", "/api/v1/device-groups/{hid}", { path: { hid: group.hid }, body })
          }
          onSaved={onSaved}
          onReload={onReload}
        />
      )}
    </section>
  );
}

interface GroupStatusProps {
  group: DeviceGroup;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** Retire a group, or bring a retired one back. Nothing is ever deleted. */
function GroupStatus({ group, onChanged, onReload }: GroupStatusProps) {
  const action = useAction();

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/device-groups/{hid}/retire", {
        path: { hid: group.hid },
        body: { row_version: group.row_version },
      }),
    );
    if (result.ok) onChanged("The group was retired, and its memberships ended today.");
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}", {
        path: { hid: group.hid },
        body: { row_version: group.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged("The group is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{group.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {group.record_status === "retired" ? (
        <>
          <p>
            This group is retired. Its record and its past memberships are kept. Brought back, it
            has no current member until members are added again.
          </p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
        </>
      ) : (
        <>
          <p>
            Retiring a group ends its current memberships today, so that its items are free to join
            another. The record and the memberships are kept, and the group can be brought back.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Retire group"
              title={`Retire ${group.name}?`}
              confirmLabel="Retire group"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>
                {group.member_count > 0
                  ? `The ${plural(group.member_count, "current membership")} of ${group.name} will end today.`
                  : "The group has no current member."}
              </p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
