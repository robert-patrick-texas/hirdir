import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { SelectField } from "../components/Field";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { itemsPath } from "../lib/filter";
import { formatTime } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useContactOptions, useTags } from "../lib/lists";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import { mayRemove, memberRoleLabel, membersInOrder, type OwnerMember } from "../lib/owners";
import type { FieldSpec } from "../lib/patch";
import { contactLine } from "../lib/places";
import { fieldErrors } from "../lib/problems";
import { allows } from "../lib/roles";

type Owner = Schemas["OwnerOut"];

const COLUMNS: GridColumn<Owner>[] = [
  {
    id: "label",
    header: "Label",
    kind: "text",
    value: (owner) => owner.label,
    link: true,
    width: 260,
  },
  {
    id: "organization",
    header: "Organization",
    kind: "text",
    value: (owner) => owner.organization,
    width: 220,
  },
  {
    id: "is_external",
    header: "External",
    kind: "boolean",
    value: (owner) => (owner.is_external ? "Yes" : "No"),
    width: 120,
  },
  {
    id: "exception_reason",
    header: "Reason for the exception",
    kind: "text",
    value: (owner) => owner.exception_reason,
    width: 320,
  },
  {
    // The primary of its people. The list is neither filtered nor sorted by it.
    id: "primary",
    header: "Primary contact",
    kind: "text",
    field: null,
    sortField: null,
    column: null,
    value: (owner) => owner.members.find((member) => member.role === "primary")?.contact.name,
    width: 200,
  },
  { id: "tags", header: "Tags", kind: "tags", value: (owner) => owner.tags.join(", "), width: 160 },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (owner) => optionLabel(RECORD_STATUSES, owner.record_status),
    choices: RECORD_STATUSES,
    width: 140,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (owner) => formatTime(owner.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (owner) => owner.hid,
    mono: true,
    hide: true,
  },
];

/** The fields of an owner that a form sets. Its people are added on its own page. */
function ownerSpecs(tags: readonly string[], current: Owner | null = null): FieldSpec[] {
  return [
    { name: "label", label: "Label", kind: "text", required: true, maxLength: 200 },
    { name: "organization", label: "Organization", kind: "text", maxLength: 200 },
    {
      name: "is_external",
      label: "Outside the operations team",
      kind: "boolean",
      hint: "An owner outside the team is an exception, and needs a reason",
    },
    {
      name: "exception_reason",
      label: "Reason for the exception",
      kind: "longtext",
      maxLength: 10000,
      hint: "Required for an owner outside the operations team",
    },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...tags, ...(current?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
      hint: "A tag is made under Admin, then used here",
    },
  ];
}

