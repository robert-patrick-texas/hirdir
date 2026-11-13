// What to offer for an item's lifecycle. The rules are data on the server, read from
// `GET /lifecycle-rules`; this only reads them, to offer what they allow. The server
// checks every move and every combination again, and its refusal is what counts.

import type { Schemas } from "../api/client";

export type Rule = Schemas["LifecycleRuleOut"];

/** The four dispositions. They are fixed, as the nine states are. */
export const DISPOSITIONS = ["Staging", "Production", "Spare", "Excess"] as const;

export function ruleOf(rules: readonly Rule[], state: string | null | undefined): Rule | null {
  return rules.find((rule) => rule.state === state) ?? null;
}

/** Every state, in the order of the lifecycle. */
export function stateNames(rules: readonly Rule[]): string[] {
  return [...rules].sort((one, other) => one.sort - other.sort).map((rule) => rule.state);
}

/**
 * The states an item may be moved to.
 *
 * An item with no state yet may be given any. Otherwise the rule of its state says where
 * it may go, and a forced move, which only an Admin may make, may go to any other state.
 */
export function nextStates(
  rules: readonly Rule[],
  current: string | null | undefined,
  forced = false,
): string[] {
  const every = stateNames(rules);
  if (!current) return every;
  if (forced) return every.filter((state) => state !== current);
  const allowed = ruleOf(rules, current)?.next_states ?? [];
  return every.filter((state) => allowed.includes(state));
}

/**
 * The dispositions an item may have in a state: the state's own, and the one the item
 * came with when the state keeps it. An item that came with none into a state that keeps
 * the disposition, because it was first entered there, may be given any.
 */
export function dispositionsIn(
  rules: readonly Rule[],
  state: string | null | undefined,
  kept: string | null | undefined,
): string[] {
  const rule = ruleOf(rules, state);
  if (!rule) return [];
  if (rule.keeps_disposition && !kept) return [...DISPOSITIONS];
  const allowed = [...rule.dispositions];
  if (rule.keeps_disposition && kept && !allowed.includes(kept)) allowed.push(kept);
  return DISPOSITIONS.filter((name) => allowed.includes(name));
}

/** True when an item in the state may be expected online at all. */
export function mayBeOnline(rules: readonly Rule[], state: string | null | undefined): boolean {
  return (ruleOf(rules, state)?.may_be_online.length ?? 0) > 0;
}

/** An item's intent as words. */
export function onlineText(expected: boolean | null | undefined): string {
  if (expected === true) return "Expected online";
  if (expected === false) return "Expected offline";
  return "";
}
