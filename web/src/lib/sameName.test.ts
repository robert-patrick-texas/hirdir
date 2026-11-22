import { describe, expect, it } from "vitest";
import { parseFilter } from "./filter";
import { namedAddress, nameFilter, sameNameWords } from "./sameName";

describe("a name another contact has is said, with how a file tells them apart (P-315)", () => {
  it("says nothing where no other contact has it", () => {
    expect(sameNameWords("Kim Lee", 0, "contact")).toBeNull();
    expect(sameNameWords("Kim Lee", 0, "own")).toBeNull();
  });

  it("names one other, or how many, and the email or the HID", () => {
    expect(sameNameWords("Kim Lee", 1, "contact")).toBe(
      "Another contact is named Kim Lee: a file tells them apart by the email or the HID.",
    );
    expect(sameNameWords("Kim Lee", 2, "contact")).toBe(
      "2 other contacts are named Kim Lee: a file tells them apart by the email or the HID.",
    );
    expect(sameNameWords("Kim Lee", 1, "own")).toBe(
      "Another contact is named Kim Lee: a file tells you apart by your email or your HID.",
    );
  });
});

describe("the contacts of a name are one link away (P-315)", () => {
  it("narrows the list by the name, in the short form where it can", () => {
    expect(nameFilter("Kim Lee")).toBe("name:eq:Kim Lee");
    expect(namedAddress("Kim Lee")).toBe("/contacts?filter=name%3Aeq%3AKim+Lee");
  });

  it("writes a name the short form cannot hold as a tree, read back whole", () => {
    for (const name of ["Ops: on:call", "a, b", "x tags:has:y"]) {
      const written = nameFilter(name);
      const read = parseFilter(written);
      expect(read.ok).toBe(true);
      expect(read.ok && read.filter).toEqual({ field: "name", op: "eq", value: name });
    }
  });
});