/** Owners: who answers for an item. */
export function Owners() {
  useTitle("Owners");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const tags = useTags();
  const specs = useMemo(() => ownerSpecs((tags.data ?? []).map((tag) => tag.label)), [tags.data]);

  return (
    <>
      <h1>Owners</h1>
      {adding && (
        <CreateForm<Schemas["OwnerCreate"], Owner>
          title="New owner"
          specs={specs}
          start={{ record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/owners", { body })}
          onCreated={(owner) => navigate(`/owners/${encodeURIComponent(owner.hid)}`)}
          onCancel={() => setAdding(false)}
          submitLabel="Create owner"
        />
      )}
      <DataGrid<Owner>
        id="owners"
        noun={["owner", "owners"]}
        entity="owners"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/owners", { query: queryParams(request), signal })
        }
        rowId={(owner) => owner.hid}
        rowLink={(owner) => `/owners/${encodeURIComponent(owner.hid)}`}
        dimmed={(owner) => owner.record_status !== "active"}
        switches={{ archived: "Include retired", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New owner
          </button>
        )}
      </DataGrid>
    </>
  );
}

/** Owners → one owner. */
export function OwnerDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const owner = useLoad(`owner ${hid}`, (signal) =>
    api.request("get", "/api/v1/owners/{hid}", { path: { hid }, signal }),
  );
  const [done, setDone] = useState("");
  const record = owner.data;
  useTitle(record ? record.label : "Owner");
  const tags = useTags();
  const specs = useMemo(
    () =>
      ownerSpecs(
        (tags.data ?? []).map((tag) => tag.label),
        record ?? null,
      ),
    [tags.data, record],
  );

  function changed(text: string) {
    setDone(text);
    owner.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/owners">Owners</Link>
      </p>
      <h1>
        {record ? record.label : "Owner"}
        {record?.is_external && (
          <span className="badge" data-testid="owner-external">
            Outside the operations team
          </span>
        )}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={owner.error} />
      <Problem error={tags.error} />
      <Notice text={done} />
      {owner.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <p>
            <Link to={itemsPath(`owner_hid:eq:${record.hid}`)}>Items of this owner</Link>
          </p>
          <dl className="facts">
            <dt>Label</dt>
            <dd>{record.label}</dd>
            <dt>Organization</dt>
            <dd>{record.organization || <span className="muted">—</span>}</dd>
            <dt>Outside the operations team</dt>
            <dd>{record.is_external ? "Yes" : "No"}</dd>
            <dt>Reason for the exception</dt>
            <dd>{record.exception_reason || <span className="muted">—</span>}</dd>
            <dt>Tags</dt>
            <dd data-testid="owner-tags">
              {record.tags.join(", ") || <span className="muted">—</span>}
            </dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <People
            owner={record}
            mayEdit={mayEdit && record.record_status !== "retired"}
            onChanged={changed}
          />
          {mayEdit && record.record_status !== "retired" && !tags.loading && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<Owner, Schemas["OwnerPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/owners/{hid}", { path: { hid: record.hid }, body })
                }
                onSaved={() => changed("The owner was saved.")}
                onReload={owner.reload}
              />
            </section>
          )}
          {mayEdit && (
            <OwnerStatus
              key={`status ${record.hid} ${record.row_version}`}
              owner={record}
              onChanged={changed}
              onReload={owner.reload}
            />
          )}
        </>
      )}
    </>
  );
}

interface OwnerStatusProps {
  owner: Owner;
  onChanged: (text: string) => void;
  onReload: () => void;
}

