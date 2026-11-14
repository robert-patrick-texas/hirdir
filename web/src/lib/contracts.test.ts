import { describe, expect, it } from "vitest";
import {
  type Agreement,
  agreementHint,
  agreementPath,
  agreementValue,
  type Contract,
  contractLabel,
  contractPath,
  contractsOfPath,
  coverageDay,
  coverBody,
  coveredItemsPath,
  coveringNumbers,
  endable,
  INHERITED,
  inForce,
  overrides,
  periodText,
  RENEW_SPECS,
  renewProblem,
  STANDALONE,
} from "./contracts";
import { parseShort } from "./filter";
import { buildPatch } from "./patch";

const AGREEMENT = "0193a1f4-0000-7000-8000-00000000a001";
const CONTRACT = "0193a1f4-0000-7000-8000-00000000c001";
const RESELLER = "0193a1f4-0000-7000-8000-00000000e001";

/** An enterprise agreement that says whom to ask, and names no support address. */
const agreement = {
  hid: AGREEMENT,
  name: "Example Enterprise Agreement",
  reseller: { hid: RESELLER, name: "Example Reseller" },
  starts_on: "2025-01-01",
  ends_on: "2027-12-31",
  support_level: "24x7, four-hour response",
  account_manager: "Jordan Reyes, jordan.reyes@example.com, +1 555 0142",
  support_contact: "Enterprise support desk, +1 555 0100",
  support_url: null,
} as unknown as Agreement;

const fromAgreement = (value: string) => ({
  value,
  source: "agreement",
  source_hid: AGREEMENT,
});
const own = (value: string) => ({ value, source: "own", source_hid: CONTRACT });
const none = { value: null, source: "none", source_hid: null };

/**
 * A contract in that agreement: co-termed with it, with a support level of its own in
 * place of the agreement's, and a support address where the agreement has none.
 */
const contract = {
  hid: CONTRACT,
  number: "CON-2025-0002",
  row_version: 3,
  vendor: { hid: "v-1", name: "Cisco" },
  agreement: { hid: AGREEMENT, name: "Example Enterprise Agreement", number: "EA-0004417" },
  agreement_hid: AGREEMENT,
  starts_on: null,
  ends_on: null,
  support_level: "8x5, next business day",
  purchase_reference: "RITM0009122",
  annual_cost: "18000.00",
  effective: {
    reseller_hid: { ...fromAgreement(RESELLER), label: "Example Reseller" },
    starts_on: fromAgreement("2025-01-01"),
    ends_on: fromAgreement("2027-12-31"),
    support_level: own("8x5, next business day"),
    account_manager: fromAgreement("Jordan Reyes, jordan.reyes@example.com, +1 555 0142"),
    support_contact: fromAgreement("Enterprise support desk, +1 555 0100"),
    support_url: own("https://support.example.com/branch"),
  },
} as unknown as Contract;

/** A contract that stands by itself, with dates of its own and nothing else. */
const alone = {
  ...contract,
  number: "CON-2026-0107",
  agreement: null,
  agreement_hid: null,
  starts_on: "2026-07-01",
  ends_on: null,
  support_level: null,
  effective: {
    reseller_hid: { ...none, label: null },
    starts_on: own("2026-07-01"),
    ends_on: none,
    support_level: none,
    account_manager: none,
    support_contact: none,
    support_url: none,
  },
} as unknown as Contract;

describe("the fields a contract may have from its agreement", () => {
  it("are the seven the server resolves, the period among them", () => {
    expect(INHERITED.map((one) => one.field)).toEqual([
      "reseller_hid",
      "starts_on",
      "ends_on",
      "support_level",
      "account_manager",
      "support_contact",
      "support_url",
    ]);
    // Each is a field of what a contract answers in force.
    for (const { field } of INHERITED) expect(contract.effective[field], field).toBeDefined();
  });

  it("are read from an agreement by the same names, the reseller by its name", () => {
    expect(agreementValue(agreement, "reseller_hid")).toBe("Example Reseller");
    expect(agreementValue(agreement, "ends_on")).toBe("2027-12-31");
    expect(agreementValue(agreement, "support_url")).toBe("");
    expect(agreementValue(null, "ends_on")).toBe("");
  });
});

