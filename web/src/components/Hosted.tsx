// 0.9.8: What runs on it, on the page of an item and of a stack or a cluster that
// something runs on (P-250): each as a link, with its kind, its state and its primary
// address, and what runs on those indented beneath them. Read from `GET
// /items/{hid}/hosted` and `GET /device-groups/{hid}/hosted`, which list each after its
// host. A record that nothing runs on shows nothing of it.

import { Link } from "react-router";
import { api } from "../api";
import { managementText } from "../lib/addresses";
import { effectiveText } from "../lib/effective";
import { itemName, plural } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { hostedRows } from "../lib/hosting";
import { CATALOG_KINDS, optionLabel } from "../lib/options";
import { Problem } from "./Problem";

interface WhatRunsOnItProps {
  of: "item" | "group";
  hid: string;
  /** How many not retired name it as their host, as its record says. */
  count: number;
  /** Changes when the record does, so that the list is read again. */
  version: string;
}

export function WhatRunsOnIt({ of, hid, count, version }: WhatRunsOnItProps) {
  const hosted = useLoad(`hosted ${of} ${hid} ${version} ${count}`, async (signal) => {
    if (count === 0) return null;
    return of === "item"
      ? api.request("get", "/api/v1/items/{hid}/hosted", { path: { hid }, signal })
      : api.request("get", "/api/v1/device-groups/{hid}/hosted", { path: { hid }, signal });
  });
  if (count === 0) return null;
  const rows = hosted.data ? hostedRows(hosted.data.items) : [];
  const beneath = rows.filter((row) => row.depth > 1).length;
  return (
    <section aria-labelledby="hosted" data-testid="hosted">
      <h2 id="hosted">What runs on it ({count.toLocaleString("en-US")})</h2>
      <Problem error={hosted.error} />
      {hosted.loading && !hosted.data && (
        <p role="status" className="muted loading-late">
          Reading what runs on it…
        </p>
      )}
      {hosted.data && (
        <>
          <p className="muted">
            {plural(count, "item runs", "items run")} on it
            {beneath > 0 ? `, and ${plural(beneath, "more")} on those, beneath them` : ""}.
          </p>
          <div className="scroll">
            <table className="narrow hosted-list" data-testid="hosted-list">
              <caption className="visually-hidden">What runs on it, and on those</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Kind</th>
                  <th scope="col">State</th>
                  <th scope="col">Primary address</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ item, depth }) => (
                  <tr key={item.hid} data-depth={depth} data-item={item.hid}>
                    <th scope="row">
                      <span className={`hosted-depth hosted-depth-${Math.min(depth, 3)}`}>
                        <Link to={`/items/${encodeURIComponent(item.hid)}`}>{itemName(item)}</Link>
                      </span>
                    </th>
                    <td>{item.catalog ? optionLabel(CATALOG_KINDS, item.catalog.kind) : ""}</td>
                    <td>
                      {effectiveText(item.effective.lifecycle_state)}
                      {item.record_status === "retired" && <span className="badge">Retired</span>}
                    </td>
                    <td className="mono">{managementText(item.addresses)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