function OwnerStatus({ owner, onChanged, onReload }: OwnerStatusProps) {
  const action = useAction();

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/owners/{hid}/retire", {
        path: { hid: owner.hid },
        body: { row_version: owner.row_version },
      }),
    );
    if (result.ok) onChanged("The owner was retired.");
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/owners/{hid}", {
        path: { hid: owner.hid },
        body: { row_version: owner.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged("The owner is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{owner.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {owner.record_status === "retired" ? (
        <>
          <p>This owner is retired. Items keep it.</p>
          <p className="actions">
            <button type="button" onClick={bringBack} disabled={action.busy}>
              Bring back as active
            </button>
          </p>
        </>
      ) : (
        <>
          <p>A retired owner is no longer offered for items. Items that have it keep it.</p>
          <p className="actions">
            <ConfirmButton
              label="Retire owner"
              title={`Retire ${owner.label}?`}
              confirmLabel="Retire owner"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>Items of this owner keep it. The owner can be brought back.</p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}

interface PeopleProps {
  owner: Owner;
  mayEdit: boolean;
  onChanged: (text: string) => void;
}

/**
 * The people of an owner, the primary first. An owner may have none; one that has any
 * has exactly one primary. Making another member the primary makes the one that had it
 * an alternate, in the same change, and the primary is not removed while others remain.
 */
function People({ owner, mayEdit, onChanged }: PeopleProps) {
  const action = useAction();
  const members = membersInOrder(owner.members);

  async function makePrimary(member: OwnerMember) {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/owners/{hid}/members/{member_hid}", {
        path: { hid: owner.hid, member_hid: member.hid },
        body: { row_version: member.row_version, role: "primary" },
      }),
    );
    if (result.ok) onChanged(`${member.contact.name} is now the primary of ${owner.label}.`);
  }

  async function remove(member: OwnerMember) {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/owners/{hid}/members/{member_hid}", {
        path: { hid: owner.hid, member_hid: member.hid },
      }),
    );
    if (result.ok) {
      onChanged(`${member.contact.name} is no longer one of the people of ${owner.label}.`);
    }
  }

  return (
    <section aria-labelledby="people">
      <h2 id="people">People</h2>
      <Problem error={action.error} />
      {members.length === 0 ? (
        <p className="muted">This owner has no people yet. The first one added is its primary.</p>
      ) : (
        <div className="scroll">
          <table data-testid="owner-people">
            <caption className="visually-hidden">
              The people of {owner.label}, the primary first
            </caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">As</th>
                <th scope="col">Reached at</th>
                {mayEdit && <th scope="col">Change</th>}
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.hid} data-role={member.role} data-member={member.hid}>
                  <th scope="row">
                    <Link to={`/contacts/${encodeURIComponent(member.contact.hid)}`}>
                      {member.contact.name}
                    </Link>
                    {member.contact.record_status !== "active" && (
                      <span className="badge">
                        {optionLabel(RECORD_STATUSES, member.contact.record_status)}
                      </span>
                    )}
                  </th>
                  <td data-testid="member-role">{memberRoleLabel(member.role)}</td>
                  <td>
                    {contactLine({ ...member.contact, name: "" }) || (
                      <span className="muted">—</span>
                    )}
                  </td>
                  {mayEdit && (
                    <td className="row-actions">
                      {member.role !== "primary" && (
                        <button
                          type="button"
                          onClick={() => makePrimary(member)}
                          disabled={action.busy}
                          aria-label={`Make primary: ${member.contact.name}`}
                        >
                          Make primary
                        </button>
                      )}
                      {mayRemove(member, members) ? (
                        <ConfirmButton
                          label="Remove"
                          title={`Remove ${member.contact.name} from ${owner.label}?`}
                          confirmLabel="Remove"
                          onConfirm={() => remove(member)}
                          disabled={action.busy}
                        >
                          <p>The contact itself stays, and can be added again.</p>
                        </ConfirmButton>
                      ) : (
                        <span className="muted">
                          The primary stays while there are others: make another the primary first.
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && (
        <AddPerson
          key={`add ${owner.hid} ${owner.members.length}`}
          owner={owner}
          onChanged={onChanged}
        />
      )}
    </section>
  );
}

/** The form that makes a contact one of the people of an owner. */
function AddPerson({ owner, onChanged }: { owner: Owner; onChanged: (text: string) => void }) {
  const contacts = useContactOptions();
  const [contact, setContact] = useState("");
  const [role, setRole] = useState("");
  const action = useAction();
  const known = ["contact_hid", "role"];
  const refused = fieldErrors(action.error, known).shown;
  const taken = new Set(owner.members.map((member) => member.contact_hid));
  const offered = (contacts.data ?? []).filter((option) => !taken.has(option.value));
  const first = owner.members.length === 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (contact === "") return;
    const body: Schemas["OwnerMemberAdd"] = {
      contact_hid: contact,
      ...(role === "primary" || role === "alternate" ? { role } : {}),
    };
    const result = await action.run(() =>
      api.request("post", "/api/v1/owners/{hid}/members", { path: { hid: owner.hid }, body }),
    );
    if (result.ok) {
      onChanged(
        `${result.value.contact.name} is now ${
          result.value.role === "primary" ? "the primary" : "an alternate"
        } of ${owner.label}.`,
      );
    }
  }

  return (
    <section aria-labelledby="add-person" className="panel">
      <h3 id="add-person">Add a person</h3>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={contacts.error} />
        <Problem error={action.error} shown={known} />
        <div className="fields">
          <SelectField
            label="Contact"
            name="contact_hid"
            value={contact}
            onChange={setContact}
            required
            disabled={action.busy}
            error={refused.contact_hid}
            hint="A contact is made under Contacts, then added here"
          >
            <option value="">Choose a contact</option>
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="As"
            name="role"
            value={first ? "" : role}
            onChange={setRole}
            disabled={action.busy || first}
            error={refused.role}
            hint={
              first
                ? "The first of its people is the primary"
                : "As the primary, it takes the place of the one who is: that one becomes an alternate"
            }
          >
            <option value="">{first ? "The primary" : "An alternate"}</option>
            {!first && <option value="primary">The primary</option>}
          </SelectField>
        </div>
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || contact === ""}>
            Add person
          </button>
        </p>
      </form>
    </section>
  );
}
