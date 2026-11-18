import { describe, expect, it } from "vitest";
import {
  type NamedRecord,
  namedLevel,
  namedMark,
  namedMore,
  namedPath,
  namedRole,
  USES_KINDS,
} from "./contactUses";

const CHOICES = [
  {
    hid: "c-1",
    list: "contact_role",
    value: "technical",
    label: "Technical",
    sort: 1,
    active: true,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  },
];

function named(more: Partial<NamedRecord>): NamedRecord {
  return {
    hid: "r-1",
    record_type: "site",
    label: "Example North > Example Yard",
    record_status: "active",
    role: null,
    priority: null,
    side: null,
    colour: null,
    ...more,
  };
}

describe("where a contact is named (P-205)", () => {
  it("lists the kinds in the order the server names them", () => {
    expect(USES_KINDS.map((one) => one.kind)).toEqual([
      "places",
      "owners",
      "operators",
      "agreements",
      "contracts",
      "vendors",
      "circuits",
    ]);
  });

  it("leads to the page of each record", () => {
    expect(namedPath(named({ record_type: "site", hid: "s 1" }))).toBe("/geography/site/s%201");
    expect(namedPath(named({ record_type: "agreement", hid: "a-1" }))).toBe("/agreements/a-1");
    expect(namedPath(named({ record_type: "circuit", hid: "c-1" }))).toBe("/circuits/c-1");
  });

  it("says the role as people call it, for each kind", () => {
    expect(namedRole(named({ role: "technical" }), CHOICES)).toBe("Technical");
    expect(namedRole(named({ record_type: "owner", role: "primary" }))).toBe("Primary");
    expect(namedRole(named({ record_type: "agreement", role: "account_manager" }))).toBe(
      "Account manager",
    );
    expect(namedRole(named({ record_type: "circuit", role: "support_contact" }))).toBe(
      "Support contact",
    );
    expect(
      namedRole(named({ record_type: "circuit", role: "technical", side: "a" }), CHOICES),
    ).toBe("Technical, A side");
    expect(namedRole(named({ record_type: "operator" }))).toBe("");
  });

  it("names the level of a place, and of nothing else", () => {
    expect(namedLevel(named({ record_type: "region" }))).toBe("Region");
    expect(namedLevel(named({ record_type: "vendor" }))).toBe("");
  });

  it("says how many are listed where there are more than a page", () => {
    expect(namedMore({ total: 2, records: [named({}), named({})] })).toBeNull();
    expect(namedMore({ total: 1250, records: [named({})] })).toBe(
      "The first 1 of 1,250, by name, are listed.",
    );
  });

  it("marks an operator by its colour, released when retired, open when its person is", () => {
    const mark = namedMark(named({ record_type: "operator", label: "ex-ops", colour: "#336699" }), {
      name: "Example Person",
      record_status: "active",
    });
    expect(mark).toMatchObject({
      label: "ex-ops",
      colour: "#336699",
      open: false,
      released: false,
    });
    const gone = namedMark(named({ record_status: "retired", colour: "red;" }), {
      name: "Example Person",
      record_status: "retired",
    });
    expect(gone).toMatchObject({ colour: null, open: true, released: true });
  });
});
