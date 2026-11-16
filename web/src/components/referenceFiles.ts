// What the pages of references ask the server: what a record lists, the content of a
// file, and the records a reference may be put on.

import { api } from "../api";
import { circuitLabel, circuitSearch } from "../lib/circuits";
import type { FilterNode } from "../lib/filter";
import { queryBody } from "../lib/gridQuery";
import { itemSearch, pickLabel } from "../lib/pick";
import { locationSearch } from "../lib/places";
import {
  entrySearch,
  type Found,
  interleaved,
  offerNote,
  regionSearch,
  siteSearch,
} from "../lib/recordSearch";
import {
  type Holder,
  type Listed,
  PAGE,
  pictureBlob,
  type Reference,
  saveReference,
} from "../lib/references";
import type { Offer } from "./SearchPicker";

/** One page of what a record lists, from the route of its kind. */
function pageOf(holder: Holder, offset: number, signal: AbortSignal) {
  const options = { path: { hid: holder.hid }, query: { limit: PAGE, offset }, signal };
  switch (holder.kind) {
    case "catalog_entry":
      return api.request("get", "/api/v1/catalog-entries/{hid}/references", options);
    case "region":
      return api.request("get", "/api/v1/regions/{hid}/references", options);
    case "site":
      return api.request("get", "/api/v1/sites/{hid}/references", options);
    case "location":
      return api.request("get", "/api/v1/locations/{hid}/references", options);
    case "circuit":
      return api.request("get", "/api/v1/circuits/{hid}/references", options);
    case "item":
      return api.request("get", "/api/v1/items/{hid}/references", options);
  }
}

/**
 * Everything a record lists: its own, then what it has from the records it stands
 * under, in the server's order. A page holds a thousand: the next is asked for only
 * where the first says there are more.
 */
export async function listReferences(holder: Holder, signal: AbortSignal): Promise<Listed[]> {
  const listed: Listed[] = [];
  for (;;) {
    const page = await pageOf(holder, listed.length, signal);
    listed.push(...page.items);
    if (page.items.length === 0 || listed.length >= page.total) return listed;
  }
}

type FileOf = Pick<Reference, "hid" | "file_name" | "media_type">;

/** Fetch a file's content and hand it to the browser to save, under its own name. */
export async function downloadReference(reference: FileOf): Promise<void> {
  const got = await api.content("/api/v1/reference-files/{hid}/content", {
    path: { hid: reference.hid },
  });
  saveReference(got.blob, reference.file_name ?? got.fileName ?? "file");
}

/** Fetch a picture's content, typed as the picture it is, to show from a `blob:` address. */
export async function pictureOf(reference: FileOf, signal: AbortSignal): Promise<Blob> {
  const got = await api.content("/api/v1/reference-files/{hid}/content", {
    path: { hid: reference.hid },
    signal,
  });
  return pictureBlob(got.blob, reference.media_type);
}

/** What a search of one kind asks for: the first that match, drafts among them. */
function listQuery(filter: FilterNode, limit: number) {
  return { filter: JSON.stringify(filter), limit, include_drafts: true };
}

function queried(filter: FilterNode, sort: string[], limit: number) {
  return queryBody({
    filter,
    sort,
    limit,
    offset: 0,
    include_archived: false,
    include_drafts: true,
  });
}

/**
 * The records of the six kinds that match what was typed, a few of each kind in turn:
 * the places by their paths, the catalog entries by vendor and PID, the circuits and the
 * items by their names. Blank text is no search.
 */
export async function findRecords(
  typed: string,
  limit: number,
  signal: AbortSignal,
): Promise<{ offers: Offer[]; total: number } | null> {
  const searches: Array<Promise<Found<Offer>>> = [];
  const regionFilter = regionSearch(typed);
  const siteFilter = siteSearch(typed);
  const locationFilter = locationSearch(typed);
  const entryFilter = entrySearch(typed);
  const circuitFilter = circuitSearch(typed);
  const itemFilter = itemSearch(typed);
  if (regionFilter) {
    searches.push(
      api
        .request("get", "/api/v1/regions", { query: listQuery(regionFilter, limit), signal })
        .then((page) => ({
          kind: "region",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: one.path,
            note: offerNote("region", one.record_status),
          })),
        })),
    );
  }
  if (siteFilter) {
    searches.push(
      api
        .request("get", "/api/v1/sites", { query: listQuery(siteFilter, limit), signal })
        .then((page) => ({
          kind: "site",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: one.path,
            note: offerNote("site", one.record_status),
          })),
        })),
    );
  }
  if (locationFilter) {
    searches.push(
      api
        .request("post", "/api/v1/locations/query", {
          body: queried(locationFilter, ["site.name", "name"], limit),
          signal,
        })
        .then((page) => ({
          kind: "location",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: one.path,
            note: offerNote("location", one.record_status),
          })),
        })),
    );
  }
  if (entryFilter) {
    searches.push(
      api
        .request("get", "/api/v1/catalog-entries", {
          query: listQuery(entryFilter, limit),
          signal,
        })
        .then((page) => ({
          kind: "catalog_entry",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: `${one.vendor.name} ${one.pid}`,
            note: offerNote("catalog_entry", one.record_status),
          })),
        })),
    );
  }
  if (circuitFilter) {
    searches.push(
      api
        .request("post", "/api/v1/circuits/query", {
          body: {
            ...queried(circuitFilter, ["name"], limit),
            fields: ["name", "enterprise_circuit_id", "record_status"],
          },
          signal,
        })
        .then((page) => ({
          kind: "circuit",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: circuitLabel(one),
            note: offerNote("circuit", one.record_status),
          })),
        })),
    );
  }
  if (itemFilter) {
    searches.push(
      api
        .request("post", "/api/v1/items/query", {
          body: queried(itemFilter, ["name"], limit),
          signal,
        })
        .then((page) => ({
          kind: "item",
          total: page.total,
          offers: page.items.map((one) => ({
            hid: one.hid,
            label: pickLabel(one),
            note: offerNote("item", one.record_status),
          })),
        })),
    );
  }
  if (searches.length === 0) return null;
  return interleaved(await Promise.all(searches), limit);
}
