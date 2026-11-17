// Where a location is searched for and none matches, the sites the same words find
// (P-184). An item is put at a location, never at a site: a site that matches is named,
// with the words that it has no location that matches and a link to its page, where a
// location is made in it.

import { Link } from "react-router";
import { api } from "../api";
import { plural } from "../lib/format";
import { useLoad, useReloadOn, useReloadOnReturn } from "../lib/hooks";
import { placePath, siteSearch } from "../lib/places";

/** The most sites named beneath the field. */
export const SITES_NAMED = 3;

/** The sites that hold the words a location was searched for with, at most three. */
export function SitesThatMatch({ asked, again }: { asked: string; again: number }) {
  const filter = siteSearch(asked);
  const found = useLoad(`sites that match ${JSON.stringify(filter)}`, (signal) =>
    filter === null
      ? Promise.resolve(null)
      : api.request("get", "/api/v1/sites", {
          query: {
            filter: JSON.stringify(filter),
            sort: ["name"],
            limit: SITES_NAMED,
            include_drafts: true,
          },
          signal,
        }),
  );
  useReloadOn(again, found.reload);
  // A site made meanwhile in another tab is named when the person comes back (P-183).
  useReloadOnReturn(found.refresh, filter !== null);
  const sites = found.data?.items ?? [];
  if (sites.length === 0) return null;
  const more = (found.data?.total ?? 0) - sites.length;
  return (
    <ul className="sites-named" aria-label="Sites that match">
      {sites.map((site) => (
        <li key={site.hid}>
          <Link to={placePath("site", site.hid)}>{site.name}</Link> has no location that matches.
          {site.locations === 0 && " It holds no location yet; one is made on its page."}
        </li>
      ))}
      {more > 0 && (
        <li className="muted">
          {plural(more, "more site", "more sites")} {more === 1 ? "matches" : "match"}. Type more to
          narrow them down.
        </li>
      )}
    </ul>
  );
}
