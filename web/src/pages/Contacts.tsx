import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { OperatorMark } from "../components/Operator";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { Time } from "../components/Time";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { EVERY, useChoices, useTags } from "../lib/lists";
import { markOf } from "../lib/operators";
import { choiceLabel, optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import { memberRoleLabel } from "../lib/owners";
import type { FieldSpec } from "../lib/patch";
import { CONTACT_ROLE_LIST, levelLabel, placePath } from "../lib/places";
import { allows } from "../lib/roles";

type Contact = Schemas["ContactOut"];

const COLUMNS: GridColumn<Contact>[] = [
  {
    id: "name",
    header: "Name",
    kind: "text",
    value: (contact) => contact.name,
    link: true,
    width: 240,
  },
  {
    id: "organization",
    header: "Organization",
    kind: "text",
    value: (contact) => contact.organization,
    width: 220,
  },
  { id: "email", header: "Email", kind: "text", value: (contact) => contact.email, width: 260 },
  { id: "phone", header: "Phone", kind: "text", value: (contact) => contact.phone, width: 160 },
  {
    // How many places and owners it is assigned to: counted by the server, for each row.
    id: "uses",
    header: "Assigned",
    kind: "integer",
    field: null,
    sortField: null,
    column: null,
    value: (contact) => String(contact.uses),
    numeric: true,
    width: 110,
  },
  {
    id: "tags",
    header: "Tags",
    kind: "tags",
    value: (contact) => contact.tags.join(", "),
    width: 160,
  },
  { id: "notes", header: "Notes", kind: "text", value: (contact) => contact.notes, hide: true },
  {
    id: "record_status",
    header: "Record status",
    kind: "choice",
    value: (contact) => optionLabel(RECORD_STATUSES, contact.record_status),
    choices: RECORD_STATUSES,
    width: 140,
  },
  {
    id: "updated_at",
    header: "Changed",
    kind: "timestamp",
    value: (contact) => formatTime(contact.updated_at),
    hide: true,
  },
  {
    id: "hid",
    header: "HID",
    kind: "reference",
    value: (contact) => contact.hid,
    mono: true,
    hide: true,
  },
];

/** The fields of a contact that a form sets. */
function contactSpecs(tags: readonly string[], current: Contact | null = null): FieldSpec[] {
  return [
    {
      name: "name",
      label: "Name",
      kind: "text",
      required: true,
      maxLength: 200,
      hint: "A person, or a shared mailbox",
    },
    { name: "organization", label: "Organization", kind: "text", maxLength: 200 },
    {
      name: "email",
      label: "Email",
      kind: "text",
      maxLength: 254,
      hint: "Belongs to one contact only. A file finds a contact by it.",
    },
    { name: "phone", label: "Phone", kind: "text", maxLength: 50 },
    { name: "record_status", label: "Record status", kind: "choice", options: SETTABLE_STATUSES },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
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

/** Contacts: the people and shared mailboxes that places and owners point at. */
export function Contacts() {
  useTitle("Contacts");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const tags = useTags();
  const specs = useMemo(() => contactSpecs((tags.data ?? []).map((tag) => tag.label)), [tags.data]);

  return (
    <>
      <h1>Contacts</h1>
      {adding && (
        <CreateForm<Schemas["ContactCreate"], Contact>
          title="New contact"
          specs={specs}
          start={{ record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/contacts", { body })}
          onCreated={(contact) => navigate(`/contacts/${encodeURIComponent(contact.hid)}`)}
          onCancel={() => setAdding(false)}
          submitLabel="Create contact"
        >
          <Problem error={tags.error} />
          <p className="hint">
            One record for each person or shared mailbox. A contact is then assigned to a region, a
            site or a location in a role, under Geography, or made one of the people of an owner.
          </p>
        </CreateForm>
      )}
      <DataGrid<Contact>
        key={startFilter ?? ""}
        id="contacts"
        noun={["contact", "contacts"]}
        entity="contacts"
        columns={COLUMNS}
        load={(request, signal) =>
          api.request("get", "/api/v1/contacts", { query: queryParams(request), signal })
        }
        rowId={(contact) => contact.hid}
        rowLink={(contact) => `/contacts/${encodeURIComponent(contact.hid)}`}
        dimmed={(contact) => contact.record_status !== "active"}
        shortFilter="organization:contains:Operations tags:has:on-call"
        startFilter={startFilter}
        switches={{ archived: "Include retired", drafts: "Include drafts" }}
      >
        {allows(user.role, "inventory") && !adding && (
          <button type="button" className="primary" onClick={() => setAdding(true)}>
            New contact
          </button>
        )}
      </DataGrid>
    </>
  );
}

function Dash() {
  return <span className="muted">—</span>;
}

/** Contacts → one contact: who it is, where it is assigned, and the ways to change it. */
export function ContactDetail() {
  const { hid = "" } = useParams();
  const { user } = useAuth();
  const mayEdit = allows(user.role, "inventory");
  const contact = useLoad(`contact ${hid}`, (signal) =>
    api.request("get", "/api/v1/contacts/{hid}", { path: { hid }, signal }),
  );
  const tags = useTags();
  const [done, setDone] = useState("");
  const record = contact.data;
  useTitle(record ? record.name : "Contact");
  const specs = useMemo(
    () =>
      contactSpecs(
        (tags.data ?? []).map((tag) => tag.label),
        record ?? null,
      ),
    [tags.data, record],
  );

  function changed(text: string) {
    setDone(text);
    contact.reload();
  }

  return (
    <>
      <p className="crumbs">
        <Link to="/contacts">Contacts</Link>
      </p>
      <h1>
        {record ? record.name : "Contact"}
        {record && record.record_status !== "active" && (
          <span className="badge">{optionLabel(RECORD_STATUSES, record.record_status)}</span>
        )}
      </h1>
      <Problem error={contact.error} />
      <Problem error={tags.error} />
      <Notice text={done} />
      {contact.loading && !record && <p role="status">Loading…</p>}
      {record && (
        <>
          <dl className="facts" data-testid="contact-facts">
            <dt>Name</dt>
            <dd>{record.name}</dd>
            <dt>Organization</dt>
            <dd>{record.organization || <Dash />}</dd>
            <dt>Email</dt>
            <dd>{record.email || <Dash />}</dd>
            <dt>Phone</dt>
            <dd>{record.phone || <Dash />}</dd>
            <dt>Notes</dt>
            <dd>{record.notes || <Dash />}</dd>
            <dt>Tags</dt>
            <dd data-testid="contact-tags">{record.tags.join(", ") || <Dash />}</dd>
            <dt>Changed</dt>
            <dd>
              <Time at={record.updated_at} />
            </dd>
            <dt>HID</dt>
            <dd className="mono">{record.hid}</dd>
          </dl>
          <Assigned contact={record} />
          {mayEdit && record.record_status !== "retired" && !tags.loading && (
            <section aria-labelledby="details">
              <h2 id="details">Details</h2>
              <EditForm<Contact, Schemas["ContactPatch"]>
                key={`${record.hid} ${record.row_version}`}
                specs={specs}
                record={record}
                save={(body) =>
                  api.request("patch", "/api/v1/contacts/{hid}", {
                    path: { hid: record.hid },
                    body,
                  })
                }
                onSaved={() => changed("The contact was saved.")}
                onReload={contact.reload}
              />
            </section>
          )}
          {mayEdit && (
            <ContactStatus
              key={`status ${record.hid} ${record.row_version}`}
              contact={record}
              onChanged={changed}
              onReload={contact.reload}
            />
          )}
        </>
      )}
    </>
  );
}

/**
 * Where a contact is assigned: the regions, sites and locations it is a contact of, each
 * with its role there, and the owners it is one of the people of.
 */
function Assigned({ contact }: { contact: Contact }) {
  const choices = useChoices();
  const places = useLoad(`contact-places ${contact.hid} ${contact.row_version}`, (signal) =>
    api.request("get", "/api/v1/contact-assignments", {
      query: { filter: `contact_hid:eq:${contact.hid}`, limit: EVERY },
      signal,
    }),
  );
  const owners = useLoad(`contact-owners ${contact.hid} ${contact.row_version}`, (signal) =>
    api.request("get", "/api/v1/owners", {
      query: {
        filter: `member.contact_hid:eq:${contact.hid}`,
        limit: EVERY,
        include_drafts: true,
        include_archived: true,
      },
      signal,
    }),
  );
  // The operators it stands behind: the labels that are assigned to this person.
  const behind = useLoad(`contact-operators ${contact.hid} ${contact.row_version}`, (signal) =>
    api.request("get", "/api/v1/operators", {
      query: {
        filter: `contact_hid:eq:${contact.hid}`,
        limit: EVERY,
        include_drafts: true,
        include_archived: true,
      },
      signal,
    }),
  );
  const labels = behind.data?.items ?? [];
  const assignments = places.data?.items ?? [];
  const among = owners.data?.items ?? [];
  const loaded = places.data !== undefined && owners.data !== undefined;

  return (
    <section aria-labelledby="assigned">
      <h2 id="assigned">Where it is assigned</h2>
      <Problem error={places.error ?? owners.error ?? choices.error ?? behind.error} />
      {!loaded && !(places.error ?? owners.error) && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {loaded &&
        behind.data &&
        assignments.length === 0 &&
        among.length === 0 &&
        labels.length === 0 && <p className="muted">This contact is assigned nowhere.</p>}
      {labels.length > 0 && (
        <p data-testid="contact-operators">
          Behind {plural(labels.length, "operator")}:{" "}
          {labels.map((operator) => {
            const mark = markOf(operator);
            return mark && <OperatorMark key={operator.hid} mark={mark} />;
          })}
          <span className="muted">
            {" "}
            · what each label is on is this person&apos;s to look after. A label is handed over on
            its own page.
          </span>
        </p>
      )}
      {assignments.length > 0 && (
        <div className="scroll">
          <table data-testid="contact-places">
            <caption>
              {plural(assignments.length, "place")} it is a contact of. Each is changed on the page
              of the place, under Geography.
            </caption>
            <thead>
              <tr>
                <th scope="col">Place</th>
                <th scope="col">Level</th>
                <th scope="col">Role</th>
                <th scope="col" className="number">
                  Priority
                </th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((assignment) => (
                <tr key={assignment.hid} data-role={assignment.role}>
                  <th scope="row">
                    <Link to={placePath(assignment.place.level, assignment.place.hid)}>
                      {assignment.place.path}
                    </Link>
                  </th>
                  <td>{levelLabel(assignment.place.level)}</td>
                  <td>{choiceLabel(choices.data, CONTACT_ROLE_LIST, assignment.role)}</td>
                  <td className="number">{assignment.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {among.length > 0 && (
        <div className="scroll">
          <table data-testid="contact-owners" className="narrow">
            <caption>
              {plural(among.length, "owner")} it is one of the people of. Each is changed on the
              page of the owner.
            </caption>
            <thead>
              <tr>
                <th scope="col">Owner</th>
                <th scope="col">As</th>
              </tr>
            </thead>
            <tbody>
              {among.map((owner) => {
                const member = owner.members.find((one) => one.contact_hid === contact.hid);
                return (
                  <tr key={owner.hid}>
                    <th scope="row">
                      <Link to={`/owners/${encodeURIComponent(owner.hid)}`}>{owner.label}</Link>
                      {owner.record_status !== "active" && (
                        <span className="badge">
                          {optionLabel(RECORD_STATUSES, owner.record_status)}
                        </span>
                      )}
                    </th>
                    <td>{member ? memberRoleLabel(member.role) : <Dash />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface ContactStatusProps {
  contact: Contact;
  onChanged: (text: string) => void;
  onReload: () => void;
}

/** Retire a contact, or bring a retired one back. Its assignments stay either way. */
function ContactStatus({ contact, onChanged, onReload }: ContactStatusProps) {
  const action = useAction();

  async function retire() {
    const result = await action.run(() =>
      api.request("post", "/api/v1/contacts/{hid}/retire", {
        path: { hid: contact.hid },
        body: { row_version: contact.row_version },
      }),
    );
    if (result.ok) onChanged("The contact was retired.");
  }

  async function bringBack() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/contacts/{hid}", {
        path: { hid: contact.hid },
        body: { row_version: contact.row_version, record_status: "active" },
      }),
    );
    if (result.ok) onChanged("The contact is active again.");
  }

  return (
    <section aria-labelledby="retire">
      <h2 id="retire">{contact.record_status === "retired" ? "Retired" : "Retire"}</h2>
      <Problem error={action.error} onReload={onReload} />
      {contact.record_status === "retired" ? (
        <>
          <p>
            This contact is retired. The places and owners it is assigned to keep it, and show it as
            retired.
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
            A retired contact is given no further assignment. The ones it has stay, and show it as
            retired, until they are removed where they are.
          </p>
          <p className="actions">
            <ConfirmButton
              label="Retire contact"
              title={`Retire ${contact.name}?`}
              confirmLabel="Retire contact"
              onConfirm={retire}
              disabled={action.busy}
            >
              <p>
                {contact.uses > 0
                  ? `It is assigned in ${plural(contact.uses, "place or owner", "places and owners")}, which keep it and show it as retired.`
                  : "It is assigned nowhere."}{" "}
                The contact can be brought back.
              </p>
            </ConfirmButton>
          </p>
        </>
      )}
    </section>
  );
}
