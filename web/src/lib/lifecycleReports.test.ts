import { describe, expect, it } from "vitest";
import {
  COVERAGE_SECTIONS,
  daysOf,
  END_OF_LIFE_DATES,
  END_OF_LIFE_SECTIONS,
  endOfLifeDateLabel,
  fiscalYearStanding,
  isCoverageSection,
  isEndOfLifeDate,
  isEndOfLifeSection,
  notRenewedModelLabel,
} from "./lifecycleReports";

describe("the lists of the coverage report", () => {
  it("are the six the server answers, the gaps first", () => {
    expect(COVERAGE_SECTIONS.map((section) => section.value)).toEqual([
      "uncovered",
      "expiring",
      "out_of_service",
      "renewal_pending",
      "overlapping",
      "not_renewed",
    ]);
    for (const section of COVERAGE_SECTIONS) expect(section.about).not.toBe("");
  });

  it("say of what is not to be renewed that it is no gap", () => {
    const left = COVERAGE_SECTIONS.find((section) => section.value === "not_renewed");
    expect(left?.about).toContain("no gap");
    expect(isCoverageSection("not_renewed")).toBe(true);
  });

  it("name a model of the items not to be renewed by its vendor and PID, or say it has none", () => {
    const row = {
      catalog_entry_hid: "e-1",
      vendor_hid: "v-1",
      vendor: "Example Voice",
      pid: "EV-PHONE-10",
      model_name: "Example desk phone",
      count: 6,
      filter: null,
    };
    expect(notRenewedModelLabel(row)).toBe("Example Voice EV-PHONE-10");
    expect(
      notRenewedModelLabel({
        ...row,
        catalog_entry_hid: null,
        vendor_hid: null,
        vendor: null,
        pid: null,
        model_name: null,
      }),
    ).toBe("No model");
  });

  it("say of the items under more than one contract that they are no fault", () => {
    const overlapping = COVERAGE_SECTIONS.find((section) => section.value === "overlapping");
    expect(overlapping?.about).toContain("not a fault");
    const pending = COVERAGE_SECTIONS.find((section) => section.value === "renewal_pending");
    expect(pending?.about).toContain("account manager");
  });

  it("are known by their names, and nothing else is", () => {
    expect(isCoverageSection("overlapping")).toBe(true);
    expect(isCoverageSection("renewal_pending")).toBe(true);
    expect(isCoverageSection("expiring")).toBe(true);
    expect(isCoverageSection("covered")).toBe(false);
    expect(isCoverageSection(null)).toBe(false);
  });
});

describe("the dates of the end-of-life report", () => {
  it("are the four of a model, the last day of support first", () => {
    expect(END_OF_LIFE_DATES.map((date) => date.value)).toEqual([
      "ldos",
      "end_of_sale",
      "end_of_sw_support",
      "end_of_hw_support",
    ]);
    expect(isEndOfLifeDate("end_of_sale")).toBe(true);
    expect(isEndOfLifeDate("warranty_end")).toBe(false);
    expect(endOfLifeDateLabel("ldos")).toBe("Last day of support (LDoS)");
    expect(endOfLifeDateLabel("another")).toBe("another");
  });

  it("has the two lists, past and approaching", () => {
    expect(END_OF_LIFE_SECTIONS.map((section) => section.value)).toEqual(["past", "approaching"]);
    expect(isEndOfLifeSection("past")).toBe(true);
    expect(isEndOfLifeSection("uncovered")).toBe(false);
  });
});

describe("daysOf", () => {
  it("reads a whole number of days, at least one", () => {
    expect(daysOf("90")).toBe(90);
    expect(daysOf(" 730 ")).toBe(730);
    expect(daysOf("1")).toBe(1);
  });

  it("is nothing for what is no such number: the report then has its own", () => {
    for (const typed of ["", "0", "-5", "1.5", "ninety", "1000000", null]) {
      expect(daysOf(typed), String(typed)).toBeNull();
    }
  });
});

describe("a fiscal year", () => {
  // Named for the calendar year it ends in: this one is fiscal year 2027.
  const year = { starts_on: "2026-07-01", ends_on: "2027-06-30" };

  it("is past, the one today is in, or ahead", () => {
    expect(fiscalYearStanding(year, "2026-11-14")).toBe("current");
    expect(fiscalYearStanding(year, "2026-07-01")).toBe("current");
    expect(fiscalYearStanding(year, "2027-06-30")).toBe("current");
    expect(fiscalYearStanding(year, "2027-07-01")).toBe("past");
    expect(fiscalYearStanding(year, "2026-06-30")).toBe("ahead");
  });
});
