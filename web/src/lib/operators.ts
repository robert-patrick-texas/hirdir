// The operator: the one person of the team who looks after an item or a device group.
// It is a contact. An item with none of its own has that of the item it is in, or of a
// group it is a member of, and a group with none has that of a group it is nested in.
// The server resolves it and says where it came from; this only says that in words, and
// builds the searches and the links that go with it.

import type { Schemas } from "../api/client";
import { all, any, type FilterNode, itemsPath } from "./filter";
import { groupTypeLabel } from "./groups";

export type OperatorInForce = Schemas["EffectiveReference"];
type ItemRef = Schemas["ItemRef"];

// The longest word of a search that is sent, and how many words are.
const LONGEST = 200;
const MOST_WORDS = 8;

/**
 * The filter that finds contacts by what was typed: each word has to be in the name or
 * in the email address. Blank text is no search.
 */
export function contactSearch(typed: string): FilterNode | null {
  const words = typed
    .split(/\s+/)
    .map((word) => word.slice(0, LONGEST))
    .filter((word) => word !== "")
    .slice(0, MOST_WORDS);
  return all(
    ...words.map((value) =>
      any({ field: "name", op: "contains", value }, { field: "email", op: "contains", value }),
    ),
  );
}

/** A contact as a search offers it: its name, and its email address beside it. */
export function contactLabel(contact: { name: string; email?: string | null }): string {
  return contact.email ? `${contact.name} (${contact.email})` : contact.name;
}

/** Where an operator in force came from, when it is not the record's own. */
export interface OperatorSource {
  /** The record that holds it, in words: "the stack site2-sw-stack1". */
  text: string;
  /** The page of that record, as a path of the app. */
  path: string;
}

/** What an item says of the records its operator may come from. */
interface ItemAbove {
  parent?: Pick<ItemRef, "hid" | "name" | "serial_number"> | null;
  groups?: ReadonlyArray<{ group_hid: string; name: string; type: string }>;
}

/**
 * The record an item has its operator from, in words and as a link: the item it is in,
 * or the group. The item names the item directly above it and the groups it is a member
 * of; an operator may also come from an item further up, from the group of the item a
 * minor item is in, or from a group that one of its groups is nested in, which is then
 * linked without its name. Null for an operator
 * of the item's own, and for none.
 */
export function itemOperatorSource(
  effective: Pick<OperatorInForce, "source" | "source_hid">,
  item: ItemAbove,
): OperatorSource | null {
  const { source, source_hid: hid } = effective;
  if (!hid) return null;
  if (source === "parent_item") {
    const parent = item.parent?.hid === hid ? item.parent : null;
    const name = parent?.name || parent?.serial_number || "";
    return {
      text: name ? `the item it is in, ${name}` : "an item above it",
      path: `/items/${encodeURIComponent(hid)}`,
    };
  }
  if (source === "device_group") {
    const group = item.groups?.find((one) => one.group_hid === hid);
    return {
      text: group
        ? `the ${groupTypeLabel(group.type).toLowerCase()} ${group.name}`
        : item.parent
          ? "the group of the item it is in"
          : "a group that its group is in",
      path: `/groups/${encodeURIComponent(hid)}`,
    };
  }
  return null;
}

/**
 * The same for a device group, whose operator may come from a group it is nested in:
 * the one directly above it, which the group names, or one further up.
 */
export function groupOperatorSource(
  effective: Pick<OperatorInForce, "source" | "source_hid">,
  group: { parent?: { hid: string; name: string; type: string } | null },
): OperatorSource | null {
  const { source, source_hid: hid } = effective;
  if (source !== "device_group" || !hid) return null;
  const parent = group.parent?.hid === hid ? group.parent : null;
  return {
    text: parent
      ? `the ${groupTypeLabel(parent.type).toLowerCase()} ${parent.name}, which it is in`
      : "a group above the one it is in",
    path: `/groups/${encodeURIComponent(hid)}`,
  };
}

/** What a cell of a grid says of an operator in force that came from above. Blank for an own one. */
export function operatorHint(
  effective: Pick<OperatorInForce, "source" | "source_hid" | "value">,
  item: ItemAbove,
): string {
  if (effective.value === null) return "";
  const from = itemOperatorSource(effective, item);
  return from ? `Inherited from ${from.text}` : "";
}

/** The filter that finds what nobody is assigned to: no operator in force. */
export const UNASSIGNED = "effective.operator_hid:empty:true";

/**
 * The grid of the items that nobody is assigned to, major items as the grid shows them:
 * the components among them are what the first page counts.
 */
export function unassignedPath(): string {
  return `/items?filter=${encodeURIComponent(UNASSIGNED)}`;
}

/** The grid of the items a contact is the operator in force of, minor items among them. */
export function operatedItemsPath(contactHid: string): string {
  return itemsPath(`effective.operator_hid:eq:${contactHid}`);
}

/** The grid of the groups a contact is the operator of, by the group's own word. */
export function operatedGroupsPath(contactHid: string): string {
  return `/groups?filter=${encodeURIComponent(`operator_hid:eq:${contactHid}`)}`;
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
