// What is planned for a place that is not in use yet, and the action that puts it in
// use. An item may be given a planned location in a draft place: it stays where it is
// until that place is made active, and is moved in by that same change, by the server.
// This shows what is planned, and asks before the change that moves it.

import { Link } from "react-router";
import { api } from "../api";
import { itemName, plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { type Loaded, type useAction, useLoad } from "../lib/hooks";
import {
  activationText,
  type Level,
  levelLabel,
  type Place,
  plannedGroupsWithin,
  plannedWithin,
} from "../lib/places";
import { ConfirmButton } from "./ConfirmButton";
import { Problem } from "./Problem";

// How many of the items planned for a place are listed on its page.
const LISTED = 5;

/** What is planned for a place: how many items, and the first few of them. */
export interface Planned {
  /** The items planned for the place or for a place beneath it, as the tree counts them. */
  count: number;
  /** The device groups planned for it or beneath it. */
  groups: number;
  first: Array<{ hid: string; name: string; from: string }>;
  /** The nearest level above the place that is still a draft, if there is one. */
  draftAbove: { level: Level; name: string } | null;
}

/** The nearest place above a place that is a draft: while there is one, the place is not in use. */
async function readDraftAbove(
  place: Place,
  signal: AbortSignal,
): Promise<{ level: Level; name: string } | null> {
  let regionHid: string | null = null;
  if ("site_hid" in place) {
    let above = place.parent_location_hid;
    while (above) {
      const location = await api.request("get", "/api/v1/locations/{hid}", {
        path: { hid: above },
        signal,
      });
      if (location.record_status === "draft") return { level: "location", name: location.name };
      above = location.parent_location_hid;
    }
    const site = await api.request("get", "/api/v1/sites/{hid}", {
      path: { hid: place.site_hid },
      signal,
    });
    if (site.record_status === "draft") return { level: "site", name: site.name };
    regionHid = site.region_hid;
  } else if ("region_hid" in place) {
    regionHid = place.region_hid;
  } else {
    regionHid = place.parent_region_hid;
  }
  while (regionHid) {
    const region = await api.request("get", "/api/v1/regions/{hid}", {
      path: { hid: regionHid },
      signal,
    });
    if (region.record_status === "draft") return { level: "region", name: region.name };
    regionHid = region.parent_region_hid;
  }
  return null;
}

/**
 * Read what is planned for a place: the count from the tree of places, the first few
 * items from the item list, and for a draft place whether a level above it is a draft
 * too.
 */
export function usePlanned(place: Place | undefined): Loaded<Planned | null> {
  return useLoad(`planned ${place?.hid ?? ""} ${place?.row_version ?? ""}`, async (signal) => {
    if (!place || place.record_status === "retired") return null;
    const draft = place.record_status === "draft";
    const [tree, items, groups, draftAbove] = await Promise.all([
      // The count that the question of a draft place gives is the tree's. For a place in
      // use, the number of the list below says the same, and the tree is not asked.
      draft
        ? api.request("get", "/api/v1/geography/tree", {
            query: { root: place.hid, locations: false, include_drafts: true },
            signal,
          })
        : Promise.resolve(null),
      api.request("post", "/api/v1/items/query", {
        body: queryBody({
          filter: { field: "planned_location", op: "within", value: place.hid },
          sort: ["name"],
          limit: LISTED,
          offset: 0,
          include_archived: false,
          include_drafts: true,
        }),
        signal,
      }),
      api.request("get", "/api/v1/device-groups", {
        query: { filter: `planned_location:within:${place.hid}`, limit: 1, include_drafts: true },
        signal,
      }),
      draft ? readDraftAbove(place, signal) : Promise.resolve(null),
    ]);
    return {
      count: tree?.roots[0]?.planned ?? items.total,
      groups: tree?.roots[0]?.planned_groups ?? groups.total,
      first: items.items.map((item) => ({
        hid: item.hid,
        name: itemName(item),
        from: item.effective.location_hid.label ?? "",
      })),
      draftAbove,
    };
  });
}

interface PlannedHereProps {
  level: Level;
  place: Place;
  planned: Loaded<Planned | null>;
}

/**
 * The items that are planned for the place or for a place beneath it: how many, the
 * first few by name with where each is now, and the way to all of them in the grid.
 * Shown for a draft place, and for any place that something is planned for.
 */
export function PlannedHere({ level, place, planned }: PlannedHereProps) {
  const data = planned.data;
  if (place.record_status !== "draft" && (!data || data.count + data.groups === 0)) return null;
  return (
    <section aria-labelledby="planned-here" data-testid="planned-here">
      <h3 id="planned-here">Planned for this place</h3>
      <Problem error={planned.error} />
      {planned.loading && !data && (
        <p role="status" className="muted loading-late">
          Loading…
        </p>
      )}
      {data && data.count + data.groups === 0 && (
        <p className="muted">
          Nothing is planned for this {level}. An item or a device group is given a planned location
          on its own page, and items by a bulk edit too.
        </p>
      )}
      {data && data.groups > 0 && (
        <p>
          <Link to={plannedGroupsWithin(place.hid)} data-testid="planned-groups">
            {plural(data.groups, "device group")}
          </Link>{" "}
          planned for this {level} or for a place within it. The members of a group that have no
          plan of their own go with it, and are among the items below.
        </p>
      )}
      {data && data.count > 0 && (
        <>
          <p>
            <Link to={plannedWithin(place.hid)} data-testid="planned-count">
              {plural(data.count, "item")}
            </Link>{" "}
            planned for this {level} or for a place within it, by their own plan or by that of the
            item or the group they are in. Each stays where it is, and is counted there, until the
            place it is planned for is in use.
          </p>
          <ul data-testid="planned-items">
            {data.first.map((item) => (
              <li key={item.hid}>
                <Link to={`/items/${encodeURIComponent(item.hid)}`}>{item.name}</Link>
                <span className="muted"> · now {item.from ? `in ${item.from}` : "nowhere"}</span>
              </li>
            ))}
            {data.count > data.first.length && (
              <li className="muted">and {plural(data.count - data.first.length, "more")}</li>
            )}
          </ul>
        </>
      )}
    </section>
  );
}

interface MakeActiveProps {
  level: Level;
  place: Place;
  planned: Loaded<Planned | null>;
  /** Make the place active: the change that moves what is planned for it. */
  activate: () => Promise<unknown>;
  action: ReturnType<typeof useAction>;
  onReload: () => void;
}

/**
 * Make a draft place active. It asks first, saying what the change does to the items
 * and the device groups that are planned for the place: they are moved in, each with an
 * entry in its history, or they wait while a level above is still a draft.
 */
export function MakeActive({ level, place, planned, activate, action, onReload }: MakeActiveProps) {
  const what = levelLabel(level).toLowerCase();
  const data = planned.data;
  return (
    <section aria-labelledby="make-active">
      <h3 id="make-active">Make active</h3>
      <Problem error={action.error} onReload={onReload} />
      <p>
        This {what} is a draft: it is left out of default views. Made active, it is in use once
        everything it is in is active too, and the items and the device groups that are planned for
        it are moved in by that same change.
      </p>
      <p className="actions">
        <ConfirmButton
          label={`Make ${what} active`}
          title={`Make ${place.name} active?`}
          confirmLabel={`Make ${what} active`}
          onConfirm={activate}
          disabled={action.busy || !data}
        >
          <p data-testid="activation-text">
            {data
              ? activationText(
                  place.name,
                  { items: data.count, groups: data.groups },
                  data.draftAbove,
                )
              : ""}
          </p>
          <p className="hint">
            What is planned for a place within it that is itself still a draft moves when that place
            is made active. Nobody moves anything one by one.
          </p>
        </ConfirmButton>
      </p>
    </section>
  );
}
