// The tables of release 0.6.0 that hold all of their rows, rendered from answers of
// the shape the server gives: the contracts of an agreement, the capacity balance and
// the counts of a vendor's portfolio. Every name and number here is invented.

import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import { balanceRows, type CapacityReport, type CapacityView } from "../lib/capacity";
import type { Agreement, Contract } from "../lib/contracts";
import { Balance } from "./CapacityBalance";
import { ContractsTable } from "./ContractsTable";
import { PortfolioCounts } from "./PortfolioTables";
import { TermsTable } from "./TermsTable";

function html(element: ReactElement): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, element));
}

/** The rows of a table in the markup, each as its own text of markup. */
function rows(markup: string, testId: string): string[] {
  const table = markup.split(`data-testid="${testId}"`)[1]?.split("</table>")[0] ?? "";
  const body = table.split("<tbody>")[1] ?? "";
  return body.split("<tr").slice(1);
}

const VENDOR = "0193a1f4-0000-7000-8000-00000000f001";
const RESELLER = "0193a1f4-0000-7000-8000-00000000f002";
const AGREEMENT = "0193a1f4-0000-7000-8000-00000000a001";

const agreement = {
  hid: AGREEMENT,
  name: "Example Enterprise Agreement",
  number: "EA-0004417",
  vendor_hid: VENDOR,
  vendor: { hid: VENDOR, name: "Cisco" },
  reseller_hid: RESELLER,
  reseller: { hid: RESELLER, name: "Example Reseller" },
  starts_on: "2025-01-01",
  ends_on: "2027-12-31",
  status: "active",
  support_level: "24x7, four-hour response",
  purchase_reference: null,
  account_manager: "Jordan Reyes, +1 555 0142",
  support_contact: "Enterprise support desk, +1 555 0100",
  support_url: "https://support.example.com/enterprise",
  annual_cost: "120000.00",
  notes: null,
  record_status: "active",
  tags: [],
  contracts: 2,
  lapsed: false,
  next_term: null,
  contacts: [],
  effective: {
    account_managers: { value: [], source: "none", source_hid: null },
    support_contacts: { value: [], source: "none", source_hid: null },
  },
  members_to_review: [],
  row_version: 1,
  created_at: "2026-11-14T20:20:37Z",
  updated_at: "2026-11-14T20:20:37Z",
} as Agreement;

const fromAgreement = (value: string) => ({
  value,
  source: "agreement" as const,
  source_hid: AGREEMENT,
  from_agreement: value,
});
const none = { value: null, source: "none" as const, source_hid: null, from_agreement: null };

function contract(number: string, more: Partial<Contract> = {}): Contract {
  const hid = `0193a1f4-0000-7000-8000-0000000${number.slice(-5)}`;
  return {
    hid,
    number,
    vendor_hid: VENDOR,
    vendor: { hid: VENDOR, name: "Cisco" },
    agreement_hid: AGREEMENT,
    agreement: { hid: AGREEMENT, name: agreement.name, number: agreement.number },
    effective: {
      reseller_hid: {
        ...fromAgreement(RESELLER),
        label: "Example Reseller",
        from_agreement_label: "Example Reseller",
      },
      starts_on: fromAgreement("2025-01-01"),
      ends_on: fromAgreement("2027-12-31"),
      support_level: fromAgreement("24x7, four-hour response"),
      account_manager: fromAgreement("Jordan Reyes, +1 555 0142"),
      support_contact: fromAgreement("Enterprise support desk, +1 555 0100"),
      support_url: fromAgreement("https://support.example.com/enterprise"),
      account_managers: { value: [], source: "none", source_hid: null },
      support_contacts: { value: [], source: "none", source_hid: null },
    },
    contacts: [],
    reseller_hid: null,
    reseller: null,
    starts_on: null,
    ends_on: null,
    status: "active",
    support_level: null,
    purchase_reference: "RITM0009121",
    account_manager: null,
    support_contact: null,
    support_url: null,
    annual_cost: "61000.00",
    notes: null,
    record_status: "active",
    tags: [],
    covers_today: true,
    covered_items: 12,
    items_in_scope: 12,
    lapsed: false,
    next_term: null,
    ends_with_term: false,
    renewal_pending_days: null,
    renewal_overdue: false,
    row_version: 1,
    created_at: "2026-11-14T20:20:37Z",
    updated_at: "2026-11-14T20:20:37Z",
    ...more,
  };
}

