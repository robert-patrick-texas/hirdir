// Condition, observation and health, as words. Three facts are kept apart: the condition
// is the state of the hardware as a person knows it, the observed status is what is
// seen, and the intent is what is meant. Health is what the server works out from the
// three each time a record is read, with its reasons. Nothing is worked out here.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type Health = Schemas["HealthOut"];
export type HealthValue = Health["value"];
export type HealthCount = Schemas["HealthCount"];
export type Observed = NonNullable<Schemas["ItemOut"]["observed_status"]>;

/** The list of choices an item's condition is taken from. */
export const CONDITION_LIST = "item_condition";

/** The four healths, from the best to the least known. Each has a colour on a page, and its word. */
export const HEALTHS: ReadonlyArray<Option & { value: HealthValue }> = [
  { value: "good", label: "Good" },
  { value: "degraded", label: "Degraded" },
  { value: "failed", label: "Failed" },
  { value: "unknown", label: "Unknown" },
];

/**
 * What may be seen of an item or a group. The first three are seen on the network.
 * `present` is what a person saw of something that is never on the network.
 */
export const OBSERVED: ReadonlyArray<Option & { value: Observed }> = [
  { value: "online", label: "Online" },
  { value: "degraded", label: "Degraded" },
  { value: "unreachable", label: "Unreachable" },
  { value: "present", label: "Present" },
];

/** The same, as a form offers them: `present` says who saw it. */
export const OBSERVED_CHOICES: readonly Option[] = OBSERVED.map((option) =>
  option.value === "present"
    ? { value: option.value, label: "Present: a person saw it, in place and in order" }
    : { value: option.value, label: `${option.label}: seen on the network` },
);

export function isHealth(value: unknown): value is HealthValue {
  return HEALTHS.some((health) => health.value === value);
}

export function isObserved(value: unknown): value is Observed {
  return OBSERVED.some((observed) => observed.value === value);
}

/** A health for people. One this build does not know is shown as sent. */
export function healthLabel(value: string | null | undefined): string {
  if (!value) return "";
  return HEALTHS.find((health) => health.value === value)?.label ?? value;
}

/** What is seen, for people. */
export function observedLabel(value: string | null | undefined): string {
  if (!value) return "";
  return OBSERVED.find((observed) => observed.value === value)?.label ?? value;
}

/**
 * The name of the colour a health is shown in: green, amber, red or grey, as a class of
 * the stylesheet. A health this build does not know is grey.
 */
export function healthTone(value: string | null | undefined): HealthValue {
  return isHealth(value) ? value : "unknown";
}

/** The reasons of a health as one line, for a hint: "its condition is suspect; it is observed degraded". */
export function reasonsText(health: Pick<Health, "reasons"> | null | undefined): string {
  return (health?.reasons ?? []).join("; ");
}

/** A health with its reasons, as one line: "Degraded: its condition is suspect". */
export function healthHint(health: Health | null | undefined): string {
  if (!health) return "";
  const why = reasonsText(health);
  return why ? `${healthLabel(health.value)}: ${why}` : healthLabel(health.value);
}

/** The fields of an observation, as a change of an item or of a group sends them. */
export interface ObservationPatch {
  observed_status: Observed | null;
  observed_at?: string;
}

/**
 * What a change of the observation sends.
 *
 * Setting a status leaves the moment to the server, which takes the present one. "Seen
 * now" states again what is already seen and names the moment itself, so that the
 * moment is the present one whatever the server makes of a status stated as it is.
 * Clearing the status clears the moment with it.
 */
export function observationPatch(
  what: "set" | "again" | "clear",
  status: string | null | undefined,
  now: Date = new Date(),
): ObservationPatch | null {
  if (what === "clear") return { observed_status: null };
  if (!isObserved(status)) return null;
  if (what === "again") return { observed_status: status, observed_at: now.toISOString() };
  return { observed_status: status };
}

/**
 * What to call the moment of an observation. For `present` it is when a person last
 * checked; for the rest, when it was seen.
 */
export function observedWhen(status: string | null | undefined): string {
  return status === "present" ? "last checked" : "seen";
}

/** The counts of a summary by health, in the order of the four healths. */
export function healthCounts(
  counts: HealthCount,
): Array<{ value: HealthValue; label: string; count: number }> {
  return HEALTHS.map((health) => ({ ...health, count: counts[health.value] }));
}
