// What is planned for a place that is not in use yet, and the action that puts it in
// use. An item may be given a planned location in a draft place: it stays where it is
// until that place is made active, and is moved in by that same change, by the server.
// This shows what is planned, and asks before the change that moves it.

import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { itemName, plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { type Loaded, type useAction, useLoad } from "../lib/hooks";
import {
  type Level,
  levelLabel,
  nameOf,
  type Opening,
  openingText,
  type Place,
  plannedGroupsWithin,
  plannedWithin,
} from "../lib/places";
import { nextSort, type SortState } from "../lib/sort";
import type { SortControl } from "../lib/useSorting";
import { ConfirmButton } from "./ConfirmButton";
import { Problem } from "./Problem";
import { SortTh } from "./SortTh";

// How many of the items planned for a place are listed on its page.
const LISTED = 5;

/** What is planned for a place: how many items and how many device groups. */
export interface Planned {
  /** The items planned for the place or for a place beneath it, as the tree counts them. */
  count: number;
  /** The device groups planned for it or beneath it. */
  groups: number;
}

/**
 * Read what is planned for a place: the counts from the tree of places.
 */
export function usePlanned(place: Place | undefined): Loaded<Planned | null> {
  return useLoad(`planned ${place?.hid ?? ""} ${place?.row_version ?? ""}`, async (signal) => {
    if (!place || place.record_status === "retired") return null;
    const draft = place.record_status === "draft";
    const [tree, items, groups] = await Promise.all([
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
          limit: 1,
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
    ]);
    return {
      count: tree?.roots[0]?.planned ?? items.total,
      groups: tree?.roots[0]?.planned_groups ?? groups.total,
    };
  });
}

interface PlannedHereProps {
  level: Level;
  place: Place;
  planned: Loaded<Planned | null>;
}

// The field of the item list that each column of the table below is sorted by.
const SORTED_BY: Readonly<Record<string, string>> = { name: "name", from: "location.name" };

/**
 * The first few items that are planned for a place, with where each is now. There may
 * be more of them than are shown, so the table is sorted by the server, over all of
 * them: a click on a header asks for the first few in that order.
 */
function PlannedItems({ place, count }: { place: Place; count: number }) {
  const [state, setState] = useState<SortState>({ column: "name", descending: false });
  const field = SORTED_BY[state.column] ?? "name";
  const listed = useLoad(
    `planned-items ${place.hid} ${place.row_version} ${count} ${field} ${state.descending}`,
    (signal) =>
      api.request("post", "/api/v1/items/query", {
        body: queryBody({
          filter: { field: "planned_location", op: "within", value: place.hid },
          sort: [`${state.descending ? "-" : ""}${field}`],
          limit: LISTED,
          offset: 0,
          include_archived: false,
          include_drafts: true,
        }),
        signal,
      }),
  );
  const sort: SortControl = {
    state,
    by: (column) => setState((was) => nextSort(was, column)),
    enabled: true,
  };
  const items = listed.data?.items ?? [];
  const total = listed.data?.total ?? count;
  return (
    <>
      <Problem error={listed.error} />
      <div className="scroll">
        <table className="narrow" data-testid="planned-items">
          <caption className="visually-hidden">
            The first items planned for this place, each with the location it is at now and the path
            of that. A header sorts all of them, on the server, by the name.
          </caption>
          <thead>
            <tr>
              <SortTh sort={sort} column="name">
                Item
              </SortTh>
              <SortTh sort={sort} column="from">
                Now in
              </SortTh>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.hid}>
                <th scope="row">
                  <Link to={`/items/${encodeURIComponent(item.hid)}`}>{itemName(item)}</Link>
                </th>
                <td>
                  {item.effective.location_hid.label ? (
                    <>
                      {nameOf(item.effective.location_hid.label)}
                      <span className="muted"> · {item.effective.location_hid.label}</span>
                    </>
                  ) : (
                    <span className="muted">nowhere</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > items.length && listed.data && (
        <p className="muted" data-testid="planned-more">
          and {plural(total - items.length, "more")}: all of them are in the grid, by the link
          above.
        </p>
      )}
    </>
  );
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
          <PlannedItems place={place} count={data.count} />
        </>
      )}
    </section>
  );
}

interface MakeActiveProps {
  level: Level;
  place: Place;
  /** Make the place active: the change that the answer shown was about. */
  activate: (opening: Opening) => Promise<unknown>;
  action: ReturnType<typeof useAction>;
  onReload: () => void;
}

/** The route that says what making a place of a level active would bring about. */
function readOpening(level: Level, hid: string, signal: AbortSignal): Promise<Opening> {
  const options = { path: { hid }, signal };
  if (level === "region") return api.request("get", "/api/v1/regions/{hid}/opening", options);
  if (level === "site") return api.request("get", "/api/v1/sites/{hid}/opening", options);
  return api.request("get", "/api/v1/locations/{hid}/opening", options);
}

/**
 * Make a draft place active. Making a place active is an intent: it asks first, and
 * shows what the server says it brings about, read when the question opens: how many
 * items and device groups move in and how many records are written to, or which place
 * above must be active first. Nothing is offered while that answer is not there: not
 * while it is read, and not when it could not be read.
 */
export function MakeActive({ level, place, activate, action, onReload }: MakeActiveProps) {
  const what = levelLabel(level).toLowerCase();
  // Each time the question opens the answer is read again: the inventory may have changed.
  const [asked, setAsked] = useState(0);
  const opening = useLoad(`opening ${place.hid} ${place.row_version} ${asked}`, (signal) =>
    asked === 0 ? Promise.resolve(null) : readOpening(level, place.hid, signal),
  );
  const answer = opening.loading ? null : (opening.data ?? null);
  return (
    <section aria-labelledby="make-active">
      <h3 id="make-active">Make active</h3>
      <Problem error={action.error} onReload={onReload} />
      <p>
        This {what} is a draft: it is left out of default views. Made active, it is in use once
        everything it is in is active too, and the items and the device groups that are planned for
        it are moved in by that same change. The action asks first, and shows what it brings about.
      </p>
      <p className="actions">
        <ConfirmButton
          label={`Make ${what} active`}
          title={`Make ${place.name} active?`}
          confirmLabel={`Make ${what} active`}
          onOpen={() => setAsked((count) => count + 1)}
          onConfirm={() => (answer ? activate(answer) : undefined)}
          confirmDisabled={answer === null}
          disabled={action.busy}
        >
          {opening.loading && (
            <p role="status" className="muted" data-testid="activation-loading">
              Reading what this brings about…
            </p>
          )}
          {!opening.loading && opening.error && (
            <div data-testid="activation-failed">
              <Problem error={opening.error} />
              <p>
                What making {place.name} active brings about could not be read, so it is not made
                active from here. Close this, and try again.
              </p>
            </div>
          )}
          {answer && (
            <>
              <p
                data-testid="activation-text"
                data-items={answer.items}
                data-groups={answer.device_groups}
                data-changed={answer.records_changed}
                data-moves={answer.moves_now ? "true" : "false"}
              >
                {openingText(place.name, answer)}
              </p>
              <p className="hint">
                What is planned for a place within it that is itself still a draft moves when that
                place is made active. Nobody moves anything one by one.
              </p>
            </>
          )}
        </ConfirmButton>
      </p>
    </section>
  );
}
