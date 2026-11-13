// The small lists that forms and filters offer, read from the server.

import { api } from "../api";
import { type Loaded, useLoad } from "./hooks";
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

/** The vendors a form may choose from, by name. */
export function useVendorOptions(): Loaded<Option[]> {
  return useLoad("vendor-options", async (signal) => {
    const page = await api.request("get", "/api/v1/vendors", { query: { limit: EVERY }, signal });
    return page.items.map((vendor) => ({ value: vendor.hid, label: vendor.name }));
  });
}

/** The owners a form may choose from, by label. */
export function useOwnerOptions(): Loaded<Option[]> {
  return useLoad("owner-options", async (signal) => {
    const page = await api.request("get", "/api/v1/owners", { query: { limit: EVERY }, signal });
    return page.items.map((owner) => ({ value: owner.hid, label: owner.label }));
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
