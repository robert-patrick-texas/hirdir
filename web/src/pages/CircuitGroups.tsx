// Circuit groups (P-152): circuits that may land at different sites, looked at and costed
// together, such as those of Internet access or of a cloud on-ramp. A circuit may be in
// any number of groups. A group has a list, with how many circuits each has and what
// they cost, and a page each, with its circuits to add, several at once, and to take out.

import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { CircuitsGrid } from "../components/CircuitsGrid";
import { CIRCUIT_GROUP_COLUMNS } from "../components/grid/circuitColumns";
import { DataGrid, type GridAction } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Retire } from "../components/Retire";
import { findCircuits, type Offer, SearchPicker } from "../components/SearchPicker";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import {
  type Circuit,
  type CircuitGroup,
  circuitGroupPath,
  circuitIsDimmed,
  circuitsInGroup,
  moneyText,
  ownerPath,
} from "../lib/circuits";
import { plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY, useOwnerOptions, useTags, withCurrent } from "../lib/lists";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import { ownerOption } from "../lib/owners";
import type { FieldSpec, Option } from "../lib/patch";
import { allows } from "../lib/roles";
import { useSorting } from "../lib/useSorting";
import { CircuitsNav } from "./Circuits";

function groupSpecs(
  owners: readonly Option[] | undefined,
  tags: readonly string[],
  record: CircuitGroup | null,
): FieldSpec[] {
  const owner = record?.owner ? ownerOption(record.owner) : null;
  return [
    { name: "name", label: "Name", kind: "text", required: true, maxLength: 200 },
    { name: "description", label: "Description", kind: "longtext", maxLength: 10000 },
    {
      name: "owner_hid",
      label: "Owner",
      kind: "choice",
      blank: "No owner",
      options: withCurrent(owners, owner),
    },
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft is left out of default views",
    },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...tags, ...(record?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
      hint: "A tag is made under Admin, then used here",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
  ];
}

function useGroupLists() {
  const owners = useOwnerOptions();
  const tags = useTags();
  const labels = useMemo(() => (tags.data ?? []).map((tag) => tag.label), [tags.data]);
  return {
    owners: owners.data,
    tags: labels,
    error: owners.error ?? tags.error,
    ready: !owners.loading && !tags.loading,
  };
}

