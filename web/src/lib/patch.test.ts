import { describe, expect, it } from "vitest";
import {
  asked,
  buildCreate,
  buildPatch,
  canonicalDecimal,
  type FieldSpec,
  formOf,
  hintOf,
} from "./patch";

const SPECS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text" },
  { name: "comments", label: "Comments", kind: "longtext" },
  { name: "quantity", label: "Quantity", kind: "integer" },
  { name: "ldos", label: "LDoS", kind: "date" },
  { name: "est_value", label: "Estimated value", kind: "decimal", places: 2 },
  { name: "support_weight", label: "Support weight", kind: "decimal", places: 2 },
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
    expect(built.errors.support_weight).toContain("at most 2 digits after the point");
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

describe("what is said beneath a field", () => {
  const note = "This owner is outside the operations team.";
  const owner: FieldSpec = {
    name: "owner_hid",
    label: "Owner",
    kind: "choice",
    hint: "Who answers for it",
    options: [
      { value: "o-engineering", label: "Network Engineering" },
      { value: "o-facilities", label: "Campus Facilities", note },
    ],
  };
  const { hint: _, ...plain } = owner;

  it("is the field's own hint, or the one the record gives it", () => {
    expect(hintOf(owner, "")).toBe("Who answers for it");
    expect(hintOf(owner, "o-engineering")).toBe("Who answers for it");
    expect(hintOf(owner, "", "Blank has the owner of the item it is in.")).toBe(
      "Blank has the owner of the item it is in.",
    );
    expect(hintOf({ name: "name", label: "Name", kind: "text" }, "x")).toBeUndefined();
  });

  it("adds what the option that is chosen says of itself", () => {
    expect(hintOf(owner, "o-facilities")).toBe(`Who answers for it ${note}`);
    expect(hintOf(plain, "o-facilities")).toBe(note);
    // Only a choice has options that speak, and only the one that is chosen does.
    expect(hintOf({ ...owner, kind: "text" }, "o-facilities")).toBe("Who answers for it");
  });
});

describe("a field that is asked for only sometimes", () => {
  // Only a cluster says how it is managed: the form asks while the type is a cluster.
  const specs: FieldSpec[] = [
    { name: "type", label: "Type", kind: "choice" },
    {
      name: "managed_as",
      label: "Managed as",
      kind: "choice",
      required: true,
      when: (values) => values.type === "cluster",
    },
  ];
  const group = { row_version: 4, type: "stack", managed_as: null };

  it("is asked for when the form holds what it depends on, and not otherwise", () => {
    const [, managed] = specs;
    expect(managed && asked(managed, { type: "cluster" })).toBe(true);
    expect(managed && asked(managed, { type: "stack" })).toBe(false);
    expect(specs[0] && asked(specs[0], {})).toBe(true);
  });

  it("is sent with a change while it is asked for", () => {
    const built = buildPatch(specs, group, { type: "cluster", managed_as: "members" });
    expect(built.body).toEqual({ row_version: 4, type: "cluster", managed_as: "members" });
  });

  it("is left out of a change while it is not, whatever the form still holds of it", () => {
    const built = buildPatch(
      specs,
      { row_version: 4, type: "cluster", managed_as: "members" },
      { type: "stack", managed_as: "one" },
    );
    expect(built.body).toEqual({ row_version: 4, type: "stack" });
    expect(built.changed).toEqual(["type"]);
  });

  it("is required of a new record only while it is asked for", () => {
    expect(buildCreate(specs, { type: "cluster", managed_as: "" }).errors).toEqual({
      managed_as: "Must not be blank.",
    });
    const stack = buildCreate(specs, { type: "stack", managed_as: "" });
    expect(stack.errors).toEqual({});
    expect(stack.body).toEqual({ type: "stack" });
  });
});

