import { describe, expect, it } from "vitest";
import { askedNext } from "./hooks";

describe("askedNext", () => {
  it("asks for other text as a new search, and counts nothing again", () => {
    expect(askedNext({ asked: "", again: 0 }, "rack")).toEqual({ asked: "rack", again: 0 });
    expect(askedNext({ asked: "rack", again: 2 }, "racks")).toEqual({ asked: "racks", again: 2 });
  });

  it("counts the same text asked again, by Enter or typed again, which is read again", () => {
    expect(askedNext({ asked: "rack", again: 0 }, "rack")).toEqual({ asked: "rack", again: 1 });
    expect(askedNext({ asked: "rack", again: 1 }, "rack ")).toEqual({ asked: "rack ", again: 2 });
  });

  it("asks for nothing again when the box is blank", () => {
    const was = { asked: "", again: 3 };
    expect(askedNext(was, "")).toBe(was);
    expect(askedNext(was, "  ")).toBe(was);
    expect(askedNext({ asked: "rack", again: 3 }, "")).toEqual({ asked: "", again: 3 });
  });
});
