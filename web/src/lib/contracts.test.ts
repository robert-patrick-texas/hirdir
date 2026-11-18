import { describe, expect, it } from "vitest";
import {
  agreementGives,
  agreementHint,
  agreementPath,
  beganByLabel,
  CONTRACT_STATUSES,
  COVER_AT_ONCE,
  COVER_MOST,
  type Contract,
  contractLabel,
  contractPath,
  contractsOfPath,
  costTotal,
  countedUnder,
  coverageDay,
  coverBatches,
  coverBody,
  coveredItemsPath,
  coveringNumbers,
  coveringStatuses,
  endable,
  endedText,
  flaggedFilter,
  flaggedItemsPath,
  flaggedWords,
  followingPeriod,
  followsOnEnd,
  INHERITED,
  inForce,
  LAPSED,
  LEAVE_OUT_NOTE,
  nextTermText,
  overrides,
  periodText,
  pieceSize,
  RENEW_SPECS,
  RENEWAL_PENDING,
  RENEWAL_PENDING_NOTE,
  renewalPending,
  renewBody,
  renewPeriodProblem,
  renewProblem,
  renewScopeFilters,
  renewStart,
  STANDALONE,
  staleCause,
  startsLater,
} from "./contracts";
import { filterText, parseShort } from "./filter";
import { buildPatch } from "./patch";

const AGREEMENT = "0193a1f4-0000-7000-8000-00000000a001";
const CONTRACT = "0193a1f4-0000-7000-8000-00000000c001";
const RESELLER = "0193a1f4-0000-7000-8000-00000000e001";

// What an enterprise agreement gives: whom to ask, and no support address. The server
// answers it beside each value of a contract in it, whether the contract overrides it.
const fromAgreement = (value: string) => ({
  value,
  source: "agreement",
  source_hid: AGREEMENT,
  from_agreement: value,
});
const own = (value: string, given: string | null = null) => ({
  value,
  source: "own",
  source_hid: CONTRACT,
  from_agreement: given,
});
const none = { value: null, source: "none", source_hid: null, from_agreement: null };

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
    reseller_hid: {
      ...fromAgreement(RESELLER),
      label: "Example Reseller",
      from_agreement_label: "Example Reseller",
    },
    starts_on: fromAgreement("2025-01-01"),
    ends_on: fromAgreement("2027-12-31"),
    support_level: own("8x5, next business day", "24x7, four-hour response"),
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
    reseller_hid: { ...none, label: null, from_agreement_label: null },
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

  it("say what the agreement gives for each, as the server answers it, the reseller by its name", () => {
    expect(agreementGives(contract, "reseller_hid")).toBe("Example Reseller");
    expect(agreementGives(contract, "ends_on")).toBe("2027-12-31");
    // Also where the contract overrides it.
    expect(agreementGives(contract, "support_level")).toBe("24x7, four-hour response");
    // Blank where the agreement has nothing, and for a contract in no agreement.
    expect(agreementGives(contract, "support_url")).toBe("");
    expect(agreementGives(alone, "starts_on")).toBe("");
    expect(agreementGives(alone, "reseller_hid")).toBe("");
  });
});

