import { describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import {
  type CircuitSide,
  carrierSourceText,
  circuitLabel,
  circuitSearch,
  circuitsInGroup,
  circuitsOfCarrier,
  circuitsWithin,
  connectedHids,
  contactSourcePath,
  countingSide,
  dateInForce,
  devicePath,
  devicesBody,
  lineCarrier,
  mbpsText,
  moneyText,
  notInServiceText,
  rateText,
  readMoney,
  retiredText,
  type SideDate,
  sideCell,
  sideHint,
  sidesWithin,
  siteSourceText,
  switchesOf,
  weightHint,
  zDateHint,
} from "./circuits";

/** The Z side's dates in force, as the server answers them: its own, or the A side's. */
function zInForce(
  own: Partial<Record<SideDate, string>>,
  a: Partial<Record<SideDate, string>> = {},
) {
  const one = (name: SideDate): Schemas["EffectiveValue"] => ({
    value: own[name] ?? a[name] ?? null,
    source: own[name] ? "own" : a[name] ? "a_side" : "none",
    source_hid: null,
  });
  return {
    z_installed_on: one("installed_on"),
    z_activated_on: one("activated_on"),
    z_disconnected_on: one("disconnected_on"),
  };
}

const NO_DATES = {
  a_installed_on: null,
  a_activated_on: null,
  a_disconnected_on: null,
  z_installed_on: null,
  z_activated_on: null,
  z_disconnected_on: null,
  effective: zInForce({}),
};

describe("the dates of each side (P-320)", () => {
  const circuit = {
    ...NO_DATES,
    a_installed_on: "2027-01-05",
    a_activated_on: "2027-01-10",
    z_activated_on: "2027-02-01",
    effective: zInForce(
      { activated_on: "2027-02-01" },
      { installed_on: "2027-01-05", activated_on: "2027-01-10" },
    ),
  };

  it("reads the A side's as its own, and the Z side's own or the A side's in force", () => {
    expect(dateInForce(circuit, "a", "installed_on")).toEqual({
      value: "2027-01-05",
      source: "own",
    });
    expect(dateInForce(circuit, "a", "disconnected_on")).toEqual({ value: null, source: "none" });
    expect(dateInForce(circuit, "z", "installed_on")).toEqual({
      value: "2027-01-05",
      source: "a_side",
    });
    expect(dateInForce(circuit, "z", "activated_on")).toEqual({
      value: "2027-02-01",
      source: "own",
    });
    expect(dateInForce(circuit, "z", "disconnected_on")).toEqual({ value: null, source: "none" });
  });

  it("says beneath a blank Z date what it is read as, from what the form holds", () => {
    expect(zDateHint("", "2027-01-10")).toBe(
      "Blank: the A side's, 2027-01-10, is read in its place.",
    );
    expect(zDateHint("", "")).toBe("Blank: the A side's is read in its place, and it has none.");
    expect(zDateHint("2027-02-01", "2027-01-10")).toBeUndefined();
  });

  it("says of a retired circuit the day the side its cost counts at was disconnected", () => {
    const retired = {
      ...NO_DATES,
      a_disconnected_on: "2027-03-31",
      effective: zInForce({}, { disconnected_on: "2027-03-31" }),
    };
    expect(retiredText({ ...retired, cost_side: "a" })).toBe(
      "This circuit is retired. It was in service until 2027-03-31, and counts for that time in what circuits cost.",
    );
    const zOwn = {
      ...retired,
      z_disconnected_on: "2027-04-30",
      effective: zInForce({ disconnected_on: "2027-04-30" }),
    };
    expect(retiredText({ ...zOwn, cost_side: "z" })).toMatch(
      /until 2027-04-30, when its Z side, where its cost counts, was disconnected,/,
    );
    expect(retiredText({ ...NO_DATES, cost_side: "z" })).toMatch(
      /^This circuit is retired, with no day its Z side, where its cost counts, was disconnected:/,
    );
  });
});

describe("a circuit that is not in service", () => {
  const base = {
    ...NO_DATES,
    in_service: false,
    record_status: "active" as const,
    cost_side: "a" as const,
  };
  const day = "2027-04-10";

  // 0.9.18: the dates of the side its cost counts at decide, the Z side's in force (P-320 (4)).
  it("says so by the Z side's dates in force where its cost counts at the Z side", () => {
    const z = { ...base, cost_side: "z" as const };
    expect(
      notInServiceText(
        { ...z, z_activated_on: "2027-05-01", effective: zInForce({ activated_on: "2027-05-01" }) },
        day,
      ),
    ).toMatch(/^It is not in service until its Z side is activated on 2027-05-01\./);
    // A blank Z date is read as the A side's.
    expect(
      notInServiceText(
        {
          ...z,
          a_disconnected_on: "2027-03-31",
          effective: zInForce({}, { disconnected_on: "2027-03-31" }),
        },
        day,
      ),
    ).toMatch(/^Its Z side was disconnected on 2027-03-31\./);
    // The A side's dates do not decide where the cost counts at the Z side.
    expect(notInServiceText({ ...z, a_activated_on: "2027-05-01" }, day)).toMatch(
      /^It is not in service today\./,
    );
  });

  it("says why it costs nothing today, though its lines keep their amounts", () => {
    expect(notInServiceText({ ...base, in_service: true }, day)).toBe("");
    // An ordered circuit, a draft, is read at what it will cost: in service, as the server
    // answers it, unless it is to be activated later.
    expect(notInServiceText({ ...base, in_service: true, record_status: "draft" }, day)).toBe("");
    expect(
      notInServiceText({ ...base, record_status: "draft", a_activated_on: "2027-05-01" }, day),
    ).toMatch(/^It is not in service until it is activated on 2027-05-01\. Its lines keep/);
    expect(notInServiceText({ ...base, a_disconnected_on: "2027-03-31" }, day)).toMatch(
      /^It was disconnected on 2027-03-31\./,
    );
    expect(notInServiceText({ ...base, record_status: "retired" }, day)).toMatch(
      /^It was retired with no day it was disconnected/,
    );
    expect(notInServiceText({ ...base, a_disconnected_on: "2027-03-31" }, day)).toContain("0.00");
  });
});

describe("a link to the circuit grid", () => {
  it("asks for retired circuits and drafts as the item grid does, or as the list names them", () => {
    expect(switchesOf(new URLSearchParams("archived=1&drafts=1"))).toEqual({
      archived: true,
      drafts: true,
    });
    expect(switchesOf(new URLSearchParams("include_archived=true&filter=x"))).toEqual({
      archived: true,
      drafts: false,
    });
    expect(switchesOf(new URLSearchParams("include_drafts=TRUE&include_archived=false"))).toEqual({
      archived: false,
      drafts: true,
    });
    expect(switchesOf(new URLSearchParams(""))).toEqual({ archived: false, drafts: false });
  });
});

const REGION = "0193a1f4-0000-7000-8000-0000000000c1";
const SITE = "0193a1f4-0000-7000-8000-0000000000c2";
const BUILDING = "0193a1f4-0000-7000-8000-0000000000c3";
const ROOM = "0193a1f4-0000-7000-8000-0000000000c4";
const CARRIER = "0193a1f4-0000-7000-8000-0000000000d1";

const building: CircuitSide = {
  location_hid: BUILDING,
  name: "Building 1",
  path: "Americas > Central > Site-2 > Building 1",
  site_hid: SITE,
  site_path: "Americas > Central > Site-2",
  region_hid: REGION,
  record_status: "active",
};

const room: CircuitSide = {
  ...building,
  location_hid: ROOM,
  name: "MDF",
  path: "Americas > Central > Site-2 > Building 1 > MDF",
};

describe("the sides of a circuit", () => {
  it("show the name of the location, or the note of a side that has none", () => {
    expect(sideCell(building, "demarc in the basement")).toBe("Building 1");
    expect(sideCell(null, "carrier network")).toBe("carrier network");
    expect(sideCell(null, null)).toBe("");
  });

  it("say the path and the note on hover, or that a side has no location", () => {
    expect(sideHint(building, null)).toBe("Americas > Central > Site-2 > Building 1");
    expect(sideHint(building, "demarc in the basement")).toBe(
      "Americas > Central > Site-2 > Building 1 · demarc in the basement",
    );
    expect(sideHint(null, "cloud on-ramp")).toBe("No location: cloud on-ramp");
  });

  it("count the cost at the side named, or at the other where that one has no location", () => {
    expect(countingSide({ cost_side: "a", a_side: building, z_side: room })).toBe("a");
    expect(countingSide({ cost_side: "z", a_side: building, z_side: room })).toBe("z");
    // The far end of an internet circuit is in the carrier's network.
    expect(countingSide({ cost_side: "a", a_side: null, z_side: room })).toBe("z");
    expect(countingSide({ cost_side: "z", a_side: building, z_side: null })).toBe("a");
  });

  it("are within a place whose path they are at or run through", () => {
    const circuit = { a_side: building, z_side: room };
    expect(sidesWithin(circuit, "Americas > Central > Site-2")).toEqual(["a", "z"]);
    expect(sidesWithin(circuit, room.path)).toEqual(["z"]);
    // A place whose name begins as another's does not hold it.
    expect(sidesWithin(circuit, "Americas > Central > Site-2 > Building")).toEqual([]);
    expect(sidesWithin({ a_side: null, z_side: room }, building.path)).toEqual(["z"]);
  });
});

describe("the site contacts of a side", () => {
  it("say the level each came from, by the place of the side", () => {
    expect(siteSourceText({ source: "own", source_hid: "x" }, building)).toBe("Named here");
    expect(siteSourceText({ source: "location", source_hid: BUILDING }, building)).toBe(
      "From its location, Americas > Central > Site-2 > Building 1",
    );
    expect(siteSourceText({ source: "location", source_hid: BUILDING }, room)).toBe(
      "From a location it is in",
    );
    expect(siteSourceText({ source: "site", source_hid: SITE }, room)).toBe(
      "From its site, Americas > Central > Site-2",
    );
    expect(siteSourceText({ source: "region", source_hid: REGION }, room)).toBe(
      "From the region of its site",
    );
    expect(siteSourceText({ source: "region", source_hid: "above" }, room)).toBe(
      "From a region above its site",
    );
  });

  it("lead to the place they came from", () => {
    expect(contactSourcePath({ source: "site", source_hid: SITE })).toBe(`/geography/site/${SITE}`);
    expect(contactSourcePath({ source: "own", source_hid: "x" })).toBe("");
  });
});

describe("the carrier's contacts", () => {
  const one = {
    hid: "n1",
    role: "account_manager",
    priority: 1,
    contact_hid: "c1",
    contact: {
      hid: "c1",
      name: "Avery Example",
      organization: "Example Telecom",
      email: "avery@example.com",
      phone: "555 0101",
      phone2: null,
      record_status: "active" as const,
    },
  };

  it("say whether they are the carrier's, its own, or nobody", () => {
    expect(
      carrierSourceText({ value: [one], source: "vendor", source_hid: CARRIER }, "Example Telecom"),
    ).toBe("1 contact from the carrier, Example Telecom");
    expect(
      carrierSourceText({ value: [one, one], source: "own", source_hid: "c" }, "Example Telecom"),
    ).toBe("2 contacts named here, in place of the carrier's");
    expect(carrierSourceText({ value: [], source: "none", source_hid: null }, null)).toBe(
      "nobody is named",
    );
  });
});

describe("figures", () => {
  it("show money with two places and the thousands marked", () => {
    expect(moneyText("12000.00")).toBe("12,000.00");
    expect(moneyText("-50.00")).toBe("-50.00");
  });

  it("show a speed in Mbps without the places that say nothing", () => {
    expect(mbpsText("1000.00")).toBe("1,000");
    expect(mbpsText("0.50")).toBe("0.5");
    expect(mbpsText("200")).toBe("200");
    expect(mbpsText(null)).toBe("");
  });

  it("say a rate that is the port's", () => {
    expect(rateText({ value: "200.00", source: "own", source_hid: null })).toBe("200 Mbps");
    expect(rateText({ value: "1000.00", source: "port", source_hid: null })).toBe(
      "1,000 Mbps, the full rate of the port",
    );
  });

  it("say where a weight came from, and what it was raised from", () => {
    expect(weightHint({ value: "2.00", source: "own", source_hid: null, raised_from: null })).toBe(
      "Its own",
    );
    expect(
      weightHint({ value: "3.00", source: "setting", source_hid: null, raised_from: "1.00" }),
    ).toBe(
      "The default of circuits, default_circuit_weight, raised from 1.00 to the minimum of circuits, minimum_circuit_weight",
    );
  });

  it("read a monthly cost, a credit below zero among them", () => {
    expect(readMoney(" 850.5 ")).toEqual({ value: "850.5" });
    expect(readMoney("-25.00")).toEqual({ value: "-25.00" });
    expect(readMoney("")).toEqual({ value: null });
    expect(readMoney("1,000")).toHaveProperty("error");
    expect(readMoney("1.005")).toHaveProperty("error");
  });

  it("name the carrier that bills a line, blank being the primary carrier", () => {
    expect(lineCarrier({ vendor: null, vendor_hid: null }, "Example Telecom")).toBe(
      "Example Telecom (the primary carrier)",
    );
    expect(lineCarrier({ vendor: "Northwind Fiber", vendor_hid: CARRIER }, "Example Telecom")).toBe(
      "Northwind Fiber",
    );
  });
});

describe("devices", () => {
  it("are sent together, each an item or a group on its side", () => {
    expect(
      devicesBody([
        { kind: "item", hid: "i1", name: "site2-rtr-01", side: "a" },
        { kind: "group", hid: "g1", name: "edge pair", side: "z" },
      ]),
    ).toEqual({
      devices: [
        { item_hid: "i1", side: "a" },
        { group_hid: "g1", side: "z" },
      ],
    });
  });

  it("lead to the page of the item or the group", () => {
    expect(devicePath({ item_hid: "i1", group_hid: null })).toBe("/items/i1");
    expect(devicePath({ item_hid: null, group_hid: "g1" })).toBe("/groups/g1");
    expect(
      connectedHids([
        { item_hid: "i1", group_hid: null },
        { item_hid: null, group_hid: "g1" },
      ] as unknown as Parameters<typeof connectedHids>[0]),
    ).toEqual(["i1", "g1"]);
  });
});

describe("finding circuits", () => {
  it("by a place, a carrier and a group", () => {
    expect(circuitsWithin(SITE)).toEqual({ field: "location", op: "within", value: SITE });
    expect(circuitsOfCarrier(CARRIER)).toEqual({
      field: "carriers.vendor_hid",
      op: "eq",
      value: CARRIER,
    });
    expect(circuitsInGroup("g1")).toEqual({ field: "groups.hid", op: "eq", value: "g1" });
  });

  it("by a part of the name, the enterprise ID or a carrier's number", () => {
    expect(circuitSearch("  ")).toBeNull();
    expect(circuitSearch(" EC-0042 ")).toEqual({
      or: [
        { field: "name", op: "contains", value: "EC-0042" },
        { field: "enterprise_circuit_id", op: "contains", value: "EC-0042" },
        { field: "carriers.circuit_number", op: "contains", value: "EC-0042" },
      ],
    });
    expect(circuitLabel({ name: "Site-2 internet", enterprise_circuit_id: "EC-0042" })).toBe(
      "Site-2 internet (EC-0042)",
    );
    expect(circuitLabel({ name: "Dark fiber", enterprise_circuit_id: null })).toBe("Dark fiber");
  });
});
