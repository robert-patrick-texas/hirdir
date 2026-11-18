// 0.9.6: working a stack (P-220, P-222). A stack is known by its name, and its members,
// which have no name of their own, by the stack they are in and their position in it.

import { any, type FilterNode, isCondition } from "./filter";

// The most device groups the line above the items names.
export const MOST_NAMED = 3;

/**
 * The words a filter of the item list looks for in the names of the groups: the values
 * of its conditions `group.name` `contains` or `eq`, as the plain words of the list send
 * them, each once, in the order they stand.
 */
export function groupWords(filter: FilterNode | null | undefined): string[] {
  const found: string[] = [];
  const walk = (node: FilterNode) => {
    if (isCondition(node)) {
      if (
        node.field === "group.name" &&
        (node.op === "contains" || node.op === "eq") &&
        typeof node.value === "string" &&
        node.value.trim() !== "" &&
        !found.includes(node.value.trim())
      ) {
        found.push(node.value.trim());
      }
      return;
    }
    for (const part of "and" in node ? node.and : node.or) walk(part);
  };
  if (filter) walk(filter);
  return found;
}

/** Whether two lists of words are the same words in the same order. */
export function sameWords(one: readonly string[], other: readonly string[]): boolean {
  return one.length === other.length && one.every((word, index) => word === other[index]);
}

/** The device groups those words name: a group whose name or host name is one of them. */
export function namedBy(words: readonly string[]): FilterNode | null {
  return any(
    ...words.flatMap((value) => [
      { field: "name", op: "eq" as const, value },
      { field: "hostname", op: "eq" as const, value },
    ]),
  );
}

/** A group a member is in, as an item names it. */
export interface Membership {
  group_hid: string;
  name: string;
  type: string;
  position: number | null;
}

/** The stack an item is a current member of: one at most. */
export function stackOf<T extends { type: string }>(groups: readonly T[]): T | undefined {
  return groups.find((group) => group.type === "stack");
}

/** A member as the item list names it: its stack and its position, "cw07-idf03-acc1 #2". */
export function memberText(groups: readonly Membership[]): string {
  const stack = stackOf(groups);
  if (!stack) return "";
  return stack.position === null ? stack.name : `${stack.name} #${stack.position}`;
}
