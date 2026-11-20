import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { Created, createdState, useCreated } from "../components/Created";
import { GapLinks } from "../components/GapLinks";
import type { GridColumn } from "../components/grid/columns";
import { DataGrid } from "../components/grid/DataGrid";
import { MakeOperator } from "../components/MakeOperator";
import { OperatorMark } from "../components/Operator";
import { Notice, Problem } from "../components/Problem";
import { CreateForm, EditForm } from "../components/RecordForm";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import {
  type NamedRecords,
  namedLevel,
  namedMark,
  namedMore,
  namedPath,
  namedRole,
  USES_KINDS,
  type UsesKind,
} from "../lib/contactUses";
import { formatTime, plural } from "../lib/format";
import { queryParams } from "../lib/gridQuery";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { useChoices, useTags } from "../lib/lists";
import { briefMark, CONTACTS_GAPS, contactsAddress, operatorLabelOf } from "../lib/onboarding";
import { operatorPath } from "../lib/operators";
import { optionLabel, RECORD_STATUSES, SETTABLE_STATUSES } from "../lib/options";
import type { FieldSpec } from "../lib/patch";
import { kindPath } from "../lib/preview";
import { allows } from "../lib/roles";
import { useSorting } from "../lib/useSorting";

type Contact = Schemas["ContactOut"];
type Choice = Schemas["ChoiceOut"];

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
  // 0.9.3: a second number, and the user a contact is, where it is one (P-172).
  {
    id: "phone2",
    header: "Second phone",
    kind: "text",
    value: (contact) => contact.phone2,
    width: 160,
  },
  {
    // The username of the user the contact is, which every role reads, and an export
    // holds as `user`: filtered and sorted by whether it is one.
    id: "is_user",
    header: "User",
    kind: "boolean",
    column: "user",
    value: (contact) => (contact.is_user ? (contact.user?.username ?? "A user") : ""),
    choices: [
      { value: "true", label: "A user: signs in to hirdir" },
      { value: "false", label: "No user" },
    ],
    width: 160,
  },
  {
    // 0.9.13: the operators it stands behind, each a link to its page, filtered and
    // sorted by whether it stands behind one that is not retired (P-280).
    id: "is_operator",
    header: "Operators",
    kind: "boolean",
    column: null,
    value: (contact) => contact.operators.map((operator) => operator.label).join(", "),
    links: (contact) =>
      contact.operators.map((operator) => ({
        text: operator.label,
        path: operatorPath(operator.hid),
      })),
    choices: [
      { value: "true", label: "Behind an operator" },
      { value: "false", label: "Behind no operator" },
    ],
    width: 180,
  },
  {
    // How many places and owners it is assigned to: counted by the server, for each row.
    id: "uses",
    header: "Assigned",
    kind: "integer",
    field: null,
    sortField: "uses",
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

/**
 * The columns of the list of contacts for one reader. 0.9.8: an Admin sees the username
 * of a user as a link to the user's page, which is an Admin's alone; everyone else reads
 * it as text, as before (P-239).
 */
function contactColumns(admin: boolean): GridColumn<Contact>[] {
  if (!admin) return COLUMNS;
  return COLUMNS.map((column) =>
    column.id === "is_user"
      ? { ...column, linkTo: (contact: Contact) => kindPath("user", contact.user?.hid, true) }
      : column,
  );
}

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
    { name: "phone2", label: "Second phone", kind: "text", maxLength: 50 },
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

/**
 * Contacts: the people and shared mailboxes that places and owners point at. 0.9.3: the
 * one list of people, of which a user and an operator are each a part (P-172).
 */
export function Contacts() {
  useTitle("Contacts");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const startFilter = params.get("filter");
  const [adding, setAdding] = useState(false);
  const tags = useTags();
  const specs = useMemo(() => contactSpecs((tags.data ?? []).map((tag) => tag.label)), [tags.data]);
  const admin = allows(user.role, "admin");
  const columns = useMemo(() => contactColumns(admin), [admin]);

  return (
    <>
      <h1>Contacts</h1>
      <p>
        The one list of people, and of shared mailboxes: each once, with what is true of them
        whatever part they play. A user, who signs in, and the person behind an operator are
        contacts, so that a number changed here shows wherever that person is named.
      </p>
      {adding && (
        <CreateForm<Schemas["ContactCreate"], Contact>
          title="New contact"
          specs={specs}
          start={{ record_status: "active" }}
          create={(body) => api.request("post", "/api/v1/contacts", { body })}
          onCreated={(contact) => {
            const to = `/contacts/${encodeURIComponent(contact.hid)}`;
            navigate(to, { state: createdState({ kind: "Contact", name: contact.name, to }) });
          }}
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
      {/* 0.9.13: the gaps, each one press away and an address of its own (P-280). */}
      <GapLinks
        label="Show contacts"
        links={CONTACTS_GAPS.map((one) => ({
          text: one.label,
          to: contactsAddress(one.filter),
          current: startFilter === one.filter,
        }))}
      />
      <DataGrid<Contact>
        key={startFilter ?? ""}
        id="contacts"
        noun={["contact", "contacts"]}
        entity="contacts"
        columns={columns}
        load={(request, signal) =>
          api.request("get", "/api/v1/contacts", { query: queryParams(request), signal })
        }
        rowId={(contact) => contact.hid}
        rowLink={(contact) => `/contacts/${encodeURIComponent(contact.hid)}`}
        dimmed={(contact) => contact.record_status !== "active"}
        shortFilter="organization:contains:Operations tags:has:on-call"
        quickFields={["name", "email"]}
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
  const created = useCreated();
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
      <Created made={created} />
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
            <dt>Second phone</dt>
            <dd data-testid="contact-phone2">{record.phone2 || <Dash />}</dd>
            <dt>User</dt>
            <dd data-testid="contact-user">
              {record.user ? (
                <>
                  {/* Every role reads the username; an Admin opens the user's page. */}
                  {allows(user.role, "admin") ? (
                    <Link to={`/admin/users/${encodeURIComponent(record.user.hid)}`}>
                      {record.user.username}
                    </Link>
                  ) : (
                    <span className="mono">{record.user.username}</span>
                  )}
                  <span className="muted"> · this person signs in to hirdir as this user</span>
                </>
              ) : record.is_user ? (
                <>A user: this person signs in to hirdir</>
              ) : (
                <span className="muted">None: this person does not sign in to hirdir</span>
              )}
            </dd>
            {/* 0.9.13: the operators it stands behind, as links, and one made in one press
                where it is behind none (P-280, P-284). */}
            <dt>Operators</dt>
            <dd data-testid="contact-operator-marks">
              {record.operators.length > 0 ? (
                <span className="people-marks">
                  {record.operators.map((operator) => (
                    <OperatorMark key={operator.hid} mark={briefMark(operator)} />
                  ))}
                </span>
              ) : (
                <span className="people-gap">no operator</span>
              )}
              {mayEdit && record.record_status !== "retired" && !record.is_operator && (
                <MakeOperator
                  contactHid={record.hid}
                  label={operatorLabelOf(record)}
                  who={record.name}
                />
              )}
            </dd>
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
 * Where a contact is named (P-205): every record that names it, by kind, each under a
 * heading and each a link to its page with the role the contact has there, from the one
 * route that lists them as the list of contacts counts them.
 */
function Assigned({ contact }: { contact: Contact }) {
  const choices = useChoices();
  const uses = useLoad(`contact-uses ${contact.hid} ${contact.row_version}`, (signal) =>
    api.request("get", "/api/v1/contacts/{hid}/uses", { path: { hid: contact.hid }, signal }),
  );
  const data = uses.data;
  return (
    <section aria-labelledby="assigned">
      <h2 id="assigned">Where it is named</h2>
      <Problem error={uses.error ?? choices.error} />
      {!data && !uses.error && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {data && data.total === 0 && <p className="muted">This contact is assigned nowhere.</p>}
      {data &&
        USES_KINDS.map(({ kind, heading }) =>
          data[kind].total === 0 ? null : (
            <div key={kind} data-testid={`contact-${kind}-named`}>
              <h3 id={`named-${kind}`}>{heading}</h3>
              {kind === "operators" ? (
                <p data-testid="contact-operators">
                  Behind {plural(data[kind].total, "operator")}:{" "}
                  {data[kind].records.map((operator) => (
                    <OperatorMark key={operator.hid} mark={namedMark(operator, contact)} />
                  ))}
                  <span className="muted">
                    {" "}
                    · what each label is on is this person&apos;s to look after. A label is handed
                    over on its own page.
                  </span>
                </p>
              ) : (
                <NamedTable kind={kind} named={data[kind]} choices={choices.data} />
              )}
              {namedMore(data[kind]) && <p className="hint">{namedMore(data[kind])}</p>}
            </div>
          ),
        )}
    </section>
  );
}

// The test IDs the tables of places and of owners had before 0.9.6, which pages are
// still found by.
const TABLE_IDS: Readonly<Partial<Record<UsesKind, string>>> = {
  places: "contact-places",
  owners: "contact-owners",
};

/** The records of one kind that name a contact, sorted here: the server sent them whole. */
function NamedTable({
  kind,
  named,
  choices,
}: {
  kind: UsesKind;
  named: NamedRecords;
  choices: readonly Choice[] | undefined;
}) {
  const places = kind === "places";
  const sorting = useSorting(
    named.records,
    {
      name: (record) => record.label,
      level: (record) => namedLevel(record),
      role: (record) => namedRole(record, choices),
      priority: (record) => record.priority,
    },
    { enabled: named.total <= named.records.length },
  );
  return (
    <div className="scroll">
      <table
        data-testid={TABLE_IDS[kind] ?? `contact-${kind}`}
        className={places ? undefined : "narrow"}
        aria-labelledby={`named-${kind}`}
      >
        <thead>
          <tr>
            <SortTh sort={sorting} column="name">
              {places ? "Place" : "Name"}
            </SortTh>
            {places && (
              <SortTh sort={sorting} column="level">
                Level
              </SortTh>
            )}
            <SortTh sort={sorting} column="role">
              {kind === "owners" ? "As" : "Role"}
            </SortTh>
            <SortTh sort={sorting} column="priority" className="number">
              Priority
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((record) => {
            const to = namedPath(record);
            return (
              <tr key={`${record.hid} ${record.role ?? ""} ${record.side ?? ""}`}>
                <th scope="row">
                  {to ? <Link to={to}>{record.label}</Link> : record.label}
                  {record.record_status !== "active" && (
                    <span className="badge">
                      {optionLabel(RECORD_STATUSES, record.record_status)}
                    </span>
                  )}
                </th>
                {places && <td>{namedLevel(record)}</td>}
                <td>{namedRole(record, choices) || <Dash />}</td>
                <td className="number">{record.priority ?? <Dash />}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
                  ? `It is named by ${plural(contact.uses, "record")}, listed under Where it is named, which keep it and show it as retired.`
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
