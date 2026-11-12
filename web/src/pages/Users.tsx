import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schemas } from "../api";
import { CheckField, SelectField, TextField } from "../components/Field";
import { Pager, toOffset } from "../components/Pager";
import { Notice, Problem } from "../components/Problem";
import { SecretBox } from "../components/SecretBox";
import { AdminNav } from "../components/Shell";
import { Time } from "../components/Time";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { ROLES, roleLabel } from "../lib/roles";

const PAGE = 50;

type Created = Schemas["UserCreated"];

/** Admin → Users: the list, the search box, and the form for a new user. */
export function Users() {
  useTitle("Users");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const offset = toOffset(params.get("offset"));
  const [search, setSearch] = useState(q);
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const users = useLoad(`users ${offset} ${q}`, (signal) =>
    api.request("get", "/api/v1/users", { query: { q, limit: PAGE, offset }, signal }),
  );

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
            hint="Part of a username or display name"
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
          <div className="scroll">
            <table>
              <caption className="visually-hidden">Users</caption>
              <thead>
                <tr>
                  <th scope="col">Username</th>
                  <th scope="col">Display name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Groups</th>
                  <th scope="col">Kind</th>
                  <th scope="col">State</th>
                  <th scope="col">Last sign-in</th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.hid} className={user.disabled ? "dim" : undefined}>
                    <th scope="row">
                      <Link to={`/admin/users/${encodeURIComponent(user.hid)}`}>
                        {user.username}
                      </Link>
                    </th>
                    <td>{user.display_name}</td>
                    <td>
                      {user.role ? roleLabel(user.role) : <span className="muted">none</span>}
                    </td>
                    <td>{user.groups.map((group) => group.name).join(", ")}</td>
                    <td>{user.is_service_account ? "Service" : "Person"}</td>
                    <td>{user.disabled ? "Disabled" : "Active"}</td>
                    <td>
                      <Time at={user.last_sign_in_at} />
                    </td>
                  </tr>
                ))}
                {users.data.items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
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

function NewUser({ onCancel, onCreated }: NewUserProps) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [service, setService] = useState(false);
  const [role, setRole] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["UserCreate"] = {
      username: username.trim(),
      display_name: displayName.trim(),
      email: email.trim(),
      is_service_account: service,
    };
    if (role) body.role = role;
    if (!service && accessCode !== "") body.access_code = accessCode;
    const result = await action.run(() => api.request("post", "/api/v1/users", { body }));
    if (result.ok) onCreated(result.value);
  }

  return (
    <section className="panel" aria-labelledby="new-user">
      <h2 id="new-user">New user</h2>
      <form onSubmit={submit} className="stack">
        <Problem
          error={action.error}
          shown={["username", "display_name", "email", "is_service_account", "role", "access_code"]}
        />
        <TextField
          label="Username"
          name="username"
          value={username}
          onChange={setUsername}
          required
          maxLength={64}
          autoComplete="off"
          hint="Letters, digits, dots, hyphens and underscores"
          error={fields.username}
        />
        <TextField
          label="Display name"
          name="display_name"
          value={displayName}
          onChange={setDisplayName}
          maxLength={200}
          autoComplete="off"
          error={fields.display_name}
        />
        <TextField
          label="Email"
          name="email"
          value={email}
          onChange={setEmail}
          maxLength={254}
          autoComplete="off"
          error={fields.email}
        />
        <CheckField
          label="Service account"
          name="is_service_account"
          checked={service}
          onChange={setService}
          hint="For automation. It cannot sign in with an access code: it holds tokens."
          error={fields.is_service_account}
        />
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
