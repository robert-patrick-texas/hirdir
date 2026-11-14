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

/**
 * The installation's currency as a heading names it after an amount: " (USD)", or
 * nothing until the setting is read. It is a label only: no amount is converted.
 */
export function useMoney(): string {
  const settings = useSettings();
  const currency = settings.data?.find((setting) => setting.key === "currency")?.value;
  return typeof currency === "string" && currency !== "" ? ` (${currency})` : "";
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

/** The regions a form may choose from, by path. */
export function useRegionOptions(): Loaded<Option[]> {
  return useLoad("region-options", async (signal) => {
    const page = await api.request("get", "/api/v1/regions", {
      query: { limit: EVERY, sort: ["name"] },
      signal,
    });
    return page.items
      .map((region) => ({ value: region.hid, label: region.path }))
      .sort((one, other) => one.label.localeCompare(other.label));
  });
}

/** The sites a form may choose from, by path. */
export function useSiteOptions(): Loaded<Option[]> {
  return useLoad("site-options", async (signal) => {
    const page = await api.request("get", "/api/v1/sites", {
      query: { limit: EVERY, sort: ["name"] },
      signal,
    });
    return page.items
      .map((site) => ({ value: site.hid, label: site.path }))
      .sort((one, other) => one.label.localeCompare(other.label));
  });
}

/**
 * The support agreements a contract may be grouped into, by name, each with its vendor:
 * a contract is grouped into an agreement with its own vendor.
 */
export function useAgreementOptions(turn = 0): Loaded<Array<Option & { vendorHid: string }>> {
  return useLoad(`agreement-options ${turn}`, async (signal) => {
    const page = await api.request("get", "/api/v1/agreements", {
      query: { limit: EVERY, include_drafts: true },
      signal,
    });
    return page.items.map((agreement) => ({
      value: agreement.hid,
      label: `${agreement.name} (${agreement.vendor.name})`,
      vendorHid: agreement.vendor_hid,
    }));
  });
}

/** The external systems, by name, retired ones among them: a registration may name one. */
export function useSystems(turn = 0) {
  return useLoad(`systems ${turn}`, async (signal) => {
    const page = await api.request("get", "/api/v1/external-systems", {
      query: { limit: EVERY, include_drafts: true, include_archived: true },
      signal,
    });
    return page.items;
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
