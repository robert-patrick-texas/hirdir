import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { CheckField, TextField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { SecretBox } from "../components/SecretBox";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { appZone, momentIn } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { roleLabel } from "../lib/roles";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";

type User = Schemas["UserOut"];
type Token = Schemas["ServiceTokenOut"];

/** Admin → Users → one user: details, access code, sessions and service tokens. */
export function UserDetail() {
  const { hid = "" } = useParams();
  const user = useLoad(`user ${hid}`, (signal) =>
    api.request("get", "/api/v1/users/{hid}", { path: { hid }, signal }),
  );
  useTitle(user.data ? `User ${user.data.username}` : "User");

  return (
    <>
      <AdminNav />
      <p className="crumbs">
        <Link to="/admin/users">Users</Link>
      </p>
      <h1>{user.data ? user.data.username : "User"}</h1>
      <Problem error={user.error} />
      {user.loading && !user.data && <p role="status">Loading…</p>}
      {user.data && (
        <>
          <Facts user={user.data} />
          <Details
            key={`${user.data.hid} ${user.data.row_version}`}
            user={user.data}
            reload={user.reload}
          />
          {!user.data.is_service_account && <AccessCode user={user.data} reload={user.reload} />}
          <Sessions user={user.data} reload={user.reload} />
          {user.data.is_service_account && <Tokens user={user.data} />}
        </>
      )}
    </>
  );
}

function Facts({ user }: { user: User }) {
  return (
    <dl className="facts">
      <dt>Kind</dt>
      <dd>{user.is_service_account ? "Service account" : "Person"}</dd>
      <dt>State</dt>
      <dd>{user.disabled ? "Disabled" : "Active"}</dd>
      <dt>Role</dt>
      <dd>
        {roleLabel(user.role)} <Link to="/admin/roles">(role grants)</Link>
      </dd>
      <dt>Groups</dt>
      <dd>
        {user.groups.length === 0 && <span className="muted">—</span>}
        {user.groups.map((group, index) => (
          <span key={group.hid}>
            {index > 0 && ", "}
            <Link to={`/admin/groups/${encodeURIComponent(group.hid)}`}>{group.name}</Link>
          </span>
        ))}
      </dd>
      <dt>Last sign-in</dt>
      <dd>
        <Time at={user.last_sign_in_at} />
      </dd>
      <dt>Created</dt>
      <dd>
        <Time at={user.created_at} />
      </dd>
      <dt>Changed</dt>
      <dd>
        <Time at={user.updated_at} />
      </dd>
    </dl>
  );
}

function Details({ user, reload }: { user: User; reload: () => void }) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email);
  const [disabled, setDisabled] = useState(user.disabled);
  const [saved, setSaved] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};
  const changed =
    displayName !== user.display_name || email !== user.email || disabled !== user.disabled;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaved("");
    // Only what changed is sent, with the version this form was filled from.
    const body: Schemas["UserPatch"] = { row_version: user.row_version };
    if (displayName !== user.display_name) body.display_name = displayName;
    if (email !== user.email) body.email = email;
    if (disabled !== user.disabled) body.disabled = disabled;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/users/{hid}", { path: { hid: user.hid }, body }),
    );
    if (result.ok) reload();
  }

  return (
    <section aria-labelledby="details">
      <h2 id="details">Details</h2>
      <form onSubmit={submit} className="stack">
        <Problem
          error={action.error}
          shown={["display_name", "email", "disabled"]}
          onReload={reload}
        />
        <Notice text={saved} />
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
          label="Disabled"
          name="disabled"
          checked={disabled}
          onChange={setDisabled}
          hint="A disabled user cannot sign in, and every session they have ends."
          error={fields.disabled}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || !changed}>
            Save
          </button>
        </p>
      </form>
    </section>
  );
}

function AccessCode({ user, reload }: { user: User; reload: () => void }) {
  const auth = useAuth();
  const own = auth.user.hid === user.hid;
  const [wanted, setWanted] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const action = useAction();

  async function reset() {
    setCode(null);
    const body: Schemas["AccessCodeSet"] = wanted === "" ? {} : { access_code: wanted };
    const result = await action.run(() =>
      api.request("post", "/api/v1/users/{hid}/access-code", { path: { hid: user.hid }, body }),
    );
    if (!result.ok) return;
    setWanted("");
    setCode(result.value.access_code);
    // Resetting your own code ends this session too. Reading the user again would bring
    // the sign-in page up before the new code has been read.
    if (!own) reload();
  }

  return (
    <section aria-labelledby="access-code">
      <h2 id="access-code">Access code</h2>
      {code !== null && (
        <SecretBox
          title={`New access code for ${user.username}`}
          secret={code}
          {...(own
            ? { note: "This is your own account. You will be asked to sign in again." }
            : {})}
          onDone={() => setCode(null)}
        />
      )}
      <p>
        A new access code replaces the old one and ends every session {user.username} has. The new
        code is shown once.
      </p>
      <div className="stack">
        <Problem error={action.error} shown={["access_code"]} />
        <TextField
          label="New access code"
          name="access_code"
          value={wanted}
          onChange={setWanted}
          maxLength={200}
          autoComplete="off"
          hint="Leave empty to have one generated"
          error={action.error?.fields.access_code}
        />
        <p className="actions">
          <ConfirmButton
            label="Reset access code"
            title={`Reset the access code of ${user.username}?`}
            confirmLabel="Reset access code"
            onConfirm={reset}
            disabled={action.busy}
          >
            <p>
              The old access code stops working at once and every session {user.username} has ends.
            </p>
          </ConfirmButton>
        </p>
      </div>
    </section>
  );
}