describe("how a value of a contract stands", () => {
  it("is inherited where the server says it came from the agreement", () => {
    expect(inForce(contract, "ends_on")).toEqual({
      standing: "inherited",
      text: "2027-12-31",
      overridden: "",
      same: false,
    });
    // A reseller is shown by its name, never by its HID.
    expect(inForce(contract, "reseller_hid")).toMatchObject({
      standing: "inherited",
      text: "Example Reseller",
    });
  });

  it("is an override where it is the contract's own and the agreement gives one too", () => {
    // What it is in place of is what the server says the agreement gives: the page
    // reads no agreement for it.
    expect(inForce(contract, "support_level")).toEqual({
      standing: "override",
      text: "8x5, next business day",
      overridden: "24x7, four-hour response",
      same: false,
    });
  });

  it("is still an override where its own is the same as the agreement's, and says so", () => {
    const same = {
      ...contract,
      effective: {
        ...contract.effective,
        support_level: own("24x7, four-hour response", "24x7, four-hour response"),
        reseller_hid: {
          ...own(RESELLER, RESELLER),
          label: "Example Reseller",
          from_agreement_label: "Example Reseller",
        },
      },
    } as unknown as Contract;
    expect(inForce(same, "support_level")).toEqual({
      standing: "override",
      text: "24x7, four-hour response",
      overridden: "24x7, four-hour response",
      same: true,
    });
    // A reseller is the same by its HID, and is named by its name.
    expect(inForce(same, "reseller_hid")).toEqual({
      standing: "override",
      text: "Example Reseller",
      overridden: "Example Reseller",
      same: true,
    });
    expect(overrides(same)).toEqual(["reseller_hid", "support_level"]);
  });

  it("is a reseller of its own in place of another, by name", () => {
    const other = {
      ...contract,
      effective: {
        ...contract.effective,
        reseller_hid: {
          ...own("0193a1f4-0000-7000-8000-00000000e002", RESELLER),
          label: "Example Distributor",
          from_agreement_label: "Example Reseller",
        },
      },
    } as unknown as Contract;
    expect(inForce(other, "reseller_hid")).toEqual({
      standing: "override",
      text: "Example Distributor",
      overridden: "Example Reseller",
      same: false,
    });
  });

  it("is plainly its own where the agreement gives nothing, and for a contract that stands alone", () => {
    expect(inForce(contract, "support_url")).toMatchObject({ standing: "own", overridden: "" });
    expect(inForce(alone, "starts_on")).toEqual({
      standing: "own",
      text: "2026-07-01",
      overridden: "",
      same: false,
    });
  });

  it("is nothing where neither has a value", () => {
    expect(inForce(alone, "ends_on")).toEqual({
      standing: "none",
      text: "",
      overridden: "",
      same: false,
    });
    expect(inForce(alone, "reseller_hid").standing).toBe("none");
  });

  it("lists the fields a contract overrides, in the order a page shows them", () => {
    expect(overrides(contract)).toEqual(["support_level"]);
    expect(overrides(alone)).toEqual([]);
  });
});

