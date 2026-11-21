import { describe, expect, it } from "vitest";
import { buildPatch } from "./patch";
import {
  codeProblems,
  codeWords,
  DETAIL_SPECS,
  MIN_LENGTH_KEY,
  minLengthOf,
  NO_CODES,
  OPERATOR_SPECS,
  OPERATOR_SPECS_TYPED,
  operatorSpecs,
} from "./profile";

describe("the forms of a person's own profile (P-294)", () => {
  it("asks the five fields of the contact that the route takes, in the order of the page", () => {
    expect(DETAIL_SPECS.map((spec) => spec.name)).toEqual([
      "name",
      "email",
      "phone",
      "phone2",
      "organization",
    ]);
  });

  it("sends only what was changed of the contact, with its version, and a blank as null", () => {
    const contact = {
      name: "Kim Lee",
      email: "kim.lee@example.com",
      phone: "+1 555 0100",
      phone2: null,
      organization: "Example Networks",
      row_version: 4,
    };
    const built = buildPatch(DETAIL_SPECS, contact, {
      name: "Kim A. Lee",
      email: "kim.lee@example.com",
      phone: "",
      phone2: "",
      organization: "Example Networks",
    });
    expect(built.errors).toEqual({});
    expect(built.body).toEqual({ row_version: 4, name: "Kim A. Lee", phone: null });
  });

  it("sends a name left blank as none, which is the server's to refuse at the field", () => {
    const contact = { name: "Kim Lee", email: null, phone: null, phone2: null, row_version: 1 };
    const built = buildPatch(DETAIL_SPECS, contact, {
      name: " ",
      email: "",
      phone: "",
      phone2: "",
      organization: "",
    });
    expect(built.errors).toEqual({});
    expect(built.body).toEqual({ row_version: 1, name: null });
  });

  it("asks the label and the colour of an operator and nothing else, the colour in lower case", () => {
    expect(OPERATOR_SPECS.map((spec) => spec.name)).toEqual(["label", "colour"]);
    const operator = { hid: "OPR-1", label: "klee", colour: "#1f6feb", row_version: 2 };
    const built = buildPatch(OPERATOR_SPECS, operator, { label: "KL", colour: "#D4A72C" });
    expect(built.errors).toEqual({});
    expect(built.body).toEqual({ row_version: 2, label: "KL", colour: "#d4a72c" });
    // The sample beside the chip is the label being typed.
    const colour = OPERATOR_SPECS.find((spec) => spec.name === "colour");
    expect(colour?.sample?.({ label: "KL", colour: "" })).toBe("KL");
  });
});

describe("the operator of a person who holds no role (P-296)", () => {
  it("has the picker with a role, and the colour typed with none", () => {
    for (const role of ["viewer", "inventory", "admin"]) {
      expect(operatorSpecs(role)).toBe(OPERATOR_SPECS);
    }
    expect(operatorSpecs(null)).toBe(OPERATOR_SPECS_TYPED);
    expect(operatorSpecs(undefined)).toBe(OPERATOR_SPECS_TYPED);
    expect(OPERATOR_SPECS_TYPED.map((spec) => [spec.name, spec.kind])).toEqual([
      ["label", "text"],
      ["colour", "text"],
    ]);
  });

  it("sends the colour as typed, which the server reads, and a blank as none", () => {
    const operator = { hid: "OPR-1", label: "klee", colour: "#1f6feb", row_version: 2 };
    expect(
      buildPatch(OPERATOR_SPECS_TYPED, operator, { label: "klee", colour: " #D4A72C " }).body,
    ).toEqual({ row_version: 2, colour: "#D4A72C" });
    expect(buildPatch(OPERATOR_SPECS_TYPED, operator, { label: "klee", colour: "" }).body).toEqual({
      row_version: 2,
      colour: null,
    });
  });
});

describe("the least length of a typed access code (P-295)", () => {
  it("is what the setting says", () => {
    expect(
      minLengthOf([
        { key: "time_zone", value: "UTC" },
        { key: MIN_LENGTH_KEY, value: 12 },
      ]),
    ).toBe(12);
    expect(minLengthOf([{ key: MIN_LENGTH_KEY, value: 1 }])).toBe(1);
  });

  it("is unknown where the settings do not say it as a whole number of one or more", () => {
    expect(minLengthOf(undefined)).toBeNull();
    expect(minLengthOf(null)).toBeNull();
    expect(minLengthOf([])).toBeNull();
    expect(minLengthOf([{ key: MIN_LENGTH_KEY, value: "12" }])).toBeNull();
    expect(minLengthOf([{ key: MIN_LENGTH_KEY, value: 0 }])).toBeNull();
    expect(minLengthOf([{ key: MIN_LENGTH_KEY, value: 12.5 }])).toBeNull();
    expect(minLengthOf([{ key: MIN_LENGTH_KEY }])).toBeNull();
  });

  it("is said with what a change ends, and that alone where the length is not known", () => {
    expect(codeWords(12)).toBe(
      "At least 12 characters. Your other sessions end when it is changed; this one stays signed in.",
    );
    expect(codeWords(1)).toMatch(/^At least 1 character\. /);
    expect(codeWords(null)).toBe(
      "Your other sessions end when it is changed; this one stays signed in.",
    );
  });
});

describe("the three boxes of the access code, before anything is sent (P-295)", () => {
  it("finds nothing wrong with a code in hand and the same new code twice", () => {
    expect(
      codeProblems({
        current: "old code in hand",
        wanted: "a new long code",
        again: "a new long code",
      }),
    ).toEqual({});
  });

  it("says two new codes that differ at the second", () => {
    expect(
      codeProblems({
        current: "old code in hand",
        wanted: "a new long code",
        again: "a new long cod",
      }),
    ).toEqual({ access_code_again: "The two new codes differ. Type the same code in both." });
    // A space is part of a code: nothing is trimmed away before the two are compared.
    expect(
      Object.keys(
        codeProblems({ current: "x", wanted: "a new long code", again: "a new long code " }),
      ),
    ).toEqual(["access_code_again"]);
  });

  it("says each box left empty, so that an empty code in hand is not sent to be counted", () => {
    expect(codeProblems(NO_CODES)).toEqual({
      current_access_code: "Type the access code you have.",
      access_code: "Type a new access code.",
    });
    expect(
      Object.keys(codeProblems({ current: "", wanted: "a new long code", again: "" })),
    ).toEqual(["current_access_code", "access_code_again"]);
  });

  it("leaves the length of the new code to the server", () => {
    expect(codeProblems({ current: "old code in hand", wanted: "short", again: "short" })).toEqual(
      {},
    );
  });
});
