// 0.9.6: a member's page says it is a member, and a switch joins a stack from its own page
// (P-222). A member of a stack has no name or address of its own: the stack's are shown
// among its first facts, each said to be the stack's and read from the stack when the
// page is read, never kept on the item.

import { type FormEvent, type ReactNode, useState } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import type { FilterNode } from "../lib/filter";
import { itemName } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { buildMembers, type PendingMember } from "../lib/groups";
import { useAction, useLoad } from "../lib/hooks";
import { useRules } from "../lib/lists";
import { fieldErrors } from "../lib/problems";
import { joinedText, MEMBER_FIELDS, refusedRows, stackOf } from "../lib/stacks";
import { TextField } from "./Field";
import { MakeStack } from "./MakeStack";
import { JoinBox, joining } from "./MemberPicker";
import { Problem } from "./Problem";
import { type Offer, SearchPicker } from "./SearchPicker";

type Item = Schemas["ItemOut"];

// The states in which an item joins no group: it has left the inventory, or is leaving it.
const JOINS_NONE: readonly string[] = ["Released", "Archived"];

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
        <NoStack item={item} onJoined={onChanged} />
      </dd>
    </>
  );
}

/**
 * An item in no stack: Join a stack, and 0.9.8 beside it Make it a stack (P-243). One of
 * the two forms is open at a time.
 */
function NoStack({ item, onJoined }: { item: Item; onJoined: (text: string) => void }) {
  const [making, setMaking] = useState(false);
  if (making) return <MakeStack item={item} onCancel={() => setMaking(false)} />;
  return (
    <JoinStack
      item={item}
      onJoined={onJoined}
      beside={
        <button type="button" onClick={() => setMaking(true)}>
          Make it a stack
        </button>
      }
    />
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
 * stack's lowest free one (P-219); then the box of the stack's name and place, ticked from
 * the start, as Add members on the stack's page has it (P-217). The server checks the
 * member as it checks any.
 */
function JoinStack({
  item,
  onJoined,
  beside,
}: {
  item: Item;
  onJoined: (text: string) => void;
  /** What stands beside Join a stack while its form is closed. */
  beside?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [stack, setStack] = useState<Offer | null>(null);
  // The position as typed: null until it is, when the stack's next one is offered.
  const [position, setPosition] = useState<string | null>(null);
  // The box and the standing, as changed: null until they are, when they are offered.
  const [change, setChange] = useState<Partial<PendingMember> | null>(null);
  const rules = useRules();
  const action = useAction();
  const group = useLoad(`stack to join ${stack?.hid ?? ""}`, async (signal) => {
    if (stack === null) return null;
    return api.request("get", "/api/v1/device-groups/{hid}", { path: { hid: stack.hid }, signal });
  });
  const next = group.data?.next_position;
  const shownPosition = position ?? (typeof next === "number" ? String(next) : "");
  const name = itemName(item);
  const row: PendingMember = {
    item_hid: item.hid,
    name,
    role: "member",
    position: shownPosition,
    ...joining(item, rules.data ?? []),
    ...change,
  };
  const fields = MEMBER_FIELDS.map((field) => `members.0.${field}`);
  const refused = fieldErrors(action.error, fields).shown;
  const answered = refusedRows([row], refused, action.error?.existing ?? null);
  const holder = answered.holders[item.hid];

  async function join(event: FormEvent) {
    event.preventDefault();
    if (stack === null) return;
    const built = buildMembers("stack", [row]);
    const member = built.members[0];
    if (!member) {
      action.clear();
      return;
    }
    const result = await action.run(() =>
      api.request("post", "/api/v1/device-groups/{hid}/members", {
        path: { hid: stack.hid },
        body: { members: [member] },
      }),
    );
    if (result.ok) {
      const made = result.value[0];
      onJoined(
        joinedText(
          stack.label,
          name,
          made?.position ?? member.position ?? null,
          member,
          row.joining,
        ),
      );
    }
  }

  function close() {
    setOpen(false);
    setStack(null);
    setPosition(null);
    setChange(null);
    action.clear();
  }

  if (!open) {
    return (
      <>
        <span className="muted">In no stack</span>{" "}
        <button type="button" onClick={() => setOpen(true)}>
          Join a stack
        </button>
        {beside && <> {beside}</>}
      </>
    );
  }
  return (
    <section className="panel join-stack" aria-labelledby="join-stack">
      <h3 id="join-stack">Join a stack</h3>
      <form onSubmit={join} className="stack" noValidate>
        <Problem error={action.error} shown={fields} />
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
          <>
            <TextField
              label="Position"
              name="position"
              inputMode="numeric"
              autoComplete="off"
              value={shownPosition}
              onChange={setPosition}
              error={answered.errors[item.hid]}
              hint="The member's number in the stack: the lowest that is free is offered."
            />
            {holder && (
              <p className="field-error" data-testid="position-holder">
                It is held by <Link to={holder.to}>{holder.label}</Link>.
              </p>
            )}
            <JoinBox
              row={row}
              rules={rules.data ?? []}
              onChange={(changed) => setChange((was) => ({ ...was, ...changed }))}
              disabled={action.busy}
            />
          </>
        )}
        <p className="actions">
          <button type="submit" className="primary" disabled={action.busy || stack === null}>
            Join the stack
          </button>
          <button type="button" onClick={close} disabled={action.busy}>
            Cancel
          </button>
        </p>
      </form>
    </section>
  );
}
