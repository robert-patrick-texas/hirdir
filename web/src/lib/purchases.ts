// Purchase requests, their lines, and receiving. A request and its lines are not
// inventory: receiving a line says which items arrived, and the server makes them. What
// has arrived on a line and what is still to come are counted by the server.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type PurchaseRequest = Schemas["PurchaseRequestOut"];
export type PurchaseLine = Schemas["PurchaseLineOut"];
export type Arrived = Schemas["Arrived"];

/** What a person says of a request. The delivery that completes it says Received. */
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
  /** The items that are known by something: a serial number, an asset tag or a name. */
  items: Arrived[];
  /** How many more arrived that nothing is known of yet. */
  quantity: number;
  /** Both together: how many items the receipt makes. */
  total: number;
  /** What is wrong with what was typed, found before anything is sent. Blank for nothing. */
  error: string;
  /** What is wrong with the count, said beside its input. Blank for nothing. */
  countError: string;
}

/**
 * What was said of a delivery, as what to receive: the items that are known by
 * something, one to a line, and a count of those that nothing is known of yet, each of
 * which the server names for its line. A blank line is passed over. The same serial
 * number, asset tag or name twice is a mistake of typing, and more than the line still
 * expects is refused by the server anyway: both are said here, before anything is sent.
 */
export function arrivedOf(
  text: string,
  by: ArrivedBy,
  count: string,
  pending: number,
): ArrivedRead {
  const values = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
  const items = values.map((value) => ({ [by]: value }) as Arrived);
  const typed = count.trim();
  const counted = /^\d{1,6}$/.test(typed);
  const quantity = counted ? Number.parseInt(typed, 10) : 0;
  const read = (error: string, countError = ""): ArrivedRead => ({
    items,
    quantity,
    total: items.length + quantity,
    error,
    countError,
  });
  if (typed !== "" && !counted) return read("", "A whole number, with digits only.");
  if (items.length + quantity === 0) {
    return read(
      "Say what arrived: one item to a line, or how many arrived that nothing is known of yet.",
    );
  }
  const seen = new Set<string>();
  for (const value of values) {
    const key = value.toLowerCase();
    if (seen.has(key)) return read(`${value} is there twice.`);
    seen.add(key);
  }
  if (items.length + quantity > pending) {
    return read(
      pending === 0
        ? "Nothing more is expected on this line. Raise its quantity first."
        : `${items.length + quantity} items are more than the ${pending} this line still expects. Raise its quantity first.`,
    );
  }
  return read("");
}

/**
 * The part of the body of a receipt that says what arrived: the items that are known,
 * the count of those that are not, or both. What there is none of is left out.
 */
export function receiptOf(read: Pick<ArrivedRead, "items" | "quantity">): {
  items?: Arrived[];
  quantity?: number;
} {
  return {
    ...(read.items.length > 0 ? { items: read.items } : {}),
    ...(read.quantity > 0 ? { quantity: read.quantity } : {}),
  };
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
