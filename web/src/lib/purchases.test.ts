import { describe, expect, it } from "vitest";
import { parseShort } from "./filter";
import {
  ARRIVED_BY,
  arrivedOf,
  arrivedPath,
  asksWhatFollows,
  isArrivedBy,
  lineModel,
  lineWhat,
  mismatchedPath,
  modelStays,
  notReceivable,
  ON_CORRECTION,
  REQUEST_STATUSES,
  receiptOf,
  requestPath,
  savedText,
} from "./purchases";

describe("what a change of a line did", () => {
  const before = { name: "RITM-1/2", received_quantity: 3 };
  const after = {
    name: "RITM-1/2",
    catalog: { vendor: "Example Networks", pid: "EN-48" } as never,
    part_number: "EN-48",
  };

  it("says that the items followed the corrected model, or stayed", () => {
    expect(savedText(before, after, { catalog_entry_hid: "m-2", items: "follow" })).toBe(
      "RITM-1/2 is of Example Networks EN-48 now. The 3 items that arrived on it follow: each that is not retired is of Example Networks EN-48 as well.",
    );
    expect(
      savedText({ ...before, received_quantity: 1 }, after, {
        catalog_entry_hid: "m-2",
        items: "stay",
      }),
    ).toContain("The item that arrived on it keeps its model, and is marked");
  });

  it("says that a line is tracked once it has a model, and not once it is taken off", () => {
    const none = { ...before, received_quantity: 0 };
    expect(savedText(none, after, { catalog_entry_hid: "m-2" })).toBe(
      "RITM-1/2 is of Example Networks EN-48 now, and tracked.",
    );
    expect(savedText(none, { ...after, catalog: null }, { catalog_entry_hid: null })).toContain(
      "is not tracked any more",
    );
  });

  it("says only that it was saved where the model was left alone", () => {
    expect(savedText(before, after, {})).toBe("RITM-1/2 was saved.");
  });
});

describe("what arrived on a line", () => {
  it("is one item to a line, each by the serial number, the asset tag or the name chosen", () => {
    expect(arrivedOf("FCW0000X101\nFCW0000X102\n", "serial_number", "", 10)).toEqual({
      items: [{ serial_number: "FCW0000X101" }, { serial_number: "FCW0000X102" }],
      quantity: 0,
      total: 2,
      error: "",
      countError: "",
    });
    expect(arrivedOf("AT-000201", "asset_tag", "", 1).items).toEqual([{ asset_tag: "AT-000201" }]);
    expect(arrivedOf("site3-sw-access-01", "name", "", 1).items).toEqual([
      { name: "site3-sw-access-01" },
    ]);
  });

  it("passes over blank lines and the spaces around a value, as a paste from a sheet has them", () => {
    const read = arrivedOf("  FCW0000X101  \r\n\r\n\tFCW0000X102\n   \n", "serial_number", "", 10);
    expect(read.items).toEqual([
      { serial_number: "FCW0000X101" },
      { serial_number: "FCW0000X102" },
    ]);
    expect(read.error).toBe("");
  });

  it("is a count of what nothing is known of yet, alone or beside the items that are known", () => {
    // Four arrived with nothing to know them by: the server names each for its line.
    expect(arrivedOf("", "serial_number", "4", 4)).toMatchObject({
      items: [],
      quantity: 4,
      total: 4,
      error: "",
      countError: "",
    });
    expect(arrivedOf("FCW0000X101", "serial_number", " 3 ", 10)).toMatchObject({
      items: [{ serial_number: "FCW0000X101" }],
      quantity: 3,
      total: 4,
      error: "",
    });
  });

  it("asks for something when neither was said, and a count of nought is nothing", () => {
    const asks =
      "Say what arrived: one item to a line, or how many arrived that nothing is known of yet.";
    expect(arrivedOf(" \n ", "serial_number", "", 10).error).toBe(asks);
    expect(arrivedOf("", "serial_number", "0", 10).error).toBe(asks);
  });

  it("says beside the count what is wrong with it", () => {
    for (const typed of ["four", "-1", "1.5", "2 items"]) {
      const read = arrivedOf("FCW0000X101", "serial_number", typed, 10);
      expect(read.countError, typed).toBe("A whole number, with digits only.");
      expect(read.error, typed).toBe("");
    }
  });

  it("names the one that is there twice, whatever its case", () => {
    expect(arrivedOf("FCW0000X101\nfcw0000x101", "serial_number", "", 10).error).toBe(
      "fcw0000x101 is there twice.",
    );
  });

  it("says so before sending more than the line still expects, the count among them", () => {
    expect(arrivedOf("A\nB\nC", "serial_number", "", 2).error).toBe(
      "3 items are more than the 2 this line still expects. Raise its quantity first.",
    );
    expect(arrivedOf("A", "serial_number", "4", 4).error).toBe(
      "5 items are more than the 4 this line still expects. Raise its quantity first.",
    );
    expect(arrivedOf("A", "serial_number", "", 0).error).toContain("Nothing more is expected");
    // As many as are left is what is wanted.
    expect(arrivedOf("A\nB", "serial_number", "", 2).error).toBe("");
    expect(arrivedOf("A", "serial_number", "3", 4).error).toBe("");
  });

  it("sends the items, the count, or both: what there is none of is left out", () => {
    expect(receiptOf(arrivedOf("A\nB", "serial_number", "", 5))).toEqual({
      items: [{ serial_number: "A" }, { serial_number: "B" }],
    });
    expect(receiptOf(arrivedOf("", "serial_number", "4", 5))).toEqual({ quantity: 4 });
    expect(receiptOf(arrivedOf("A", "asset_tag", "2", 5))).toEqual({
      items: [{ asset_tag: "A" }],
      quantity: 2,
    });
  });

  it("knows the three ways of telling one item from another", () => {
    expect(ARRIVED_BY.map((by) => by.value)).toEqual(["serial_number", "asset_tag", "name"]);
    expect(isArrivedBy("asset_tag")).toBe(true);
    expect(isArrivedBy("hostname")).toBe(false);
  });
});

