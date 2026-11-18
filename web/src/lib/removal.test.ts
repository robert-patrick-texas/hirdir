import { describe, expect, it } from "vitest";
import {
  countOf,
  createdPath,
  deletedText,
  dependentKind,
  dependentPath,
  reasonGiven,
  removalKindOf,
  removalPath,
  retiredText,
  stateLabel,
  stayTicked,
  tickable,
  tooManyText,
} from "./removal";

const one = { hid: "0193a1f4-0001", label: "site7-sw-example-01" };
const two = { hid: "0193a1f4-0002", label: "site7-sw-example-02" };

describe("what a Retire of the rows ticked did (P-228)", () => {
  it("says how many were retired", () => {
    expect(
      retiredText("item", { retired: [one, two], already: [], refused: [], missing: [] }),
    ).toBe("Retired 2 items.");
    expect(
      retiredText("device_group", { retired: [one], already: [], refused: [], missing: [] }),
    ).toBe("Retired 1 group.");
  });

  it("counts those retired already, refused and not found", () => {
    const answer = {
      retired: [],
      already: [one],
      refused: [{ ...two, detail: "an example refusal" }],
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
