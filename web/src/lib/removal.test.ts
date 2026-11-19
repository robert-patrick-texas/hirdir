import { describe, expect, it } from "vitest";
import {
  countOf,
  createdPath,
  deletedText,
  dependentKind,
  dependentPath,
  goesWithItText,
  itemRetiredText,
  itemsInTheWay,
  reasonGiven,
  removalKindOf,
  removalPath,
  retiredText,
  retireWillText,
  runningOn,
  runOnItLead,
  stateLabel,
  stayTicked,
  tickable,
  tooManyText,
  withThemText,
} from "./removal";

const one = { hid: "0193a1f4-0001", label: "site7-sw-example-01" };
const two = { hid: "0193a1f4-0002", label: "site7-sw-example-02" };
// What a Retire answers where it did nothing: the fields each test leaves alone.
const nothing = { dry_run: false, retired: [], already: [], refused: [], missing: [], hosted: [] };

describe("what a Retire of the rows ticked did (P-228)", () => {
  it("says how many were retired", () => {
    expect(retiredText("item", { ...nothing, retired: [one, two] })).toBe("Retired 2 items.");
    expect(retiredText("device_group", { ...nothing, retired: [one] })).toBe("Retired 1 group.");
  });

  it("counts those retired already, refused and not found", () => {
    const answer = {
      ...nothing,
      already: [one],
      refused: [{ ...two, detail: "an example refusal", depends_on: [] }],
      missing: ["0193a1f4-0003"],
    };
    expect(retiredText("item", answer)).toBe(
      "No items were retired. 1 item retired already. 1 item refused, still ticked: 1 item not found, as deleted since.",
    );
    expect(stayTicked(answer)).toEqual([two.hid]);
  });
});

describe("what a Delete did, or would do (P-227)", () => {
  const refused = {
    ...two,
    depends_on: [{ record_type: "contract", hid: "0193a1f4-0009", label: "CON-EXAMPLE-1" }],
  };

  it("says what a dry run would delete and refuse", () => {
    expect(
      deletedText("item", { dry_run: true, deleted: [one], refused: [refused], missing: [] }),
    ).toBe("1 item will be deleted. 1 item refused, while what depends on each is there:");
    expect(
      deletedText("device_group", { dry_run: true, deleted: [], refused: [], missing: [] }),
    ).toBe("No groups can be deleted.");
  });

  it("says what was deleted, and keeps the refused ticked", () => {
    const answer = { dry_run: false, deleted: [one], refused: [refused], missing: [] };
    expect(deletedText("item", answer)).toBe("Deleted 1 item. 1 item refused, still ticked:");
    expect(stayTicked(answer)).toEqual([two.hid]);
  });

  it("says nothing of ticks on a record's page, where nothing is ticked", () => {
    const answer = { dry_run: false, deleted: [], refused: [refused], missing: [] };
    expect(deletedText("item", answer, false)).toBe("No items were deleted. 1 item refused:");
    expect(
      retiredText(
        "item",
        { ...nothing, refused: [{ ...two, detail: "why", depends_on: [] }] },
        false,
      ),
    ).toBe("No items were retired. 1 item refused:");
  });

  it("names what is in the way, with a link where its kind has a page", () => {
    expect(dependentPath({ record_type: "contract", hid: "C-1" })).toBe("/contracts/C-1");
    expect(dependentPath({ record_type: "purchase_line", hid: "PL-1" })).toBeNull();
    expect(dependentKind({ record_type: "item_replacement" })).toBe("replacement");
    expect(dependentKind({ record_type: "some_new_kind" })).toBe("some new kind");
    expect(removalPath("device_group", "G-1")).toBe("/groups/G-1");
  });

  it("needs a reason that is more than spaces", () => {
    expect(reasonGiven("   ")).toBe(false);
    expect(reasonGiven("a wrong file")).toBe(true);
  });

  it("ticks among what an import made only the records of its kind that are still there", () => {
    expect(removalKindOf("items")).toBe("item");
    expect(removalKindOf("device_groups")).toBe("device_group");
    expect(removalKindOf("vendors")).toBeNull();
    expect(tickable({ record_type: "item", state: "retired" }, "item")).toBe(true);
    expect(tickable({ record_type: "item", state: "deleted" }, "item")).toBe(false);
    expect(tickable({ record_type: "address", state: "active" }, "item")).toBe(false);
    expect(tickable({ record_type: "vendor", state: "active" }, null)).toBe(false);
    expect(createdPath({ record_type: "item", record_hid: "I-1", state: "active" })).toBe(
      "/items/I-1",
    );
    expect(createdPath({ record_type: "item", record_hid: "I-1", state: "deleted" })).toBeNull();
    expect(stateLabel("deleted")).toBe("Deleted");
  });

  it("says before any request that one takes 1,000 at most", () => {
    expect(tooManyText(1000)).toBeNull();
    expect(tooManyText(1204)).toBe(
      "Retire and Delete take at most 1,000 rows at a time, and 1,204 are ticked: untick some first.",
    );
  });

  it("counts with the separator of thousands", () => {
    expect(countOf("item", 1000)).toBe("1,000 items");
  });
});