describe("a field that is cleared while it is not asked for", () => {
  // Deliveries go to the street address: the shipping address is then not asked for,
  // and one the record holds is cleared with the tick, which the server would refuse
  // beside it.
  const typed = (values: Record<string, unknown>) => values.ship_same_as_address !== true;
  const specs: FieldSpec[] = [
    { name: "ship_same_as_address", label: "Deliveries go to the street address", kind: "boolean" },
    {
      name: "ship_address1",
      label: "Shipping address line 1",
      kind: "text",
      when: typed,
      clearedWhenNotAsked: true,
    },
    {
      name: "ship_city",
      label: "Shipping city",
      kind: "text",
      when: typed,
      clearedWhenNotAsked: true,
    },
    { name: "ship_instructions", label: "Shipping instructions", kind: "longtext" },
  ];
  const site = {
    row_version: 3,
    ship_same_as_address: false,
    ship_address1: "100 Example Way",
    ship_city: null,
    ship_instructions: "Dock B",
  };

  it("clears what the record holds of it, in the same change as the tick", () => {
    const built = buildPatch(specs, site, { ...formOf(specs, site), ship_same_as_address: true });
    expect(built.body).toEqual({ row_version: 3, ship_same_as_address: true, ship_address1: null });
    expect(built.changed).toEqual(["ship_same_as_address", "ship_address1"]);
  });

  it("sends nothing of a field the record does not hold, and leaves the others alone", () => {
    const empty = { ...site, ship_address1: null };
    const built = buildPatch(specs, empty, { ...formOf(specs, empty), ship_same_as_address: true });
    expect(built.body).toEqual({ row_version: 3, ship_same_as_address: true });
  });

  it("asks for the address again when the tick is taken off, and sends what is typed", () => {
    const ticked = { ...site, ship_same_as_address: true, ship_address1: null };
    const built = buildPatch(specs, ticked, {
      ...formOf(specs, ticked),
      ship_same_as_address: false,
      ship_address1: "300 Example Avenue",
    });
    expect(built.body).toEqual({
      row_version: 3,
      ship_same_as_address: false,
      ship_address1: "300 Example Avenue",
    });
  });

  it("sends nothing of it for a new record, where there is nothing to clear", () => {
    const built = buildCreate(specs, {
      ...formOf(specs),
      ship_same_as_address: true,
      ship_address1: "typed before the tick",
    });
    expect(built.body).toEqual({ ship_same_as_address: true });
  });
});

describe("an operator and a contact in a form", () => {
  it("holds the person behind an operator as the HID of a contact, and blank as nobody", () => {
    const behind: FieldSpec[] = [{ name: "contact_hid", label: "Person", kind: "contact" }];
    const label = { row_version: 2, contact_hid: "k-lee" };
    // Another person hands the label over; a blank leaves it open.
    expect(buildPatch(behind, label, { contact_hid: "k-priya" }).body).toEqual({
      row_version: 2,
      contact_hid: "k-priya",
    });
    expect(buildPatch(behind, label, { contact_hid: "" }).body).toEqual({
      row_version: 2,
      contact_hid: null,
    });
  });

  // The operator of an item: a label, found by searching, held as its HID.
  const specs: FieldSpec[] = [{ name: "operator_hid", label: "Operator", kind: "operator" }];
  const item = { row_version: 5, operator_hid: "k-lee" };

  it("is held as the HID of the operator, and blank as none", () => {
    expect(formOf(specs, item)).toEqual({ operator_hid: "k-lee" });
    expect(formOf(specs, { operator_hid: null })).toEqual({ operator_hid: "" });
  });

  it("is sent as that HID, and cleared with null, so that the one from above is in force again", () => {
    expect(buildPatch(specs, item, { operator_hid: "k-priya" }).body).toEqual({
      row_version: 5,
      operator_hid: "k-priya",
    });
    expect(buildPatch(specs, item, { operator_hid: "" }).body).toEqual({
      row_version: 5,
      operator_hid: null,
    });
    expect(buildPatch(specs, item, { operator_hid: "k-lee" }).changed).toEqual([]);
    expect(buildCreate(specs, { operator_hid: "" }).body).toEqual({});
  });
});

describe("a planned location in a form", () => {
  const specs: FieldSpec[] = [
    { name: "planned_location_hid", label: "Planned location", kind: "planned_location" },
  ];
  const item = { row_version: 3, planned_location_hid: "l-9" };

  it("is held and sent as the HID of the place, and given up with null", () => {
    expect(formOf(specs, item)).toEqual({ planned_location_hid: "l-9" });
    expect(buildPatch(specs, item, { planned_location_hid: "l-10" }).body).toEqual({
      row_version: 3,
      planned_location_hid: "l-10",
    });
    expect(buildPatch(specs, item, { planned_location_hid: "" }).body).toEqual({
      row_version: 3,
      planned_location_hid: null,
    });
    expect(buildCreate(specs, { planned_location_hid: "" }).body).toEqual({});
  });
});

describe("a location in a form", () => {
  const specs: FieldSpec[] = [{ name: "location_hid", label: "Location", kind: "location" }];

  it("is held as the HID of the location, and blank as none", () => {
    expect(formOf(specs, { location_hid: "l-102" })).toEqual({ location_hid: "l-102" });
    expect(formOf(specs, { location_hid: null })).toEqual({ location_hid: "" });
  });

  it("is sent as that HID, and cleared with null, so that a minor item inherits again", () => {
    const item = { row_version: 2, location_hid: "l-102" };
    expect(buildPatch(specs, item, { location_hid: "l-201" }).body).toEqual({
      row_version: 2,
      location_hid: "l-201",
    });
    expect(buildPatch(specs, item, { location_hid: "" }).body).toEqual({
      row_version: 2,
      location_hid: null,
    });
    expect(buildPatch(specs, item, { location_hid: "l-102" }).changed).toEqual([]);
    expect(buildCreate(specs, { location_hid: "" }).body).toEqual({});
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
