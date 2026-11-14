import { api } from "../api";
import { queryBody } from "../lib/gridQuery";
import { PICK_LIMIT } from "../lib/pick";
import { locationSearch } from "../lib/places";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few locations that match what was typed, each by its path. */
async function findLocations(typed: string, signal: AbortSignal): Promise<Found | null> {
  const filter = locationSearch(typed);
  if (filter === null) return null;
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

/**
 * A field of a form that holds a location, chosen by searching for it. A site may have
 * thousands of locations, so they are never listed whole: what is typed is sent to the
 * server as a filter of the list of locations, and the first few that match are offered,
 * each by its path. Drafts are offered too; retired locations are not.
 */
export function LocationField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["location", "locations"]}
      how="To choose one, type a part of its name or code, or of the name of its site, of the region of that site or of the location it is in."
      find={findLocations}
    />
  );
}