/** Circuit groups: the list, with how many circuits each has and what they cost, and a new one. */
export function CircuitGroups() {
  useTitle("Circuit groups");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const lists = useGroupLists();
  const specs = useMemo(
    () => groupSpecs(lists.owners, lists.tags, null),
    [lists.owners, lists.tags],
  );

  return (
    <>
      <CircuitsNav />
      <h1>Circuit groups</h1>
      <p>
        Circuits that may land at different sites, looked at and costed together: those of Internet
        access, or of a cloud on-ramp. A circuit may be in any number of groups. The cost of a group
        is what its circuits in service cost today, each circuit once.
      </p>
      <Problem error={lists.error} />
      {adding && lists.ready && (
        <CreateForm<Schemas["CircuitGroupCreate"], CircuitGroup>
          title="New circuit group"
          specs={specs}
          start={{ record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/circuit-groups", { body })}
          onCreated={(group) => navigate(circuitGroupPath(group.hid))}
          onCancel={() => setAdding(false)}
          submitLabel="Create group"
        />
      )}
      <DataGrid<CircuitGroup>
        key={startFilter ?? ""}
        id="circuit-groups"
        noun={["circuit group", "circuit groups"]}
        entity="circuit_groups"
        columns={CIRCUIT_GROUP_COLUMNS}
        load={(request, signal) =>
          api.request("post", "/api/v1/circuit-groups/query", { body: queryBody(request), signal })
        }
        rowId={(group) => group.hid}
        rowLink={(group) => circuitGroupPath(group.hid)}
        dimmed={circuitIsDimmed}
        shortFilter="name:contains:Internet annual_cost:gt:10000"
        startFilter={startFilter}
        switches={{ archived: "Include archived", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New circuit group
          </button>
        )}
      </DataGrid>
    </>
  );
}

/** Circuit groups → one group: what it is, what its circuits cost, and its circuits. */
export function CircuitGroupDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const group = useLoad(`circuit-group ${hid}`, (signal) =>
    api.request("get", "/api/v1/circuit-groups/{hid}", { path: { hid }, signal }),
  );
  const lists = useGroupLists();
  const [done, setDone] = useState("");
  const [turn, setTurn] = useState(0);
  const record = group.data;
  useTitle(record ? record.name : "Circuit group");

  function changed(text: string) {
    setDone(text);
    setTurn((count) => count + 1);
    group.reload();
  }

  const open = mayEdit && record !== undefined && record.record_status !== "retired";
  return (
    <>
      <CircuitsNav />
      <p className="crumbs">
        <Link to="/circuit-groups">Circuit groups</Link>
      </p>
      <h1>
        {record ? record.name : "Circuit group"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={group.error} />
      <Problem error={lists.error} />
      <Notice text={done} />
      {group.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="totals" data-testid="group-totals">
            <div>
              <dt>Circuits</dt>
              <dd data-testid="group-circuits">{record.circuits}</dd>
            </div>
            <div>
              <dt>In service today</dt>
              <dd data-testid="group-in-service">{record.in_service}</dd>
            </div>
            <div>
              <dt>Monthly cost</dt>
              <dd data-testid="group-monthly-cost">{moneyText(record.monthly_cost)}</dd>
            </div>
            <div>
              <dt>Annual cost</dt>
              <dd data-testid="group-annual-cost">{moneyText(record.annual_cost)}</dd>
            </div>
          </dl>
          <p className="hint">
            What its circuits in service cost today, each circuit once, however many groups it is
            in. The report of what circuits cost has the year, by group among the other groupings.
          </p>
          <dl className="facts">
            <dt>Description</dt>
            <dd>{record.description || <span className="muted">—</span>}</dd>
            <dt>Owner</dt>
            <dd>
              {record.owner ? (
                <Link to={ownerPath(record.owner.hid)}>{record.owner.label}</Link>
              ) : (
                <span className="muted">—</span>
              )}
            </dd>
            <dt>Tags</dt>
            <dd>{record.tags.join(", ") || <span className="muted">—</span>}</dd>
            <dt>Notes</dt>
            <dd>{record.notes || <span className="muted">—</span>}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <GroupCircuits group={record} mayEdit={open} turn={turn} onChanged={changed} />
          {open && lists.ready && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<CircuitGroup, Schemas["CircuitGroupPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={groupSpecs(lists.owners, lists.tags, record)}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/circuit-groups/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The group was saved.")}
                onReload={group.reload}
              />
            </section>
          )}
          {mayEdit && (
            <Retire
              what="group"
              name={record.name}
              retired={record.record_status === "retired"}
              about="A retired group takes no new circuit. Its circuits stay in it, and it can be brought back."
              retiredAbout="This group is retired: its circuits stay listed in it, and it takes no new one."
              retire={() =>
                api.request("post", "/api/v1/circuit-groups/{hid}/retire", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version },
                })
              }
              bringBack={() =>
                api.request("patch", "/api/v1/circuit-groups/{hid}", {
                  path: { hid: record.hid },
                  body: { row_version: record.row_version, record_status: "active" },
                })
              }
              onChanged={changed}
              onReload={group.reload}
            />
          )}
        </>
      )}
    </>
  );
}

/** Every membership of a group, by the HID of its circuit: what a circuit is taken out by. */
async function membershipsOf(groupHid: string): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  for (let offset = 0; ; offset += EVERY) {
    const page = await api.request("get", "/api/v1/circuit-groups/{hid}/members", {
      path: { hid: groupHid },
      query: { limit: EVERY, offset },
    });
    for (const member of page.items) found.set(member.circuit_hid, member.hid);
    if (offset + page.items.length >= page.total || page.items.length === 0) return found;
  }
}

interface GroupCircuitsProps {
  group: CircuitGroup;
  mayEdit: boolean;
  /** Changed after every change made on the page, so that the grid is read again. */
  turn: number;
  onChanged: (text: string) => void;
}

/**
 * The circuits of a group, as the grid of circuits has them: sorted, filtered and
 * exported by the server, drafts and retired ones among them, greyed. Those chosen are
 * taken out of the group together; circuits are added several at a time.
 */
