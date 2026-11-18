// 0.9.6: a catalog entry is chosen by searching for it (P-200), in New item, in an item's
// details, as the successor of an entry and in a bulk edit. An inventory may hold hundreds
// of models: what is typed is sent to the server as a filter of the catalog, each word
// looked for in the PID, the model name and the vendor's name, and the first few that
// match are offered, those with the most items first, each with its vendor beside its PID.

import { useContext } from "react";
import { api } from "../api";
import { offeredEntries } from "../lib/entries";
import { queryParams } from "../lib/gridQuery";
import { useLoad } from "../lib/hooks";
import type { Option } from "../lib/patch";
import { entryLabel, entrySearch, entrySeen, PICK_LIMIT, sawEntries } from "../lib/pick";
import { AddModel, addedOption, nextField, OffersNewModel } from "./AddModel";
import { type Found, PickField, type PickFieldProps } from "./PickField";

/** The first few catalog entries that match what was typed, the most used first. */
async function findEntries(
  typed: string,
  signal: AbortSignal,
  exclude: readonly string[] = [],
): Promise<Found | null> {
  const filter = entrySearch(typed);
  if (filter === null) return null;
  const page = await api.request("get", "/api/v1/catalog-entries", {
    query: queryParams({
      filter,
      sort: ["-items", "vendor", "pid"],
      limit: PICK_LIMIT,
      offset: 0,
      // The models the list of every entry offered: none retired, none a draft.
      include_archived: false,
      include_drafts: false,
    }),
    signal,
  });
  sawEntries(page.items);
  return offeredEntries(page, exclude);
}

/**
 * The entry a form holds, by its name: as the form knows it, as a search offered it, or
 * else read from the server, as the successor of an entry, which the entry names by HID.
 */
function useNamed(value: string, known: readonly Option[]): Option[] {
  const seen = value === "" ? undefined : entrySeen(value);
  const unnamed = value !== "" && !seen && !known.some((option) => option.value === value);
  const read = useLoad(`catalog entry named ${unnamed ? value : ""}`, async (signal) => {
    if (!unnamed) return null;
    const entry = await api.request("get", "/api/v1/catalog-entries/{hid}", {
      path: { hid: value },
      signal,
    });
    sawEntries([entry]);
    return entry;
  });
  const named = seen ?? (read.data?.hid === value ? read.data : undefined);
  return named ? [...known, { value: named.hid, label: entryLabel(named) }] : [...known];
}

/**
 * A field of a form that holds a catalog entry, chosen by searching for it (P-200). In New
 * item it offers to add a model the catalog does not have (P-201).
 */
export function EntryField(props: PickFieldProps & { exclude?: readonly string[] }) {
  const { exclude = [], ...field } = props;
  const known = useNamed(props.value, props.known ?? []);
  const offers = useContext(OffersNewModel);
  return (
    <PickField
      {...field}
      known={known}
      noun={["catalog entry", "catalog entries"]}
      how="To choose one, type words of its PID, of its model name or of its vendor's name. Those with the most items come first."
      find={(typed, signal) => findEntries(typed, signal, exclude)}
      {...(offers && !props.disabled
        ? {
            after: ({ typed, nothing, choose }) => (
              <AddModel
                // Closed again once an entry is chosen, by the search or here (P-201).
                key={props.value}
                typed={typed}
                nothing={nothing}
                onAdded={(entry, from) => {
                  // The item's next field, found while this part of the form is still there.
                  const next = nextField(from);
                  choose(addedOption(entry));
                  requestAnimationFrame(() => next?.focus());
                }}
              />
            ),
          }
        : {})}
    />
  );
}
