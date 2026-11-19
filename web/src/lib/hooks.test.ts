import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { askAgain, askedNext, canAskAgain, hearAskAgain, noteRead, sameAnswer } from "./hooks";

describe("asking again of a busy server", () => {
  const busy = () =>
    new ApiError({
      status: 503,
      title: "Busy",
      retryAfter: 5,
      busy: { state: "busy", because: ["cpu_percent"], retry_after: 5 },
    });

  it("is offered under the refusal of a read that a busy server did not answer", () => {
    const refusal = busy();
    expect(canAskAgain(refusal)).toBe(false);
    noteRead(refusal);
    expect(canAskAgain(refusal)).toBe(true);
    // Another refusal of the same words, as of a preview that a form sent, is not a read.
    expect(canAskAgain(busy())).toBe(false);
  });

  it("is not offered under any other failure of a read, nor under none", () => {
    const waited = new ApiError({
      status: 503,
      title: "Busy",
      detail: "another change",
      retryAfter: 1,
    });
    noteRead(waited);
    expect(canAskAgain(waited)).toBe(false);
    const unreachable = new ApiError({ status: 0, title: "No answer" });
    noteRead(unreachable);
    expect(canAskAgain(unreachable)).toBe(false);
    expect(canAskAgain(null)).toBe(false);
    expect(canAskAgain(undefined)).toBe(false);
  });

  it("tells everything that hears, until it stops hearing", () => {
    const heard: string[] = [];
    const stopOne = hearAskAgain(() => heard.push("one"));
    const stopOther = hearAskAgain(() => heard.push("other"));
    askAgain();
    expect(heard).toEqual(["one", "other"]);
    stopOne();
    askAgain();
    expect(heard).toEqual(["one", "other", "other"]);
    stopOther();
    askAgain();
    expect(heard).toHaveLength(3);
  });

  it("tells those that heard when it was asked, though one stops another meanwhile", () => {
    const heard: string[] = [];
    let stopSecond = () => {};
    const stopFirst = hearAskAgain(() => {
      heard.push("first");
      stopSecond();
    });
    stopSecond = hearAskAgain(() => heard.push("second"));
    askAgain();
    expect(heard).toEqual(["first", "second"]);
    stopFirst();
  });
});

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
