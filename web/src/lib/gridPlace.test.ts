import { describe, expect, it } from "vitest";
import { GridPlaces, parsePlace, placeFor, viewText } from "./gridPlace";
import { memoryStorage } from "./session";

const VIEW = viewText({ short: "", filter: {}, sort: [], includeArchived: false });

const PLACE = {
  view: VIEW,
  top: 7_500,
  windowY: 400,
  opened: { id: "01a1ecaa-0000-7000-8000-000000000001", index: 237 },
};

describe("viewText", () => {
  it("is the same for the same view, whatever the order of its keys", () => {
    expect(viewText({ a: 1, b: { d: 2, c: 3 } })).toBe(viewText({ b: { c: 3, d: 2 }, a: 1 }));
  });

  it("differs for another filter or sort", () => {
    expect(viewText({ sort: [{ colId: "name", sort: "asc" }] })).not.toBe(
      viewText({ sort: [{ colId: "name", sort: "desc" }] }),
    );
    expect(viewText({ short: "state:eq:Prod" })).not.toBe(viewText({ short: "" }));
  });
});

describe("parsePlace", () => {
  it("reads what was kept", () => {
    expect(parsePlace(JSON.stringify(PLACE))).toEqual(PLACE);
    expect(parsePlace(JSON.stringify({ ...PLACE, opened: null }))?.opened).toBeNull();
  });

  it("takes anything malformed as no place", () => {
    expect(parsePlace(null)).toBeNull();
    expect(parsePlace("not json")).toBeNull();
    expect(parsePlace(JSON.stringify({ ...PLACE, top: -1 }))).toBeNull();
    expect(parsePlace(JSON.stringify({ ...PLACE, view: 3 }))).toBeNull();
    expect(parsePlace(JSON.stringify({ ...PLACE, opened: { id: 5 } }))?.opened).toBeNull();
  });
});

describe("placeFor", () => {
  it("goes back only to a place kept under the same view", () => {
    expect(placeFor(PLACE, VIEW)).toBe(PLACE);
    expect(placeFor(PLACE, viewText({ short: "x" }))).toBeNull();
    expect(placeFor(null, VIEW)).toBeNull();
  });
});

describe("GridPlaces", () => {
  it("keeps a place for each person and grid", () => {
    const storage = memoryStorage();
    const mine = new GridPlaces(storage, "user-1");
    mine.save("items", PLACE);
    expect(mine.load("items")).toEqual(PLACE);
    expect(mine.load("vendors")).toBeNull();
    expect(new GridPlaces(storage, "user-2").load("items")).toBeNull();
    mine.clear("items");
    expect(mine.load("items")).toBeNull();
  });

  it("keeps nothing, and fails nothing, where the browser refuses the storage", () => {
    const refusing = {
      getItem: () => {
        throw new Error("refused");
      },
      setItem: () => {
        throw new Error("refused");
      },
      removeItem: () => {
        throw new Error("refused");
      },
    };
    for (const places of [new GridPlaces(refusing, "user-1"), new GridPlaces(null, "user-1")]) {
      places.save("items", PLACE);
      expect(places.load("items")).toBeNull();
      places.clear("items");
    }
  });
});
