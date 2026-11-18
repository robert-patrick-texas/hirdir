// The small lists that forms and filters offer, read from the server. A list a page
// reads whole when it opens is read again, in the background, when the person comes
// back to the tab (P-183), so that what was made meanwhile in another tab is offered.
// 0.9.6: a list of a kind that can be long is chosen from by searching instead (P-200);
// a list read whole is read to its end, past the first 1,000 (`whole`).

import { useCallback, useRef } from "react";
import { api } from "../api";
import { groupTypeLabel } from "./groups";
import { type Loaded, useLoad, useReloadOnReturn } from "./hooks";
import { type Mark, markOf } from "./operators";
import { ownerOptions } from "./owners";
import type { Option } from "./patch";
import { EVERY, whole } from "./whole";

export { EVERY, whole };

// The least time between two reads of a list on coming back to the tab, in milliseconds.
const RETURN_PAUSE = 5000;

/** A list read whole, and again in the background when the person comes back to the tab. */
function useList<T>(key: string, load: (signal: AbortSignal) => Promise<T>, active = true) {
  const list = useLoad(key, load);
  // Going from tab to tab quickly does not read every list each time.
  const last = useRef(0);
  const { refresh } = list;
  const back = useCallback(() => {
    const now = Date.now();
    if (now - last.current < RETURN_PAUSE) return;
    last.current = now;
    refresh();
  }, [refresh]);
  useReloadOnReturn(back, active);
  return list;
}

/** Every value of every editable list. */
export function useChoices() {
  return useList("choices", (signal) => api.request("get", "/api/v1/choices", { signal }));
}

/** What each lifecycle state allows, in the order of the lifecycle. */
export function useRules() {
  return useLoad("lifecycle-rules", (signal) =>
    api.request("get", "/api/v1/lifecycle-rules", { signal }),
  );
}

export function useTags() {
  return useList("tags", (signal) => api.request("get", "/api/v1/tags", { signal }));
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
  return useList("vendor-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/vendors", { query: { limit: EVERY, offset }, signal }),
    );
    return items.map((vendor) => ({ value: vendor.hid, label: vendor.name }));
  });
}

/**
 * The owners a form may choose from, by label. Those outside the operations team stand
 * under a heading of their own, so that it shows which choice is an exception.
 */
export function useOwnerOptions(): Loaded<Option[]> {
  return useList("owner-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/owners", { query: { limit: EVERY, offset }, signal }),
    );
    return ownerOptions(items);
  });
}

/** The contacts a place or an owner may be given, by name, with the address of each. */
export function useContactOptions(turn = 0): Loaded<Option[]> {
  return useList(`contact-options ${turn}`, async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/contacts", {
        query: { limit: EVERY, offset, include_drafts: true },
        signal,
      }),
    );
    return items.map((contact) => ({
      value: contact.hid,
      label: contact.email ? `${contact.name} (${contact.email})` : contact.name,
    }));
  });
}

/** The regions a site or a region may be in, by path, drafts among them. */
export function useRegions(turn = 0) {
  return useList(`regions ${turn}`, async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/regions", {
        query: { limit: EVERY, offset, include_drafts: true },
        signal,
      }),
    );
    return [...items].sort((one, other) => one.path.localeCompare(other.path));
  });
}

/** The regions a form may choose from, by path. */
export function useRegionOptions(): Loaded<Option[]> {
  return useList("region-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/regions", {
        query: { limit: EVERY, offset, sort: ["name"] },
        signal,
      }),
    );
    return items
      .map((region) => ({ value: region.hid, label: region.path }))
      .sort((one, other) => one.label.localeCompare(other.label));
  });
}

/** The sites a form may choose from, by path. */
export function useSiteOptions(): Loaded<Option[]> {
  return useList("site-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/sites", {
        query: { limit: EVERY, offset, sort: ["name"] },
        signal,
      }),
    );
    return items
      .map((site) => ({ value: site.hid, label: site.path }))
      .sort((one, other) => one.label.localeCompare(other.label));
  });
}

/**
 * The support agreements a contract may be grouped into, by name, each with its vendor:
 * a contract is grouped into an agreement with its own vendor.
 */
export function useAgreementOptions(turn = 0): Loaded<Array<Option & { vendorHid: string }>> {
  return useList(`agreement-options ${turn}`, async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/agreements", {
        query: { limit: EVERY, offset, include_drafts: true },
        signal,
      }),
    );
    return items.map((agreement) => ({
      value: agreement.hid,
      label: `${agreement.name} (${agreement.vendor.name})`,
      vendorHid: agreement.vendor_hid,
    }));
  });
}

/** The external systems, by name, retired ones among them: a registration may name one. */
export function useSystems(turn = 0) {
  return useList(`systems ${turn}`, async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/external-systems", {
        query: { limit: EVERY, offset, include_drafts: true, include_archived: true },
        signal,
      }),
    );
    return items;
  });
}

/** The catalog entries a form may choose from, by vendor and PID. */
export function useEntryOptions(): Loaded<Option[]> {
  return useList("entry-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/catalog-entries", { query: { limit: EVERY, offset }, signal }),
    );
    return items.map((entry) => ({
      value: entry.hid,
      label: entry.model_name ? `${entry.pid} (${entry.model_name})` : entry.pid,
      group: entry.vendor.name,
    }));
  });
}

/** The networks an address may be under, by label. */
export function useNetworkOptions(turn = 0): Loaded<Option[]> {
  return useList(`network-options ${turn}`, async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/networks", { query: { limit: EVERY, offset }, signal }),
    );
    return items.map((network) => ({ value: network.hid, label: network.label }));
  });
}

/** The device groups another group may be nested in, by name, with the type of each. */
export function useGroupOptions(): Loaded<Option[]> {
  return useList("group-options", async (signal) => {
    const items = await whole((offset) =>
      api.request("get", "/api/v1/device-groups", {
        query: { limit: EVERY, offset, include_drafts: true },
        signal,
      }),
    );
    return items.map((group) => ({
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
    const items = await whole((offset) =>
      api.request("get", "/api/v1/operators", {
        query: { limit: EVERY, offset, include_drafts: true, include_archived: true },
        signal,
      }),
    );
    for (const operator of items) {
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
