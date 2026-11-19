import { describe, expect, it } from "vitest";
import { askedNext, sameAnswer } from "./hooks";

describe("askedNext", () => {
  it("asks for other text as a new search, and counts nothing again", () => {
    expect(askedNext({ asked: "", again: 0 }, "rack")).toEqual({ asked: "rack", again: 0 });
    expect(askedNext({ asked: "rack", again: 2 }, "racks")).toEqual({ asked: "racks", again: 2 });
  });

  it("counts the same text asked again, by Enter or typed again, which is read again", () => {
    expect(askedNext({ asked: "rack", again: 0 }, "rack")).toEqual({ asked: "rack", again: 1 });
    expect(askedNext({ asked: "rack", again: 1 }, "rack")).toEqual({ asked: "rack", again: 2 });
  });

  it("does not count text that differs only by a space, which is the same search", () => {
    expect(askedNext({ asked: "rack", again: 1 }, "rack ")).toEqual({ asked: "rack ", again: 1 });
  });

  it("asks for nothing again when the box is blank", () => {
    const was = { asked: "", again: 3 };
    expect(askedNext(was, "")).toBe(was);
    expect(askedNext(was, "  ")).toBe(was);
    expect(askedNext({ asked: "rack", again: 3 }, "")).toEqual({ asked: "", again: 3 });
  });
});

describe("sameAnswer", () => {
  it("holds for the same values in other objects, in any order of their names", () => {
    const one = [{ list: "item_role", value: "switch", label: "Switch", sort: 1, hid: null }];
    const other = [{ hid: null, sort: 1, label: "Switch", value: "switch", list: "item_role" }];
    expect(sameAnswer(one, other)).toBe(true);
    expect(sameAnswer([], [])).toBe(true);
    expect(sameAnswer(undefined, undefined)).toBe(true);
  });

  it("does not hold for a value added, taken away, changed or moved", () => {
    const one = { item_role: [{ value: "switch" }, { value: "router" }] };
    expect(sameAnswer(one, { item_role: [{ value: "switch" }] })).toBe(false);
    expect(sameAnswer(one, { item_role: [{ value: "router" }, { value: "switch" }] })).toBe(false);
    expect(sameAnswer(one, { ...one, added: [] })).toBe(false);
    expect(sameAnswer({ a: 1 }, { b: 1 })).toBe(false);
    expect(sameAnswer({ a: undefined }, { b: undefined })).toBe(false);
  });

  it("does not take a list for a record, nor nothing for something", () => {
    expect(sameAnswer([], {})).toBe(false);
    expect(sameAnswer(null, {})).toBe(false);
    expect(sameAnswer(undefined, [])).toBe(false);
    expect(sameAnswer("1", 1)).toBe(false);
  });
});