describe("whether a line can be received on", () => {
  it("receives while its request is neither a draft nor cancelled and something is to come", () => {
    expect(notReceivable({ request_status: "pending", pending_quantity: 4 })).toBe("");
    expect(notReceivable({ request_status: "ordered", pending_quantity: 1 })).toBe("");
    // The status is what a person says: one marked received still takes what is left.
    expect(notReceivable({ request_status: "received", pending_quantity: 1 })).toBe("");
  });

  it("says that a line that is not tracked takes no item", () => {
    expect(
      notReceivable({ request_status: "ordered", pending_quantity: 0, tracked: false }),
    ).toContain("not tracked");
    expect(notReceivable({ request_status: "ordered", pending_quantity: 2, tracked: true })).toBe(
      "",
    );
  });

  it("says why not: a draft, a cancelled request, a line with nothing to come", () => {
    expect(notReceivable({ request_status: "draft", pending_quantity: 4 })).toContain("draft");
    expect(notReceivable({ request_status: "cancelled", pending_quantity: 4 })).toContain(
      "cancelled",
    );
    expect(notReceivable({ request_status: "ordered", pending_quantity: 0 })).toContain(
      "raise its quantity",
    );
  });
});

describe("requests and lines as words and links", () => {
  it("has the five statuses a person may give a request", () => {
    expect(REQUEST_STATUSES.map((status) => status.value)).toEqual([
      "draft",
      "pending",
      "ordered",
      "received",
      "cancelled",
    ]);
  });

  it("leads to a request by its HID, and to what arrived on a line by a filter of the items", () => {
    expect(requestPath("r-1")).toBe("/purchases/r-1");
    const query = new URLSearchParams(arrivedPath("l-1").split("?")[1]);
    expect(parseShort(query.get("filter") ?? "")).toEqual({
      ok: true,
      filter: { field: "purchase_line_hid", op: "eq", value: "l-1" },
    });
    expect(query.get("minor")).toBe("1");
  });

  it("leads to the items on a line that are of another model, as many as the line counts", () => {
    const query = new URLSearchParams(mismatchedPath("l-1").split("?")[1]);
    expect(parseShort(query.get("filter") ?? "")).toEqual({
      ok: true,
      filter: {
        and: [
          { field: "purchase_line_hid", op: "eq", value: "l-1" },
          { field: "purchase_line_mismatch", op: "eq", value: "true" },
        ],
      },
    });
    // The line counts them as the item list does: drafts and archived items left out.
    expect([query.get("minor"), query.get("archived"), query.get("drafts")]).toEqual([
      "1",
      null,
      null,
    ]);
  });

  it("calls the model of a line by its vendor and its PID", () => {
    expect(lineModel({ catalog: { vendor: "Cisco", pid: "C9300-48P" } } as never)).toBe(
      "Cisco C9300-48P",
    );
  });

  it("calls a line that is not tracked by its part number, as procurement gave it", () => {
    const untracked = {
      catalog: null,
      part_number: "CAB-TIE-100",
      description: "Cable ties, 100",
      tracked: false,
    };
    expect(lineModel(untracked)).toBe("CAB-TIE-100");
    expect(lineWhat(untracked)).toBe("CAB-TIE-100, not tracked");
    expect(lineWhat({ ...untracked, part_number: null })).toBe("Cable ties, 100, not tracked");
    expect(
      lineWhat({
        catalog: { vendor: "Example Networks", pid: "EN-24" } as never,
        part_number: "EN-24=",
        description: null,
        tracked: true,
      }),
    ).toBe("Example Networks EN-24");
  });
});

describe("correcting the model of a line", () => {
  const line = { catalog_entry_hid: "m-1", received_quantity: 3 };

  it("asks what becomes of the items that arrived, where the model chosen is another", () => {
    expect(asksWhatFollows(line, "m-2")).toBe(true);
    expect(asksWhatFollows(line, "m-1")).toBe(false);
    // Taking the model off is refused while items are on it: there is nothing to ask.
    expect(asksWhatFollows(line, "")).toBe(false);
    expect(asksWhatFollows({ ...line, received_quantity: 0 }, "m-2")).toBe(false);
    expect(asksWhatFollows({ catalog_entry_hid: null, received_quantity: 0 }, "m-2")).toBe(false);
  });

  it("offers the two answers, follow and stay", () => {
    expect(ON_CORRECTION.map((option) => option.value)).toEqual(["follow", "stay"]);
  });

  it("keeps a model on a line on which something has arrived", () => {
    expect(modelStays(line)).toContain("3 items have arrived on it");
    expect(modelStays({ ...line, received_quantity: 1 })).toContain("An item has arrived");
    expect(modelStays({ ...line, received_quantity: 0 })).toBe("");
    expect(modelStays({ catalog_entry_hid: null, received_quantity: 0 })).toBe("");
  });
});
