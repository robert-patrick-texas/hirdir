// The coverage report and the end-of-life report, as words. The server counts, and for
// each count it gives the filter that lists the same items on the item list: a count
// leads to its rows, to the grid and to an export of them.

import type { Schemas } from "../api/client";
import type { Option } from "./patch";

export type CoverageReport = Schemas["CoverageReport"];
export type EndOfLifeReport = Schemas["EndOfLifeReport"];
export type ReportSection = Schemas["ReportSection"];

export type CoverageSection = NonNullable<CoverageReport["section"]>;
export type EndOfLifeSection = NonNullable<EndOfLifeReport["section"]>;
export type EndOfLifeDate = EndOfLifeReport["date"];

/** The three lists of the coverage report. */
export const COVERAGE_SECTIONS: ReadonlyArray<{
  value: CoverageSection;
  label: string;
  about: string;
}> = [
  {
    value: "uncovered",
    label: "In service with no cover",
    about: "Major items in service that no contract covers today.",
  },
  {
    value: "expiring",
    label: "Cover that runs out soon",
    about: "Items in service whose cover runs out within the days asked for, the soonest first.",
  },
  {
    value: "out_of_service",
    label: "Cover on items out of service",
    about:
      "Items that a contract covers today though they are retired, or in Pending-Removal, Released or Archived: cover that is paid for and no longer needed.",
  },
];

export function isCoverageSection(value: string | null): value is CoverageSection {
  return COVERAGE_SECTIONS.some((section) => section.value === value);
}

/** The four end-of-life dates, the last day of support first: it is what the report is of unless asked. */
export const END_OF_LIFE_DATES: ReadonlyArray<Option & { value: EndOfLifeDate }> = [
  { value: "ldos", label: "Last day of support (LDoS)" },
  { value: "end_of_sale", label: "End of sale" },
  { value: "end_of_sw_support", label: "End of software support" },
  { value: "end_of_hw_support", label: "End of hardware support" },
];

export function isEndOfLifeDate(value: string | null): value is EndOfLifeDate {
  return END_OF_LIFE_DATES.some((date) => date.value === value);
}

export function endOfLifeDateLabel(date: string): string {
  return END_OF_LIFE_DATES.find((known) => known.value === date)?.label ?? date;
}

export const END_OF_LIFE_SECTIONS: ReadonlyArray<{
  value: EndOfLifeSection;
  label: string;
}> = [
  { value: "past", label: "Past" },
  { value: "approaching", label: "Approaching" },
];

export function isEndOfLifeSection(value: string | null): value is EndOfLifeSection {
  return END_OF_LIFE_SECTIONS.some((section) => section.value === value);
}

/**
 * A number of days from what was typed, for `within_days`: a whole number of at least
 * one, or null for what is none, and the report then has its own.
 */
export function daysOf(text: string | null): number | null {
  const typed = (text ?? "").trim();
  if (!/^\d{1,5}$/.test(typed)) return null;
  const days = Number.parseInt(typed, 10);
  return days >= 1 ? days : null;
}

/** Whether a fiscal year has ended, begun, or is the one today is in. */
export function fiscalYearStanding(
  year: { starts_on: string; ends_on: string },
  today: string,
): "past" | "current" | "ahead" {
  if (year.ends_on < today) return "past";
  return year.starts_on > today ? "ahead" : "current";
}
