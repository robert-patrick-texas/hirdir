import { api } from "../api";
import { queryBody } from "../lib/gridQuery";
import { PICK_LIMIT } from "../lib/pick";
import { locationsWithin } from "../lib/within";
import { type Found, PickField, type PickFieldProps } from "./PickField";
import { SitesThatMatch } from "./SitesThatMatch";

/**
 * The first few locations that match what was typed, each by its path. Within a site,
 * blank text is the site's first locations; elsewhere it is no search.
 */
async function findLocations(
  typed: string,
  site: string | undefined,
  signal: AbortSignal,
): Promise<Found | null> {
  const filter = locationsWithin(typed, site);
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

interface LocationFieldProps extends PickFieldProps {
  /**
   * 0.9.6: the HID of a site to search within (P-209): what is typed is looked for among
   * its locations alone, and its first locations are offered before anything is typed.
   */
  site?: string | undefined;
}

/**
 * A field of a form that holds a location, chosen by searching for it. A site may have
 * thousands of locations, so they are never listed whole: what is typed is sent to the
 * server as a filter of the list of locations, and the first few that match are offered,
 * each by its path. Drafts are offered too; retired locations are not.
 */
export function LocationField({ site, ...props }: LocationFieldProps) {
  return (
    <PickField
      {...props}
      noun={["location", "locations"]}
      how={
        site
          ? "To choose one, type a part of its name or code, or of the location it is in."
          : "To choose one, type a part of its name or code, or of the name of its site, of the region of that site or of the location it is in."
      }
      find={(typed, signal) => findLocations(typed, site, signal)}
      none={site ? undefined : (asked, again) => <SitesThatMatch asked={asked} again={again} />}
    />
  );
}
