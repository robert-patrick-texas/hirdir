import { api } from "../api";
import { queryBody } from "../lib/gridQuery";
import { PICK_LIMIT } from "../lib/pick";
import { planSearch } from "../lib/places";
import { type Found, PickField, type PickFieldProps } from "./PickField";

async function find(typed: string, signal: AbortSignal): Promise<Found | null> {
  const filter = planSearch(typed);
  if (filter === null) return null;
  const page = await api.request("post", "/api/v1/locations/query", {
    body: queryBody({
      filter,
      sort: ["site.name", "name"],
      limit: PICK_LIMIT,
      offset: 0,
      include_archived: false,
      // A place that is not in use is a draft, or within one: the drafts are asked for.
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
 * A field of a form that holds a planned location: where an item or a device group is
 * going, in a place that is not in use yet. Only such places are offered: a draft
 * location, or a location within a draft site or region, which the list of locations
 * finds with `in_use`. The server judges all the same, and refuses a place in use.
 */
export function PlannedLocationField(props: PickFieldProps) {
  return (
    <PickField
      {...props}
      noun={["location", "locations"]}
      how="Only a place that is not in use yet is offered: a draft, or one within a draft site or region. To choose one, type a part of its name or code, or of the name of its site."
      find={find}
    />
  );
}
