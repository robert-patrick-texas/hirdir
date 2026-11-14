// Purchase requests, their lines, and receiving. A request and its lines are not
// inventory: receiving a line says which items arrived, and the server makes them. What
// has arrived on a line and what is still to come are counted by the server.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type PurchaseRequest = Schemas["PurchaseRequestOut"];
export type PurchaseLine = Schemas["PurchaseLineOut"];
export type Arrived = Schemas["Arrived"];

/** What a person says of a request. A delivery never changes it. */
export const REQUEST_STATUSES: readonly Option[] = [
  { value: "draft", label: "Draft" },
  { value: "pending", label: "Pending" },
  { value: "ordered", label: "Ordered" },
  { value: "received", label: "Received" },
  { value: "cancelled", label: "Cancelled" },
];

export function requestPath(hid: string): string {
  return `/purchases/${encodeURIComponent(hid)}`;
}

/** The items that arrived on a line, in the grid of items. */
export function arrivedPath(lineHid: string): string {
  return `/items?filter=${encodeURIComponent(`purchase_line_hid:eq:${lineHid}`)}&minor=1`;
}

/** What tells one arrived item from another: every item needs one of the three. */
export type ArrivedBy = "serial_number" | "asset_tag" | "name";

export const ARRIVED_BY: ReadonlyArray<Option & { value: ArrivedBy }> = [
  { value: "serial_number", label: "Serial numbers" },
  { value: "asset_tag", label: "Asset tags" },
  { value: "name", label: "Names" },
];

export function isArrivedBy(value: string): value is ArrivedBy {
  return ARRIVED_BY.some((by) => by.value === value);
}

export interface ArrivedRead {
  items: Arrived[];
  /** What is wrong with what was typed, found before anything is sent. Blank for nothing. */
  error: string;
}

/**
 * What was typed of a delivery, one item to a line, as the items to receive. A blank
 * line is passed over. The same serial number, asset tag or name twice is a mistake of
 * typing, and more than the line still expects is refused by the server anyway: both
 * are said here, before anything is sent.
 */
export function arrivedOf(text: string, by: ArrivedBy, pending: number): ArrivedRead {
  const values = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
  const items = values.map((value) => ({ [by]: value }) as Arrived);
  if (values.length === 0) {
    return { items, error: "Say what arrived, one item to a line." };
  }
  const seen = new Set<string>();
  for (const value of values) {
    const key = value.toLowerCase();
    if (seen.has(key)) return { items, error: `${value} is there twice.` };
    seen.add(key);
  }
  if (values.length > pending) {
    return {
      items,
      error:
        pending === 0
          ? "Nothing more is expected on this line. Raise its quantity first."
          : `${values.length} items are more than the ${pending} this line still expects. Raise its quantity first.`,
    };
  }
  return { items, error: "" };
}

/**
 * Why nothing can be received on a line, or blank when something can: a request that is
 * a draft or cancelled receives nothing, and neither does a line with nothing to come.
 */
export function notReceivable(
  line: Pick<PurchaseLine, "request_status" | "pending_quantity">,
): string {
  if (line.request_status === "draft") return "The request is a draft: it receives nothing yet.";
  if (line.request_status === "cancelled") return "The request is cancelled: it receives nothing.";
  if (line.pending_quantity <= 0) {
    return "Everything on this line has arrived. To receive more, raise its quantity.";
  }
  return "";
}

/** A model as a line names it: the vendor, then the PID. */
export function lineModel(line: Pick<PurchaseLine, "catalog">): string {
  return [line.catalog.vendor, line.catalog.pid].filter(Boolean).join(" ");
}
