import { afterEach, describe, expect, it } from "vitest";
// The one list of cases the server and the page are held to (P-322 (7)).
import contract from "../../../contract/formats.json" with { type: "json" };
import {
  DEFAULT_FORMATS,
  type Formats,
  formatsInUse,
  formatsOf,
  OFFERED_PATTERNS,
  patternProblem,
  patternSample,
  phoneText,
  setFormats,
  type TextFormat,
  tidied,
  tidier,
  titleCase,
} from "./formats";
import { withPattern } from "./settings";

const US = "+1 (###) ###-####";
const PLAIN = "###-###-####";

interface Case {
  format: string;
  setting: unknown;
  typed: string;
  kept: string;
  note?: string;
}

/** The format of a box, and the formats in force, as a case of the contract names them. */
const AS_BOX: Readonly<Record<string, TextFormat>> = {
  phone_formats: "phone",
  email_lower_case: "email",
  title_case_names: "person_name",
};

function formatsFor(one: Case): Formats {
  const settings = [{ key: one.format, value: one.setting }];
  return formatsOf(settings);
}

afterEach(() => setFormats(DEFAULT_FORMATS));

describe("the cases of contract/formats.json", () => {
  const cases = contract.cases as Case[];

  it("has cases of each of the three formats", () => {
    for (const format of Object.keys(AS_BOX)) {
      expect(cases.some((one) => one.format === format)).toBe(true);
    }
  });

  for (const one of cases) {
    it(`${one.format} ${JSON.stringify(one.setting)}: ${JSON.stringify(one.typed)} is kept as ${JSON.stringify(one.kept)}`, () => {
      const format = AS_BOX[one.format];
      if (format === undefined) throw new Error(`no format ${one.format}`);
      const formats = formatsFor(one);
      // The setting is read as it is listed, and nothing else of the defaults is taken.
      if (one.format === "phone_formats") expect(formats.phoneFormats).toEqual(one.setting);
      expect(tidied(format, one.typed, formats), one.note).toBe(one.kept);
    });
  }

  for (const one of contract.patterns as Array<{ pattern: string; kept: string | null }>) {
    it(`the pattern ${JSON.stringify(one.pattern)} is ${one.kept === null ? "refused" : "taken"}`, () => {
      const added = withPattern([], one.pattern);
      expect(added.ok ? added.list : null).toEqual(one.kept === null ? null : [one.kept]);
    });
  }
});

describe("phoneText and titleCase beyond the contract", () => {
  it("keeps as typed a number with a tab or a sign that is no separator", () => {
    expect(phoneText("555\t010\t0123", [US])).toBe("555\t010\t0123");
    expect(phoneText("*555 010 0123", [US])).toBe("*555 010 0123");
    expect(phoneText("", [US])).toBe("");
  });

  it("leaves what is not a letter, and a letter whose capital is two", () => {
    expect(titleCase("3rd shift")).toBe("3rd Shift");
    expect(titleCase("straße")).toBe("Straße");
    expect(titleCase("ßa")).toBe("ßa");
    expect(titleCase("ada mcDonald")).toBe("Ada McDonald");
  });
});

describe("tidied", () => {
  it("follows the formats given", () => {
    const formats = { phoneFormats: [US], emailLowerCase: false, titleCaseNames: false };
    expect(tidied("phone", "5550100123", formats)).toBe("+1 (555) 010-0123");
    expect(tidied("email", "Ada@Example.org", formats)).toBe("Ada@Example.org");
    expect(tidied("person_name", "ada example", formats)).toBe("ada example");
  });

  it("follows the formats in use, read when the tidy is made", () => {
    const tidy = tidier("phone");
    expect(tidy?.("5550100123")).toBe("5550100123");
    setFormats({ ...DEFAULT_FORMATS, phoneFormats: [PLAIN] });
    expect(tidy?.("5550100123")).toBe("555-010-0123");
    expect(tidier(undefined)).toBeUndefined();
  });

  it("starts with the defaults: lower case and Title Case, no number formatted", () => {
    expect(formatsInUse()).toEqual(DEFAULT_FORMATS);
    expect(tidied("email", "Ada@Example.org")).toBe("ada@example.org");
    expect(tidied("person_name", "ada example")).toBe("Ada Example");
    expect(tidied("phone", "5550100123")).toBe("5550100123");
  });
});

describe("formatsOf", () => {
  it("reads the three settings", () => {
    const settings = [
      { key: "phone_formats", value: [US, PLAIN] },
      { key: "email_lower_case", value: false },
      { key: "title_case_names", value: false },
      { key: "time_zone", value: "UTC" },
    ];
    expect(formatsOf(settings)).toEqual({
      phoneFormats: [US, PLAIN],
      emailLowerCase: false,
      titleCaseNames: false,
    });
  });

  it("keeps the default of a setting not listed or of another kind", () => {
    expect(formatsOf(null)).toEqual(DEFAULT_FORMATS);
    expect(formatsOf([{ key: "phone_formats", value: "###" }])).toEqual(DEFAULT_FORMATS);
    expect(formatsOf([{ key: "title_case_names", value: "no" }])).toEqual(DEFAULT_FORMATS);
  });
});

describe("patternProblem and patternSample", () => {
  it("takes the two patterns offered", () => {
    for (const pattern of OFFERED_PATTERNS) expect(patternProblem(pattern)).toBeNull();
    expect(patternProblem("+44 #### ######")).toBeNull();
    expect(patternProblem("##.##.##.##")).toBeNull();
  });

  it("says what is wrong with one of an Admin's own", () => {
    expect(patternProblem("###")).toMatch(/4 to 40/);
    expect(patternProblem("#".repeat(41))).toMatch(/4 to 40/);
    expect(patternProblem("1-###-x")).toMatch(/four at least/);
    expect(patternProblem("###-##1-####")).toMatch(/only before the first #/);
    expect(patternProblem("###_###_####")).toMatch(/only spaces/);
    expect(patternProblem("###\t###-####")).toMatch(/only spaces/);
  });

  it("shows a number written in a pattern", () => {
    expect(patternSample(PLAIN)).toBe("555-010-0123");
    expect(patternSample(US)).toBe("+1 (555) 010-0123");
  });
});
