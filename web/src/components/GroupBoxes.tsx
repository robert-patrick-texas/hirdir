// 0.9.13: the groups of a user, on the user's page (P-282). A box to each group there
// is, with the roles the group grants; ticking it puts the user in the group at once,
// and unticking takes the user out, each by its own request, as the page of the group
// does. A refusal is said beside the box, which goes back to what the server holds. A
// box pressed again while its request is out sends nothing more. A group deleted since
// the page was read is said so, by its name, and its box taken away.

import { useId, useRef, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { ApiError } from "../api/client";
import { useAction, useLoad } from "../lib/hooks";
import { goneGroups, goneWords, groupGrants } from "../lib/onboarding";
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
  // 0.9.13: the groups deleted since the page was read, by name.
  const [gone, setGone] = useState<readonly string[]>([]);

  /**
   * A change was refused as of a group that is not there: where the group was deleted,
   * the list is read again, without its box, and the page says so by the group's name.
   */
  async function missing(group: Group) {
    try {
      const now = await api.request("get", "/api/v1/user-groups", {});
      const names = goneGroups(groups.data ?? [], now, [group.hid]);
      if (names.length === 0) return;
      setGone((was) => [...was.filter((name) => !names.includes(name)), ...names]);
      groups.reload();
    } catch {
      // Not read: the refusal beside the box says what there is to say.
    }
  }

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
          <div className="live" role="status">
            {gone.length > 0 && (
              <p className="field-error" data-testid="groups-gone">
                {goneWords(gone)}
              </p>
            )}
          </div>
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
              onMissing={(missed) => void missing(missed)}
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
  /** A change was refused as of a group or a user that is not there. */
  onMissing: (group: Group) => void;
}

function GroupBox({ user, group, member, onChanged, onMissing }: GroupBoxProps) {
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
    let notThere = false;
    const result = await action.run(async () => {
      try {
        return await (next
          ? api.request("put", "/api/v1/user-groups/{hid}/members/{user_hid}", { path })
          : api.request("delete", "/api/v1/user-groups/{hid}/members/{user_hid}", { path }));
      } catch (thrown) {
        // Not there: the group may have been deleted since the page was read.
        notThere = thrown instanceof ApiError && thrown.status === 404;
        throw thrown;
      }
    });
    out.current = false;
    setWanted(null);
    if (result.ok) onChanged(group, next);
    else if (notThere) onMissing(group);
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
