import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_FORMATS,
  emailText,
  formatsInUse,
  formatsOf,
  OFFERED_PATTERNS,
  patternProblem,
  patternSample,
  phoneText,
  setFormats,
  tidied,
  tidier,
  titleCase,
} from "./formats";

const US = "+1 (###) ###-####";
const PLAIN = "###-###-####";

afterEach(() => setFormats(DEFAULT_FORMATS));

describe("phoneText", () => {
  it("writes the digits in the pattern whose # are as many", () => {
    expect(phoneText("5550100123", [US])).toBe("+1 (555) 010-0123");
    expect(phoneText("555.010.0123", [PLAIN])).toBe("555-010-0123");
  });

  it("writes the leading digits of a pattern once, where the number has them", () => {
    expect(phoneText("1 555 010 0123", [US])).toBe("+1 (555) 010-0123");
    expect(phoneText("+1 555-010-0123", [US])).toBe("+1 (555) 010-0123");
    expect(phoneText("+1 (555) 010-0123", [US])).toBe("+1 (555) 010-0123");
  });

  it("takes the first pattern that fits, in the order given", () => {
    expect(phoneText("5550100123", [PLAIN, US])).toBe("555-010-0123");
    expect(phoneText("5550100123", [US, PLAIN])).toBe("+1 (555) 010-0123");
    expect(phoneText("15550100123", [PLAIN, US])).toBe("+1 (555) 010-0123");
  });

  it("keeps as typed a number with a letter, one that fits no pattern, and any with no pattern", () => {
    expect(phoneText("555 0100 x12", [US])).toBe("555 0100 x12");
    expect(phoneText("555 010 0123 ext. 4", [US])).toBe("555 010 0123 ext. 4");
    expect(phoneText("555 0100", [US])).toBe("555 0100");
    expect(phoneText("25550100123", [US])).toBe("25550100123");
    expect(phoneText("15550100123", [PLAIN])).toBe("15550100123");
    expect(phoneText("5550100123", [])).toBe("5550100123");
    expect(phoneText("", [US])).toBe("");
  });

  it("keeps as typed a number with a sign that is no separator", () => {
    expect(phoneText("555 010 0123 #12", [US])).toBe("555 010 0123 #12");
    expect(phoneText("*555 010 0123", [US])).toBe("*555 010 0123");
  });
});

describe("emailText and titleCase", () => {
  it("keeps an email address in lower case, whatever its host", () => {
    expect(emailText("John.Smith@Example.COM")).toBe("john.smith@example.com");
    expect(emailText("Ops@LOCALHOST")).toBe("ops@localhost");
  });

  it("raises the first letter of each word, after a space, a hyphen or an apostrophe", () => {
    expect(titleCase("ada example")).toBe("Ada Example");
    expect(titleCase("kim o'lee-roe")).toBe("Kim O'Lee-Roe");
    expect(titleCase("sam o’roe")).toBe("Sam O’Roe");
    expect(titleCase("  rex  example ")).toBe("  Rex  Example ");
  });

  it("never lowers a letter typed as a capital", () => {
    expect(titleCase("McDonald")).toBe("McDonald");
    expect(titleCase("IT desk")).toBe("IT Desk");
    expect(titleCase("NOC")).toBe("NOC");
    expect(titleCase("ada mcDonald")).toBe("Ada McDonald");
  });

  it("leaves what is not a letter, and a letter whose capital is two", () => {
    expect(titleCase("3rd shift")).toBe("3rd Shift");
    expect(titleCase("straße")).toBe("Straße");
    expect(titleCase("ßa")).toBe("ßa");
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
