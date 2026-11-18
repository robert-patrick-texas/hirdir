import { type FormEvent, Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { CheckField, SelectField, TextField } from "../components/Field";
import { Pager, toOffset } from "../components/Pager";
import { PersonChooser } from "../components/Person";
import { Notice, Problem } from "../components/Problem";
import { SecretBox } from "../components/SecretBox";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { ValueLink } from "../components/ValueLink";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import {
  NEW_PERSON_FIELDS,
  newPersonErrors,
  type PersonChoice,
  personChoice,
  readPerson,
} from "../lib/people";
import { ROLES, roleLabel } from "../lib/roles";
import { USERS_SORT } from "../lib/tableSorts";
import { useServerSort } from "../lib/useServerSort";

const PAGE = 50;

type Created = Schemas["UserCreated"];
type User = Schemas["UserOut"];

/** Admin → Users: the list, the search box, and the form for a new user. */
export function Users() {
  useTitle("Users");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const offset = toOffset(params.get("offset"));
  const [search, setSearch] = useState(q);
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  // The server pages this list and sorts it, over every user and not the page on show:
  // a header asks for the list in its order, from the first page.
  const sort = useServerSort<User>({
    fields: USERS_SORT,
    onChange: () => {
      if (offset > 0) show({ q, offset: 0 });
    },
  });
  const users = sort.held(
    useLoad(`users ${offset} ${q} ${sort.param ?? ""}`, (signal) =>
      api.request("get", "/api/v1/users", {
        query: {
          q,
          ...sort.query,
          limit: PAGE,
          offset,
        },
        signal,
      }),
    ),
  );
  const holdsAll = users.data ? users.data.total === users.data.items.length : false;

  function show(next: { q: string; offset: number }) {
    const wanted = new URLSearchParams();
    if (next.q) wanted.set("q", next.q);
    if (next.offset > 0) wanted.set("offset", String(next.offset));
    setParams(wanted);
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    show({ q: search.trim(), offset: 0 });
  }

  return (
    <>
      <AdminNav />
      <h1>Users</h1>

      {created && (
        <CreatedUser
          created={created}
          onDone={() => {
            setCreated(null);
          }}
        />
      )}

      <div className="toolbar">
        <form onSubmit={submitSearch} className="inline">
          <TextField
            label="Search users"
            name="q"
            type="search"
            value={search}
            onChange={setSearch}
            hint="Part of a username or of the name of its contact"
          />
          <button type="submit">Search</button>
        </form>
        {!adding && (
          <button
            type="button"
            className="primary"
            onClick={() => {
              setCreated(null);
              setAdding(true);
            }}
          >
            New user
          </button>
        )}
      </div>

      {adding && (
        <NewUser
          onCancel={() => setAdding(false)}
          onCreated={(answer) => {
            setAdding(false);
            setCreated(answer);
            users.reload();
          }}
        />
      )}

      <Problem error={users.error} />
      {users.loading && !users.data && <p role="status">Loading…</p>}
      {users.data && (
        <>
          <p className="hint">
            A user is the part of a person who signs in. Its name, its email and its numbers are
            those of its contact, and are changed on the contact, or on the page of the user.
          </p>
          <div className="scroll">
            <table data-testid="users">
              <caption className="visually-hidden">
                Users, each with the name, email and numbers of its contact
              </caption>
              <thead>
                <tr>
                  <SortTh sort={sort.header("username", holdsAll)} column="username">
                    Username
                  </SortTh>
                  <SortTh sort={sort.header("display_name", holdsAll)} column="display_name">
                    Name
                  </SortTh>
                  <th scope="col">Email</th>
                  <th scope="col">Phone</th>
                  <th scope="col">Second phone</th>
                  <SortTh sort={sort.header("role", holdsAll)} column="role">
                    Role
                  </SortTh>
                  <SortTh sort={sort.header("groups", holdsAll)} column="groups">
                    Groups
                  </SortTh>
                  <SortTh sort={sort.header("kind", holdsAll)} column="kind">
                    Kind
                  </SortTh>
                  <SortTh sort={sort.header("state", holdsAll)} column="state">
                    State
                  </SortTh>
                  <SortTh sort={sort.header("last_sign_in", holdsAll)} column="last_sign_in">
                    Last sign-in
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sort.arrange(users.data.items, holdsAll).map((user) => (
                  <tr
                    key={user.hid}
                    className={user.disabled ? "dim" : undefined}
                    data-user={user.username}
                  >
                    <th scope="row">
                      <Link to={`/admin/users/${encodeURIComponent(user.hid)}`}>
                        {user.username}
                      </Link>
                    </th>
                    {/* 0.9.3: the name, email and numbers of its contact (P-172). */}
                    <td data-testid="user-name">
                      {user.contact ? (
                        <>
                          {user.display_name}
                          {user.contact.record_status === "retired" && (
                            <span className="badge">Retired</span>
                          )}
                        </>
                      ) : (
                        <span className="muted">
                          {user.is_service_account ? "Service account" : "No contact"}
                        </span>
                      )}
                    </td>
                    <td data-testid="user-email">{user.email}</td>
                    <td data-testid="user-phone">{user.contact?.phone}</td>
                    <td data-testid="user-phone2">{user.contact?.phone2}</td>
                    <td>
                      {user.role ? roleLabel(user.role) : <span className="muted">none</span>}
                    </td>
                    <td>
                      {user.groups.map((group, index) => (
                        <Fragment key={group.hid}>
                          {index > 0 && ", "}
                          <ValueLink kind="user_group" hid={group.hid} admin>
                            {group.name}
                          </ValueLink>
                        </Fragment>
                      ))}
                    </td>
                    <td>{user.is_service_account ? "Service" : "Person"}</td>
                    <td>{user.disabled ? "Disabled" : "Active"}</td>
                    <td>
                      <Time at={user.last_sign_in_at} />
                    </td>
                  </tr>
                ))}
                {users.data.items.length === 0 && (
                  <tr>
                    <td colSpan={10} className="muted">
                      {q ? "No user matches the search." : "There are no users."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager
            total={users.data.total}
            limit={PAGE}
            offset={offset}
            noun="users"
            onChange={(next) => show({ q, offset: next })}
          />
        </>
      )}
    </>
  );
}

function CreatedUser({ created, onDone }: { created: Created; onDone: () => void }) {
  const { user, access_code } = created;
  if (access_code === null) {
    return (
      <Notice
        text={`The service account ${user.username} was created. It has no access code: open it to create a token.`}
      />
    );
  }
  return (
    <SecretBox title={`Access code for ${user.username}`} secret={access_code} onDone={onDone} />
  );
}

interface NewUserProps {
  onCancel: () => void;
  onCreated: (created: Created) => void;
}

/** What the server may refuse of a new user, each said beside its input. */
const NEW_USER_FIELDS = [
  "username",
  "is_service_account",
  "contact_hid",
  ...NEW_PERSON_FIELDS,
  ...NEW_PERSON_FIELDS.map((field) => `contact.${field}`),
  "role",
  "access_code",
];

/**
 * A new user. 0.9.3: the person is a contact, a new one made with the user, one there is
 * that is no other user's, or none for now; a service account, which is no person, has
 * none (P-172). The username is what the person signs in with, and an Admin can change
 * it later (P-173).
 */
function NewUser({ onCancel, onCreated }: NewUserProps) {
  const [username, setUsername] = useState("");
  const [service, setService] = useState(false);
  const [person, setPerson] = useState<PersonChoice>(() => personChoice("new"));
  const [role, setRole] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [found, setFound] = useState<Record<string, string>>({});
  const action = useAction();
  // What the server refused of the new contact is said beside the field of the person.
  const fields: Readonly<Record<string, string | undefined>> = {
    ...action.error?.fields,
    ...newPersonErrors(action.error?.fields ?? {}),
    ...found,
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["UserCreate"] = {
      username: username.trim(),
      is_service_account: service,
    };
    if (!service) {
      const read = readPerson(person);
      if (!read.ok) {
        action.clear();
        setFound({ [read.field]: read.error });
        return;
      }
      if (read.contactHid !== null) body.contact_hid = read.contactHid;
      if (read.person !== null) body.contact = read.person;
    }
    setFound({});
    if (role) body.role = role;
    if (!service && accessCode !== "") body.access_code = accessCode;
    const result = await action.run(() => api.request("post", "/api/v1/users", { body }));
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-user">
      <h2 id="new-user">New user</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <Problem error={action.error} shown={NEW_USER_FIELDS} />
        <TextField
          label="Username"
          name="username"
          value={username}
          onChange={setUsername}
          required
          maxLength={64}
          autoComplete="off"
          hint="What the person signs in with: 1 to 64 letters, digits, dots, hyphens and underscores. An Admin can change it later."
          error={fields.username}
        />
        <CheckField
          label="Service account"
          name="is_service_account"
          checked={service}
          onChange={setService}
          hint="For automation. It cannot sign in with an access code: it holds tokens. It is no person, and has no contact."
          error={fields.is_service_account}
        />
        {!service && (
          <PersonChooser
            legend="The person"
            name="new-user"
            ways={["new", "contact", "none"]}
            wayLabels={{
              new: "A new contact",
              contact: "A contact there is",
              none: "None for now",
            }}
            choice={person}
            onChange={(next) => {
              setFound({});
              setPerson(next);
            }}
            errors={fields}
            organization
            hint="The user's name, email and numbers are those of its contact. Left without one, the user is shown by its username until it is given one."
            disabled={action.busy}
          />
        )}
        <SelectField label="Role" name="role" value={role} onChange={setRole} error={fields.role}>
          <option value="">No role</option>
          {ROLES.map((name) => (
            <option key={name} value={name}>
              {roleLabel(name)}
            </option>
          ))}
        </SelectField>
        {!service && (
          <TextField
            label="Access code"
            name="access_code"
            value={accessCode}
            onChange={setAccessCode}
            maxLength={200}
            autoComplete="off"
            hint="Leave empty to have one generated"
            error={fields.access_code}
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy}>
            Create user
          </button>
          <button type="button" onClick={onCancel} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
