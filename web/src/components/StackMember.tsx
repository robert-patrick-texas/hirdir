// 0.9.6: a member's page says it is a member, and a switch joins a stack from its own page
// (P-222). A member of a stack has no name or address of its own: the stack's are shown
// among its first facts, each said to be the stack's and read from the stack when the
// page is read, never kept on the item.

import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import type { FilterNode } from "../lib/filter";
import { itemName } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { nextPosition } from "../lib/groups";
import { useAction, useLoad } from "../lib/hooks";
import { fieldErrors } from "../lib/problems";
import { stackOf } from "../lib/stacks";
import { TextField } from "./Field";
import { Problem } from "./Problem";
import { type Offer, SearchPicker } from "./SearchPicker";

type Item = Schemas["ItemOut"];

// The states in which an item joins no group: it has left the inventory, or is leaving it.
const JOINS_NONE: readonly string[] = ["Released", "Archived"];
// The most members of a stack read to offer the next position.
const MOST_MEMBERS = 100;

function groupPath(hid: string): string {
  return `/groups/${encodeURIComponent(hid)}`;
}

/** Whether an item that is in no stack may join one: a major item, in hand, not retired. */
export function mayJoin(item: Item): boolean {
  return (
    item.is_major &&
    item.record_status !== "retired" &&
    !JOINS_NONE.includes(item.lifecycle_state ?? "") &&
    stackOf(item.groups) === undefined
  );
}

interface StackFactsProps {
  item: Item;
  /** Whether the person may change the item: Join a stack is offered then. */
  mayChange: boolean;
  /** Said at the top of the page when the item has joined, which is read again. */
  onChanged: (text: string) => void;
}

/**
 * Among the first facts: Member 2 of the stack, as a link, with the stack's host name,
 * FQDN and addresses; or, for an item in no stack that may be in one, Join a stack.
 */
export function StackFacts({ item, mayChange, onChanged }: StackFactsProps) {
  const stack = stackOf(item.groups);
  if (stack)
    return <MemberFacts groupHid={stack.group_hid} name={stack.name} position={stack.position} />;
  if (!mayChange || !mayJoin(item)) return null;
  return (
    <>
      <dt>Stack</dt>
      <dd data-testid="stack-member">
        <JoinStack item={item} onJoined={onChanged} />
      </dd>
    </>
  );
}

