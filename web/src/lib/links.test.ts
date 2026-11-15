import { describe, expect, it } from "vitest";
import {
  draftsOf,
  isWebAddress,
  linkLabel,
  linksBody,
  MAX_LINKS,
  moved,
  refusedLink,
  sameLinks,
} from "./links";

const SHEET = { url: "https://www.example.com/c9300/datasheet.pdf", text: "Data sheet" };
const RACKS = { url: "http://intranet.example.net/site-2/room-102/racks", text: "" };

describe("a link", () => {
  it("is shown by its text, or by its address where it has none", () => {
    expect(linkLabel(SHEET)).toBe("Data sheet");
    expect(linkLabel(RACKS)).toBe(RACKS.url);
    expect(linkLabel({ url: RACKS.url, text: "  " })).toBe(RACKS.url);
  });

  it("is followed only when its address is on the web", () => {
    expect(isWebAddress(SHEET.url)).toBe(true);
    expect(isWebAddress(RACKS.url)).toBe(true);
    expect(isWebAddress("HTTPS://www.example.com/")).toBe(true);
    for (const other of [
      "javascript:alert(1)",
      "ftp://files.example.com/a",
      "mailto:noc@example.com",
      "https://www.example.com/a b",
      "//www.example.com/",
      "",
    ]) {
      expect(isWebAddress(other), other).toBe(false);
    }
  });

  it("is one of twenty at most", () => {
    expect(MAX_LINKS).toBe(20);
  });
});

describe("the links of the editor", () => {
  let count = 0;
  const key = () => {
    count += 1;
    return `k${count}`;
  };

  it("start as the record has them, each with a key of its own", () => {
    const drafts = draftsOf([SHEET, RACKS], key);
    expect(drafts.map((draft) => draft.url)).toEqual([SHEET.url, RACKS.url]);
    expect(new Set(drafts.map((draft) => draft.key)).size).toBe(2);
  });

  it("move one place up or down, and not off either end", () => {
    expect(moved(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moved(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(moved(["a", "b", "c"], 0, -1)).toEqual(["a", "b", "c"]);
    expect(moved(["a", "b", "c"], 2, 1)).toEqual(["a", "b", "c"]);
  });

  it("are sent in their order, trimmed, without one left wholly blank", () => {
    expect(
      linksBody([
        { url: ` ${RACKS.url} `, text: "" },
        { url: "", text: "" },
        { url: SHEET.url, text: " Data sheet " },
      ]),
    ).toEqual([RACKS, SHEET]);
    // A link with text and no address is sent, for the server to refuse by its number.
    expect(linksBody([{ url: "", text: "Plan" }])).toEqual([{ url: "", text: "Plan" }]);
  });

  it("are the record's when they hold the same links in the same order", () => {
    expect(sameLinks([SHEET, RACKS], [SHEET, { url: RACKS.url }])).toBe(true);
    expect(sameLinks([SHEET, RACKS], [RACKS, SHEET])).toBe(false);
    expect(sameLinks([SHEET], [])).toBe(false);
  });

  it("find the link a refusal names", () => {
    expect(refusedLink("link 2: an address that begins with https:// or http://")).toBe(2);
    expect(refusedLink("at most 20 links")).toBeNull();
    expect(refusedLink(undefined)).toBeNull();
  });
});