describe("what goes with a Retire because it runs on what is retired (P-247)", () => {
  const vm = { hid: "0193a1f4-0101", label: "site2-vm-app01", host_hid: one.hid };
  const ctr = { hid: "0193a1f4-0102", label: "site2-ctr-dns1", host_hid: vm.hid };

  it("says both numbers once retired", () => {
    expect(retiredText("item", { ...nothing, retired: [one], hosted: [vm, ctr] })).toBe(
      "Retired 1 item. With it, 2 items that ran on it were retired.",
    );
    expect(retiredText("item", { ...nothing, retired: [one, two], hosted: [vm] })).toBe(
      "Retired 2 items. With them, 1 item that ran on them was retired.",
    );
  });

  it("asks with what the dry run answers: how many of those ticked, and what goes with them", () => {
    const dry = { ...nothing, dry_run: true, retired: [one], hosted: [vm] };
    expect(retireWillText("item", dry, 1)).toBe("1 item will be retired.");
    expect(withThemText(1, 1, "ahead")).toBe(
      "With it, 1 item that runs on it will be retired: what runs on it goes with its host.",
    );
    const refused = { ...two, detail: "1 item runs on it", depends_on: [] };
    expect(retireWillText("device_group", { ...dry, hosted: [], refused: [refused] }, 2)).toBe(
      "1 of the 2 groups ticked will be retired. 1 group refused:",
    );
    expect(retireWillText("device_group", { ...nothing, refused: [refused] }, 1)).toBe(
      "None of the 1 group ticked can be retired. 1 group refused:",
    );
  });

  it("says on an item's page what goes with it", () => {
    expect(goesWithItText(3, true)).toBe(
      "3 items run on it, or on what runs on it, and are retired with it, each as its own page retires it:",
    );
    expect(itemRetiredText(0)).toBe("The item was retired.");
    expect(itemRetiredText(2)).toBe("The item was retired, and with it 2 items that ran on it.");
    expect(runOnItLead(1)).toBe("What runs on it:");
    expect(runOnItLead(12)).toBe("The 12 that run on it:");
  });
});

describe("an item in the way of a deletion that runs on it (P-247)", () => {
  const refused = [
    {
      hid: one.hid,
      depends_on: [
        { record_type: "item", hid: "0193a1f4-0201" },
        { record_type: "item", hid: "0193a1f4-0202" },
        { record_type: "contract", hid: "0193a1f4-0203" },
      ],
    },
  ];

  it("is told from one installed in it by what it names as its host", () => {
    expect(itemsInTheWay(refused)).toEqual(["0193a1f4-0201", "0193a1f4-0202"]);
    const hosts = [
      { hid: "0193a1f4-0201", host_item_hid: one.hid },
      { hid: "0193a1f4-0202", host_item_hid: null },
    ];
    expect([...runningOn(refused, hosts)]).toEqual(["0193a1f4-0201"]);
  });

  it("is said to run on it, and one installed in it as before", () => {
    expect(dependentKind({ record_type: "item" }, true)).toBe("item that runs on it");
    expect(dependentKind({ record_type: "item" })).toBe("item installed in it");
    expect(dependentKind({ record_type: "contract" }, true)).toBe("contract");
  });
});