describe("what a form says under a field a contract may have from its agreement", () => {
  it("says what a blank brings, and what clearing an own value brings back", () => {
    expect(agreementHint(contract, "ends_on")).toBe(
      "Blank has 2027-12-31 from Example Enterprise Agreement.",
    );
    expect(agreementHint(contract, "support_level")).toBe(
      "Set here, in place of 24x7, four-hour response from Example Enterprise Agreement. Clear it to have that.",
    );
    expect(agreementHint(contract, "support_url")).toBe(
      "Set here. Example Enterprise Agreement gives nothing for it.",
    );
  });

  it("says so where an own value is the same as the agreement's", () => {
    const same = {
      ...contract,
      effective: {
        ...contract.effective,
        support_level: own("24x7, four-hour response", "24x7, four-hour response"),
      },
    } as unknown as Contract;
    expect(agreementHint(same, "support_level")).toBe(
      "Set here, and the same as Example Enterprise Agreement gives. Clear it to follow Example Enterprise Agreement when that changes.",
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

describe("a renewal that is entered early", () => {
  const TODAY = "2026-11-14";

  it("is the next term when its period begins after today, and in force at once otherwise", () => {
    expect(startsLater({ starts_on: "2027-01-01" }, TODAY)).toBe(true);
    expect(startsLater({ starts_on: TODAY }, TODAY)).toBe(false);
    expect(startsLater({ starts_on: "2026-01-01" }, TODAY)).toBe(false);
    expect(startsLater({ starts_on: null }, TODAY)).toBe(false);
    expect(startsLater({}, TODAY)).toBe(false);
  });

  it("always says the end of a term to come: the day the form holds, or that it names none", () => {
    const early = { row_version: 3, number: "CON-2027-0002", starts_on: "2027-01-01" };
    expect(renewBody(early, "2027-12-31", TODAY)).toEqual({ ...early, ends_on: "2027-12-31" });
    expect(renewBody(early, null, TODAY)).toEqual({ ...early, ends_on: null });
    // An end that the form changed is in the body already, and stays as it is.
    const withEnd = { ...early, ends_on: "2028-06-30" };
    expect(renewBody(withEnd, "2027-12-31", TODAY)).toBe(withEnd);
  });

  it("sends a renewal that is in force at once as it was built", () => {
    const now = { row_version: 3, number: "CON-2026-0009", starts_on: "2026-11-01" };
    expect(renewBody(now, "2026-12-31", TODAY)).toBe(now);
    const numberOnly = { row_version: 3, number: "CON-2026-0009" };
    expect(renewBody(numberOnly, "2026-12-31", TODAY)).toBe(numberOnly);
  });

  it("says before it is sent that a term to come cannot keep the end of the term before", () => {
    const body = renewBody({ row_version: 3, starts_on: "2027-01-01" }, "2026-12-31", TODAY);
    expect(renewPeriodProblem(body, TODAY)).toBe(
      "A term that begins on 2027-01-01 cannot end on 2026-12-31. Give the day the new term ends, or leave it blank for none.",
    );
    expect(
      renewPeriodProblem({ row_version: 3, starts_on: "2027-01-01", ends_on: "2027-12-31" }, TODAY),
    ).toBe("");
    expect(
      renewPeriodProblem({ row_version: 3, starts_on: "2027-01-01", ends_on: null }, TODAY),
    ).toBe("");
    // A renewal that is in force at once is the server's to judge.
    expect(
      renewPeriodProblem({ row_version: 3, starts_on: "2026-01-01", ends_on: "2025-12-31" }, TODAY),
    ).toBe("");
  });

  it("says of a term to come the number it brings, the day it begins and the day it ends", () => {
    expect(
      nextTermText({
        number: "CON-2027-0001",
        starts_on: "2027-01-01",
        ends_on: "2027-12-31",
        annual_cost: null,
        purchase_reference: null,
      }),
    ).toBe("Renews as CON-2027-0001 on 2027-01-01, until 2027-12-31");
    // An agreement may have no number, and a term no end.
    expect(
      nextTermText({
        number: null,
        starts_on: "2028-01-01",
        ends_on: null,
        annual_cost: null,
        purchase_reference: null,
      }),
    ).toBe("Renews on 2028-01-01, with no end named");
  });

  it("says of a new number that waits on the agreement's next term whose dates it has", () => {
    expect(
      nextTermText({
        number: "CON-2027-0002",
        starts_on: "2027-01-01",
        ends_on: "2027-12-31",
        annual_cost: null,
        purchase_reference: null,
        with_agreement: true,
      }),
    ).toBe(
      "Renews as CON-2027-0002 on 2027-01-01, until 2027-12-31, with the agreement's next term, whose dates these are",
    );
  });
});

describe("the parts of a contract's history", () => {
  it("names what began each part", () => {
    expect(beganByLabel("created")).toBe("Made");
    expect(beganByLabel("renewal")).toBe("A renewal");
    expect(beganByLabel("joined")).toBe("Joining an agreement");
    expect(beganByLabel("left")).toBe("Leaving its agreement");
    expect(beganByLabel(null)).toBe("");
  });
});

describe("a renewal that is late, and a contract that has lapsed", () => {
  const ref = (number: string, status: string, in_force: boolean) =>
    ({ contract: { number, status }, in_force }) as Parameters<typeof renewalPending>[0][number];

  it("has Renewal pending among the statuses a person may give, after Active", () => {
    expect(CONTRACT_STATUSES.map((status) => status.value)).toEqual([
      "active",
      "renewal_pending",
      "pending",
      "expired",
      "cancelled",
    ]);
    expect(RENEWAL_PENDING).toBe("renewal_pending");
    expect(RENEWAL_PENDING_NOTE).toContain("account manager");
  });

  it("says of an item that its cover is under a contract whose renewal is pending", () => {
    expect(renewalPending([ref("A-1", "renewal_pending", true)])).toBe(true);
    expect(renewalPending([ref("A-1", "active", true)])).toBe(false);
    // A coverage that is not in force says nothing of today.
    expect(renewalPending([ref("A-1", "renewal_pending", false)])).toBe(false);
    expect(renewalPending([])).toBe(false);
  });

  it("lists the statuses of the contracts that cover an item today, each once, in words", () => {
    expect(
      coveringStatuses([
        ref("A-1", "active", true),
        ref("B-2", "renewal_pending", true),
        ref("C-3", "active", true),
        ref("D-4", "expired", false),
      ]),
    ).toBe("Active, Renewal pending");
    expect(coveringStatuses([])).toBe("");
  });

  it("finds the contracts that have lapsed by a filter the list takes", () => {
    expect(parseShort(LAPSED)).toEqual({
      ok: true,
      filter: { field: "lapsed", op: "eq", value: "true" },
    });
  });
});

describe("covering many items", () => {
  it("sends a thousand to a request, the rest in requests of their own", () => {
    const hids = Array.from({ length: 2500 }, (_, place) => `i-${place}`);
    const batches = coverBatches(hids);
    expect(batches.map((batch) => batch.length)).toEqual([1000, 1000, 500]);
    expect(batches.flat()).toEqual(hids);
    expect(COVER_AT_ONCE).toBe(1000);
    expect(COVER_MOST).toBeGreaterThan(COVER_AT_ONCE);
  });

  it("sends few in one request, and none for none", () => {
    expect(coverBatches(["i-1", "i-2"])).toEqual([["i-1", "i-2"]]);
    expect(coverBatches([])).toEqual([]);
  });

  it("sends the piece the setting max_items_per_request says", () => {
    const hids = Array.from({ length: 450 }, (_, place) => `i-${place}`);
    const settings = [{ key: "max_items_per_request", value: 200 }];
    expect(pieceSize(settings)).toBe(200);
    expect(coverBatches(hids, pieceSize(settings)).map((batch) => batch.length)).toEqual([
      200, 200, 50,
    ]);
  });

  it("takes the default piece until the setting is read, or where it is no count", () => {
    expect(pieceSize(undefined)).toBe(COVER_AT_ONCE);
    expect(pieceSize([])).toBe(COVER_AT_ONCE);
    expect(pieceSize([{ key: "max_items_per_request", value: "many" }])).toBe(COVER_AT_ONCE);
    expect(pieceSize([{ key: "max_items_per_request", value: 0 }])).toBe(COVER_AT_ONCE);
    expect(coverBatches(["i-1", "i-2", "i-3"], 0)).toEqual([["i-1", "i-2", "i-3"]]);
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

  it("lists the contracts the server says still count an item that left, each once", () => {
    const counted = (...numbers: string[]) => ({
      out_of_service_contracts: numbers.map((number) => ({ number })),
    });
    expect(countedUnder(counted("A-1"))).toBe("A-1");
    expect(countedUnder(counted("A-1", "B-2", "A-1"))).toBe("A-1, B-2");
    // Blank for an item in service.
    expect(countedUnder(counted())).toBe("");
  });
});

describe("a change that is refused as stale", () => {
  it("says that a term still to begin may have begun, and names its day", () => {
    const next = { number: "CON-2027-0002", starts_on: "2027-01-01", ends_on: "2027-12-31" };
    const said = staleCause({ next_term: next }, "contract");
    expect(said).toContain("or its next term, from 2027-01-01, has begun");
    expect(said).toContain("the contract is read with that term, at a new version");
    expect(said).toContain("not made to a term it was not meant for");
    expect(staleCause({ next_term: next }, "agreement")).toContain("the agreement is read");
  });

  it("says nothing of its own for a record with no term to come", () => {
    expect(staleCause({ next_term: null }, "contract")).toBe("");
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

describe("ending a coverage on the contract's own last day (P-213)", () => {
  const open = { ends_on: null, effective_ends_on: "2026-12-31" };
  const own = { ends_on: "2026-06-30", effective_ends_on: "2026-06-30" };

  it("is said to change nothing where the day is the contract's end", () => {
    expect(followsOnEnd(open, "2026-12-31", "2026-12-31")).toBe(true);
    expect(followsOnEnd(own, "2026-12-31", "2026-12-31")).toBe(true);
    expect(followsOnEnd(open, "2026-12-30", "2026-12-31")).toBe(false);
  });

  it("reads the contract's end from a coverage that has none of its own", () => {
    expect(followsOnEnd(open, "2026-12-31")).toBe(true);
    expect(followsOnEnd(open, "2026-11-30")).toBe(false);
    // One with an end of its own does not say what the contract's is.
    expect(followsOnEnd(own, "2026-12-31")).toBe(false);
  });

  it("leaves alone an end that is the coverage's own already, and no day", () => {
    const kept = { ends_on: "2026-12-31", effective_ends_on: "2026-12-31" };
    expect(followsOnEnd(kept, "2026-12-31", "2026-12-31")).toBe(false);
    expect(followsOnEnd(open, "", "2026-12-31")).toBe(false);
  });

  it("says what the server kept, not what was asked", () => {
    const day = "2026-12-31";
    expect(endedText(day, [{ ends_on: day }, { ends_on: day }])).toBe(
      "2 coverages were ended on 2026-12-31. Nothing was removed.",
    );
    const none = endedText(day, [{ ends_on: null }, { ends_on: null }, { ends_on: null }]);
    expect(none).toContain("None of the 3 coverages was ended");
    expect(none).not.toContain("were ended");
    expect(none).toContain(LEAVE_OUT_NOTE);
    expect(endedText(day, [{ ends_on: null }])).toMatch(/^The coverage was not ended: /);
    const some = endedText(day, [{ ends_on: day }, { ends_on: null }]);
    expect(some).toMatch(
      /^1 coverage was ended on 2026-12-31\. Nothing was removed\. 1 was not ended: /,
    );
  });
});

describe("the renewal form starts from what follows (P-214)", () => {
  it("follows a calendar year with the next", () => {
    expect(followingPeriod("2026-12-31")).toEqual({
      starts_on: "2027-01-01",
      ends_on: "2027-12-31",
    });
  });

  it("gives a year from the day after, whatever the length of the term before", () => {
    // Seven months, ending in the middle of a month.
    expect(followingPeriod("2026-07-14")).toEqual({
      starts_on: "2026-07-15",
      ends_on: "2027-07-14",
    });
    // The end of a month that has fewer days in the year after.
    expect(followingPeriod("2026-03-30")).toEqual({
      starts_on: "2026-03-31",
      ends_on: "2027-03-30",
    });
  });

  it("keeps to the calendar about the leap day", () => {
    // A term that begins on the 29th of February runs to the 28th the year after.
    expect(followingPeriod("2028-02-28")).toEqual({
      starts_on: "2028-02-29",
      ends_on: "2029-02-28",
    });
    // One that begins on the 1st of March of the year before runs over the leap day.
    expect(followingPeriod("2027-02-28")).toEqual({
      starts_on: "2027-03-01",
      ends_on: "2028-02-29",
    });
    // A term that ends on the leap day is followed from the 1st of March.
    expect(followingPeriod("2028-02-29")).toEqual({
      starts_on: "2028-03-01",
      ends_on: "2029-02-28",
    });
  });

  it("gives nothing for a term with no end, or a day that is no day", () => {
    expect(followingPeriod(null)).toBeNull();
    expect(followingPeriod(undefined)).toBeNull();
    expect(followingPeriod("")).toBeNull();
    expect(followingPeriod("2026-02-30")).toBeNull();
    expect(followingPeriod("31/12/2026")).toBeNull();
  });

  it("begins with those dates and a blank purchase reference", () => {
    const form = { number: "EX-1", starts_on: "2026-01-01", ends_on: "2026-12-31" };
    const record = { ends_on: "2026-12-31", next_term: null };
    expect(renewStart(record, { ...form, purchase_reference: "REQ-0001" })).toEqual({
      number: "EX-1",
      starts_on: "2027-01-01",
      ends_on: "2027-12-31",
      purchase_reference: "",
    });
  });

  it("leaves the dates as they are for an end that is the agreement's, or a term to come", () => {
    const form = { starts_on: "", ends_on: "", purchase_reference: "REQ-0002" };
    expect(renewStart({ ends_on: null, next_term: null }, form)).toEqual({
      starts_on: "",
      ends_on: "",
      purchase_reference: "",
    });
    const waiting = { ends_on: "2026-12-31", next_term: { starts_on: "2027-01-01" } };
    expect(renewStart(waiting, { ...form, ends_on: "2026-12-31" })).toEqual({
      starts_on: "",
      ends_on: "2026-12-31",
      purchase_reference: "",
    });
  });

  it("counts what follows by filters the server reads", () => {
    const filters = renewScopeFilters("2026-12-31", "2026-11-17");
    expect(filters.begin).toEqual({ field: "starts_on", op: "gt", value: "2026-12-31" });
    expect(parseShort(filterText(filters.ownEnd))).toEqual({
      ok: true,
      filter: filters.ownEnd,
    });
    expect(JSON.stringify(filters.follow)).toContain('"op":"empty"');
    expect(flaggedFilter("CT-0001")).toEqual({
      and: [
        { field: "contract.hid", op: "eq", value: "CT-0001" },
        { field: "effective.do_not_renew", op: "eq", value: true },
      ],
    });
    expect(decodeURIComponent(flaggedItemsPath("CT-0001"))).toBe(
      "/items?filter=contract.hid:eq:CT-0001 effective.do_not_renew:eq:true&minor=1",
    );
  });
});

describe("what the renewal form says of the items marked not to be renewed (P-214)", () => {
  it("says what is counted, and the rule the server keeps, never that it ends them all", () => {
    expect(flaggedWords(0, "2027-12-31")).toEqual({
      link: null,
      text: "None of the items it covers today is marked not to be renewed.",
    });
    expect(flaggedWords(1, "2027-12-31")).toEqual({
      link: "1 item it covers today",
      text: " is marked not to be renewed; the renewal leaves behind those whose coverage runs to 2027-12-31, and its answer says how many it left.",
    });
    expect(flaggedWords(3, "").text).toBe(
      " are marked not to be renewed; the renewal leaves behind those whose coverage runs to the day before the new term begins, and its answer says how many it left.",
    );
  });
});

describe("what an agreement's contracts cost a year (P-215)", () => {
  it("adds the costs exactly, a contract with none counting as none", () => {
    expect(costTotal(["600000.00", "450000.00", "151500.00"])).toEqual({
      total: "1201500.00",
      counted: 3,
      none: 0,
    });
    // Tenths that a float would not add exactly.
    expect(costTotal(["0.10", "0.20", null, ""])).toEqual({
      total: "0.30",
      counted: 2,
      none: 2,
    });
  });

  it("keeps the places of the most precise cost, and gives none as nothing", () => {
    expect(costTotal(["12", "0.125"]).total).toBe("12.125");
    expect(costTotal([])).toEqual({ total: "0.00", counted: 0, none: 0 });
    expect(costTotal([null])).toEqual({ total: "0.00", counted: 0, none: 1 });
    expect(costTotal(["-5.00", "2.50"]).total).toBe("-2.50");
  });
});
