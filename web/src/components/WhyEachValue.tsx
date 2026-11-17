// The walks of a record, read from the server when its page shows them (P-176):
// `GET /items/{hid}/resolution` for an item, `GET /device-groups/{hid}/resolution` for a
// group. Both are read by every role.

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
}

export function WhyEachValue({ of, hid, version, level }: WhyEachValueProps) {
  const found = useLoad(`resolution ${of} ${hid} ${version}`, (signal) =>
    of === "item"
      ? api.request("get", "/api/v1/items/{hid}/resolution", { path: { hid }, signal })
      : api.request("get", "/api/v1/device-groups/{hid}/resolution", { path: { hid }, signal }),
  );
  return (
    <div data-testid="why-each-value">
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
