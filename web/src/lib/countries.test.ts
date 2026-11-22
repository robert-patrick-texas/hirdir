import { describe, expect, it } from "vitest";
import {
  type Country,
  countryName,
  countryOptions,
  countryShown,
  followingState,
  notListed,
  type State,
  stateCounts,
  stateOptions,
  statesOf,
  US,
  unlistedCountryHint,
  unlistedFieldLabel,
  unlistedSetLabel,
  unlistedStateHint,
} from "./countries";

const AT = "2026-11-22T10:15:00Z";

function country(code: string, name: string): Country {
  return { hid: `c-${code}`, code, name, row_version: 1, created_at: AT, updated_at: AT };
}

function state(of: string, code: string, name: string): State {
  return {
    hid: `s-${of}-${code}`,
    country: of,
    code,
    name,
    row_version: 1,
    created_at: AT,
    updated_at: AT,
  };
}

// As the server sends them: the United States first, then by name; the states of each
// country together, in the order of the countries, by name.
const COUNTRIES = [
  country("US", "United States"),
  country("AQ", "Antarctica"),
  country("CA", "Canada"),
  country("MX", "Mexico"),
];
const STATES = [
  state("US", "IL", "Illinois"),
  state("US", "TX", "Texas"),
  state("CA", "ON", "Ontario"),
  state("CA", "QC", "Quebec"),
  state("MX", "NLE", "Nuevo León"),
];

describe("the country of an address in a form", () => {
  it("is the one chosen, or the United States where none is (P-321 (8))", () => {
    expect(countryShown("MX")).toBe("MX");
    expect(countryShown("")).toBe(US);
    expect(countryShown("  ")).toBe(US);
    expect(countryShown(undefined)).toBe(US);
  });

  it("offers every country in the order of the list, by name, sending its code", () => {
    expect(countryOptions(COUNTRIES, "")).toEqual([
      { value: "US", label: "United States" },
      { value: "AQ", label: "Antarctica" },
      { value: "CA", label: "Canada" },
      { value: "MX", label: "Mexico" },
    ]);
    expect(countryOptions(COUNTRIES, "MX")).toHaveLength(4);
  });

  it("offers a value held that no list holds first, as it was typed and marked so", () => {
    const options = countryOptions(COUNTRIES, "Untied States");
    expect(options?.[0]).toEqual({
      value: "Untied States",
      label: "Untied States (not in the list)",
    });
    expect(options).toHaveLength(5);
    expect(notListed(" usa ")).toBe("usa (not in the list)");
  });

  it("is a box of text while there is no list to offer", () => {
    expect(countryOptions([], "")).toBeUndefined();
    expect(countryOptions([], "US")).toBeUndefined();
  });

  it("names a country by its code, and a code the list does not hold by itself", () => {
    expect(countryName(COUNTRIES, "CA")).toBe("Canada");
    expect(countryName(COUNTRIES, "XQ")).toBe("XQ");
  });

  it("says beneath a country that no list holds that it is not in the list", () => {
    expect(unlistedCountryHint(COUNTRIES, "Untied States")).toBe(
      "Untied States is not in the list of countries: choose the country it is.",
    );
    expect(unlistedCountryHint(COUNTRIES, "CA")).toBeUndefined();
    expect(unlistedCountryHint(COUNTRIES, "")).toBeUndefined();
    expect(unlistedCountryHint([], "anything")).toBeUndefined();
  });
});

describe("the state of an address in a form", () => {
  it("is a list of the states of the country shown, by name, sending the code", () => {
    expect(stateOptions(STATES, "CA", "")).toEqual([
      { value: "ON", label: "Ontario" },
      { value: "QC", label: "Quebec" },
    ]);
    expect(stateOptions(STATES, US, "TX")).toEqual([
      { value: "IL", label: "Illinois" },
      { value: "TX", label: "Texas" },
    ]);
  });

  it("is a box of text where the country has no states listed", () => {
    expect(stateOptions(STATES, "AQ", "Ross Dependency")).toBeUndefined();
    expect(stateOptions(STATES, "Untied States", "Texas")).toBeUndefined();
  });

  it("offers a value held that is none of the country's states first, marked so", () => {
    const options = stateOptions(STATES, US, "Texsa");
    expect(options?.[0]).toEqual({ value: "Texsa", label: "Texsa (not in the list)" });
    expect(options).toHaveLength(3);
    expect(unlistedStateHint(COUNTRIES, STATES, US, "Texsa")).toBe(
      "Texsa is not in the list of the states of United States: choose the one it is.",
    );
    expect(unlistedStateHint(COUNTRIES, STATES, US, "TX")).toBeUndefined();
    expect(unlistedStateHint(COUNTRIES, STATES, "AQ", "anything")).toBeUndefined();
    expect(unlistedStateHint(COUNTRIES, STATES, US, "")).toBeUndefined();
  });

  it("follows the country: a state of the new one kept as its code, any other cleared", () => {
    // Found by its code or its name, without regard to case.
    expect(followingState(STATES, US, "CA", "Ontario")).toBe("ON");
    expect(followingState(STATES, "AQ", "CA", " ontario ")).toBe("ON");
    expect(followingState(STATES, US, "CA", "qc")).toBe("QC");
    // A state of one country is none of another's.
    expect(followingState(STATES, US, "CA", "TX")).toBe("");
    expect(followingState(STATES, US, "AQ", "TX")).toBe("");
    // Text typed for a country with no states listed stays for another with none.
    expect(followingState(STATES, "AQ", "Untied States", "Ross Dependency")).toBe(
      "Ross Dependency",
    );
    expect(followingState(STATES, US, "MX", "")).toBe("");
  });
});

describe("the lists", () => {
  it("count the states of each country, and give the states of one", () => {
    expect(Object.fromEntries(stateCounts(STATES))).toEqual({ US: 2, CA: 2, MX: 1 });
    expect(statesOf(STATES, "MX").map((one) => one.code)).toEqual(["NLE"]);
    expect(statesOf(STATES, "AQ")).toEqual([]);
  });

  it("name the field and the address that hold a value no list holds", () => {
    expect(unlistedFieldLabel("country")).toBe("Country");
    expect(unlistedFieldLabel("ship_state")).toBe("Shipping state or province");
    expect(unlistedSetLabel("street")).toBe("Street address");
    expect(unlistedSetLabel("shipping")).toBe("Shipping address");
  });
});
