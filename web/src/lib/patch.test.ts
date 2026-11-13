import { describe, expect, it } from "vitest";
import { buildCreate, buildPatch, canonicalDecimal, type FieldSpec, formOf } from "./patch";

const SPECS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text" },
  { name: "comments", label: "Comments", kind: "longtext" },
  { name: "quantity", label: "Quantity", kind: "integer" },
  { name: "ldos", label: "LDoS", kind: "date" },
  { name: "est_value", label: "Estimated value", kind: "decimal", places: 2 },
  { name: "support_weight", label: "Support weight", kind: "decimal", places: 3 },
  { name: "is_external", label: "External", kind: "boolean" },
  { name: "expected_online", label: "Expected online", kind: "tristate" },
  { name: "owner_hid", label: "Owner", kind: "choice", blank: "No owner" },
  { name: "aliases", label: "Also known as", kind: "lines" },
  { name: "tags", label: "Tags", kind: "set" },
];

const ITEM = {
  row_version: 7,
  name: "site2-sw-access-01",
  comments: null,
  quantity: 1,
  ldos: null,
  est_value: null,
  support_weight: "1.5",
  is_external: false,
  expected_online: true,
  owner_hid: "0193a1f4-0000-7000-8000-00000000000a",
  aliases: ["Cisco Systems"],
  tags: ["core", "refresh-2030"],
  // A field the form does not show is never sent.
  serial_number: "FCW0000X001",
};

describe("formOf", () => {
  it("fills a form from a record, each field in the form its input takes", () => {
    expect(formOf(SPECS, ITEM)).toEqual({
      name: "site2-sw-access-01",
      comments: "",
      quantity: "1",
      ldos: "",
      est_value: "",
      support_weight: "1.5",
      is_external: false,
      expected_online: "true",
      owner_hid: "0193a1f4-0000-7000-8000-00000000000a",
      aliases: "Cisco Systems",
      tags: ["core", "refresh-2030"],
    });
  });

  it("starts every field blank when there is no record", () => {
    const blank = formOf(SPECS);
    expect(blank.name).toBe("");
    expect(blank.is_external).toBe(false);
    expect(blank.expected_online).toBe("");
    expect(blank.tags).toEqual([]);
  });
});

