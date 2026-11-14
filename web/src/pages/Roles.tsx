import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { SelectField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { Time } from "../components/Time";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { ROLES, roleLabel } from "../lib/roles";
import { dateValue } from "../lib/sort";
import { useSorting } from "../lib/useSorting";

type Grant = Schemas["GrantOut"];
type Target = "user" | "group";

// The most users the server lists at once.
const EVERY_USER = 1000;

/** Admin → Roles: who holds which role, granting one and taking one back. */
export function Roles() {
  useTitle("Roles");
  const auth = useAuth();
  const grants = useLoad("grants", (signal) =>
    api.request("get", "/api/v1/role-grants", { signal }),
  );
  const [done, setDone] = useState("");
  const revoke = useAction();
  const sorting = useSorting(grants.data, {
    role: (grant) => roleLabel(grant.role),
    granted_to: (grant) => grant.target_name,
    kind: (grant) => (grant.user_hid ? "User" : "Group"),
    since: (grant) => dateValue(grant.created_at),
  });

  function changed(text: string) {
    setDone(text);
    grants.reload();
    // The reader's own role may be what changed.
    auth.refresh();
  }

  async function revokeGrant(grant: Grant) {
    setDone("");
    const result = await revoke.run(() =>
      api.request("delete", "/api/v1/role-grants/{hid}", { path: { hid: grant.hid } }),
    );
    if (result.ok) {
      changed(`${roleLabel(grant.role)} was taken back from ${grant.target_name}.`);
    }
  }

  return (
    <>
      <AdminNav />
      <h1>Roles</h1>
      <p>
        A role is granted to a user or to a group. A user holds the highest role granted to them or
        to any group they are in.
      </p>
      <Problem error={grants.error} />
      <Problem error={revoke.error} />
      <Notice text={done} />
      {grants.loading && !grants.data && <p role="status">Loading…</p>}
      {grants.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">Role grants</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="role">
                  Role
                </SortTh>
                <SortTh sort={sorting} column="granted_to">
                  Granted to
                </SortTh>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="since">
                  Since
                </SortTh>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((grant) => (
                <tr key={grant.hid}>
                  <th scope="row">{roleLabel(grant.role)}</th>
                  <td>
                    <TargetLink grant={grant} />
                  </td>
                  <td>{grant.user_hid ? "User" : "Group"}</td>
                  <td>
                    <Time at={grant.created_at} />
                  </td>
                  <td>
                    <ConfirmButton
                      label="Revoke"
                      title={`Take ${roleLabel(grant.role)} back from ${grant.target_name}?`}
                      confirmLabel="Revoke role"
                      onConfirm={() => revokeGrant(grant)}
                      disabled={revoke.busy}
                    >
                      <p>
                        {grant.user_hid
                          ? `The user ${grant.target_name} loses this role at once, unless a group gives it to them.`
                          : `Every member of the group ${grant.target_name} loses this role at once, unless they hold it another way.`}
                      </p>
                    </ConfirmButton>
                  </td>
                </tr>
              ))}
              {grants.data.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No role has been granted.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <GrantForm
        onGranted={(grant) =>
          changed(`${roleLabel(grant.role)} was granted to ${grant.target_name}.`)
        }
      />
    </>
  );
}

function TargetLink({ grant }: { grant: Grant }) {
  if (grant.user_hid) {
    return (
      <Link to={`/admin/users/${encodeURIComponent(grant.user_hid)}`}>{grant.target_name}</Link>
    );
  }
  if (grant.group_hid) {
    return (
      <Link to={`/admin/groups/${encodeURIComponent(grant.group_hid)}`}>{grant.target_name}</Link>
    );
  }
  return <>{grant.target_name}</>;
}

function GrantForm({ onGranted }: { onGranted: (grant: Grant) => void }) {
  const users = useLoad("users for grants", (signal) =>
    api.request("get", "/api/v1/users", { query: { limit: EVERY_USER }, signal }),
  );
  const groups = useLoad("groups for grants", (signal) =>
    api.request("get", "/api/v1/user-groups", { signal }),
  );
  const [role, setRole] = useState<string>(ROLES[0]);
  const [target, setTarget] = useState<Target>("user");
  const [userHid, setUserHid] = useState("");
  const [groupHid, setGroupHid] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};
  const chosen = target === "user" ? userHid : groupHid;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (chosen === "") return;
    const body: Schemas["GrantCreate"] =
      target === "user" ? { role, user_hid: userHid } : { role, group_hid: groupHid };
    const result = await action.run(() => api.request("post", "/api/v1/role-grants", { body }));
    if (!result.ok) return;
    setUserHid("");
    setGroupHid("");
    onGranted(result.value);
  }

  return (
    <section className="panel" aria-labelledby="grant">
      <h2 id="grant">Grant a role</h2>
      <form onSubmit={submit} className="stack">
        <Problem error={action.error} shown={["role", "user_hid", "group_hid"]} />
        <Problem error={users.error} />
        <Problem error={groups.error} />
        <SelectField label="Role" name="role" value={role} onChange={setRole} error={fields.role}>
          {ROLES.map((name) => (
            <option key={name} value={name}>
              {roleLabel(name)}
            </option>
          ))}
        </SelectField>
        <fieldset>
          <legend>Grant it to</legend>
          <label className="choice">
            <input
              type="radio"
              name="target"
              value="user"
              checked={target === "user"}
              onChange={() => setTarget("user")}
            />
            A user
          </label>
          <label className="choice">
            <input
              type="radio"
              name="target"
              value="group"
              checked={target === "group"}
              onChange={() => setTarget("group")}
            />
            A group
          </label>
        </fieldset>
        {target === "user" ? (
          <SelectField
            label="User"
            name="user_hid"
            value={userHid}
            onChange={setUserHid}
            disabled={!users.data}
            error={fields.user_hid}
          >
            <option value="">Choose a user…</option>
            {(users.data?.items ?? []).map((user) => (
              <option key={user.hid} value={user.hid}>
                {user.display_name ? `${user.username} (${user.display_name})` : user.username}
              </option>
            ))}
          </SelectField>
        ) : (
          <SelectField
            label="Group"
            name="group_hid"
            value={groupHid}
            onChange={setGroupHid}
            disabled={!groups.data}
            error={fields.group_hid}
          >
            <option value="">Choose a group…</option>
            {(groups.data ?? []).map((group) => (
              <option key={group.hid} value={group.hid}>
                {group.name}
              </option>
            ))}
          </SelectField>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || chosen === ""}>
            Grant role
          </button>
        </p>
      </form>
    </section>
  );
}
