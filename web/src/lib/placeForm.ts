// The fields of the forms of a place, a region, a site or a location: new and edit. They
// were in components/PlaceParts.tsx until 0.9.18, which moved them here, beside nothing
// that reads the page or the server, to be tested as they are built (review of the web,
// findings 2 and 9).

import {
  type Country,
  countryOptions,
  countryShown,
  followingState,
  type State,
  stateOptions,
  US,
  unlistedCountryHint,
  unlistedStateHint,
} from "./countries";
import { operatorOptionLabel } from "./operators";
import { SETTABLE_STATUSES } from "./options";
import type { FieldSpec, Option } from "./patch";
import type { Level, Place } from "./places";
// 0.8.0: the support weight of a place (P-139, P-155).
import { siteWeightHint } from "./weights";

/**
 * The fields of an address in a form, in their order. 0.9.18: the country before the
 * state, whose list it gives, so that a state is not chosen from one list and cleared by
 * the country after it (review of the web, finding 9). An address as it is shown keeps
 * its own order, the country last (`addressLines`).
 */
const STREET: ReadonlyArray<[field: string, label: string]> = [
  ["address1", "Address line 1"],
  ["address2", "Address line 2"],
  ["city", "City"],
  ["country", "Country"],
  ["state", "State or province"],
  ["postal_code", "Postal code"],
];

/** A value a record holds, as a form holds it: text, blank for none. */
function heldText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** What the forms of a place offer: the kinds of a location, the tags, and the lists of an address. */
export interface PlaceLists {
  kinds: readonly Option[];
  tags: readonly string[];
  /** 0.9.18: the countries, the United States first, and the states of every country (P-321). */
  countries: readonly Country[];
  states: readonly State[];
}

/**
 * 0.9.18: what the country and the state of one address, of the fields that begin with
 * `prefix`, are in a form (P-321 (8)). The country is a list of the countries by name,
 * sending the code, a blank shown as the United States and sent only beside another
 * field of the address; the state a list of the states of the country the form shows,
 * or a box of text where it has none, following the country as it is changed. A value
 * held that no list holds is offered as it was typed, marked so, with a word beneath.
 * The other fields are as any field of text.
 *
 * A country changed back to the one the record holds, as it is in force, a blank being
 * the United States, brings back the state the record holds with it, listed or not, so
 * that a country changed and changed back loses nothing and sends nothing of the state
 * (review of the web, finding 2). `held` is the record; null for a new place.
 */
function addressPart(
  field: string,
  prefix: string,
  lists: PlaceLists,
  held: Readonly<Record<string, unknown>> | null,
): Partial<FieldSpec> {
  const country = `${prefix}country`;
  const state = `${prefix}state`;
  if (field === "country") {
    return {
      optionsFrom: (values) => countryOptions(lists.countries, values[country]),
      blankAs: {
        value: US,
        with: STREET.map(([name]) => `${prefix}${name}`).filter((name) => name !== country),
      },
      fills: (value, before) => {
        const to = countryShown(value);
        if (held !== null && to === countryShown(heldText(held[country]))) {
          return { [state]: heldText(held[state]) };
        }
        return {
          [state]: followingState(lists.states, countryShown(before[country]), to, before[state]),
        };
      },
      hintFrom: (values) => unlistedCountryHint(lists.countries, values[country]),
    };
  }
  if (field === "state") {
    return {
      blank: "None",
      optionsFrom: (values) =>
        stateOptions(lists.states, countryShown(values[country]), values[state]),
      hintFrom: (values) =>
        unlistedStateHint(
          lists.countries,
          lists.states,
          countryShown(values[country]),
          values[state],
        ),
    };
  }
  return {};
}

/**
 * The fields of a place that a form sets. A region has the shipping set and no street
 * address; a location also has a kind. What a place is in is not among them: a place is
 * moved by the form of its own under Move.
 */