function GroupCircuits({ group, mayEdit, turn, onChanged }: GroupCircuitsProps) {
  const taking = useAction();
  const actions: GridAction<Circuit>[] = mayEdit
    ? [
        {
          label: "Take out of the group",
          rowsOnly: true,
          run: async (_chosen, _view, rows) => {
            const result = await taking.run(async () => {
              const members = await membershipsOf(group.hid);
              for (const circuit of rows) {
                const member = members.get(circuit.hid);
                if (member === undefined) continue;
                await api.request("delete", "/api/v1/circuit-groups/{hid}/members/{member_hid}", {
                  path: { hid: group.hid, member_hid: member },
                });
              }
              return rows.length;
            });
            if (result.ok) {
              onChanged(
                `${plural(result.value, "circuit")} ${result.value === 1 ? "was" : "were"} taken out of ${group.name}.`,
              );
            }
          },
        },
      ]
    : [];
  return (
    <section aria-labelledby="group-circuits" data-testid="group-circuits-section">
      <h2 id="group-circuits">Its circuits</h2>
      <Problem error={taking.error} />
      <CircuitsGrid
        id="circuit-group-circuits"
        within={{
          filter: circuitsInGroup(group.hid),
          includeArchived: true,
          includeDrafts: true,
        }}
        shown={["monthly_cost", "annual_cost"]}
        reloadKey={turn}
        actions={actions}
      />
      {mayEdit && <AddCircuits group={group} onChanged={onChanged} />}
    </section>
  );
}

/** Choose circuits to put into a group, and put them in together. A retired circuit is not offered. */
function AddCircuits({
  group,
  onChanged,
}: {
  group: CircuitGroup;
  onChanged: (text: string) => void;
}) {
  const [pending, setPending] = useState<Offer[]>([]);
  const action = useAction();
  const sorting = useSorting(pending, {
    circuit: (offer) => offer.label,
    note: (offer) => offer.note,
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.length === 0) return;
    const result = await action.run(() =>
      api.request("post", "/api/v1/circuit-groups/{hid}/members", {
        path: { hid: group.hid },
        body: { circuit_hids: pending.map((offer) => offer.hid) },
      }),
    );
    if (!result.ok) return;
    const count = pending.length;
    setPending([]);
    onChanged(
      `${plural(count, "circuit")} ${count === 1 ? "was" : "were"} put into ${group.name}.`,
    );
  }

  return (
    <section aria-labelledby="add-circuits" className="panel">
      <h3 id="add-circuits">Add circuits</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} />
        <div className="fields">
          <SearchPicker
            label="Add a circuit"
            hint="Type a part of its name, its enterprise ID or a number a carrier gives it."
            noun={["circuit", "circuits"]}
            find={findCircuits}
            taken={pending.map((offer) => offer.hid)}
            disabled={action.busy}
            onPick={(offer) =>
              setPending((was) =>
                was.some((one) => one.hid === offer.hid) ? was : [...was, offer],
              )
            }
          />
        </div>
        {pending.length > 0 && (
          <div className="scroll">
            <table data-testid="circuits-to-add">
              <caption>The circuits to put into {group.name}</caption>
              <thead>
                <tr>
                  <SortTh sort={sorting} column="circuit">
                    Circuit
                  </SortTh>
                  <SortTh sort={sorting} column="note">
                    Speed
                  </SortTh>
                  <th scope="col">Leave out</th>
                </tr>
              </thead>
              <tbody>
                {sorting.rows.map((offer) => (
                  <tr key={offer.hid} data-circuit={offer.label}>
                    <th scope="row">{offer.label}</th>
                    <td>{offer.note || <span className="muted">—</span>}</td>
                    <td>
                      <button
                        type="button"
                        disabled={action.busy}
                        onClick={() =>
                          setPending((was) => was.filter((one) => one.hid !== offer.hid))
                        }
                      >
                        Leave out
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || pending.length === 0}>
            {pending.length === 1 ? "Put 1 circuit in" : `Put ${pending.length} circuits in`}
          </button>
        </p>
      </form>
    </section>
  );
}