function MemberFacts({
  groupHid,
  name,
  position,
}: {
  groupHid: string;
  name: string;
  position: number | null;
}) {
  const group = useLoad(`stack of the member ${groupHid}`, (signal) =>
    api.request("get", "/api/v1/device-groups/{hid}", { path: { hid: groupHid }, signal }),
  );
  const data = group.data;
  // The lines are there from the start, so that what comes late moves nothing.
  const late = (value: string | null | undefined) =>
    data ? value || <span className="muted">—</span> : <span className="muted">…</span>;
  return (
    <>
      <dt>Stack</dt>
      <dd data-testid="stack-member">
        {position === null ? "Member" : `Member ${position}`} of{" "}
        <Link to={groupPath(groupHid)}>{name}</Link>
      </dd>
      <dt>Stack&apos;s hostname</dt>
      <dd data-testid="stack-hostname">
        {late(data?.hostname)}
        <span className="muted"> · the stack&apos;s, not the switch&apos;s own</span>
      </dd>
      <dt>Stack&apos;s FQDN</dt>
      <dd data-testid="stack-fqdn">{late(data?.fqdn)}</dd>
      <dt>Stack&apos;s addresses</dt>
      <dd data-testid="stack-addresses">
        {data && data.addresses.length > 0 ? (
          <ul className="plain-list">
            {data.addresses.map((address) => (
              <li key={address.hid}>
                <span className="mono">{address.address}</span>
                <span className="muted">
                  {" "}
                  {[address.role, address.is_primary ? "primary" : "", address.network ?? ""]
                    .filter(Boolean)
                    .join(", ")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          late(null)
        )}
        <Problem error={group.error} />
      </dd>
    </>
  );
}

/** The stacks whose name holds what was typed, drafts among them. */
async function findStacks(typed: string, limit: number, signal: AbortSignal) {
  const value = typed.trim().slice(0, 200);
  if (value === "") return null;
  const filter: FilterNode = {
    and: [
      { field: "type", op: "eq", value: "stack" },
      { field: "name", op: "contains", value },
    ],
  };
  const page = await api.request("post", "/api/v1/device-groups/query", {
    body: {
      ...queryBody({
        filter,
        sort: ["name"],
        limit,
        offset: 0,
        include_archived: false,
        include_drafts: true,
      }),
      fields: ["name", "record_status", "member_count"],
    },
    signal,
  });
  return {
    offers: page.items.map(
      (group): Offer => ({
        hid: group.hid,
        label: group.name,
        note: [`${group.member_count ?? 0} members`, group.record_status === "draft" ? "draft" : ""]
          .filter(Boolean)
          .join(", "),
      }),
    ),
    total: page.total,
  };
}

/**
 * Join a stack: the stack is searched for by its name, and the position offered is the
 * next one. The server checks the member as it checks any.
 */
function JoinStack({ item, onJoined }: { item: Item; onJoined: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [stack, setStack] = useState<Offer | null>(null);
  // The position as typed: null until it is, when the next one is offered.
  const [position, setPosition] = useState<string | null>(null);
  const action = useAction();
  const members = useLoad(`members of ${stack?.hid ?? ""}`, async (signal) => {
    if (stack === null) return null;
    return api.request("get", "/api/v1/device-groups/{hid}/members", {
      path: { hid: stack.hid },
      query: { limit: MOST_MEMBERS, offset: 0 },
      signal,
    });
  });
  const offered = members.data
    ? String(nextPosition(members.data.items.map((member) => member.position)))
    : "";
  const shownPosition = position ?? offered;
  const refused = fieldErrors(action.error, ["members.0.position"]).shown;

  async function join(event: FormEvent) {
    event.preventDefault();
    if (stack === null) return;
    const typed = shownPosition.trim();
    const result = await action.run(() =>
      api.request("post", "/api/v1/device-groups/{hid}/members", {
        path: { hid: stack.hid },
        body: {
          members: [
            {
              item_hid: item.hid,
              role: "member",
              ...(typed === "" ? {} : { position: Number(typed) }),
            },
          ],
        },
      }),
    );
    if (result.ok) {
      const at = typed === "" ? "a member" : `member ${typed}`;
      onJoined(`${itemName(item)} joined the stack ${stack.label} as ${at}.`);
    }
  }

  if (!open) {
    return (
      <>
        <span className="muted">In no stack</span>{" "}
        <button type="button" onClick={() => setOpen(true)}>
          Join a stack
        </button>
      </>
    );
  }
  return (
    <section className="panel join-stack" aria-labelledby="join-stack">
      <h3 id="join-stack">Join a stack</h3>
      <form onSubmit={join} className="stack" noValidate>
        <Problem error={action.error} shown={["members.0.position"]} />
        {stack === null ? (
          <SearchPicker
            label="Stack"
            hint="Type a part of the stack's name."
            noun={["stack", "stacks"]}
            find={findStacks}
            onPick={(offer) => {
              setStack(offer);
              setPosition(null);
            }}
          />
        ) : (
          <p data-testid="join-stack-chosen">
            Stack <Link to={groupPath(stack.hid)}>{stack.label}</Link>{" "}
            <button type="button" onClick={() => setStack(null)} disabled={action.busy}>
              Choose another
            </button>
          </p>
        )}
        {stack !== null && (
          <TextField
            label="Position"
            name="position"
            inputMode="numeric"
            autoComplete="off"
            value={shownPosition}
            onChange={setPosition}
            error={refused["members.0.position"]}
            hint="The member's number in the stack. The next one is offered."
          />
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || stack === null}>
            Join the stack
          </button>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setStack(null);
              setPosition(null);
              action.clear();
            }}
            disabled={action.busy}
          >
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