describe("how a value of a contract stands", () => {
  it("is inherited where the server says it came from the agreement", () => {
    expect(inForce(contract, "ends_on", agreement)).toEqual({
      standing: "inherited",
      text: "2027-12-31",
      overridden: "",
    });
    // A reseller is shown by its name, never by its HID.
    expect(inForce(contract, "reseller_hid", agreement)).toMatchObject({
      standing: "inherited",
      text: "Example Reseller",
    });
  });

  it("is an override where it is the contract's own and the agreement has one too", () => {
    expect(inForce(contract, "support_level", agreement)).toEqual({
      standing: "override",
      text: "8x5, next business day",
      overridden: "24x7, four-hour response",
    });
  });

  it("is plainly its own where the agreement says nothing, and for a contract that stands alone", () => {
    expect(inForce(contract, "support_url", agreement)).toMatchObject({ standing: "own" });
    expect(inForce(alone, "starts_on", null)).toEqual({
      standing: "own",
      text: "2026-07-01",
      overridden: "",
    });
  });

  it("is its own, and not yet an override, until the agreement has been read", () => {
    // The contract's answer does not say what its own value overrides: the agreement does.
    expect(inForce(contract, "support_level")).toMatchObject({ standing: "own", overridden: "" });
  });

  it("is nothing where neither has a value", () => {
    expect(inForce(alone, "ends_on", null)).toEqual({ standing: "none", text: "", overridden: "" });
    expect(inForce(alone, "reseller_hid", null).standing).toBe("none");
  });

  it("lists the fields a contract overrides, in the order a page shows them", () => {
    expect(overrides(contract, agreement)).toEqual(["support_level"]);
    expect(overrides(alone, null)).toEqual([]);
  });
});

describe("what a form says under a field a contract may have from its agreement", () => {
  it("says what a blank brings, and what clearing an own value brings back", () => {
    expect(agreementHint(contract, "ends_on")).toBe(
      "Blank has 2027-12-31 from Example Enterprise Agreement.",
    );
    expect(agreementHint(contract, "support_level")).toBe(
      "Set here. Clear it to have what Example Enterprise Agreement says.",
    );
  });

  it("says nothing for a contract that stands by itself, and for a new one", () => {
    expect(agreementHint(alone, "ends_on")).toBeUndefined();
    expect(agreementHint(null, "ends_on")).toBeUndefined();
  });

  it("says so where the agreement has nothing either", () => {
    const silent = {
      ...contract,
      effective: { ...contract.effective, support_url: none },
    } as unknown as Contract;
    expect(agreementHint(silent, "support_url")).toContain("says nothing of it either");
  });
});

describe("periodText", () => {
  it("writes a period, and what a blank end and a blank start mean", () => {
    expect(periodText("2025-01-01", "2027-12-31")).toBe("2025-01-01 to 2027-12-31");
    expect(periodText("2026-07-01", null)).toBe("From 2026-07-01");
    expect(periodText(null, "2027-12-31")).toBe("Until 2027-12-31");
    expect(periodText(null, undefined)).toBe("Open");
  });
});

describe("a renewal", () => {
  const stored = contract as Contract & Readonly<Record<string, unknown>>;
  const form = (changes: Record<string, string>) => ({
    number: "CON-2025-0002",
    starts_on: "",
    ends_on: "",
    purchase_reference: "RITM0009122",
    annual_cost: "18000.00",
    support_level: "8x5, next business day",
    ...changes,
  });

  it("asks for the new number and the new period first", () => {
    expect(RENEW_SPECS.slice(0, 3).map((spec) => spec.name)).toEqual([
      "number",
      "starts_on",
      "ends_on",
    ]);
  });

  it("sends the version and only what the new term changes", () => {
    const built = buildPatch(
      RENEW_SPECS,
      stored,
      form({
        number: "CON-2027-0002",
        starts_on: "2027-01-01",
        ends_on: "2027-12-31",
        purchase_reference: "RITM0019455",
      }),
    );
    expect(built.body).toEqual({
      row_version: 3,
      number: "CON-2027-0002",
      starts_on: "2027-01-01",
      ends_on: "2027-12-31",
      purchase_reference: "RITM0019455",
    });
    expect(renewProblem(built.changed)).toBe("");
  });

  it("is a renewal with a new number alone, and with a new period alone", () => {
    expect(renewProblem(["number"])).toBe("");
    expect(renewProblem(["ends_on", "annual_cost"])).toBe("");
  });

  it("is refused here, as the server refuses it, when it gives neither", () => {
    const built = buildPatch(RENEW_SPECS, stored, form({ annual_cost: "19500.00" }));
    expect(built.changed).toEqual(["annual_cost"]);
    expect(renewProblem(built.changed)).toContain("a new number, a new period, or both");
    expect(renewProblem([])).not.toBe("");
  });
});

