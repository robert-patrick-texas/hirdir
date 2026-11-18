import { describe, expect, it } from "vitest";
import { ITEM_WORDS, parseFilter } from "./filter";
import { groupWords, memberText, namedBy, sameWords, stackOf } from "./stacks";

describe("groupWords", () => {
  it("finds the words the plain words of the item list look for in the groups' names", () => {
    const read = parseFilter("cw07-idf03-acc1 FCW9", ITEM_WORDS);
    expect(read.ok).toBe(true);
    const words = read.ok ? groupWords(read.filter) : [];
    expect(words).toEqual(["cw07-idf03-acc1", "FCW9"]);
  });

  it("takes each word once, a condition of the short form too, and nothing blank", () => {
    expect(
      groupWords({
        and: [
          { field: "group.name", op: "eq", value: "core-pair" },
          { or: [{ field: "group.name", op: "contains", value: "core-pair" }] },
          { field: "group.name", op: "contains", value: "  " },
          { field: "group.name", op: "prefix", value: "edge" },
          { field: "hostname", op: "contains", value: "edge" },
        ],
      }),
    ).toEqual(["core-pair"]);
    expect(groupWords(null)).toEqual([]);
  });
});

describe("namedBy", () => {
  it("finds a group whose name or host name is one of the words", () => {
    expect(namedBy(["cw07-idf03-acc1"])).toEqual({
      or: [
        { field: "name", op: "eq", value: "cw07-idf03-acc1" },
        { field: "hostname", op: "eq", value: "cw07-idf03-acc1" },
      ],
    });
    expect(namedBy([])).toBeNull();
  });
});

describe("sameWords", () => {
  it("is true for the same words in the same order", () => {
    expect(sameWords(["a", "b"], ["a", "b"])).toBe(true);
    expect(sameWords(["a", "b"], ["b", "a"])).toBe(false);
    expect(sameWords([], ["a"])).toBe(false);
  });
});

describe("memberText", () => {
  const stack = { group_hid: "g-1", name: "cw07-idf03-acc1", type: "stack", position: 2 };
  const custom = { group_hid: "g-2", name: "lab-switches", type: "custom", position: null };

  it("names a member by its stack and its position", () => {
    expect(memberText([custom, stack])).toBe("cw07-idf03-acc1 #2");
    expect(memberText([{ ...stack, position: null }])).toBe("cw07-idf03-acc1");
  });

  it("is blank for an item in no stack", () => {
    expect(memberText([custom])).toBe("");
    expect(stackOf([custom])).toBeUndefined();
  });
});
