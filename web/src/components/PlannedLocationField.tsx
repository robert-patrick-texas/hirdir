import { useMemo } from "react";
import { api } from "../api";
import { queryBody } from "../lib/gridQuery";
import { useLoad } from "../lib/hooks";
import { EVERY } from "../lib/lists";
import { PICK_LIMIT } from "../lib/pick";
import { type DraftPlace, planScope, planSearch } from "../lib/places";
import { type Found, PickField, type PickFieldProps } from "./PickField";
import { Problem } from "./Problem";

/** Every place that is a draft: what is at or beneath one of them is not in use. */
async function readDrafts(signal: AbortSignal): Promise<DraftPlace[]> {
  const query = { filter: "record_status:eq:draft", limit: EVERY, include_drafts: true };
  const [regions, sites, locations] = await Promise.all([
    api.request("get", "/api/v1/regions", { query, signal }),
    api.request("get", "/api/v1/sites", { query, signal }),
    api.request("get", "/api/v1/locations", { query, signal }),
  ]);
  return [
    ...regions.items.map((place) => ({
      level: "region" as const,
      hid: place.hid,
      path: place.path,
    })),
    ...sites.items.map((place) => ({ level: "site" as const, hid: place.hid, path: place.path })),
    ...locations.items.map((place) => ({
      level: "location" as const,
      hid: place.hid,
      path: place.path,
    })),
  ];
}

/**
 * A field of a form that holds the planned location of an item: where it is going, in a
 * place that is not in use yet. Only such places are offered: a draft location, or a
 * location within a draft site or region. The list of locations has no word for "in
 * use", so the draft places are read first and the search is kept to what is at or
 * beneath one of them. The server judges all the same, and refuses a place in use.
 */
export function PlannedLocationField(props: PickFieldProps) {
  const drafts = useLoad("draft-places", readDrafts);
  const scope = useMemo(() => planScope(drafts.data ?? []), [drafts.data]);

  async function find(typed: string, signal: AbortSignal): Promise<Found | null> {
    if (typed.trim() === "") return null;
    const filter = planSearch(typed, scope);
    // No place is a draft: there is nothing to plan for, and nothing is asked.
    if (filter === null) return { options: [], total: 0 };
    const page = await api.request("post", "/api/v1/locations/query", {
      body: queryBody({
        filter,
        sort: ["site.name", "name"],
        limit: PICK_LIMIT,
        offset: 0,
        include_archived: false,
        include_drafts: true,
      }),
      signal,
    });
    return {
      options: page.items.map((location) => ({
        value: location.hid,
        label: location.path,
        draft: location.record_status === "draft",
      })),
      total: page.total,
    };
  }

  return (
    <>
      <PickField
        {...props}
        noun={["location", "locations"]}
        scope={drafts.data ? `drafts ${drafts.data.length}` : "drafts not read"}
        how="Only a place that is not in use yet is offered: a draft, or one within a draft site or region. To choose one, type a part of its name or code, or of the name of its site."
        find={find}
      />
      <Problem error={drafts.error} />
    </>
  );
}
