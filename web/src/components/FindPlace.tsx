// 0.9.5: Find a place, above the tree of Geography (P-188). What is typed is searched for,
// once the typing pauses and when Enter is pressed, among the sites as a site is searched
// for elsewhere, and among the locations as the Location field of an item searches them,
// so that the site named with a room narrows it; up to ten of each that match are listed
// by their path, each a link to its page, with how many more match. A draft is found,
// and a retired place while the view of the tree has Retired places on; each is marked.
// The tree beneath is as it was.

import { type FormEvent, useId, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { plural } from "../lib/format";
import { useAsked, useLoad, useReloadOn, useReloadOnReturn } from "../lib/hooks";
import { optionLabel, RECORD_STATUSES } from "../lib/options";
import { locationSearch, placePath, siteSearch } from "../lib/places";
import { TextField } from "./Field";
import { Problem } from "./Problem";

/** The most places of each level listed beneath the box. */
export const PLACES_LISTED = 10;

type Level = "site" | "location";

interface Found {
  hid: string;
  path: string;
  record_status: string;
}

async function readPlaces(
  level: Level,
  filter: string,
  retired: boolean,
  signal: AbortSignal,
): Promise<{ items: Found[]; total: number }> {
  const query = {
    filter,
    sort: ["name"],
    limit: PLACES_LISTED,
    include_drafts: true,
    ...(retired ? { include_archived: true } : {}),
  };
  return level === "site"
    ? await api.request("get", "/api/v1/sites", { query, signal })
    : await api.request("get", "/api/v1/locations", { query, signal });
}

/** The places of one level that match, as links, and how many more do. */
function Matches({
  level,
  asked,
  again,
  search,
  retired,
}: {
  level: Level;
  asked: string;
  again: number;
  search: string;
  retired: boolean;
}) {
  const filter = level === "site" ? siteSearch(asked) : locationSearch(asked);
  const text = filter === null ? "" : JSON.stringify(filter);
  const id = useId();
  const found = useLoad(`find a place ${level} ${text} ${retired}`, (signal) =>
    text === "" ? Promise.resolve(null) : readPlaces(level, text, retired, signal),
  );
  useReloadOn(again, found.reload);
  // A place made meanwhile in another tab is found when the person comes back (P-183).
  useReloadOnReturn(found.refresh, text !== "");
  if (text === "") return null;
  const name = level === "site" ? "Sites that match" : "Locations that match";
  const heading = `${id}-heading`;
  const places: Found[] = found.data?.items ?? [];
  const more = (found.data?.total ?? 0) - places.length;
  return (
    <div className="find-place-level">
      <Problem error={found.error} />
      {found.loading && !found.data && (
        <p role="status" className="muted loading-late">
          Looking…
        </p>
      )}
      <h3 id={heading} className="find-place-heading">
        {name}
      </h3>
      {found.data && (
        <ul className="plain-list" aria-labelledby={heading} data-testid={`found-${level}s`}>
          {places.map((place) => (
            <li key={place.hid}>
              <Link to={{ pathname: placePath(level, place.hid), search }}>{place.path}</Link>
              {place.record_status !== "active" && (
                <>
                  {" "}
                  <span className="badge">{optionLabel(RECORD_STATUSES, place.record_status)}</span>
                </>
              )}
            </li>
          ))}
          {places.length === 0 && (
            <li className="muted">
              {level === "site" ? "No site matches." : "No location matches."}
            </li>
          )}
          {more > 0 && (
            <li className="muted">
              {plural(more, `more ${level}`, `more ${level}s`)} {more === 1 ? "matches" : "match"}.
              Type more to narrow them down.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

/**
 * The box, Find a place, and what it finds. `search` is the view of the tree, kept, and
 * `retired` its switch for retired places, which the box follows.
 */
export function FindPlace({ search, retired }: { search: string; retired: boolean }) {
  const [typed, setTyped] = useState("");
  const asked = useAsked(typed);

  function submit(event: FormEvent) {
    event.preventDefault();
    asked.askNow();
  }

  return (
    <search className="find-place" aria-label="Find a place">
      <form onSubmit={submit} noValidate>
        <TextField
          label="Find a place"
          name="find_place"
          type="search"
          value={typed}
          onChange={setTyped}
          autoComplete="off"
          hint="A site or a location, by its name or its code; a location with its site's, as in a path."
        />
      </form>
      {(["site", "location"] as const).map((level) => (
        <Matches
          key={level}
          level={level}
          asked={asked.asked}
          again={asked.again}
          search={search}
          retired={retired}
        />
      ))}
    </search>
  );
}
