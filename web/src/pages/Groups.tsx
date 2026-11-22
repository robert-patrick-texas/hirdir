import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { ConfirmButton } from "../components/ConfirmButton";
import { SelectField, TextField } from "../components/Field";
import { Notice, Problem } from "../components/Problem";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { kindWord, noRoleWords } from "../lib/accounts";
import { plural } from "../lib/format";
import { useAction, useLoad, useTitle } from "../lib/hooks";
import { roleLabel } from "../lib/roles";
import { useSorting } from "../lib/useSorting";

type Group = Schemas["GroupDetail"];

// The most users the server lists at once.
const EVERY_USER = 1000;

/** Admin → Groups: the list and the form for a new group. */
export function Groups() {
  useTitle("Groups");
  const groups = useLoad("groups", (signal) =>
    api.request("get", "/api/v1/user-groups", { signal }),
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [done, setDone] = useState("");
  const action = useAction();
  const fields = action.error?.fields ?? {};
  const sorting = useSorting(groups.data, {
    name: (group) => group.name,
    description: (group) => group.description,
    members: (group) => group.member_count,
    roles: (group) => group.roles.map((role) => roleLabel(role)).join(", "),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setDone("");
    const body: Schemas["GroupCreate"] = { name: name.trim(), description: description.trim() };
    const result = await action.run(() => api.request("post", "/api/v1/user-groups", { body }));
    if (!result.ok) return;
    setName("");
    setDescription("");
    setDone(`The group ${result.value.name} was created.`);
    groups.reload();
  }

  return (
    <>
      <AdminNav />
      <h1>Groups</h1>
      <p>
        A group is a label for a set of users. A role granted to a group is held by every member.
      </p>
      <Problem error={groups.error} />
      {groups.loading && !groups.data && <p role="status">Loading…</p>}
      {groups.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">User groups</caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="name">
                  Name
                </SortTh>
                <SortTh sort={sorting} column="description">
                  Description
                </SortTh>
                <SortTh sort={sorting} column="members" className="number">
                  Members
                </SortTh>
                <SortTh sort={sorting} column="roles">
                  Roles
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((group) => (
                <tr key={group.hid}>
                  <th scope="row">
                    <Link to={`/admin/groups/${encodeURIComponent(group.hid)}`}>{group.name}</Link>
                  </th>
                  <td>{group.description}</td>
                  <td className="number">{group.member_count}</td>
                  <td>{group.roles.map((role) => roleLabel(role)).join(", ")}</td>
                </tr>
              ))}
              {groups.data.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    There are no groups.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <section className="panel" aria-labelledby="new-group">
        <h2 id="new-group">New group</h2>
        <form onSubmit={submit} className="stack">
          <Problem error={action.error} shown={["name", "description"]} />
          <Notice text={done} />
          <TextField
            label="Name"
            name="name"
            value={name}
            onChange={setName}
            required
            maxLength={100}
            autoComplete="off"
            error={fields.name}
          />
          <TextField
            label="Description"
            name="description"
            value={description}
            onChange={setDescription}
            autoComplete="off"
            error={fields.description}
          />
          <p className="actions">
            <button type="submit" className="primary" disabled={action.busy}>
              Create group
            </button>
          </p>
        </form>
      </section>
    </>
  );
}

/** Admin → Groups → one group: its name, its members, and removing it. */
export function GroupDetail() {
  const { hid = "" } = useParams();
  const group = useLoad(`group ${hid}`, (signal) =>
    api.request("get", "/api/v1/user-groups/{hid}", { path: { hid }, signal }),
  );
  useTitle(group.data ? `Group ${group.data.name}` : "Group");

  return (
    <>
      <AdminNav />
      <p className="crumbs">
        <Link to="/admin/groups">Groups</Link>
      </p>
      <h1>{group.data ? group.data.name : "Group"}</h1>
      <Problem error={group.error} />
      {group.loading && !group.data && <p role="status">Loading…</p>}
      {group.data && (
        <>
          <dl className="facts">
            <dt>Roles</dt>
            <dd>
              {group.data.roles.length > 0 ? (
                group.data.roles.map((role) => roleLabel(role)).join(", ")
              ) : (
                <span className="muted">none</span>
              )}{" "}
              <Link to="/admin/roles">(role grants)</Link>
            </dd>
            <dt>Members</dt>
            <dd>{group.data.member_count}</dd>
          </dl>
          <GroupForm
            key={`${group.data.hid} ${group.data.row_version}`}
            group={group.data}
            reload={group.reload}
          />
          {/* 0.9.17: the roles it grants, each revoked here, saying first whom that leaves
              with no role (P-314 (4)). */}
          <GroupGrants group={group.data} reload={group.reload} />
          <Members group={group.data} reload={group.reload} />
          <DeleteGroup group={group.data} />
        </>
      )}
    </>
  );
}

function GroupForm({ group, reload }: { group: Group; reload: () => void }) {
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description);
  const action = useAction();
  const fields = action.error?.fields ?? {};
  const changed = name !== group.name || description !== group.description;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: Schemas["GroupPatch"] = { row_version: group.row_version };
    if (name !== group.name) body.name = name.trim();
    if (description !== group.description) body.description = description;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/user-groups/{hid}", { path: { hid: group.hid }, body }),
    );
    if (result.ok) reload();
  }

  return (
    <section aria-labelledby="group-details">
      <h2 id="group-details">Name and description</h2>
      <form onSubmit={submit} className="stack">
        <Problem error={action.error} shown={["name", "description"]} onReload={reload} />
        <TextField
          label="Name"
          name="name"
          value={name}
          onChange={setName}
          required
          maxLength={100}
          autoComplete="off"
          error={fields.name}
        />
        <TextField
          label="Description"
          name="description"
          value={description}
          onChange={setDescription}
          autoComplete="off"
          error={fields.description}
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

/**
 * 0.9.17: the roles a group grants, each a grant revoked here by an Admin. Before it is,
 * the confirmation says which members it leaves with no role, from the roles each holds
 * and where they come from (P-314 (4)).
 */
function GroupGrants({ group, reload }: { group: Group; reload: () => void }) {
  const auth = useAuth();
  const grants = useLoad(`grants of group ${group.hid} ${group.row_version}`, async (signal) =>
    (await api.request("get", "/api/v1/role-grants", { signal })).filter(
      (grant) => grant.group_hid === group.hid,
    ),
  );
  const [done, setDone] = useState("");
  const action = useAction();

  async function revoke(grant: Schemas["GrantOut"]) {
    setDone("");
    const result = await action.run(() =>
      api.request("delete", "/api/v1/role-grants/{hid}", { path: { hid: grant.hid } }),
    );
    if (!result.ok) return;
    setDone(`${roleLabel(grant.role)} was taken back from ${group.name}.`);
    grants.reload();
    reload();
    // The reader's own role may be what changed.
    auth.refresh();
  }

  return (
    <section aria-labelledby="group-grants">
      <h2 id="group-grants">Roles it grants</h2>
      <Problem error={grants.error} />
      <Problem error={action.error} />
      <Notice text={done} />
      {grants.data && grants.data.length === 0 && (
        <p className="muted">
          It grants no role: a role is granted to it under <Link to="/admin/roles">Roles</Link>.
        </p>
      )}
      {grants.data && grants.data.length > 0 && (
        <ul className="group-grants" data-testid="group-grants">
          {grants.data.map((grant) => {
            const leaves = noRoleWords(group.members, { kind: "revoke", grantHid: grant.hid });
            return (
              <li key={grant.hid} className="role-source" data-grant={grant.hid}>
                {roleLabel(grant.role)}{" "}
                <ConfirmButton
                  label={`Revoke ${roleLabel(grant.role)}`}
                  title={`Take ${roleLabel(grant.role)} back from ${group.name}?`}
                  confirmLabel="Revoke role"
                  onConfirm={() => revoke(grant)}
                  disabled={action.busy}
                >
                  <p>
                    Every member of the group {group.name} loses this role at once, unless they hold
                    it another way.
                  </p>
                  {leaves && (
                    <p data-testid="no-role-left">
                      <strong>{leaves}</strong>
                    </p>
                  )}
                </ConfirmButton>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Members({ group, reload }: { group: Group; reload: () => void }) {
  const auth = useAuth();
  const users = useLoad("users for members", (signal) =>
    api.request("get", "/api/v1/users", { query: { limit: EVERY_USER }, signal }),
  );
  const [chosen, setChosen] = useState("");
  const [done, setDone] = useState("");
  const action = useAction();
  // Add, apart from Remove: its refusal is said at the member chosen.
  const adding = useAction();
  const sorting = useSorting(group.members, {
    username: (member) => member.username,
    display_name: (member) => member.display_name,
    role: (member) => roleLabel(member.role),
    kind: (member) => kindWord(member.kind),
  });
  const inGroup = new Set(group.members.map((member) => member.hid));
  const candidates = (users.data?.items ?? []).filter((user) => !inGroup.has(user.hid));

  function changed(text: string) {
    setDone(text);
    reload();
    // Membership can carry a role, the reader's own included.
    auth.refresh();
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (chosen === "") return;
    setDone("");
    const user = candidates.find((candidate) => candidate.hid === chosen);
    action.clear();
    const result = await adding.run(() =>
      api.request("put", "/api/v1/user-groups/{hid}/members/{user_hid}", {
        path: { hid: group.hid, user_hid: chosen },
      }),
    );
    if (!result.ok) return;
    setChosen("");
    changed(`${user?.username ?? "The user"} was added to ${group.name}.`);
  }

  async function remove(member: Schemas["UserOut"]) {
    setDone("");
    adding.clear();
    const result = await action.run(() =>
      api.request("delete", "/api/v1/user-groups/{hid}/members/{user_hid}", {
        path: { hid: group.hid, user_hid: member.hid },
      }),
    );
    if (result.ok) changed(`${member.username} was removed from ${group.name}.`);
  }

  return (
    <section aria-labelledby="members">
      <h2 id="members">Members</h2>
      <Problem error={action.error} />
      {/* What the server refuses of Add is said in its words, and of the member chosen at
          the field, with no name of a field before it (review 3). */}
      <Problem error={adding.error} shown={["user_hid"]} />
      <Problem error={users.error} />
      <Notice text={done} />
      <div className="scroll">
        <table>
          <caption className="visually-hidden">Members of {group.name}</caption>
          <thead>
            <tr>
              <SortTh sort={sorting} column="username">
                Username
              </SortTh>
              <SortTh sort={sorting} column="display_name">
                Display name
              </SortTh>
              <SortTh sort={sorting} column="role">
                Role
              </SortTh>
              <SortTh sort={sorting} column="kind">
                Kind
              </SortTh>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((member) => (
              <tr key={member.hid} className={member.disabled ? "dim" : undefined}>
                <th scope="row">
                  <Link to={`/admin/users/${encodeURIComponent(member.hid)}`}>
                    {member.username}
                  </Link>
                </th>
                <td>{member.display_name}</td>
                <td>{roleLabel(member.role)}</td>
                <td>{kindWord(member.kind)}</td>
                <td>
                  <RemoveMember
                    group={group}
                    member={member}
                    disabled={action.busy}
                    onRemove={() => remove(member)}
                  />
                </td>
              </tr>
            ))}
            {group.members.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  This group has no members.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <form onSubmit={add} className="inline">
        <SelectField
          label="Add a member"
          name="user_hid"
          value={chosen}
          onChange={(hid) => {
            adding.clear();
            setChosen(hid);
          }}
          disabled={!users.data}
          error={adding.error?.fields.user_hid}
        >
          <option value="">Choose a user…</option>
          {candidates.map((user) => (
            <option key={user.hid} value={user.hid}>
              {user.display_name ? `${user.username} (${user.display_name})` : user.username}
            </option>
          ))}
        </SelectField>
        <button type="submit" disabled={action.busy || adding.busy || chosen === ""}>
          Add
        </button>
      </form>
      {users.data && users.data.total > users.data.items.length && (
        <p className="hint">
          Only the first {plural(users.data.items.length, "user")} of {users.data.total} can be
          chosen here.
        </p>
      )}
    </section>
  );
}

/**
 * Remove, of a member: at once, as before, unless it takes the member's last role; then
 * it asks first, saying so (P-314 (4)).
 */
function RemoveMember(props: {
  group: Group;
  member: Schemas["UserOut"];
  disabled: boolean;
  onRemove: () => Promise<void>;
}) {
  const { group, member, disabled, onRemove } = props;
  const leaves = noRoleWords([member], { kind: "leave", groupHid: group.hid });
  if (leaves === null) {
    return (
      <button type="button" onClick={() => void onRemove()} disabled={disabled}>
        Remove<span className="visually-hidden"> {member.username}</span>
      </button>
    );
  }
  return (
    <ConfirmButton
      label="Remove"
      hiddenLabel={member.username}
      title={`Take ${member.username} out of ${group.name}?`}
      confirmLabel={`Take ${member.username} out`}
      onConfirm={onRemove}
      disabled={disabled}
    >
      <p>{`The roles ${group.name} grants are all that ${member.username} holds.`}</p>
      <p data-testid="no-role-left">
        <strong>{leaves}</strong>
      </p>
    </ConfirmButton>
  );
}

function DeleteGroup({ group }: { group: Group }) {
  const navigate = useNavigate();
  const auth = useAuth();
  const action = useAction();
  // 0.9.17: the members a deletion leaves with no role, said first (P-314 (4)).
  const leaves = noRoleWords(group.members, { kind: "leave", groupHid: group.hid });

  async function remove() {
    const result = await action.run(() =>
      api.request("delete", "/api/v1/user-groups/{hid}", { path: { hid: group.hid } }),
    );
    if (!result.ok) return;
    auth.refresh();
    navigate("/admin/groups");
  }

  return (
    <section aria-labelledby="delete-group">
      <h2 id="delete-group">Delete</h2>
      <Problem error={action.error} />
      <p className="actions">
        <ConfirmButton
          label="Delete group"
          title={`Delete the group ${group.name}?`}
          confirmLabel="Delete group"
          onConfirm={remove}
          disabled={action.busy}
        >
          <p>
            The group goes, with its {plural(group.member_count, "membership")} and every role
            granted to it. The users themselves stay.
          </p>
          {leaves && (
            <p data-testid="no-role-left">
              <strong>{leaves}</strong>
            </p>
          )}
        </ConfirmButton>
      </p>
    </section>
  );
}