/** Co-termed with the agreement, and everything from it. */
const coTermed = contract("CON-2025-00001");
/** With a support level of its own, in place of the agreement's, and retired. */
const overriding = contract("CON-2025-00002", {
  support_level: "8x5, next business day",
  covered_items: 3,
  record_status: "retired",
  effective: {
    ...coTermed.effective,
    support_level: {
      value: "8x5, next business day",
      source: "own",
      source_hid: "c-2",
      from_agreement: "24x7, four-hour response",
    },
  },
});
/** One that stands by itself, with a start of its own and no end. */
const alone = contract("CON-2026-00107", {
  agreement_hid: null,
  agreement: null,
  starts_on: "2026-07-01",
  covered_items: 2,
  effective: {
    reseller_hid: { ...none, label: null, from_agreement_label: null },
    starts_on: { value: "2026-07-01", source: "own", source_hid: "c-3", from_agreement: null },
    ends_on: none,
    support_level: none,
    account_manager: none,
    support_contact: none,
    support_url: none,
    account_managers: { value: [], source: "none", source_hid: null },
    support_contacts: { value: [], source: "none", source_hid: null },
  },
});

describe("the contracts of an agreement", () => {
  const markup = html(
    createElement(ContractsTable, {
      contracts: [coTermed, overriding],
      agreement,
      empty: "No contract is grouped into it yet.",
    }),
  );
  const [first = "", second = ""] = rows(markup, "contracts-of");

  it("lists each contract as a link to its page, with how many items it covers", () => {
    expect(markup).toContain('data-agreement="Example Enterprise Agreement"');
    expect(first).toContain('data-contract="CON-2025-00001"');
    expect(first).toContain(`href="/contracts/${coTermed.hid}"`);
    expect(first).toContain('<td class="number">12</td>');
    expect(second).toContain('data-contract="CON-2025-00002"');
  });

  it("shows what a contract has from the agreement lighter, and says from where on hover", () => {
    expect(first).toContain(
      '<td class="inherited" data-field="ends_on" data-standing="inherited" title="Inherited from Example Enterprise Agreement">2027-12-31</td>',
    );
    expect(first).toContain("Nothing: all of it is the agreement");
    expect(first).not.toContain(">Overrides</span>");
  });

  it("marks what a contract says of its own in place of the agreement's, and names the field", () => {
    expect(second).toContain('data-field="support_level" data-standing="override"');
    expect(second).toContain(
      'title="Its own. Overrides 24x7, four-hour response of Example Enterprise Agreement"',
    );
    expect(second).toContain('<span class="badge mark">Overrides</span> Support level');
    // Its dates are still the agreement's.
    expect(second).toContain('data-field="ends_on" data-standing="inherited"');
  });

  it("shows a retired contract greyed, with its record status", () => {
    expect(second).toContain('class="muted"');
    expect(second).toContain('<span class="badge">Retired</span>');
    expect(first).not.toContain("Retired");
  });

  it("has a header to sort by for every column, and no vendor: it is the agreement's", () => {
    const head = markup.split("<thead>")[1]?.split("</thead>")[0] ?? "";
    expect(head.match(/data-sort="/g)).toHaveLength(7);
    expect(head).not.toContain('data-sort="vendor"');
    expect(head).toContain('data-sort="overrides"');
  });
});

describe("the contracts that stand by themselves", () => {
  const markup = html(
    createElement(ContractsTable, { contracts: [alone], agreement: null, empty: "None." }),
  );
  const [row = ""] = rows(markup, "contracts-of");

  it("name the vendor of each, and have nothing to override", () => {
    expect(markup).toContain('data-agreement=""');
    expect(markup).toContain('data-sort="vendor"');
    expect(markup).not.toContain('data-sort="overrides"');
    // 0.9.7: the vendor is a link to its page, in the style of the text (P-232).
    expect(row).toMatch(
      /<td><a class="value-link" href="\/vendors\/[0-9a-f-]+"[^>]*>Cisco<\/a><\/td>/,
    );
    expect(row).not.toContain('data-testid="overrides"');
  });

  it("show a date of its own plainly, and a dash for an end that is open", () => {
    expect(row).toContain('data-field="starts_on" data-standing="own">2026-07-01</td>');
    expect(row).toContain('data-field="ends_on" data-standing="none"><span class="muted">—</span>');
  });

  it("say so when there is none", () => {
    const empty = html(
      createElement(ContractsTable, {
        contracts: [],
        agreement: null,
        empty: "Every contract is grouped into an agreement.",
      }),
    );
    expect(empty).toBe('<p class="muted">Every contract is grouped into an agreement.</p>');
  });
});

/** The worked example of the data model page, with the draft services line beside it. */
function view(more: Partial<CapacityView>): CapacityView {
  return {
    support_weight: "2400",
    items_weight: "2400",
    places_weight: "0",
    circuits_weight: "0",
    defaulted: { items: 0, sites: 0, circuits: 0 },
    raised: { items: 0, sites: 0, circuits: 0 },
    infrastructure_demand: "8",
    other_demand: "2",
    demand: "10",
    supply: "9",
    balance: "-1",
    coverage_pct: "90",
    own_units: "6",
    own_share_pct: "66.67",
    outside_units: "3",
    annual_cost: "57000.00",
    by_category: [
      { category: "staff", label: "Staff", lines: 3, units: "6", annual_cost: "0.00" },
      {
        category: "professional_services",
        label: "Professional services",
        lines: 1,
        units: "1",
        annual_cost: "48000.00",
      },
      {
        category: "smart_hands",
        label: "Smart hands",
        lines: 1,
        units: "0.5",
        annual_cost: "9000.00",
      },
      { category: "tools", label: "Tools", lines: 1, units: "1.5", annual_cost: "0.00" },
      { category: "services", label: "Services", lines: 0, units: "0", annual_cost: "0.00" },
    ],
    multiplying_lines: [],
    demand_by_region: [],
    ...more,
  };
}

const active = view({});
const report: CapacityReport = {
  as_of: "2026-11-14",
  weight_per_resource_unit: "300",
  active,
  with_drafts: view({
    supply: "10",
    balance: "0",
    coverage_pct: "100",
    outside_units: "4",
    own_share_pct: "60",
    annual_cost: "81000.00",
    by_category: active.by_category.map((row) =>
      row.category === "services" ? { ...row, lines: 1, units: "1", annual_cost: "24000.00" } : row,
    ),
  }),
};

describe("demand beside supply, as rows", () => {
  const made = balanceRows(report);

  it("has the two parts of the demand first, then every category that supplies", () => {
    expect(made.map((row) => `${row.side} ${row.key}`)).toEqual([
      "Demand infrastructure_demand",
      "Demand other_demand",
      "Supply staff",
      "Supply professional_services",
      "Supply smart_hands",
      "Supply tools",
      "Supply services",
    ]);
  });

  it("gives each row what both views answer for it", () => {
    expect(made[0]).toMatchObject({ active: "8", drafts: "8", lines: null, cost: null });
    // The draft line is a supply of the view with drafts alone.
    expect(made.at(-1)).toMatchObject({
      name: "Services",
      active: "0",
      drafts: "1",
      lines: 0,
      draftLines: 1,
      cost: "0.00",
      draftCost: "24000.00",
    });
  });
});

describe("the capacity balance", () => {
  const markup = html(createElement(Balance, { report, money: " (USD)" }));

  it("shows every measure of the view without the drafts, as the server sent it", () => {
    expect(markup).toContain('data-testid="capacity-active" data-balance="short"');
    expect(markup).toContain('<dd data-testid="active-demand" data-value="10">10</dd>');
    expect(markup).toContain('<dd data-testid="active-supply" data-value="9">9</dd>');
    // A shortfall is written with a minus sign, and said in words.
    expect(markup).toContain('<dd data-testid="active-balance" data-value="-1">−1</dd>');
    expect(markup).toContain('<dd data-testid="active-coverage_pct" data-value="90">90%</dd>');
    expect(markup).toContain(
      '<dd data-testid="active-own_share_pct" data-value="66.67">66.67%</dd>',
    );
    expect(markup).toContain(
      '<p class="warning" data-testid="active-balance-words">Short: demand is more than supply.</p>',
    );
  });

  it("shows the view with the drafts beside it: the balance is then zero", () => {
    expect(markup).toContain('data-testid="capacity-with_drafts" data-balance="even"');
    expect(markup).toContain('<dd data-testid="with_drafts-supply" data-value="10">10</dd>');
    expect(markup).toContain('<dd data-testid="with_drafts-balance" data-value="0">0</dd>');
    expect(markup).toContain('<p data-testid="with_drafts-balance-words">Supply meets demand.</p>');
  });

  it("lists demand beside supply by category, each with its units in both views", () => {
    const made = rows(markup, "capacity-sides");
    expect(made).toHaveLength(7);
    const services = made.find((row) => row.includes('data-row="services"')) ?? "";
    expect(services).toContain('data-side="supply"');
    expect(services).toContain('data-testid="units-active" data-value="0">0</td>');
    expect(services).toContain('data-testid="units-with-drafts" data-value="1">1</td>');
    const infrastructure = made.find((row) => row.includes('data-row="infrastructure_demand"'));
    expect(infrastructure).toContain('data-side="demand"');
    expect(infrastructure).toContain('data-value="8">8</td>');
  });

  it("names the currency after the costs, and the weight of one resource unit", () => {
    expect(markup).toContain("Annual cost (USD)");
    expect(markup).toContain("One resource unit carries a support weight of 300");
    expect(markup).toContain("as of 2026-11-14");
  });

  it("shows a coverage that is blank, when there is no demand, as a dash", () => {
    const idle = html(
      createElement(Balance, {
        report: { ...report, active: view({ demand: "0", balance: "9", coverage_pct: null }) },
        money: "",
      }),
    );
    expect(idle).toContain('<dd data-testid="active-coverage_pct" data-value="">—</dd>');
    expect(idle).toContain('data-testid="capacity-active" data-balance="over"');
  });
});

type Portfolio = Schemas["PortfolioOut"];

const measures = (items: number, covered: number) => ({
  items,
  component_count: items,
  support_weight: items === 0 ? "0" : "0.8",
  est_value: items === 0 ? "0.00" : "5600.00",
  annual_support_cost: items === 0 ? "0.00" : "380.00",
  covered,
  uncovered: items - covered,
});

const portfolio: Portfolio = {
  vendor: { hid: VENDOR, name: "Cisco" },
  as_of: "2026-11-14",
  totals: {
    items: 29,
    component_count: 23,
    support_weight: "20.5",
    est_value: "346760.00",
    annual_support_cost: "30960.00",
    covered: 20,
    uncovered: 4,
  },
  kinds: [
    { ...measures(4, 4), kind: "hardware" },
    { ...measures(0, 0), kind: "virtual_machine" },
    { ...measures(0, 0), kind: "software" },
    { ...measures(0, 0), kind: "service" },
  ],
  models: [
    {
      ...measures(4, 4),
      catalog_entry_hid: "0193a1f4-0000-7000-8000-00000000e001",
      pid: "C9130AXI-B",
      model_name: "Catalyst 9130AX access point",
      kind: "hardware",
      type: "access-point",
      function: "wireless",
      end_of_sale: null,
      end_of_sw_support: null,
      end_of_hw_support: null,
      ldos: "2032-05-31",
      covered_until: "2027-12-31",
    },
  ],
  agreements: [agreement],
  // One the vendor provides, and one that was bought through it from another.
  contracts: [
    coTermed,
    contract("CON-2026-00301", {
      vendor_hid: "0193a1f4-0000-7000-8000-00000000f003",
      vendor: { hid: "0193a1f4-0000-7000-8000-00000000f003", name: "Juniper" },
      agreement: null,
      agreement_hid: null,
    }),
  ],
  capacity_lines: [
    {
      hid: "0193a1f4-0000-7000-8000-00000000d001",
      side: "supply",
      category: "professional_services",
      category_label: "Professional services",
      name: "Escalation partner",
      effect: "add",
      quantity: "1",
      units_each: "1",
      units: "1",
      factor: null,
      share: null,
      applies_to: [],
      annual_cost: "48000.00",
      vendor_hid: VENDOR,
      vendor: { hid: VENDOR, name: "Cisco" },
      region_hid: null,
      region: null,
      site_hid: null,
      site: null,
      starts_on: null,
      ends_on: null,
      in_date: true,
      notes: null,
      record_status: "draft",
      row_version: 1,
      created_at: "2026-11-14T20:20:54Z",
      updated_at: "2026-11-14T20:20:54Z",
    },
  ],
  filter: { field: "catalog.vendor_hid", op: "eq", value: VENDOR },
};

describe("what a portfolio counts", () => {
  const markup = html(
    createElement(PortfolioCounts, { portfolio, money: " (USD)", choices: undefined }),
  );

  it("shows the totals as the server counted them, the money with its thousands marked", () => {
    expect(markup).toContain('<dd data-testid="portfolio-items">29</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-components">23</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-weight">20.5</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-value">346,760.00</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-cost">30,960.00</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-covered">20</dd>');
    expect(markup).toContain('<dd data-testid="portfolio-uncovered">4</dd>');
    expect(markup).toContain("Estimated value (USD)");
  });

  it("lists all four kinds, also the ones the vendor has nothing of", () => {
    const kinds = rows(markup, "portfolio-kinds");
    expect(kinds.map((row) => /data-kind="([a-z_]+)"/.exec(row)?.[1])).toEqual([
      "hardware",
      "virtual_machine",
      "software",
      "service",
    ]);
    expect(kinds[0]).toContain('<th scope="row">Hardware</th>');
    expect(kinds[0]).toContain('<td class="number" data-measure="cost">380.00</td>');
    // A kind with nothing of it is still a row, shown greyed.
    expect(kinds[1]).toContain('class="muted"');
    expect(kinds[1]).toContain('<td class="number" data-measure="items">0</td>');
  });

  it("lists each model with its dates and the day the first of its covers runs out", () => {
    const [model = ""] = rows(markup, "portfolio-models");
    expect(model).toContain('data-pid="C9130AXI-B"');
    expect(model).toContain('href="/catalog/0193a1f4-0000-7000-8000-00000000e001"');
    expect(model).toContain('<td class="nowrap" data-testid="model-ldos">2032-05-31</td>');
    expect(model).toContain('<td class="nowrap" data-testid="model-covered-until">2027-12-31</td>');
    expect(model).toContain('<td class="number" data-measure="covered">4</td>');
  });

  it("lists the agreements with the vendor, each a link", () => {
    const [row = ""] = rows(markup, "portfolio-agreements");
    expect(row).toContain(`href="/agreements/${AGREEMENT}"`);
    expect(row).toContain("EA-0004417");
    expect(row).toContain('<td class="number">2</td>');
  });

  it("says of each contract whether the vendor provides it or it was bought through it", () => {
    const [provided = "", through = ""] = rows(markup, "portfolio-contracts");
    expect(provided).toContain("<td>Provides it</td>");
    expect(provided).toContain(`href="/agreements/${AGREEMENT}"`);
    // Dates that are the agreement's are shown lighter.
    expect(provided).toContain('class="nowrap inherited"');
    expect(provided).toContain('<td class="number">61,000.00</td>');
    expect(through).toContain("<td>Bought through it</td>");
    expect(through).toContain("Stands by itself");
  });

  it("lists the capacity lines that name the vendor, a draft one marked and not counting", () => {
    const [line = ""] = rows(markup, "portfolio-capacity");
    expect(line).toContain('href="/capacity/0193a1f4-0000-7000-8000-00000000d001"');
    expect(line).toContain('<span class="badge">Draft</span>');
    expect(line).toContain("<td>Professional services</td>");
    expect(line).toContain("<td>No</td>");
  });

  it("says so where the vendor has none of a thing", () => {
    const bare = html(
      createElement(PortfolioCounts, {
        portfolio: { ...portfolio, models: [], agreements: [], contracts: [], capacity_lines: [] },
        money: "",
        choices: undefined,
      }),
    );
    expect(bare).toContain("No model of this vendor has an item in view.");
    expect(bare).toContain("There is no support agreement with this vendor.");
    expect(bare).toContain("This vendor provides no contract, and none was bought through it.");
    expect(bare).toContain("No capacity line names this vendor.");
  });
});

describe("the terms a contract had before it was renewed", () => {
  const term = (number: string, more: Partial<Schemas["ContractTerm"]> = {}) =>
    ({
      number,
      starts_on: "2025-01-01",
      ends_on: "2025-12-31",
      starts_on_source: "own",
      ends_on_source: "own",
      agreement_hid: null,
      annual_cost: "18000.00",
      purchase_reference: "RITM0009122",
      renewed_at: "2026-11-14T20:20:37Z",
      renewed_by: null,
      renewed_by_name: "jordan.reyes",
      ...more,
    }) as Schemas["ContractTerm"];
  /** One co-termed with its agreement: both of its dates were the agreement's then. */
  const coTermed = term("CON-2024-0001", {
    starts_on: "2024-01-01",
    ends_on: "2024-12-31",
    starts_on_source: "agreement",
    ends_on_source: "agreement",
    agreement_hid: AGREEMENT,
  });
  /** One with a start of its own and no end at all. */
  const open = term("CON-2023-0001", { ends_on: null, ends_on_source: "none" });
  const markup = html(
    createElement(TermsTable<Schemas["ContractTerm"]>, {
      terms: [coTermed, term("CON-2025-0001"), open],
      testId: "contract-terms",
      caption: "The terms",
      money: " (USD)",
      inheritedFrom: (one) => (one.agreement_hid === AGREEMENT ? agreement.name : "its agreement"),
    }),
  );
  const [first = "", second = "", third = ""] = rows(markup, "contract-terms");

  it("shows a date it had from its agreement lighter, with the agreement it came from", () => {
    expect(first).toContain('data-term="CON-2024-0001"');
    expect(first).toContain('class="nowrap inherited" data-source="agreement"');
    expect(first).toContain("2024-01-01");
    expect(first).toContain(`(inherited from ${agreement.name})`);
    expect(first).toContain(
      `title="Inherited from ${agreement.name}: the date of the agreement&#x27;s term this term began in`,
    );
  });

  it("shows a date of its own plainly, and none as a dash", () => {
    expect(second).toContain('<td class="nowrap" data-source="own">2025-01-01</td>');
    expect(second).not.toContain("inherited");
    expect(third).toContain('data-source="none"');
    expect(third).toContain("—");
  });
});
