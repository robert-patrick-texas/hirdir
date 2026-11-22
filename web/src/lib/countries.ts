// 0.9.18: the lists of countries and states that an address takes its country and its
// state from (P-318, P-321), as the forms of a place offer them and Admin › Choices
// lists them.
//
// The server keeps both lists, the United States first in the list of countries and the
// states of a country by name, finds a country or a state by its code or its name, and
// keeps the code. Nothing of that is worked out again here: this lays the lists out as
// options, each shown by its name and sending its code, follows the country chosen in a
// form with the states it has, and marks a value held from before that no list holds.

import type { Schemas } from "../api/client";
import type { FormValue, Option } from "./patch";

export type Country = Schemas["CountryOut"];
export type State = Schemas["StateOut"];
export type UnlistedAddress = Schemas["UnlistedAddress"];

/** The United States: first in the list, and the country of an address that names none. */
export const US = "US";

/** What a form field holds, as text. */
function textOf(value: FormValue | undefined): string {
  return typeof value === "string" ? value : "";
}

/** A name or a code as the server compares them: without regard to case or spaces. */
function keyOf(text: string): string {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

/** A value held that no list holds, as it is offered: as it was typed, and marked so. */
export function notListed(value: string): string {
  return `${value.trim()} (not in the list)`;
}

/**
 * The country of an address as a form shows it: the one chosen, or the United States
 * where none is, which a blank country is read as (P-321 (4), (8)).
 */
export function countryShown(value: FormValue | undefined): string {
  const chosen = textOf(value).trim();
  return chosen === "" ? US : chosen;
}

/** The name of a country by its code, or the code itself where the list has none. */
export function countryName(countries: readonly Country[], code: string): string {
  return countries.find((country) => country.code === code)?.name ?? code;
}

/**
 * The countries a form offers, in the order of the list, each shown by its name and
 * sending its code; first, where the form holds a value that no list holds, that value
 * as it was typed and marked so, chosen until another is. Undefined while there is no
 * list to offer, when the field is a box of text.
 */
export function countryOptions(
  countries: readonly Country[],
  held: FormValue | undefined,
): Option[] | undefined {
  if (countries.length === 0) return undefined;
  const options: Option[] = countries.map((country) => ({
    value: country.code,
    label: country.name,
  }));
  const value = textOf(held);
  if (value.trim() !== "" && !countries.some((country) => country.code === value)) {
    options.unshift({ value, label: notListed(value) });
  }
  return options;
}

/** The states of one country, by its code, in the order of the list: by name. */
export function statesOf(states: readonly State[], country: string): State[] {
  return states.filter((state) => state.country === country);
}

/** How many states each country has, by its code. */
export function stateCounts(states: readonly State[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const state of states) counts.set(state.country, (counts.get(state.country) ?? 0) + 1);
  return counts;
}

/**
 * The states a form offers for the country it shows, each by its name and sending its
 * code, with the value held first where it is none of them, as typed and marked so.
 * Undefined where the country has no states listed: the state is then text as typed.
 */
export function stateOptions(
  states: readonly State[],
  country: string,
  held: FormValue | undefined,
): Option[] | undefined {
  const own = statesOf(states, country);
  if (own.length === 0) return undefined;
  const options: Option[] = own.map((state) => ({ value: state.code, label: state.name }));
  const value = textOf(held);
  if (value.trim() !== "" && !own.some((state) => state.code === value)) {
    options.unshift({ value, label: notListed(value) });
  }
  return options;
}

/**
 * The state a form holds once its country is changed from `from` to `to`: a state of
 * the new country, found by its code or its name, is kept as its code; text typed for
 * a country with no states listed stays for another with none; anything else is
 * cleared, to be chosen again, since a state of one country is none of another's.
 */
export function followingState(
  states: readonly State[],
  from: string,
  to: string,
  state: FormValue | undefined,
): string {
  const value = textOf(state);
  const key = keyOf(value);
  if (key === "") return "";
  const own = statesOf(states, to);
  if (own.length === 0) return statesOf(states, from).length === 0 ? value : "";
  const found =
    own.find((one) => one.code.toLowerCase() === key) ?? own.find((one) => keyOf(one.name) === key);
  return found?.code ?? "";
}

/**
 * What is said beneath a country that no list holds: that it is not in the list, and
 * where to choose one. Undefined where the form holds none such.
 */
export function unlistedCountryHint(
  countries: readonly Country[],
  held: FormValue | undefined,
): string | undefined {
  const value = textOf(held).trim();
  if (value === "" || countries.length === 0) return undefined;
  if (countries.some((country) => country.code === value)) return undefined;
  return `${value} is not in the list of countries: choose the country it is.`;
}

/**
 * What is said beneath a state that is none of the states listed for the country the
 * form shows. Undefined where it is one, or blank, or the country has none listed.
 */
export function unlistedStateHint(
  countries: readonly Country[],
  states: readonly State[],
  country: string,
  held: FormValue | undefined,
): string | undefined {
  const value = textOf(held).trim();
  const own = statesOf(states, country);
  if (value === "" || own.length === 0 || own.some((state) => state.code === value)) {
    return undefined;
  }
  return `${value} is not in the list of the states of ${countryName(countries, country)}: choose the one it is.`;
}

/** The field of an address that holds a value no list holds, as a person calls it. */
const FIELD_WORDS: Readonly<Record<UnlistedAddress["field"], string>> = {
  country: "Country",
  state: "State or province",
  ship_country: "Shipping country",
  ship_state: "Shipping state or province",
};

export function unlistedFieldLabel(field: UnlistedAddress["field"]): string {
  return FIELD_WORDS[field];
}

/** Which address of a place holds it, as a person calls it. */
export function unlistedSetLabel(set: UnlistedAddress["set"]): string {
  return set === "street" ? "Street address" : "Shipping address";
}
