// 0.9.8: among the first facts of an item of a kind that runs on a host, what it runs on
// and what it was seen on (P-250), where a member of a stack says it is a member (P-222).
// The host is a link, an item or a stack or a cluster, said to be which. An item that
// names none says so, as to be looked at (P-249), with the way to name one; one whose
// host is gone says that, with the host still a link. That the host seen differs from
// the one named is no fault, and is said in a plain word.

import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Schemas } from "../api";
import { itemName } from "../lib/format";
import { hostPath, hostWhat, runsOnHost } from "../lib/hosting";
import { Time } from "./Time";

type Item = Schemas["ItemOut"];

interface HostFactsProps {
  item: Item;
  /** The way to name or change its host: a link to the field of the form of details. */
  change?: ReactNode;
}

/** The mark of a reason to look at an item: a word, not the colour of a fault. */
export function ReviewMark() {
  return <span className="badge badge-plain review-mark">To be looked at</span>;
}

/** Whether an item's page says what it runs on: one of such a kind, or one that names a host. */
export function showsHost(item: Item): boolean {
  return runsOnHost(item.catalog?.kind) || item.host !== null || item.observed_host !== null;
}

export function HostFacts({ item, change }: HostFactsProps) {
  if (!showsHost(item)) return null;
  const { host } = item;
  const gone = item.review.some((reason) => reason.reason === "host_gone");
  const none = item.review.some((reason) => reason.reason === "no_host");
  return (
    <>
      <dt>Runs on</dt>
      <dd data-testid="runs-on" data-review={gone ? "host_gone" : none ? "no_host" : undefined}>
        {host ? (
          <>
            <Link to={hostPath(host)} data-testid="host-link">
              {host.name}
            </Link>
            <span className="muted">
              {" "}
              · {hostWhat(host)}
              {host.pid ? `, ${host.pid}` : ""}
            </span>
            {gone && (
              <span className="review-line" data-testid="host-gone">
                {" "}
                <ReviewMark /> Its host is{" "}
                {host.record_status === "retired" ? "retired" : "out of the team's hands"}: name
                another host, or retire this item.
              </span>
            )}
          </>
        ) : (
          <span className="review-line" data-testid="no-host">
            <span className="muted">It names no host.</span>
            {none && (
              <>
                {" "}
                <ReviewMark /> Name the one it runs on under Host in Details.
              </>
            )}
          </span>
        )}
        {change}
      </dd>
      {item.observed_host && (
        <>
          <dt>Seen on</dt>
          <dd data-testid="seen-on">
            <Link to={`/items/${encodeURIComponent(item.observed_host.hid)}`}>
              {itemName(item.observed_host)}
            </Link>
            <span className="muted">
              {" "}
              · <Time at={item.host_observed_at} />
            </span>
            {item.host_differs === true && (
              <span className="muted" data-testid="host-differs">
                {" "}
                · not the host named
              </span>
            )}
          </dd>
        </>
      )}
    </>
  );
}
