import { type FormEvent, Fragment, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Addresses, ManagementAddresses } from "../components/Addresses";
import { BringBackElsewhere, refusedForItsPlace } from "../components/BringBack";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, SelectField, TextField } from "../components/Field";
import { FormFields } from "../components/FormFields";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { HealthWithReasons, Observation, ObservedText } from "../components/Health";
import { MemberPicker } from "../components/MemberPicker";
import { Operator, OperatorNote } from "../components/Operator";
import { Pager } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { addressList, managementText, networkLabels } from "../lib/addresses";
import { itemsPath } from "../lib/filter";
import { formatTime, itemName, plural, today } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import {
  buildMembers,
  type DeviceGroup,
  defaultRole,
  GROUP_TYPES,
  groupTypeLabel,
  MANAGED_AS,
  MASTER,
  type Member,
  managedAsText,
  ownerDisputed,
  type PendingMember,
  roleLabel,
  roleOptions,
  rolesOf,
  serialSourceText,
  stackProblem,
  takesTheMark,
} from "../lib/groups";
import { healthLabel, OBSERVED, observedLabel, reasonsText } from "../lib/health";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useGroupOptions, useOwnerOptions, useTags, withCurrent } from "../lib/lists";
import {
  markOf,
  markTitle,
  operatorOptionLabel,
  operatorPath,
  operatorSource,
} from "../lib/operators";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import { ownerOption } from "../lib/owners";
import {
  buildCreate,
  type FieldSpec,
  type FormValue,
  type FormValues,
  formOf,
  type Option,
} from "../lib/patch";
import { pickLabel } from "../lib/pick";
import { placePath, planMembersPath } from "../lib/places";
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
 * The columns of the grid of device groups. The serial number, the two masters, the
 * number of members and the health are read from the members as the list is asked for,
 * and the server does not sort by them. A stack answers to the serial number of any of
 * its current members, so that is what the Serial number column filters by. The health
 * of a group is shown and not yet filtered by.
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
    // For a stack: the serial number of the master that is seen, or else of the one
    // intended. The filter finds a stack by the serial number of any current member.
    id: "serial_number",
    header: "Serial number",
    kind: "text",
    field: "member.serial_number",
    sortField: null,
    value: (group) => group.serial_number,
    hint: (group) =>
      group.serial_source ? `The serial number is ${serialSourceText(group.serial_source)}` : "",
    mono: true,
    width: 150,
  },
  {
    id: "health",
    header: "Health",
    kind: "choice",
    field: null,
    sortField: null,
    value: (group) => healthLabel(group.health?.value),
    mark: (group) => group.health?.value,
    hint: (group) => reasonsText(group.health),
    width: 130,
  },
  {
    id: "master",
    header: "Intended master",
    kind: "text",
    field: null,
    sortField: null,
    column: null,
    value: (group) => (group.master ? itemName(group.master) : ""),
    hide: true,
    width: 180,
  },
  {
    id: "observed_master",
    header: "Master seen",
    kind: "text",
    field: null,
    sortField: null,
    column: null,
    value: (group) => (group.observed_master ? itemName(group.observed_master) : ""),
    hint: (group) =>
      group.master_as_intended === false ? "Not the intended master, which is no fault" : "",
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
    id: "expected_members",
    header: "Expected members",
    kind: "integer",
    value: (group) => (group.expected_members === null ? "" : String(group.expected_members)),
    numeric: true,
    hide: true,
    width: 160,
  },
  {
    id: "observed_status",
    header: "Observed status",
    kind: "choice",
    value: (group) => observedLabel(group.observed_status),
    choices: OBSERVED,
    hide: true,
    width: 150,
  },
  {
    id: "observed_at",
    header: "Observed at",
    kind: "timestamp",
    value: (group) => formatTime(group.observed_at),
    hide: true,
  },
  {
    // A cluster only: what it is on the network, and so how many managed nodes.
    id: "managed_as",
    header: "Managed as",
    kind: "choice",
    value: (group) => managedAsText(group.managed_as),
    choices: MANAGED_AS.map((way) => ({ value: way.value, label: way.nodes })),
    hide: true,
    width: 220,
  },
  {
    id: "owner.label",
    header: "Owner",
    kind: "text",
    value: (group) => group.owner?.label,
    width: 170,
  },
  {
    // The group's own operator, by its label: what the list of groups filters and sorts
    // by. A group with none of its own may have one from a group it is nested in or from
    // where it is, which its page shows and the hint of the cell says.
    id: "operator.label",
    header: "Operator",
    kind: "text",
    column: "operator",
    value: (group) => group.operator?.label,
    chip: (group) => {
      const mark = markOf(group.operator);
      return (
        mark && {
          colour: mark.colour,
          path: operatorPath(mark.hid),
          ...(mark.open ? { note: "open" } : {}),
        }
      );
    },
    hint: (group) => {
      const own = markOf(group.operator);
      if (own) return markTitle(own);
      const inForce = group.effective.operator_hid;
      const from = operatorSource(inForce);
      return from && inForce.label
        ? `None of its own: ${inForce.label}, inherited from ${from.text}`
        : "";
    },
    hide: true,
    width: 180,
  },
  {
    // True for a group whose owner is outside the operations team. A file of groups
    // has no such column.
    id: "owner_exception",
    header: "Outside the team",
    kind: "boolean",
    column: null,
    value: (group) => (group.owner_exception ? "Yes" : "No"),
    hide: true,
    width: 160,
  },
  {
    id: "parent.name",
    header: "In group",
    kind: "text",
    value: (group) => group.parent?.name,
    width: 170,
  },
  {
    // The location of a group that is in one place, by its name: what the list filters
    // and sorts by. The whole path is the hint of the cell, and what an export writes.
    id: "location.name",
    header: "Location",
    kind: "text",
    column: "location",
    value: (group) => group.location?.name,
    hint: (group) => group.location?.path,
    hide: true,
    width: 200,
  },
  {
    // Where the group is going: a place that is not in use yet. The list finds it with
    // `planned_location:within:<place>` in the filter box; the column has no filter.
    id: "planned_location",
    header: "Planned location",
    kind: "text",
    field: null,
    sortField: null,
    value: (group) => group.planned_location?.name,
    hint: (group) => group.planned_location?.path,
    hide: true,
    width: 200,
  },
  {
    id: "site",
    header: "Site",
    kind: "text",
    column: null,
    value: (group) => group.location?.site,
    hide: true,
    width: 150,
  },
  {
    // The region the site is in, by its name. A file of groups has no such column.
    id: "region",
    header: "Region",
    kind: "text",
    column: null,
    value: (group) => group.location?.region,
    hide: true,
    width: 150,
  },
  { id: "tags", header: "Tags", kind: "tags", value: (group) => group.tags.join(", "), width: 160 },
  {
    // The primary one of each family. An export writes a column for each.
    id: "mgmt_address",
    header: "Management address",
    kind: "address",
    field: null,
    sortField: null,
    column: ["mgmt_ipv4", "mgmt_ipv6"],
    value: (group) => managementText(group.addresses),
    mono: true,
    hide: true,
    width: 240,
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

/**
 * The fields of a group that a form sets. `current` is the group being changed, if any,
 * and `type` the type the form holds: only a cluster says how it is managed.
 */
function groupSpecs(
  lists: { owners: readonly Option[]; groups: readonly Option[]; tags: readonly string[] },
  current: DeviceGroup | null,
  type: string,
): FieldSpec[] {
  const { owner, parent, location } = current ?? {};
  const managed: FieldSpec[] =
    type === "cluster"
      ? [
          {
            name: "managed_as",
            label: "Managed as",
            kind: "choice",
            options: MANAGED_AS,
            ...(current ? {} : { blank: "Not said: one managed node" }),
            hint: "What the cluster is on the network. The three ways are explained above the form.",
          },
        ]
      : [];
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
    ...managed,
    {
      name: "expected_members",
      label: "Expected members",
      kind: "integer",
      hint:
        type === "stack"
          ? "How many members it is meant to have. With fewer it shows as degraded, also once a failed switch has been taken out. Left blank, a stack that is one switch alone is degraded: say 1 for a stack that is meant to be one."
          : type === "cluster"
            ? "How many members it is meant to have. With fewer it shows as degraded."
            : "How many members it is meant to have. Optional.",
    },
    {
      name: "parent_group_hid",
      label: "In group",
      kind: "choice",
      blank: "In no group",
      options: withCurrent(
        lists.groups.filter((option) => option.value !== current?.hid),
        parent ? { value: parent.hid, label: parent.name } : null,
      ),
      hint: "A cluster of controllers is nested in its controller domain. A domain may hold several.",
    },
    {
      name: "owner_hid",
      label: "Owner",
      kind: "choice",
      blank: "No owner",
      options: withCurrent(
        lists.owners,
        owner
          ? ownerOption({ ...owner, exception_reason: current?.owner_exception_reason ?? null })
          : null,
      ),
    },
    {
      name: "operator_hid",
      label: "Operator",
      kind: "operator",
      blank: "None of its own",
      options: current?.operator
        ? [{ value: current.operator.hid, label: operatorOptionLabel(current.operator) }]
        : [],
      hint: "The label of who of the team looks after it. Its members have this operator unless they have their own.",
    },
    {
      name: "location_hid",
      label: "Location",
      kind: "location",
      blank: "No location",
      options: location ? [{ value: location.hid, label: location.path }] : [],
      hint: "For a group that is in one place.",
    },
    {
      name: "planned_location_hid",
      label: "Planned location",
      kind: "planned_location",
      blank: "No plan",
      options: current?.planned_location
        ? [{ value: current.planned_location.hid, label: current.planned_location.path }]
        : [],
      hint: "Where the group is going, when that place is not in use yet. It stays where it is until the place is made active, and is then moved there by that change. Its members are items with plans of their own.",
    },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint:
        type === "stack" || type === "cluster"
          ? `A draft ${type} is not yet one managed node: its members count as the items they are`
          : "A draft is left out of default views",
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

/** The three ways a cluster is managed, each explained: shown with the form of a cluster. */
function ManagedAsHelp() {
  return (
    <div data-testid="managed-as-help">
      <p className="hint">
        A cluster says how it is managed: what it is on the network, and so how many managed nodes
        it counts as. The component count and the support weight do not depend on it.
      </p>
      <dl className="facts">
        {MANAGED_AS.map((way) => (
          <Fragment key={way.value}>
            <dt>{way.label}</dt>
            <dd>{way.explained}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
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
  const [values, setValues] = useState<FormValues>(() => ({
    ...formOf(groupSpecs(lists, null, "cluster")),
    type: "stack",
    record_status: "active",
  }));
  const type = typeof values.type === "string" ? values.type : "stack";
  const specs = useMemo(() => groupSpecs(lists, null, type), [lists, type]);
  const [pending, setPending] = useState<PendingMember[]>([]);
  const [found, setFound] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const action = useAction();
  const names = specs.map((spec) => spec.name);
  const refused = fieldErrors(action.error, names).shown;
  const problem = stackProblem(
    type,
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
        {type === "cluster" && <ManagedAsHelp />}
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
            They are added together with the group, by one request. A group may also be made with
            none, and given its members later.
            {type === "stack" &&
              " A stack may be one switch alone. The role Intended master marks the member given the priority: it is optional, and at most one member has it. Which member is seen to be master is recorded on the page of the stack."}
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
          {record.health && (
            <GroupHealth
              key={`health ${record.hid} ${record.row_version}`}
              group={record}
              health={record.health}
              mayEdit={open}
              onChanged={changed}
              onReload={group.reload}
            />
          )}
          <Members group={record} mayEdit={open} onChanged={changed} onReload={group.reload} />
          <Nested group={record} />
          <Addresses
            key={`addresses ${record.hid}`}
            holder={{ group_hid: record.hid }}
            whose={record.name}
            mayEdit={open}
            onChanged={group.reload}
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
  const { owner, parent, location, master, observed_master: seen } = group;
  const { user } = useAuth();
  // Planning the members is a bulk edit of items, which needs the Inventory role.
  const mayPlan = allows(user.role, "inventory");
  const disputed = ownerDisputed(group);
  const members = itemsPath(`group.hid:eq:${group.hid}`);
  const source = serialSourceText(group.serial_source);
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
              <span
                className="muted"
                data-testid="serial-source"
                data-source={group.serial_source ?? ""}
              >
                {source
                  ? ` · ${source}, and stored nowhere`
                  : " · no master is recorded to read it from"}
              </span>
            </dd>
            <dt>Intended master</dt>
            <dd data-testid="group-master">
              {master ? (
                <Link to={itemPath(master.hid)}>{pickLabel(master)}</Link>
              ) : (
                <span className="muted">None is marked</span>
              )}
            </dd>
            <dt>Master seen</dt>
            <dd data-testid="group-observed-master">
              {seen ? (
                <>
                  <Link to={itemPath(seen.hid)}>{pickLabel(seen)}</Link>
                  <span className="muted"> · seen </span>
                  <Time at={group.master_observed_at} />
                </>
              ) : (
                <span className="muted">Nobody has recorded one</span>
              )}
            </dd>
          </>
        )}
        {group.type === "cluster" && (
          <>
            <dt>Managed as</dt>
            <dd data-testid="managed-as" data-managed-as={group.managed_as ?? ""}>
              {managedAsText(group.managed_as) || <Dash />}
            </dd>
          </>
        )}
        <dt>Management address</dt>
        <dd>
          <ManagementAddresses addresses={group.addresses} />
        </dd>
        <dt>Members</dt>
        <dd>
          <span data-testid="member-count">{plural(group.member_count, "current member")}</span>
          {group.member_count > 0 && (
            <>
              {" · "}
              <Link to={members}>in the grid of items</Link>
            </>
          )}
          {group.expected_members !== null && (
            <span className="muted" data-testid="expected-members">
              {" "}
              · {group.expected_members} expected
            </span>
          )}
        </dd>
        {!group.health && group.observed_status && (
          <>
            <dt>Observed</dt>
            <dd>
              <ObservedText status={group.observed_status} at={group.observed_at} />
            </dd>
          </>
        )}
        <dt>Owner</dt>
        <dd data-testid="group-owner" data-disputed={disputed ? "true" : "false"}>
          {owner ? (
            <Link to={`/owners/${encodeURIComponent(owner.hid)}`}>{owner.label}</Link>
          ) : (
            <Dash />
          )}
          {group.owner_exception && (
            <span className="badge" data-testid="group-owner-exception">
              Outside the operations team
            </span>
          )}
          {disputed && <span className="badge">Members disagree</span>}
        </dd>
        {group.owner_exception && owner && (
          <>
            <dt>Reason for the exception</dt>
            <dd>
              <span data-testid="group-owner-exception-reason">
                {group.owner_exception_reason || <Dash />}
              </span>
              <span className="muted">
                {" "}
                · the owner&apos;s own reason, changed on{" "}
                <Link to={`/owners/${encodeURIComponent(owner.hid)}`}>the page of the owner</Link>
              </span>
            </dd>
          </>
        )}
        <dt>Operator</dt>
        <dd>
          <Operator effective={group.effective.operator_hid} testId="group-operator" />
          {typeof group.effective.operator_hid.value === "string" && (
            <span className="muted" data-testid="group-operator-members">
              {" "}
              · its members have this operator unless they have their own
            </span>
          )}
        </dd>
        <dt>Location</dt>
        <dd data-testid="group-location">
          {location ? (
            <>
              <Link to={placePath("location", location.hid)}>{location.path}</Link>
              <span className="muted">
                {" "}
                · site <Link to={placePath("site", location.site_hid)}>{location.site}</Link>
                {" · region "}
                <Link to={placePath("region", location.region_hid)}>{location.region}</Link>
              </span>
            </>
          ) : (
            <Dash />
          )}
        </dd>
        {group.planned_location && (
          <>
            <dt>Planned location</dt>
            <dd>
              <span data-testid="group-planned-location">
                Planned for{" "}
                <Link to={placePath("location", group.planned_location.hid)}>
                  {group.planned_location.path}
                </Link>
                , when that place is made active
              </span>
              <span className="muted">
                {" "}
                · the plan moves the group. Its members are items with plans of their own
                {mayPlan && group.member_count > 0 ? ": " : "."}
              </span>
              {mayPlan && group.member_count > 0 && (
                <Link
                  to={planMembersPath(group.hid, group.planned_location.hid)}
                  data-testid="plan-members"
                >
                  plan its {plural(group.member_count, "current member")} for the same place
                </Link>
              )}
            </dd>
          </>
        )}
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
      {group.master_as_intended === false && (
        <p className="note" data-testid="master-differs">
          The master that is seen is not the one intended. A stack chooses its master as it boots,
          and the choice may move from one member to another, so the two may differ: this is no
          fault. The serial number of the stack is that of the master that is seen.
        </p>
      )}
      {disputed && (
        <p className="warning" data-testid="owner-disputed">
          The owner above is the group's own. At least one current member has another owner in
          force: see the Owner column of its members in the grid of items.
        </p>
      )}
    </section>
  );
}

interface GroupHealthProps {
  group: DeviceGroup;
  health: NonNullable<DeviceGroup["health"]>;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * How a stack or a cluster is doing: its health with the reasons, worked out by the
 * server from its current members, and what is seen of the group as one device.
 */
function GroupHealth({ group, health, mayEdit, onChanged, onReload }: GroupHealthProps) {
  const seeing = useAction();
  const what = groupTypeLabel(group.type).toLowerCase();
  return (
    <section aria-labelledby="group-doing">
      <h2 id="group-doing">Health</h2>
      <dl className="facts">
        <dt>Health</dt>
        <dd>
          <HealthWithReasons health={health} testId="health" />
        </dd>
        <dt>Observed</dt>
        <dd data-testid="observed" data-observed={group.observed_status ?? ""}>
          <ObservedText status={group.observed_status} at={group.observed_at} />
        </dd>
        <dt>Expected members</dt>
        <dd>
          {group.expected_members === null ? (
            <span className="muted">No number is named</span>
          ) : (
            String(group.expected_members)
          )}
          <span className="muted"> · it has {plural(group.member_count, "current member")}</span>
        </dd>
      </dl>
      <p className="hint">
        The health of a {what} is worked out from its current members each time it is read: from the
        health of each, from a member that is in Down or Pending-Removal, from whether it has the
        members it is expected to have, and from what is observed of the {what} itself as one
        device.
        {group.type === "stack" &&
          " A stack that names no number of expected members is degraded when it is one switch alone."}{" "}
        The number of expected members is set under Details.
      </p>
      {mayEdit && (
        <section aria-labelledby="set-observed" className="panel">
          <h3 id="set-observed">Record what is seen of the {what}</h3>
          <Observation
            whose={group.name}
            status={group.observed_status}
            busy={seeing.busy}
            error={seeing.error}
            onReload={onReload}
            onChange={async (patch, done) => {
              const result = await seeing.run(() =>
                api.request("patch", "/api/v1/device-groups/{hid}", {
                  path: { hid: group.hid },
                  body: { row_version: group.row_version, ...patch },
                }),
              );
              if (result.ok) onChanged(done);
            }}
          />
        </section>
      )}
    </section>
  );
}

interface MembersProps {
  group: DeviceGroup;
  mayEdit: boolean;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * Who is in the group, by position, and who was. Members are added several at a time,
 * and a membership is ended with a date and never removed. In a stack one member may be
 * marked as the intended master, which takes the mark from the one that had it, and the
 * master that is seen is recorded apart.
 */
function Members({ group, mayEdit, onChanged, onReload }: MembersProps) {
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

  async function markMaster(member: Member) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}/members/{member_hid}", {
        path: { hid: group.hid, member_hid: member.hid },
        body: { row_version: member.row_version, role: MASTER },
      }),
    );
    if (result.ok) {
      changed(`${itemName(member.item)} is now the intended master of ${group.name}.`);
    }
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
                {group.type === "stack" && <th scope="col">Seen as master</th>}
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
                const seen = !ended && group.observed_master_hid === member.item_hid;
                return (
                  <tr
                    key={member.hid}
                    data-item={member.item_hid}
                    data-role={member.role}
                    data-seen-master={seen ? "true" : "false"}
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
                    {group.type === "stack" && <td>{seen ? "Seen as master" : ""}</td>}
                    <td className="nowrap">{member.joined_on}</td>
                    <td className="nowrap">{member.left_on ?? <Dash />}</td>
                    {mayEdit && (
                      <td className="row-actions">
                        {!ended && group.type === "stack" && member.role !== MASTER && (
                          <button
                            type="button"
                            disabled={action.busy}
                            onClick={() => markMaster(member)}
                            aria-label={`Mark ${name} as the intended master`}
                          >
                            Mark as intended master
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
      {mayEdit && group.type === "stack" && (current.length > 0 || group.observed_master_hid) && (
        <ObservedMaster
          key={`seen ${group.hid} ${group.row_version}`}
          group={group}
          current={current}
          onChanged={changed}
          onReload={onReload}
        />
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

interface ObservedMasterProps {
  group: DeviceGroup;
  /** The current members on show: any of them may be the master that is seen. */
  current: readonly Member[];
  onChanged: (text: string) => void;
  onReload: () => void;
}

/**
 * The master that is seen: which member the stack made master, recorded with the moment.
 * It is set to any current member, stated again with the present moment, or cleared.
 */
function ObservedMaster({ group, current, onChanged, onReload }: ObservedMasterProps) {
  const [chosen, setChosen] = useState(group.observed_master_hid ?? "");
  const action = useAction();
  const known = ["observed_master_hid", "master_observed_at"];
  const refused = fieldErrors(action.error, known).shown;
  const seen = group.observed_master;
  const picked = current.find((member) => member.item_hid === chosen);

  async function send(body: Omit<Schemas["DeviceGroupPatch"], "row_version">, done: string) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}", {
        path: { hid: group.hid },
        body: { row_version: group.row_version, ...body },
      }),
    );
    if (result.ok) onChanged(done);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!picked) return;
    send(
      { observed_master_hid: picked.item_hid },
      `${itemName(picked.item)} is recorded as the master that is seen of ${group.name}.`,
    );
  }

  return (
    <section className="panel" aria-labelledby="observed-master">
      <h3 id="observed-master">The master that is seen</h3>
      <p className="hint">
        A stack decides which member is master as it boots, and that may move from one member to
        another over time, so it is an observation, recorded here with the moment it was seen. It
        need not be the intended master, and nothing depends on it but the serial number the stack
        shows.
      </p>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={known} onReload={onReload} />
        <div className="inline">
          <SelectField
            label="Member seen as master"
            name="observed_master_hid"
            value={chosen}
            onChange={setChosen}
            disabled={action.busy}
            error={refused.observed_master_hid ?? refused.master_observed_at}
          >
            <option value="">Choose a member</option>
            {seen && !current.some((member) => member.item_hid === seen.hid) && (
              <option value={seen.hid}>{pickLabel(seen)}</option>
            )}
            {current.map((member) => (
              <option key={member.hid} value={member.item_hid}>
                {member.position === null ? "" : `${member.position}: `}
                {itemName(member.item)}
              </option>
            ))}
          </SelectField>
        </div>
        <p className="actions">
          <button
            type="submit"
            className="primary"
            disabled={action.busy || !picked || chosen === group.observed_master_hid}
          >
            Record the master that is seen
          </button>
          {seen && (
            <button
              type="button"
              disabled={action.busy}
              onClick={() =>
                send(
                  { observed_master_hid: seen.hid, master_observed_at: new Date().toISOString() },
                  `${itemName(seen)} was seen as the master again, now.`,
                )
              }
            >
              Seen now
            </button>
          )}
          {seen && (
            <button
              type="button"
              disabled={action.busy}
              onClick={() =>
                send({ observed_master_hid: null }, "The master that was seen was cleared.")
              }
            >
              Clear the master that is seen
            </button>
          )}
        </p>
      </form>
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
  const adding = pending.map((row) => row.role);
  const problem = stackProblem(group.type, adding);
  const takes =
    current !== null &&
    takesTheMark(
      group.type,
      current.map((member) => member.role),
      adding,
    );

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
        {!problem && takes && (
          <p className="note" role="status" data-testid="takes-the-mark">
            The member added as the intended master takes the mark from the member that has it now.
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
            {
              name: "role",
              label: "Role",
              kind: "choice",
              options: roleOptions(group.type),
              ...(group.type === "stack"
                ? {
                    hint: "The intended master is the member given the priority. It is optional, and marking a member takes the mark from the one that had it.",
                  }
                : {}),
            },
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
          " Any member may leave, the master among them: the stack is then without the mark, or without a master that is seen, until one is recorded again."}
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
          and the current members of every cluster nested here, at any depth. A domain may hold
          several clusters: an endpoint that fails over between them is a member of the domain
          alone, and its page lists each controller with the cluster it is in.
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
  const specs = useMemo(() => groupSpecs(lists, group, group.type), [lists, group]);
  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <Problem error={error} />
      {!ready && <p role="status">Loading…</p>}
      {ready && group.type === "cluster" && <ManagedAsHelp />}
      {ready && (
        <EditForm<DeviceGroup, Schemas["DeviceGroupPatch"]>
          specs={specs}
          record={group}
          {...(group.operator_hid
            ? {}
            : {
                notes: {
                  operator_hid: (
                    <OperatorNote effective={group.effective.operator_hid} what="group" />
                  ),
                },
              })}
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

  /** Bring the group back: as it was, or with another location, or none, in the same change. */
  async function bringBack(location?: string | null) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/device-groups/{hid}", {
        path: { hid: group.hid },
        body: {
          row_version: group.row_version,
          record_status: "active",
          ...(location === undefined ? {} : { location_hid: location }),
        },
      }),
    );
    if (result.ok) onChanged("The group is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{group.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} labels={{ record_status: "" }} />
      {group.record_status === "retired" ? (
        <>
          <p>
            This group is retired. Its record and its past memberships are kept. Brought back, it
            has no current member until members are added again.
          </p>
          <p className="actions">
            <button type="button" onClick={() => bringBack()} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
          {refusedForItsPlace(action.error) && (
            <BringBackElsewhere
              what="group"
              blank="No location"
              busy={action.busy}
              onBringBack={bringBack}
            />
          )}
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
