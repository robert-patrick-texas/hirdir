// 0.9.13: the groups of a user, on the user's page (P-282). A box to each group there
// is, with the roles the group grants; ticking it puts the user in the group at once,
// and unticking takes the user out, each by its own request, as the page of the group
// does. A refusal is said beside the box, which goes back to what the server holds. A
// box pressed again while its request is out sends nothing more.

import { useId, useRef, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { useAction, useLoad } from "../lib/hooks";
import { groupGrants } from "../lib/onboarding";
import { Problem } from "./Problem";

type Group = Schemas["GroupOut"];
type User = Schemas["UserOut"];

interface GroupBoxesProps {
  user: User;
  /** A membership changed: the page reads the user again, its role and its groups. */
  onChanged: () => void;
}

export function GroupBoxes({ user, onChanged }: GroupBoxesProps) {
  const groups = useLoad("user-groups", (signal) =>
    api.request("get", "/api/v1/user-groups", { signal }),
  );
  // What the server holds, as the user was read and as each change since has made it.
  const [member, setMember] = useState<ReadonlySet<string>>(
    () => new Set(user.groups.map((group) => group.hid)),
  );
  const id = useId();

  function changed(group: Group, now: boolean) {
    setMember((was) => {
      const next = new Set(was);
      if (now) next.add(group.hid);
      else next.delete(group.hid);
      return next;
    });
    onChanged();
  }

  return (
    <section aria-labelledby={`${id}-groups`}>
      <h2 id={`${id}-groups`}>Groups</h2>
      <Problem error={groups.error} />
      {!groups.data && !groups.error && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {groups.data && (
        <fieldset
          className="field check-group group-boxes"
          data-testid="user-groups"
          aria-describedby={`${id}-hint`}
        >
          <legend>The groups {user.username} is in</legend>
          <p className="hint" id={`${id}-hint`}>
            A box puts {user.username} in the group, or takes them out of it, at once. A member
            holds the roles the group grants.
          </p>
          {groups.data.length === 0 && (
            <p className="muted">
              There are no groups. A group is made under <Link to="/admin/groups">Groups</Link>.
            </p>
          )}
          {groups.data.map((group) => (
            <GroupBox
              key={group.hid}
              user={user}
              group={group}
              member={member.has(group.hid)}
              onChanged={changed}
            />
          ))}
        </fieldset>
      )}
    </section>
  );
}

interface GroupBoxProps {
  user: User;
  group: Group;
  member: boolean;
  onChanged: (group: Group, member: boolean) => void;
}

function GroupBox({ user, group, member, onChanged }: GroupBoxProps) {
  const id = useId();
  const action = useAction();
  // What was asked for while its request is out; null when none is.
  const [wanted, setWanted] = useState<boolean | null>(null);
  // Held at once, before the page has drawn the box as busy: a second press sends nothing.
  const out = useRef(false);
  const shown = wanted ?? member;

  async function toggle(next: boolean) {
    if (out.current) return;
    out.current = true;
    setWanted(next);
    const path = { hid: group.hid, user_hid: user.hid };
    const result = await action.run(() =>
      next
        ? api.request("put", "/api/v1/user-groups/{hid}/members/{user_hid}", { path })
        : api.request("delete", "/api/v1/user-groups/{hid}/members/{user_hid}", { path }),
    );
    out.current = false;
    setWanted(null);
    if (result.ok) onChanged(group, next);
  }

  const refusal = action.error && !action.error.aborted ? action.error.message : "";
  return (
    <div className="choice group-box" data-group={group.name} aria-busy={wanted !== null}>
      <input
        id={id}
        type="checkbox"
        name="group_hids"
        value={group.hid}
        checked={shown}
        aria-invalid={refusal ? true : undefined}
        aria-describedby={`${id}-grants${refusal ? ` ${id}-error` : ""}`}
        onChange={(event) => {
          void toggle(event.target.checked);
        }}
      />
      <label htmlFor={id}>{group.name}</label>
      <span className="muted" id={`${id}-grants`}>
        {groupGrants(group.roles)}
      </span>
      <span className="group-box-state" role="status">
        {wanted === true && " Adding…"}
        {wanted === false && " Taking out…"}
      </span>
      {refusal && (
        <p className="field-error" id={`${id}-error`}>
          {member
            ? `Not taken out of ${group.name}: ${refusal}`
            : `Not added to ${group.name}: ${refusal}`}
        </p>
      )}
    </div>
  );
}
