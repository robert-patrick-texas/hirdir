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

/**
 * The items on a line that are of another model than the line's, which 0.6.0 let in, in
 * the grid of items. The line counts them as the item list does, drafts, retired items
 * and items in Archived left out, so the grid holds as many rows as the line says.
 */
export function mismatchedPath(lineHid: string): string {
  const filter = `purchase_line_hid:eq:${lineHid} purchase_line_mismatch:eq:true`;
  return `/items?filter=${encodeURIComponent(filter)}&minor=1`;
}

/** What is said of an item that is on a line of another model than its own. */
export const MISMATCH_NOTE =
  "It is on a line of another model than its own, which 0.6.0 let in. Give it the line's model, where that is what it is, or name the line it arrived on, or none.";

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
  line: Pick<PurchaseLine, "request_status" | "pending_quantity"> &
    Partial<Pick<PurchaseLine, "tracked">>,
): string {
  if (line.tracked === false) {
    return "The line is not tracked: it has no model, and takes no item. Give it a model to track it.";
  }
  if (line.request_status === "draft") return "The request is a draft: it receives nothing yet.";
  if (line.request_status === "cancelled") return "The request is cancelled: it receives nothing.";
  if (line.pending_quantity <= 0) {
    return "Everything on this line has arrived. To receive more, raise its quantity.";
  }
  return "";
}

/** A model as a line names it: the vendor, then the PID. A line with no model is not
 * tracked, and is named by the part number procurement gave it. */
export function lineModel(line: Pick<PurchaseLine, "catalog" | "part_number">): string {
  if (line.catalog === null) {
    return line.part_number ?? "";
  }
  return [line.catalog.vendor, line.catalog.pid].filter(Boolean).join(" ");
}

/**
 * What is said of a line that is not tracked: one with no model, as procurement buys
 * cable ties or a monitor beside the network equipment (D-172).
 */
export const NOT_TRACKED_NOTE =
  "Not tracked: the line has no model of the catalog. It takes no item, is in no count, and the request is not kept waiting for it. Give it a model to track it.";

/** A line as a sentence names what it is of: its model, or its part number and that it is not tracked. */
export function lineWhat(
  line: Pick<PurchaseLine, "catalog" | "part_number" | "description" | "tracked">,
): string {
  if (line.tracked && line.catalog) return lineModel(line);
  const named = line.part_number || line.description || "a part";
  return `${named}, not tracked`;
}

/** What becomes of the items that have arrived on a line whose model is corrected (D-171). */
export type OnCorrection = "follow" | "stay";

export const ON_CORRECTION: ReadonlyArray<Option & { value: OnCorrection }> = [
  {
    value: "follow",
    label: "They follow: each is given the corrected model as well",
  },
  {
    value: "stay",
    label: "They stay as they are, and are marked as of another model than their line's",
  },
];

/** What each answer means, said beside the question. */
export const ON_CORRECTION_NOTE =
  "Follow gives every item on the line that is not retired the corrected model, in the same change, each with an audit event of its own: what an item inherits it then has from the corrected model. Stay leaves each item with the model it has, and each is then marked as of another model than its line's, to be looked at one by one.";

/**
 * Whether a change of a line asks what becomes of the items on it: where items have
 * arrived and the model chosen is another than the line has. The server refuses such a
 * change without the answer.
 */
export function asksWhatFollows(
  line: Pick<PurchaseLine, "catalog_entry_hid" | "received_quantity">,
  chosen: unknown,
): boolean {
  if (line.received_quantity <= 0) return false;
  const wanted = typeof chosen === "string" ? chosen : "";
  return wanted !== "" && wanted !== (line.catalog_entry_hid ?? "");
}

/**
 * Why the model of a line cannot be taken off, or blank where it can: a line keeps a
 * model while anything has arrived on it, and one with none has nothing to take off.
 */
export function modelStays(
  line: Pick<PurchaseLine, "catalog_entry_hid" | "received_quantity">,
): string {
  if (line.catalog_entry_hid === null) return "";
  if (line.received_quantity > 0) {
    return `${line.received_quantity === 1 ? "An item has" : `${line.received_quantity} items have`} arrived on it, so it keeps a model: it can be corrected to another, and not taken off.`;
  }
  return "";
}

/** What a change of a line did, said once it is taken: above all, what its model became. */
export function savedText(
  before: Pick<PurchaseLine, "name" | "received_quantity">,
  after: Pick<PurchaseLine, "name" | "catalog" | "part_number">,
  sent: Pick<Schemas["PurchaseLinePatch"], "catalog_entry_hid" | "items">,
): string {
  if (!("catalog_entry_hid" in sent)) return `${after.name} was saved.`;
  if (sent.catalog_entry_hid === null) {
    return `${after.name} is not tracked any more: its model was taken off. It takes no item, and the request is not kept waiting for it.`;
  }
  const model = lineModel(after);
  const arrived = before.received_quantity;
  const them =
    arrived === 1 ? "The item that arrived on it" : `The ${arrived} items that arrived on it`;
  if (sent.items === "follow") {
    return `${after.name} is of ${model} now. ${them} ${arrived === 1 ? "follows" : "follow"}: each that is not retired is of ${model} as well.`;
  }
  if (sent.items === "stay") {
    return `${after.name} is of ${model} now. ${them} ${arrived === 1 ? "keeps its" : "keep their"} model, and ${arrived === 1 ? "is" : "are"} marked as of another model than the line's, to be looked at one by one.`;
  }
  return `${after.name} is of ${model} now, and tracked.`;
}
