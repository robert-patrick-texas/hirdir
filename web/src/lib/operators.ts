// The operator: a short label of the site's choosing, with a colour, that stands for the
// member of the team who is assigned behind it. Items, device groups and places are given
// the label, never the person. A label with nobody behind it is an open assignment; one
// that is retired is released, and stands for nothing. An item with no operator of its
// own has that of the item it is in, of a group, or of the place it is at.
//
// The server resolves all of it and says where each came from. This only says that in
// words, and builds the searches and the links that go with it.

import type { Schemas } from "../api/client";
import { all, any, type FilterNode, itemsPath } from "./filter";
import { isLevel, placePath } from "./places";

export type Operator = Schemas["OperatorOut"];
export type OperatorRef = Schemas["OperatorRef"];
export type OperatorInForce = Schemas["EffectiveOperator"];

// The longest word of a search that is sent, and how many words are.
const LONGEST = 200;
const MOST_WORDS = 8;

function words(typed: string): string[] {
  return typed
    .split(/\s+/)
    .map((word) => word.slice(0, LONGEST))
    .filter((word) => word !== "")
    .slice(0, MOST_WORDS);
}

/**
 * The filter that finds contacts by what was typed: each word has to be in the name or
 * in the email address. Blank text is no search.
 */
export function contactSearch(typed: string): FilterNode | null {
  return all(
    ...words(typed).map((value) =>
      any({ field: "name", op: "contains", value }, { field: "email", op: "contains", value }),
    ),
  );
}

/** A contact as a search offers it: its name, and its email address beside it. */
export function contactLabel(contact: { name: string; email?: string | null }): string {
  return contact.email ? `${contact.name} (${contact.email})` : contact.name;
}

/**
 * The filter that finds operators by what was typed: each word has to be in the label or
 * in the name of the person behind it, so that an operator is found by either.
 */
export function operatorSearch(typed: string): FilterNode | null {
  return all(
    ...words(typed).map((value) =>
      any(
        { field: "label", op: "contains", value },
        { field: "contact.name", op: "contains", value },
      ),
    ),
  );
}

/** What a page needs of an operator to show its mark. */
export interface Mark {
  hid: string;
  label: string;
  /** The colour of the label, as `#rrggbb`, or null when it has none that can be used. */
  colour: string | null;
  /** The name of the person behind the label, or blank. */
  person: string;
  /** Nobody is behind it: an open assignment. */
  open: boolean;
  /** The label is retired: it is released, and stands for nothing. */
  released: boolean;
}

/** An operator as the server names it: on a record, in force, or as its own record. */
type Named = {
  label: string | null;
  colour: string | null;
  is_open: boolean;
  contact: string | { name: string } | null;
  record_status?: string;
} & ({ hid: string } | { value: string | null });

/** A colour as the server stores it, and nothing else: it is put on the page as a style. */
export function safeColour(colour: string | null | undefined): string | null {
  return colour && /^#[0-9a-f]{6}$/i.test(colour) ? colour : null;
}

/**
 * The mark of an operator, from any of the shapes the server names one in. Null when
 * there is none: an operator in force with no value.
 */
export function markOf(operator: Named | null | undefined): Mark | null {
  if (!operator) return null;
  const hid = "hid" in operator ? operator.hid : operator.value;
  if (!hid) return null;
  const { contact } = operator;
  return {
    hid,
    label: operator.label || hid,
    colour: safeColour(operator.colour),
    person: typeof contact === "string" ? contact : (contact?.name ?? ""),
    open: operator.is_open,
    released: operator.record_status === "retired",
  };
}

/** What a mark says when it is pointed at: who is behind the label, or that nobody is. */
export function markTitle(mark: Pick<Mark, "person" | "open" | "released">): string {
  if (mark.released) return "Released: this label is retired, and stands for nothing";
  if (mark.open) {
    return mark.person
      ? `Open: ${mark.person}, who was behind this label, is retired`
      : "Open: nobody is behind this label";
  }
  return mark.person;
}

/** An operator as a search offers it: the label, then the person behind it, or that it is open. */
export function operatorOptionLabel(operator: Named): string {
  const mark = markOf(operator);
  if (!mark) return "";
  return `${mark.label} · ${mark.open || !mark.person ? "open" : mark.person}`;
}

/** The page of one operator, as a path of the app. */
export function operatorPath(hid: string): string {
  return `/operators/${encodeURIComponent(hid)}`;
}

/** Where an operator in force came from, when it is not the record's own. */
export interface OperatorSource {
  /** The record that holds it, in words: "the group site2-sw-stack1", "the site Americas > Central > Site-2". */
  text: string;
  /** The page of that record, as a path of the app. */
  path: string;
}

const SOURCE_WORDS: Readonly<Record<string, string>> = {
  parent_item: "the item",
  device_group: "the group",
  location: "the location",
  site: "the site",
  region: "the region",
};

/**
 * The record an operator in force came from, in words and as a link: the item above, a
 * group, or a place, by the name or the path the server sends with it. Null for an
 * operator of the record's own, and for none.
 */
export function operatorSource(
  effective: Pick<OperatorInForce, "source" | "source_hid" | "source_label">,
): OperatorSource | null {
  const { source, source_hid: hid, source_label: label } = effective;
  const what = SOURCE_WORDS[source];
  if (!hid || what === undefined) return null;
  const path =
    source === "parent_item"
      ? `/items/${encodeURIComponent(hid)}`
      : source === "device_group"
        ? `/groups/${encodeURIComponent(hid)}`
        : isLevel(source)
          ? placePath(source, hid)
          : null;
  if (path === null) return null;
  return { text: label ? `${what} ${label}` : what, path };
}

/**
 * What a cell of a grid says of an operator in force beyond its label: the person behind
 * it, or that it is open, and where it came from when it is inherited. Blank for none.
 */
export function operatorHint(effective: OperatorInForce): string {
  const mark = markOf(effective);
  if (!mark) return "";
  const from = operatorSource(effective);
  return [markTitle(mark), from ? `Inherited from ${from.text}` : ""].filter(Boolean).join(" · ");
}

/** The filter that finds what nobody is assigned to: no operator in force. */
export const UNASSIGNED = "effective.operator_hid:empty:true";
/** The filter that finds what is assigned to a label with nobody behind it. */
export const OPEN = "operator.is_open:eq:true";

/**
 * The grid of the items a filter of this kind keeps, major items as the grid shows them:
 * the components among them are what the first page counts.
 */
export function assignmentPath(filter: typeof UNASSIGNED | typeof OPEN): string {
  return `/items?filter=${encodeURIComponent(filter)}`;
}

/** The grid of the items an operator is in force for, minor items among them. */
export function operatedItemsPath(operatorHid: string): string {
  return itemsPath(`effective.operator_hid:eq:${operatorHid}`);
}

/** The grid of the groups that are given an operator as their own. */
export function operatedGroupsPath(operatorHid: string): string {
  return `/groups?filter=${encodeURIComponent(`operator_hid:eq:${operatorHid}`)}`;
}

/**
 * How many components nobody is assigned to, from a summary by operator: the components
 * of the blank row. None when the summary has no such row.
 */
export function unassignedComponents(
  rows: ReadonlyArray<{ key: string | null; component_count: number }> | null | undefined,
): number {
  return rows?.find((row) => row.key === null)?.component_count ?? 0;
}