function Sessions({ user, reload }: { user: User; reload: () => void }) {
  const auth = useAuth();
  const own = auth.user.hid === user.hid;
  const [done, setDone] = useState("");
  const action = useAction();

  async function end() {
    setDone("");
    const result = await action.run(() =>
      api.request("post", "/api/v1/users/{hid}/sign-out-everywhere", { path: { hid: user.hid } }),
    );
    if (!result.ok) return;
    if (own) {
      auth.signOut();
      return;
    }
    setDone(`Every session of ${user.username} has ended.`);
    reload();
  }

  return (
    <section aria-labelledby="sessions">
      <h2 id="sessions">Sessions</h2>
      <Problem error={action.error} />
      <Notice text={done} />
      <p className="actions">
        <ConfirmButton
          label="Sign out everywhere"
          title={`Sign ${user.username} out everywhere?`}
          confirmLabel="Sign out everywhere"
          onConfirm={end}
          disabled={action.busy}
        >
          <p>
            This ends every session {user.username} has, in every browser and on every machine.
            {own && " This is your own account: you will have to sign in again."}
          </p>
        </ConfirmButton>
      </p>
    </section>
  );
}

function tokenState(token: Token, now: number): string {
  if (token.revoked_at) return "Revoked";
  if (token.expires_at && Date.parse(token.expires_at) <= now) return "Expired";
  return "Active";
}

function Tokens({ user }: { user: User }) {
  const tokens = useLoad(`tokens ${user.hid}`, (signal) =>
    api.request("get", "/api/v1/users/{hid}/service-tokens", { path: { hid: user.hid }, signal }),
  );
  const [name, setName] = useState("");
  const [expires, setExpires] = useState("");
  const [secret, setSecret] = useState<Schemas["ServiceTokenCreated"] | null>(null);
  const create = useAction();
  const revoke = useAction();
  const fields = create.error?.fields ?? {};
  const now = Date.now();
  const sorting = useSorting(tokens.data, {
    name: (token) => token.name,
    state: (token) => tokenState(token, now),
    created: (token) => dateValue(token.created_at),
    expires: (token) => dateValue(token.expires_at),
    last_used: (token) => dateValue(token.last_used_at),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSecret(null);
    const body: Schemas["ServiceTokenCreate"] = { name: name.trim() };
    if (expires !== "") {
      // The field holds a time in the application's zone. The server is sent that moment.
      const [year = 0, month = 1, day = 1, hour = 0, minute = 0] = expires
        .split(/[-T:]/)
        .map(Number);
      const at = momentIn(appZone(), year, month, day, hour, minute);
      body.expires_at = Number.isNaN(at.getTime()) ? expires : at.toISOString();
    }
    const result = await create.run(() =>
      api.request("post", "/api/v1/users/{hid}/service-tokens", { path: { hid: user.hid }, body }),
    );
    if (!result.ok) return;
    setName("");
    setExpires("");
    setSecret(result.value);
    tokens.reload();
  }

  async function revokeToken(token: Token) {
    const result = await revoke.run(() =>
      api.request("post", "/api/v1/service-tokens/{hid}/revoke", { path: { hid: token.hid } }),
    );
    if (result.ok) tokens.reload();
  }

  return (
    <section aria-labelledby="tokens">
      <h2 id="tokens">Service tokens</h2>
      {secret && (
        <SecretBox
          title={`Token ${secret.token.name} for ${user.username}`}
          secret={secret.secret}
          onDone={() => setSecret(null)}
        />
      )}
      <Problem error={tokens.error} />
      <Problem error={revoke.error} />
      {tokens.loading && !tokens.data && <p role="status">Loading…</p>}
      {tokens.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">Service tokens of {user.username}</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                <SortTh sort={sorting} column="state">
                  State
                </SortTh>
                <SortTh sort={sorting} column="created">
                  Created
                </SortTh>
                <SortTh sort={sorting} column="expires">
                  Expires
                </SortTh>
                <SortTh sort={sorting} column="last_used">
                  Last used
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((token) => (
                <tr
                  key={token.hid}
                  className={tokenState(token, now) === "Active" ? undefined : "dim"}
                >
                  <th scope="row">{token.name}</th>
                  <td>{tokenState(token, now)}</td>
                  <td>
                    <Time at={token.created_at} />
                  </td>
                  <td>
                    <Time at={token.expires_at} />
                  </td>
                  <td>
                    <Time at={token.last_used_at} />
                  </td>
                  <td>
                    {!token.revoked_at && (
                      <ConfirmButton
                        label="Revoke"
                        title={`Revoke the token ${token.name}?`}
                        confirmLabel="Revoke token"
                        onConfirm={() => revokeToken(token)}
                        disabled={revoke.busy}
                      >
                        <p>Whatever uses this token will be refused from now on.</p>
                      </ConfirmButton>
                    )}
                  </td>
                </tr>
              ))}
              {tokens.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    This service account has no tokens.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <h3>New token</h3>
      <form onSubmit={submit} className="stack">
        <Problem error={create.error} shown={["name", "expires_at"]} />
        <TextField
          label="Name"
          name="name"
          value={name}
          onChange={setName}
          required
          maxLength={100}
          autoComplete="off"
          hint="What will use the token"
          error={fields.name}
        />
        <TextField
          label="Expires"
          name="expires_at"
          type="datetime-local"
          value={expires}
          onChange={setExpires}
          hint={`In ${appZone()} time. Leave empty for a token that does not expire.`}
          error={fields.expires_at}
        />
        <p className="actions">
          <button type="submit" className="primary" disabled={create.busy}>
            Create token
          </button>
        </p>
      </form>
    </section>
  );
}