describe("buildPatch", () => {
  const form = () => formOf(SPECS, ITEM);

  it("sends the version alone when nothing was changed", () => {
    expect(buildPatch(SPECS, ITEM, form())).toEqual({
      body: { row_version: 7 },
      changed: [],
      errors: {},
    });
  });

  it("sends only the fields that were changed, with the version they were read at", () => {
    const built = buildPatch(SPECS, ITEM, {
      ...form(),
      name: "site2-sw-access-01a",
      ldos: "2034-04-30",
    });
    expect(built.body).toEqual({ row_version: 7, name: "site2-sw-access-01a", ldos: "2034-04-30" });
    expect(built.changed).toEqual(["name", "ldos"]);
  });

  it("sends an amount as the text that was typed, never as a number", () => {
    const built = buildPatch(SPECS, ITEM, { ...form(), est_value: "18000.10" });
    expect(built.body).toEqual({ row_version: 7, est_value: "18000.10" });
    expect(typeof (built.body as Record<string, unknown>).est_value).toBe("string");
    // More digits than a JavaScript number holds arrive whole.
    const large = buildPatch(SPECS, ITEM, { ...form(), est_value: "9007199254740993.07" });
    expect((large.body as Record<string, unknown>).est_value).toBe("9007199254740993.07");
  });

  it("creates an override by a value, and clears it with null so that it inherits again", () => {
    const overridden = { ...ITEM, est_value: "21000.50" };
    expect(buildPatch(SPECS, ITEM, { ...form(), est_value: "21000.50" }).body).toEqual({
      row_version: 7,
      est_value: "21000.50",
    });
    expect(
      buildPatch(SPECS, overridden, { ...formOf(SPECS, overridden), est_value: "" }).body,
    ).toEqual({ row_version: 7, est_value: null });
  });

  it("does not call an amount changed for zeros that say nothing", () => {
    const record = { ...ITEM, est_value: "18000.00" };
    for (const typed of ["18000", "18000.0", "18000.00", "018000.00", " 18000.00 "]) {
      expect(
        buildPatch(SPECS, record, { ...formOf(SPECS, record), est_value: typed }).changed,
        typed,
      ).toEqual([]);
    }
    expect(
      buildPatch(SPECS, record, { ...formOf(SPECS, record), est_value: "18000.01" }).changed,
    ).toEqual(["est_value"]);
  });

  it("clears text with null, and trims what was typed", () => {
    expect(buildPatch(SPECS, ITEM, { ...form(), name: "  " }).body).toEqual({
      row_version: 7,
      name: null,
    });
    expect(buildPatch(SPECS, ITEM, { ...form(), name: " site2-sw-access-01 " }).changed).toEqual(
      [],
    );
    expect(buildPatch(SPECS, ITEM, { ...form(), owner_hid: "" }).body).toEqual({
      row_version: 7,
      owner_hid: null,
    });
  });

  it("sends a whole number as a number, yes and no as booleans, and a blank intent as null", () => {
    expect(buildPatch(SPECS, ITEM, { ...form(), quantity: "25" }).body).toEqual({
      row_version: 7,
      quantity: 25,
    });
    expect(buildPatch(SPECS, ITEM, { ...form(), is_external: true }).body).toEqual({
      row_version: 7,
      is_external: true,
    });
    expect(buildPatch(SPECS, ITEM, { ...form(), expected_online: "false" }).body).toEqual({
      row_version: 7,
      expected_online: false,
    });
    expect(buildPatch(SPECS, ITEM, { ...form(), expected_online: "" }).body).toEqual({
      row_version: 7,
      expected_online: null,
    });
  });

  it("compares tags as a set and other names as a list", () => {
    expect(buildPatch(SPECS, ITEM, { ...form(), tags: ["refresh-2030", "core"] }).changed).toEqual(
      [],
    );
    expect(buildPatch(SPECS, ITEM, { ...form(), tags: ["core"] }).body).toEqual({
      row_version: 7,
      tags: ["core"],
    });
    expect(buildPatch(SPECS, ITEM, { ...form(), tags: [] }).body).toEqual({
      row_version: 7,
      tags: [],
    });
    expect(
      buildPatch(SPECS, ITEM, { ...form(), aliases: "Cisco Systems\n\n Cisco Systems, Inc. \n" })
        .body,
    ).toEqual({ row_version: 7, aliases: ["Cisco Systems", "Cisco Systems, Inc."] });
  });

  it("finds what cannot be sent before sending anything, and leaves it out", () => {
    const built = buildPatch(SPECS, ITEM, {
      ...form(),
      quantity: "many",
      est_value: "18,000",
      support_weight: "1.2345",
      ldos: "next year",
      name: "site2-sw-access-01b",
    });
    expect(Object.keys(built.errors).sort()).toEqual([
      "est_value",
      "ldos",
      "quantity",
      "support_weight",
    ]);
    expect(built.errors.support_weight).toContain("at most 3 digits after the point");
    expect(built.body).toEqual({ row_version: 7, name: "site2-sw-access-01b" });
  });

  it("refuses a negative amount and an exponent", () => {
    for (const typed of ["-1", "1e3", "+5", ".5", "5."]) {
      expect(
        buildPatch(SPECS, ITEM, { ...form(), est_value: typed }).errors.est_value,
        typed,
      ).toBeDefined();
    }
  });
});

describe("buildCreate", () => {
  it("sends the fields that were given a value, and leaves a blank to the server", () => {
    const built = buildCreate(SPECS, {
      ...formOf(SPECS),
      name: "site2-sw-access-02",
      est_value: "18000",
      tags: ["core"],
    });
    expect(built.body).toEqual({ name: "site2-sw-access-02", est_value: "18000", tags: ["core"] });
    expect(built.errors).toEqual({});
  });

  it("asks for a required field before sending", () => {
    const specs: FieldSpec[] = [{ name: "label", label: "Label", kind: "text", required: true }];
    expect(buildCreate(specs, formOf(specs)).errors).toEqual({ label: "Must not be blank." });
    expect(buildCreate(specs, { label: "Network Engineering" }).errors).toEqual({});
  });

  it("finds an amount that cannot be sent", () => {
    expect(
      buildCreate(SPECS, { ...formOf(SPECS), est_value: "a lot" }).errors.est_value,
    ).toBeDefined();
  });
});

describe("canonicalDecimal", () => {
  it("drops the zeros that say nothing, by text alone", () => {
    expect(canonicalDecimal("18000.00")).toBe("18000");
    expect(canonicalDecimal("018000.50")).toBe("18000.5");
    expect(canonicalDecimal("0.50")).toBe("0.5");
    expect(canonicalDecimal("0")).toBe("0");
    expect(canonicalDecimal("9007199254740993.070")).toBe("9007199254740993.07");
  });
});