describe("covering items", () => {
  it("names each item once, with no dates: the coverage is then for the contract's period", () => {
    expect(coverBody(["i-1", "i-2"], "", " ")).toEqual({
      items: [{ item_hid: "i-1" }, { item_hid: "i-2" }],
    });
  });

  it("gives every item the days that were asked for", () => {
    expect(coverBody(["i-1"], "2026-11-01", "2027-10-31")).toEqual({
      items: [{ item_hid: "i-1", starts_on: "2026-11-01", ends_on: "2027-10-31" }],
    });
    expect(coverBody(["i-1"], "", "2027-10-31")).toEqual({
      items: [{ item_hid: "i-1", ends_on: "2027-10-31" }],
    });
  });

  it("shows a day of its own plainly, and the contract's as inherited", () => {
    expect(coverageDay("2026-11-01", "2026-11-01")).toEqual({
      text: "2026-11-01",
      inherited: false,
    });
    expect(coverageDay(null, "2027-12-31")).toEqual({ text: "2027-12-31", inherited: true });
    expect(coverageDay(null, null)).toEqual({ text: "", inherited: false });
  });

  it("can be ended until its own last day has passed", () => {
    expect(endable({ ends_on: null }, "2026-11-14")).toBe(true);
    expect(endable({ ends_on: "2026-12-31" }, "2026-11-14")).toBe(true);
    expect(endable({ ends_on: "2026-11-14" }, "2026-11-14")).toBe(true);
    expect(endable({ ends_on: "2026-06-30" }, "2026-11-14")).toBe(false);
  });

  it("lists the numbers of the contracts in force, each once", () => {
    const ref = (number: string, in_force: boolean) =>
      ({ contract: { number }, in_force }) as Parameters<typeof coveringNumbers>[0][number];
    expect(coveringNumbers([ref("B-2", true), ref("A-1", false), ref("B-2", true)])).toBe("B-2");
    expect(coveringNumbers([ref("B-2", true), ref("A-1", true)])).toBe("B-2, A-1");
    expect(coveringNumbers([])).toBe("");
  });
});

describe("paths and labels", () => {
  it("lead to a contract and to an agreement by their HIDs", () => {
    expect(contractPath(CONTRACT)).toBe(`/contracts/${CONTRACT}`);
    expect(agreementPath(AGREEMENT)).toBe(`/agreements/${AGREEMENT}`);
  });

  it("find the contracts of an agreement, and those that stand alone, by filters the list takes", () => {
    const query = new URLSearchParams(contractsOfPath(AGREEMENT).split("?")[1]);
    expect(parseShort(query.get("filter") ?? "")).toEqual({
      ok: true,
      filter: { field: "agreement_hid", op: "eq", value: AGREEMENT },
    });
    expect(parseShort(STANDALONE)).toEqual({
      ok: true,
      filter: { field: "agreement_hid", op: "empty", value: "true" },
    });
  });

  it("find the items a contract covers today, minor items among them", () => {
    const query = new URLSearchParams(coveredItemsPath(CONTRACT).split("?")[1]);
    expect(query.get("filter")).toBe(`contract.hid:eq:${CONTRACT}`);
    expect(query.get("minor")).toBe("1");
  });

  it("call a contract by its number and its vendor", () => {
    expect(contractLabel(contract)).toBe("CON-2025-0002 · Cisco");
    expect(contractLabel({ number: "CON-1", vendor: "Juniper" })).toBe("CON-1 · Juniper");
  });
});
