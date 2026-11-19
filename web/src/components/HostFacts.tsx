// 0.9.8: among the first facts of an item of a kind that runs on a host, what it runs on
// and what it was seen on (P-250), where a member of a stack says it is a member (P-222).
// The host is a link, an item or a stack or a cluster, said to be which. An item that
// names none says so, as to be looked at (P-249), with the way to name one; one whose
// host is gone says that, with the host still a link. That the host seen differs from
// the one named is no fault, and is said in a plain word. One entered, before 0.9.8, as
// installed in its server says so, with one press that makes that server its host.

import type { ReactNode } from "react";
import { Link } from "react-router";
import { api, type Schemas } from "../api";
import { itemName } from "../lib/format";
import { useAction } from "../lib/hooks";
import { hostMadeText, hostPath, hostWhat, parentAsHostBody, runsOnHost } from "../lib/hosting";
import { Problem } from "./Problem";
import { Time } from "./Time";

type Item = Schemas["ItemOut"];

interface HostFactsProps {
  item: Item;
  /** The way to name or change its host: a link to the field of the form of details. */
  change?: ReactNode;
  /** Whether the person may change the item: Make <parent> its host is offered then. */
  mayChange?: boolean;
  /** Said at the top of the page when the item was changed, which is read again. */
  onChanged?: (text: string) => void;
}

/**
 * An item of a kind that runs on a host, entered as installed in another, as a virtual
 * machine was in its server before 0.9.8: it says so, and one press makes that item its
 * host, taking it out of its parent in the same request, which is the one the server takes.
 */
function InstalledIn({
  item,
  mayChange,
  onChanged,
}: {
  item: Item;
  mayChange: boolean;
  onChanged: ((text: string) => void) | undefined;
}) {
  const action = useAction();
  const parent = item.parent;
  if (!parent) return null;
  const name = itemName(parent);
  async function make() {
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: parentAsHostBody(item),
      }),
    );
    if (result.ok) onChanged?.(hostMadeText(result.value, item.parent_item_hid ?? ""));
  }
  return (
    <div className="review-line" data-testid="installed-in">
      {" "}
      It is entered as installed in{" "}
      <Link to={`/items/${encodeURIComponent(parent.hid)}`}>{name}</Link>.
      {mayChange && (
        <>
          {" "}
          <button type="button" onClick={make} disabled={action.busy}>
            Make {name} its host
          </button>
        </>
      )}
      <Problem error={action.error} />
    </div>
  );
}

/**
 * The item a virtual context's serial number is the serial number of, where it names no
 * host and one item has it (P-251): the `about` of its `no_host` reason.
 */
function serialOf(item: Item): { hid: string; label: string } | null {
  const about = item.review.find((reason) => reason.reason === "no_host")?.about;
  return about && about.record_type === "item" && item.serial_number
    ? { hid: about.hid, label: about.label }
    : null;
}

/**
 * A virtual context that holds the serial number of an item it does not name as its
 * host, as one reported before its switch was entered (P-251): which item has it, and
 * one press that makes that item its host. The server clears the number it held.
 */
function SerialOf({
  item,
  mayChange,
  onChanged,
}: {
  item: Item;
  mayChange: boolean;
  onChanged: ((text: string) => void) | undefined;
}) {
  const action = useAction();
  const of = serialOf(item);
  if (!of) return null;
  async function make() {
    if (!of) return;
    const result = await action.run(() =>
      api.request("patch", "/api/v1/items/{hid}", {
        path: { hid: item.hid },
        body: { row_version: item.row_version, host_item_hid: of.hid },
      }),
    );
    if (result.ok) onChanged?.(hostMadeText(result.value, of.hid));
  }
  return (
    <div className="review-line" data-testid="serial-of">
      <span className="mono">{item.serial_number}</span> is the serial number of{" "}
      <Link to={`/items/${encodeURIComponent(of.hid)}`}>{of.label}</Link>.
      {mayChange && (
        <>
          {" "}
          <button type="button" onClick={make} disabled={action.busy}>
            Make it its host
          </button>
        </>
      )}
      <Problem error={action.error} />
    </div>
  );
}

/** The mark of a reason to look at an item: a word, not the colour of a fault. */
export function ReviewMark() {
  return <span className="badge badge-plain review-mark">To be looked at</span>;
}

/** Whether an item's page says what it runs on: one of a kind that runs on a host. */
export function showsHost(item: Item): boolean {
  return runsOnHost(item.catalog?.kind);
}

export function HostFacts({ item, change, mayChange = false, onChanged }: HostFactsProps) {
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
                <ReviewMark /> {item.parent ? "" : "Name the one it runs on under Host in Details."}
              </>
            )}
          </span>
        )}
        {!host && item.parent ? (
          <InstalledIn item={item} mayChange={mayChange} onChanged={onChanged} />
        ) : !host && serialOf(item) ? (
          <SerialOf item={item} mayChange={mayChange} onChanged={onChanged} />
        ) : (
          change
        )}
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
