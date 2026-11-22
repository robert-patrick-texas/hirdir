// 0.9.18: the country and the state of an address in the forms of a place (P-321), as the
// review of the web found them: the country is asked for before the state, whose list it
// gives (finding 9), and a state the record holds comes back with the country it holds,
// so that a country changed and changed back loses nothing and sends nothing (finding 2).

import { describe, expect, it } from "vitest";
import type { Country, State } from "./countries";
import { buildPatch, changedValues, formOf } from "./patch";
import { type PlaceLists, placeSpecs } from "./placeForm";
import type { Place } from "./places";

const AT = "2026-11-22T10:15:00Z";

const COUNTRIES: Country[] = [
  {
    hid: "c-us",
    code: "US",
    name: "United States",
    row_version: 1,
    created_at: AT,
    updated_at: AT,
  },
  { hid: "c-ca", code: "CA", name: "Canada", row_version: 1, created_at: AT, updated_at: AT },
];

function state(country: string, code: string, name: string): State {
  return { hid: `s-${code}`, country, code, name, row_version: 1, created_at: AT, updated_at: AT };
}

const LISTS: PlaceLists = {
  kinds: [],
  tags: [],
  countries: COUNTRIES,
  states: [state("US", "TX", "Texas"), state("CA", "ON", "Ontario")],
};

/** A site as the server answers it, with what the forms of a place read of it. */
function site(fields: Record<string, unknown>): Place & { row_version: number } {
  return {
    hid: "site-1",
    row_version: 3,
    name: "Review USA site",
    tags: [],
    operator: null,
    address1: "1 Example Way",
    address2: null,
    city: "Springfield",
    state: null,
    postal_code: null,
    country: null,
    ship_address1: null,
    ship_address2: null,
    ship_city: null,
    ship_state: null,
    ship_postal_code: null,
    ship_country: null,
    ship_same_as_address: false,
    notes: null,
    ...fields,
  } as unknown as Place & { row_version: number };
}

describe("the address of a place in its form", () => {
  it("asks for the country before the state, whose list it gives (finding 9)", () => {
    const names = placeSpecs("site", LISTS).map((spec) => spec.name);
    expect(names.indexOf("country")).toBeLessThan(names.indexOf("state"));
    expect(names.indexOf("ship_country")).toBeLessThan(names.indexOf("ship_state"));
    expect(names.filter((name) => /^(address|city|state|postal|country)/.test(name))).toEqual([
      "address1",
      "address2",
      "city",
      "country",
      "state",
      "postal_code",
    ]);
    const region = placeSpecs("region", LISTS).map((spec) => spec.name);
    expect(region.indexOf("ship_country")).toBeLessThan(region.indexOf("ship_state"));
  });

  for (const held of ["Tejas", "TX"]) {
    it(`brings back the state held, ${held}, with the country held, and sends nothing of it (finding 2)`, () => {
      const record = site({ state: held });
      const specs = placeSpecs("site", LISTS, record);
      const opened = formOf(specs, record);
      // Canada has no Tejas and no TX: the state is cleared, to be chosen.
      const canada = changedValues(specs, opened, "country", "CA");
      expect(canada.state).toBe("");
      // The United States again, the country in force of a blank one: the state comes back.
      const back = changedValues(specs, canada, "country", "US");
      expect(back.state).toBe(held);
      const built = buildPatch(specs, record, { ...back, notes: "Dock B" });
      expect(built.body).toEqual({ row_version: 3, notes: "Dock B" });
    });
  }

  it("brings back the state held with a country held by its code, and with its shipping country", () => {
    const record = site({
      country: "CA",
      state: "ON",
      ship_city: "Toronto",
      ship_state: "Ontaria",
    });
    const specs = placeSpecs("site", LISTS, record);
    const opened = formOf(specs, record);
    const away = changedValues(specs, opened, "country", "US");
    expect(away.state).toBe("");
    expect(changedValues(specs, away, "country", "CA").state).toBe("ON");
    const shipAway = changedValues(specs, opened, "ship_country", "CA");
    expect(shipAway.ship_state).toBe("");
    const shipBack = changedValues(specs, shipAway, "ship_country", "US");
    expect(shipBack.ship_state).toBe("Ontaria");
    expect(buildPatch(specs, record, shipBack).changed).toEqual([]);
  });

  it("follows a new country with no record held, in the form of a new place", () => {
    const specs = placeSpecs("site", LISTS);
    const typed = changedValues(specs, formOf(specs), "state", "TX");
    expect(changedValues(specs, typed, "country", "CA").state).toBe("");
  });
});
