// The small lists that forms and filters offer, read from the server.

import { api } from "../api";
import { groupTypeLabel } from "./groups";
import { type Loaded, useLoad } from "./hooks";
import { type Mark, markOf } from "./operators";
import { ownerOptions } from "./owners";
import type { Option } from "./patch";

// The most rows the server lists at once.
export const EVERY = 1000;

/** Every value of every editable list. */
export function useChoices() {
  return useLoad("choices", (signal) => api.request("get", "/api/v1/choices", { signal }));
}

/** What each lifecycle state allows, in the order of the lifecycle. */
export function useRules() {
  return useLoad("lifecycle-rules", (signal) =>
    api.request("get", "/api/v1/lifecycle-rules", { signal }),
  );
}

export function useTags() {
  return useLoad("tags", (signal) => api.request("get", "/api/v1/tags", { signal }));
}

/** Every setting with the value in force. Any role that reads the inventory may read them. */
export function useSettings() {
  return useLoad("settings", (signal) => api.request("get", "/api/v1/settings", { signal }));
}

/** The vendors a form may choose from, by name. */
export function useVendorOptions(): Loaded<Option[]> {
  return useLoad("vendor-options", async (signal) => {
    const page = await api.request("get", "/api/v1/vendors", { query: { limit: EVERY }, signal });
    return page.items.map((vendor) => ({ value: vendor.hid, label: vendor.name }));
  });
}

/**
 * The owners a form may choose from, by label. Those outside the operations team stand
 * under a heading of their own, so that it shows which choice is an exception.
 */
export function useOwnerOptions(): Loaded<Option[]> {
  return useLoad("owner-options", async (signal) => {
    const page = await api.request("get", "/api/v1/owners", { query: { limit: EVERY }, signal });
    return ownerOptions(page.items);
  });
}

/** The contacts a place or an owner may be given, by name, with the address of each. */
export function useContactOptions(turn = 0): Loaded<Option[]> {
  return useLoad(`contact-options ${turn}`, async (signal) => {
    const page = await api.request("get", "/api/v1/contacts", {
      query: { limit: EVERY, include_drafts: true },
      signal,
    });
    return page.items.map((contact) => ({
      value: contact.hid,
      label: contact.email ? `${contact.name} (${contact.email})` : contact.name,
    }));
  });
}

/** The regions a site or a region may be in, by path, drafts among them. */
export function useRegions(turn = 0) {
  return useLoad(`regions ${turn}`, async (signal) => {
    const page = await api.request("get", "/api/v1/regions", {
      query: { limit: EVERY, include_drafts: true },
      signal,
    });
    return [...page.items].sort((one, other) => one.path.localeCompare(other.path));
  });
}

/** The catalog entries a form may choose from, by vendor and PID. */
export function useEntryOptions(): Loaded<Option[]> {
  return useLoad("entry-options", async (signal) => {
    const page = await api.request("get", "/api/v1/catalog-entries", {
      query: { limit: EVERY },
      signal,
    });
    return page.items.map((entry) => ({
      value: entry.hid,
      label: entry.model_name ? `${entry.pid} (${entry.model_name})` : entry.pid,
      group: entry.vendor.name,
    }));
  });
}

/** The networks an address may be under, by label. */
export function useNetworkOptions(turn = 0): Loaded<Option[]> {
  return useLoad(`network-options ${turn}`, async (signal) => {
    const page = await api.request("get", "/api/v1/networks", { query: { limit: EVERY }, signal });
    return page.items.map((network) => ({ value: network.hid, label: network.label }));
  });
}

/** The device groups another group may be nested in, by name, with the type of each. */
export function useGroupOptions(): Loaded<Option[]> {
  return useLoad("group-options", async (signal) => {
    const page = await api.request("get", "/api/v1/device-groups", {
      query: { limit: EVERY, include_drafts: true },
      signal,
    });
    return page.items.map((group) => ({
      value: group.hid,
      label: group.name,
      group: groupTypeLabel(group.type),
    }));
  });
}

/**
 * The marks of the operators, by HID, released ones among them: for a report whose rows
 * are operators, which names each by its HID and its label and not by its colour. Asked
 * for only when wanted.
 */
export function useOperatorMarks(wanted: boolean): Loaded<Map<string, Mark>> {
  return useLoad(`operator-marks ${wanted}`, async (signal) => {
    const marks = new Map<string, Mark>();
    if (!wanted) return marks;
    const page = await api.request("get", "/api/v1/operators", {
      query: { limit: EVERY, include_drafts: true, include_archived: true },
      signal,
    });
    for (const operator of page.items) {
      const mark = markOf(operator);
      if (mark) marks.set(operator.hid, mark);
    }
    return marks;
  });
}

/** An option for the record a form already points at, when the list does not offer it. */
export function withCurrent(
  options: readonly Option[] | undefined,
  current: Option | null,
): Option[] {
  const offered = [...(options ?? [])];
  if (current && current.value !== "" && !offered.some((o) => o.value === current.value)) {
    offered.push(current);
  }
  return offered;
}
