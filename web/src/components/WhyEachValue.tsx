// The walks of a record, read from the server when they are asked for (P-176, P-198):
// `GET /items/{hid}/resolution` for an item, `GET /device-groups/{hid}/resolution` for a
// group. Both are read by every role. They stand behind a line, closed when the page
// opens: the table of the values in force above says the source of each, and the walks
// are long.

import { type ReactNode, useState } from "react";
import { api } from "../api";
import { useLoad } from "../lib/hooks";
import { Problem } from "./Problem";
import { ResolutionWalks } from "./ResolutionWalks";

interface WhyEachValueProps {
  /** Whose walks: an item's or a device group's. */
  of: "item" | "group";
  hid: string;
  /**
   * What the page knows of the record and of its values in force: when it changes, the
   * walks are read again. A change of a group or a place above is seen when the page is.
   */
  version: string;
  level?: 3 | 4;
  /** What is said of the walks above them, once they are open. */
  children?: ReactNode;
}

/**
 * The walks, folded until they are asked for (P-198). They are read when the line is
 * opened and not before, so a page does not wait for them and nothing under them is
 * moved when they come.
 */
export function WhyEachValue({ children, ...asked }: WhyEachValueProps) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="why-each-value"
      data-testid="why-each-value"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Why it has each value</summary>
      {open && (
        <>
          {children}
          <Walks {...asked} />
        </>
      )}
    </details>
  );
}

function Walks({ of, hid, version, level }: Omit<WhyEachValueProps, "children">) {
  const found = useLoad(`resolution ${of} ${hid} ${version}`, (signal) =>
    of === "item"
      ? api.request("get", "/api/v1/items/{hid}/resolution", { path: { hid }, signal })
      : api.request("get", "/api/v1/device-groups/{hid}/resolution", { path: { hid }, signal }),
  );
  return (
    <div>
      <Problem error={found.error} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Working out each walk…
        </p>
      )}
      {found.data && <ResolutionWalks resolution={found.data} {...(level ? { level } : {})} />}
    </div>
  );
}
