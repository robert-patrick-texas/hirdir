// 0.9.17: who made a change, as a history shows it (P-316 (6)): the account, a link to
// its page for an Admin, and of an agent the person it was answerable to then, a link
// too, as `agent-reconcile for sam`.

import type { Acted } from "../lib/audit";
import { ValueLink } from "./ValueLink";

export function Actor({ event, admin }: { event: Acted; admin: boolean }) {
  if (!event.actor_name) return <span className="muted">—</span>;
  const agent = event.actor_kind === "agent" && event.for_name;
  return (
    <span data-testid="actor">
      <ValueLink kind="user" hid={event.actor_hid} admin={admin}>
        {event.actor_name}
      </ValueLink>
      {agent && (
        <>
          {" for "}
          <ValueLink kind="user" hid={event.for_hid} admin={admin}>
            {event.for_name}
          </ValueLink>
        </>
      )}
    </span>
  );
}