export function placeSpecs(
  level: Level,
  lists: PlaceLists,
  current: Place | null = null,
): FieldSpec[] {
  const shipFrom =
    level === "region" ? "the nearest region above that has one" : "the nearest place above it";
  // Deliveries go to the street address: then no shipping address is asked for, and one
  // the record holds is cleared with the tick, in the same change.
  const typed = (values: Readonly<Record<string, unknown>>) => values.ship_same_as_address !== true;
  const street: FieldSpec[] =
    level === "region"
      ? []
      : [
          ...STREET.map(
            ([name, label], place): FieldSpec => ({
              name,
              label,
              kind: "text",
              maxLength: 200,
              ...addressPart(name, "", lists, current),
              ...(place === 0
                ? {
                    heading: "Street address",
                    hint: "Where the place is. It is never taken for a shipping address.",
                  }
                : {}),
            }),
          ),
          {
            name: "latitude",
            label: "Latitude",
            kind: "text",
            maxLength: 10,
            hint: "Decimal degrees, as 41.878100. Given with the longitude or not at all.",
          },
          {
            name: "longitude",
            label: "Longitude",
            kind: "text",
            maxLength: 11,
            hint: "Decimal degrees, as -87.629800",
          },
        ];
  return [
    { name: "name", label: "Name", kind: "text", required: true, maxLength: 200 },
    {
      name: "code",
      label: "Code",
      kind: "text",
      maxLength: 40,
      hint: "A short name such as CEN or S2. Optional, and unique when given.",
    },
    ...(level === "location"
      ? [
          {
            name: "kind",
            label: "Kind",
            kind: "choice",
            blank: "Not said",
            options: lists.kinds,
          } satisfies FieldSpec,
        ]
      : []),
    {
      name: "record_status",
      label: "Record status",
      kind: "choice",
      options: SETTABLE_STATUSES,
      hint: "A draft is left out of default views",
    },
    { name: "notes", label: "Notes", kind: "longtext", maxLength: 10000 },
    {
      name: "tags",
      label: "Tags",
      kind: "set",
      options: [...new Set([...lists.tags, ...(current?.tags ?? [])])].map((label) => ({
        value: label,
        label,
      })),
      hint: "A tag is made under Admin, then used here",
    },
    // 0.8.0: the support weight of a place, its own, not passed down (P-139, P-155).
    {
      name: "support_weight",
      label: "Support weight",
      kind: "decimal",
      places: 2,
      hint: [
        "The work supporting the network here adds by itself, beside what its devices weigh: distance, a language the team does not speak, a campus spread across a city, a restricted site. The places beneath do not take it.",
        current && "effective" in current
          ? siteWeightHint(current.support_weight, current.effective.support_weight)
          : level === "site"
            ? siteWeightHint(null, null)
            : "",
      ]
        .filter(Boolean)
        .join(" "),
    },
    // End of 0.8.0.
    {
      name: "operator_hid",
      label: "Operator",
      kind: "operator",
      blank: "None of its own",
      options: current?.operator
        ? [{ value: current.operator.hid, label: operatorOptionLabel(current.operator) }]
        : [],
      hint: `The label of who of the team looks after what is at this ${level}. An item or a group here has it when it has none of its own, of the item it is in or of its group, so that a new device is never nobody's.`,
    },
    ...street,
    ...(level === "region"
      ? []
      : [
          {
            name: "ship_same_as_address",
            label: "Deliveries go to the street address",
            kind: "boolean",
            heading: "Shipping address",
            hint: "Ticked, the shipping address is the street address above, for this place and every place beneath it: nothing is typed a second time. It needs a street address.",
          } satisfies FieldSpec,
        ]),
    ...STREET.map(
      ([name, label], place): FieldSpec => ({
        name: `ship_${name}`,
        label: `Shipping ${label.toLowerCase()}`,
        kind: "text",
        maxLength: 200,
        ...addressPart(name, "ship_", lists, current),
        ...(level === "region" ? {} : { when: typed, clearedWhenNotAsked: true }),
        ...(place === 0
          ? {
              ...(level === "region" ? { heading: "Shipping address" } : {}),
              hint: `Where deliveries go. Left blank in all six fields, the address is that of ${shipFrom}, taken whole.`,
            }
          : {}),
      }),
    ),
    {
      name: "ship_instructions",
      label: "Shipping instructions",
      kind: "longtext",
      maxLength: 10000,
      hint: "Left blank, the instructions of the nearest place above that has any",
    },
  ];
}
