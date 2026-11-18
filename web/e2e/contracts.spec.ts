// The browser scenarios of contracts in release 0.6.0, as a person meets them:
//
//   D-139  A support agreement, a contract made in it that has its period and whom to
//          ask from it, an override and giving it up, a contract that stands by itself
//          rolled into the agreement and taken out again.
//   D-137  The rows selected in the item grid put under a contract in one request; the
//          contract renewed in one place, with every item in scope showing the new number
//          at once and the term before kept as history; a coverage ended with a date.
//   D-140  A renewal entered before its period begins is kept as the next term, shown on
//          the contract and in the list, and withdrawn again.
//   S29    One contract covering items in two regions, one of them archived: the
//          archived item's coverage ended on the day it left, and the coverage report
//          lists it as out of service under a contract that still runs.
//   S30    An item in Prod with no coverage, and items whose model's last day of support
//          is next year: each is on its report, and each count leads to its rows.
//
// It keeps to the rules of support.ts: an account and names of its own, every report and
// every grid filtered down to this file's records before anything is counted, and nothing
// changed that another file reads. The dates are worked out from today, so that the
// agreement is in force whenever the file is run.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, main, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("contracts", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-48P-${suffix}`;
const west = `West ${suffix}`;
const east = `East ${suffix}`;
const westSite = `Site-W ${suffix}`;
const eastSite = `Site-E ${suffix}`;
const westRoom = `${west} > ${westSite} > Room 1`;
const eastRoom = `${east} > ${eastSite} > Room 1`;
const prefix = `site9-sw-${suffix}`;
// The first is covered, the second is covered and then archived, the third is never covered.
const [covered, archived, bare] = [1, 2, 3].map((place) => `${prefix}-0${place}`) as [
  string,
  string,
  string,
];
const own = `hostname:prefix:${prefix}`;

const agreement = `Example Enterprise Agreement ${suffix}`;
const agreementStarts = `${year - 1}-01-01`;
const agreementEnds = `${year + 1}-12-31`;
const supportLevel = "24x7, four-hour response";
const manager = "Jordan Reyes, jordan.reyes@example.com, +1 555 0142";
const firstNumber = `CON-${suffix}-1`;
const renewedNumber = `CON-${suffix}-2`;
const renewedStarts = `${year}-01-01`;
const renewedEnds = `${year + 2}-12-31`;
// A renewal that is entered before its period begins.
const earlyNumber = `CON-${suffix}-2E`;
const earlyStarts = `${year + 2}-01-01`;
const earlyEnds = `${year + 3}-12-31`;
const aloneNumber = `CON-${suffix}-9`;
// A day of its own for one coverage, within the agreement's period and well before today.
const bareStarts = `${year - 1}-06-01`;

function gridRow(page: Page, grid: string, text: string): Locator {
  return page.getByTestId(grid).locator("[row-id]", { hasText: text });
}

/** One field of a contract as it is in force, on the page of the contract. */
function inForce(page: Page, field: string): Locator {
  return page.getByTestId("contract-in-force").locator(`[data-field="${field}"]`);
}

/** Open a contract from the grid of contracts, by its number. */
async function openContract(page: Page, number: string) {
  await page.goto(`./contracts?filter=${encodeURIComponent(`number:eq:${number}`)}`);
  await page.getByTestId("grid-contracts").getByRole("link", { name: number, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
}

/** Find a contract in a form by its number, and choose it. */
async function pickContract(form: Locator, number: string) {
  await form.getByLabel("Contract", { exact: true }).fill(number);
  await form
    .getByRole("list", { name: "Contracts that match" })
    .getByRole("button", { name: new RegExp(`^${number} `) })
    .click();
  await expect(form.getByTestId("chosen-contract_hid")).toContainText(number);
}

/** Move the item on show to another state, with a reason. */
async function move(page: Page, to: string, reason: string) {
  const form = region(page, "Move to another state");
  await form.getByLabel("Move to").selectOption(to);
  await form.getByLabel("Reason").selectOption({ label: reason });
  await form.getByRole("button", { name: "Move" }).click();
  await expect(page.getByTestId("state")).toHaveText(to);
}

test("the model, two regions and three switches in service are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  // The last day of support of the model is next year: S30.
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "ldos", "support_weight", "annual_support_cost"],
    [[vendor, pid, "Example 9300 48-port", "switch", `${year + 1}-06-30`, "1.00", "1200.00"]],
  );
  await importFile(page, "regions", `regions-${suffix}.csv`, ["name"], [[west], [east]]);
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region"],
    [
      [westSite, west],
      [eastSite, east],
    ],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [
      ["Room 1", `${west} > ${westSite}`, "room"],
      ["Room 1", `${east} > ${eastSite}`, "room"],
    ],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "location"],
    [
      [vendor, pid, `ENS${upper}01`, covered, "Prod", westRoom],
      [vendor, pid, `ENS${upper}02`, archived, "Prod", eastRoom],
      [vendor, pid, `ENS${upper}03`, bare, "Prod", westRoom],
    ],
  );
  await expectClean(page, seen);
});

test("D-139: an agreement, a contract in it, what the contract has from it and what it overrides", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // A support agreement with the vendor: its period, its support level and whom to ask.
  await main(page).getByRole("link", { name: "Contracts", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Contracts" })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Contracts" })
    .getByRole("link", { name: "Support agreements" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Support agreements" })).toBeVisible();
  await page.getByRole("button", { name: "New agreement" }).click();
  const newAgreement = region(page, "New support agreement");
  await newAgreement.getByLabel("Name (required)").fill(agreement);
  await newAgreement.getByLabel("Number", { exact: true }).fill(`EA-${upper}`);
  await newAgreement.getByLabel("Vendor (required)").selectOption({ label: vendor });
  await newAgreement.getByLabel("Starts on").fill(agreementStarts);
  await newAgreement.getByLabel("Ends on").fill(agreementEnds);
  await newAgreement.getByLabel("Support level").fill(supportLevel);
  await newAgreement.getByLabel("Account manager").fill(manager);
  await newAgreement.getByLabel("Support URL").fill("https://support.example.com/enterprise");
  await newAgreement.getByRole("button", { name: "Create agreement" }).click();
  await expect(page.getByRole("heading", { level: 1, name: agreement })).toBeVisible();
  await expect(page.getByTestId("agreement-period")).toHaveText(
    `${agreementStarts} to ${agreementEnds}`,
  );
  await expect(region(page, "Its contracts")).toContainText("No contract is grouped into it yet.");

  // A contract made in the agreement: only its number is said. It is with the
  // agreement's vendor, and everything else it has from the agreement.
  await page.getByRole("button", { name: "New contract in this agreement" }).click();
  const newContract = region(page, `New contract in ${agreement}`);
  await expect(newContract.getByLabel("Vendor")).toHaveCount(0);
  await newContract.getByLabel("Number (required)").fill(firstNumber);
  await newContract.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: firstNumber })).toBeVisible();
  await expect(page.getByTestId("contract-agreement")).toHaveText(agreement);
  await expect(page.getByTestId("contract-facts")).toContainText(vendor);
  // What is inherited is seen to be inherited, with the agreement it came from.
  for (const [field, text] of [
    ["starts_on", agreementStarts],
    ["ends_on", agreementEnds],
    ["support_level", supportLevel],
    ["account_manager", manager],
  ] as const) {
    await expect(inForce(page, field)).toHaveAttribute("data-standing", "inherited");
    await expect(inForce(page, field)).toContainText(text);
    await expect(inForce(page, field)).toContainText("Inherited");
    await expect(inForce(page, field).getByRole("link", { name: agreement })).toBeVisible();
  }
  // The support address is a link that opens apart.
  await expect(inForce(page, "support_url").getByTestId("support-url")).toHaveAttribute(
    "href",
    "https://support.example.com/enterprise",
  );
  // What neither says is not set.
  await expect(inForce(page, "support_contact")).toHaveAttribute("data-standing", "none");
  await expect(page.getByTestId("covers-today")).toHaveText("Yes");
  await expect(page.getByTestId("no-terms")).toBeVisible();

  // A support level of its own is an override, and says what it overrides.
  const details = region(page, "Details");
  await expect(details.getByText(`Blank has ${supportLevel} from ${agreement}.`)).toBeVisible();
  await details.getByLabel("Support level").fill("8x5, next business day");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The contract was saved.")).toBeVisible();
  await expect(inForce(page, "support_level")).toHaveAttribute("data-standing", "override");
  await expect(inForce(page, "support_level")).toContainText("8x5, next business day");
  await expect(inForce(page, "support_level")).toContainText("Overrides");
  await expect(inForce(page, "support_level")).toContainText(supportLevel);
  // Its dates are still the agreement's.
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "inherited");

  // The agreement lists its contracts, with what each has from it and what each overrides.
  await page.getByRole("link", { name: agreement }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: agreement })).toBeVisible();
  const ofAgreement = page
    .getByTestId("agreement-contracts")
    .locator(`tr[data-contract="${firstNumber}"]`);
  await expect(ofAgreement.locator('[data-field="ends_on"]')).toHaveAttribute(
    "data-standing",
    "inherited",
  );
  await expect(ofAgreement.locator('[data-field="ends_on"]')).toContainText(agreementEnds);
  await expect(ofAgreement.locator('[data-field="support_level"]')).toHaveAttribute(
    "data-standing",
    "override",
  );
  await expect(ofAgreement.locator('[data-field="support_level"]')).toContainText("Overrides");

  // The override is given up on the contract: the agreement speaks again.
  await ofAgreement.getByRole("link", { name: firstNumber }).click();
  await expect(page.getByRole("heading", { level: 1, name: firstNumber })).toBeVisible();
  await inForce(page, "support_level")
    .getByRole("button", { name: /Have the agreement's again/ })
    .click();
  await expect(
    page.getByText(`${firstNumber} has the support level of ${agreement} again.`),
  ).toBeVisible();
  await expect(inForce(page, "support_level")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "support_level")).toContainText(supportLevel);

  // A contract that stands by itself, with a start of its own.
  await page.goto("./contracts");
  await page.getByRole("button", { name: "New contract" }).click();
  const standalone = region(page, "New contract");
  await standalone.getByLabel("Number (required)").fill(aloneNumber);
  await standalone.getByLabel("Vendor", { exact: true }).selectOption({ label: vendor });
  await standalone.getByLabel("Starts on").fill(renewedStarts);
  await standalone.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: aloneNumber })).toBeVisible();
  await expect(page.getByTestId("contract-agreement")).toHaveText("None: it stands by itself");
  await expect(inForce(page, "starts_on")).toHaveAttribute("data-standing", "own");
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "none");

  // It is rolled into the agreement, which is one change of the contract. What it says
  // of its own stays, as an override; the rest it has from the agreement at once.
  const grouping = region(page, "Support agreement");
  await grouping.getByLabel("Put it into").selectOption({ label: `${agreement} (${vendor})` });
  await grouping.getByRole("button", { name: "Put into the agreement" }).click();
  await expect(page.getByText(`${aloneNumber} is now grouped into ${agreement}.`)).toBeVisible();
  await expect(page.getByTestId("contract-agreement")).toHaveText(agreement);
  await expect(inForce(page, "starts_on")).toHaveAttribute("data-standing", "override");
  await expect(inForce(page, "starts_on")).toContainText(renewedStarts);
  await expect(inForce(page, "starts_on")).toContainText(agreementStarts);
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "ends_on")).toContainText(agreementEnds);

  // The page of contracts groups both under the agreement, once its tables by agreement
  // are opened (P-212).
  await page.goto("./contracts");
  await page.getByTestId("contracts-grouped-line").click();
  const grouped = page
    .getByTestId("contracts-grouped")
    .locator(`table[data-agreement="${agreement}"]`);
  await expect(grouped.locator(`tr[data-contract="${firstNumber}"]`)).toBeVisible();
  await expect(grouped.locator(`tr[data-contract="${aloneNumber}"]`)).toBeVisible();
  await expect(
    grouped.locator(`tr[data-contract="${aloneNumber}"]`).getByTestId("overrides"),
  ).toContainText("Starts on");
  await expect(
    grouped.locator(`tr[data-contract="${firstNumber}"]`).getByTestId("overrides"),
  ).toContainText("Nothing");

  // And it is taken out again: it stands by itself, with only what it says of its own.
  await grouped.getByRole("link", { name: aloneNumber }).click();
  await expect(page.getByRole("heading", { level: 1, name: aloneNumber })).toBeVisible();
  await region(page, "Support agreement")
    .getByRole("button", { name: `Take out of ${agreement}` })
    .click();
  await expect(
    page.getByText(`${aloneNumber} was taken out of ${agreement}: it stands by itself.`),
  ).toBeVisible();
  await expect(page.getByTestId("contract-agreement")).toHaveText("None: it stands by itself");
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "none");

  await expectClean(page, seen);
});

test("D-137: rows of the item grid covered by one contract, the contract renewed in one place", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Two of the three switches are selected in the grid and put under the contract.
  await page.goto(`./items?filter=${encodeURIComponent(own)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await gridRow(page, "grid-items", covered).locator('[col-id="catalog.pid"]').click();
  await gridRow(page, "grid-items", archived)
    .locator('[col-id="catalog.pid"]')
    .click({ modifiers: ["ControlOrMeta"] });
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const cover = page.getByTestId("cover-items");
  await expect(cover.getByRole("heading", { name: "Cover 2 items with a contract" })).toBeVisible();
  await pickContract(cover, firstNumber);
  await cover.getByRole("button", { name: "Cover 2 items" }).click();
  await expect(
    page.getByText(`2 items are now under ${firstNumber}. Nothing was written to any of them.`),
  ).toBeVisible();

  // The grid says which are covered, until when and by what, once those columns are
  // asked for: they are hidden until then.
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  for (const column of ["Covered", "Covered until", "Contracts"]) {
    await expect(columns.getByLabel(column, { exact: true })).not.toBeChecked();
    await columns.getByLabel(column, { exact: true }).check();
  }
  // Room is made for them: the grid draws only the columns in view.
  for (const column of [
    "Serial number",
    "Disposition",
    "Expected online",
    "Health",
    "Owner",
    "Operator",
    "Tags",
    "LDoS",
  ]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  await expect(gridRow(page, "grid-items", covered).locator('[col-id="covered"]')).toHaveText(
    "Yes",
  );
  await expect(gridRow(page, "grid-items", covered).locator('[col-id="covered_until"]')).toHaveText(
    agreementEnds,
  );
  await expect(
    gridRow(page, "grid-items", covered).locator('[col-id="contract.number"]'),
  ).toHaveText(firstNumber);
  await expect(gridRow(page, "grid-items", bare).locator('[col-id="covered"]')).toHaveText("No");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();

  // The contract shows the two items it covers, as a grid, each with the contract's days.
  await openContract(page, firstNumber);
  await expect(page.getByTestId("covered-items")).toHaveText("2 items");
  await expect(page.getByTestId("items-in-scope")).toContainText("2 items");
  await expect(page.getByTestId("grid-total")).toHaveText("2 coverages");
  const coverage = "grid-contract-coverage";
  await expect(gridRow(page, coverage, covered).locator('[col-id="effective.ends_on"]')).toHaveText(
    agreementEnds,
  );
  // The day is the contract's, which has it from its agreement: it is shown as inherited.
  await expect(
    gridRow(page, coverage, covered).locator('[col-id="effective.ends_on"]'),
  ).toHaveClass(/cell-inherited/);
  await expect(gridRow(page, coverage, archived).locator('[col-id="in_force"]')).toHaveText("Yes");

  // The third switch is added from the page of the contract, and its coverage is ended
  // again with a date: nothing is removed.
  await page.getByRole("button", { name: "Add items" }).click();
  const adding = page.getByTestId("add-coverage");
  await adding.getByLabel("Add an item", { exact: true }).fill(bare);
  await adding
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${bare}( |$)`) })
    .click();
  await expect(adding.getByTestId("coverage-pending")).toContainText(bare);
  await adding.getByLabel("Covered from").fill(bareStarts);
  await adding.getByRole("button", { name: "Cover 1 item" }).click();
  await expect(
    page.getByText(`1 item was put under ${firstNumber}. Nothing was written to it.`),
  ).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 coverages");
  // A start of its own is shown plainly.
  await expect(
    gridRow(page, coverage, bare).locator('[col-id="effective.starts_on"]'),
  ).not.toHaveClass(/cell-inherited/);
  await gridRow(page, coverage, bare).locator('[col-id="item.pid"]').click();
  await page.getByRole("button", { name: "End coverage" }).click();
  const ending = page.getByTestId("end-coverage");
  await expect(ending).toContainText(`End the coverage of ${bare} under ${firstNumber}`);
  // It is ended yesterday, so that it covers no longer: an end of today would still hold.
  const today = await ending.getByLabel("Last day (required)").inputValue();
  expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  const yesterday = new Date(`${today}T12:00:00Z`);
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const lastDay = yesterday.toISOString().slice(0, 10);
  await ending.getByLabel("Last day (required)").fill(lastDay);
  await ending.getByRole("button", { name: "End coverage" }).click();
  await expect(
    page.getByText(`1 coverage was ended on ${lastDay}. Nothing was removed.`),
  ).toBeVisible();
  // The row is still there, with its last day, and is in force no longer.
  await expect(page.getByTestId("grid-total")).toHaveText("3 coverages");
  await expect(gridRow(page, coverage, bare).locator('[col-id="effective.ends_on"]')).toHaveText(
    lastDay,
  );
  await expect(gridRow(page, coverage, bare).locator('[col-id="in_force"]')).toHaveText("No");
  await expect(page.getByTestId("covered-items")).toHaveText("2 items");
  await expect(page.getByTestId("items-in-scope")).toContainText("2 items");

  // Renew. A renewal that gives neither a new number nor a new period is no renewal,
  // and the form says so before anything is sent.
  const renew = region(page, "Renew");
  await expect(page.getByTestId("renew-scope")).toContainText("2 items");
  await renew.getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  await form.getByLabel("Annual cost").fill("61000");
  await form.getByRole("button", { name: "Renew for 2 items" }).click();
  await expect(
    form.getByText("A renewal gives the contract a new number, a new period, or both."),
  ).toBeVisible();
  // D-140: a renewal entered early, with a period that begins after today, is kept as
  // the next term. The present number and period stay in force until that day.
  await form.getByLabel("New number").fill(earlyNumber);
  await form.getByLabel("New period: starts on").fill(earlyStarts);
  await form.getByLabel("New period: ends on").fill(earlyEnds);
  await form.getByRole("button", { name: "Renew for 2 items" }).click();
  await expect(page.getByText(/^The renewal is kept as the next term\./)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: firstNumber })).toBeVisible();
  await expect(page.getByTestId("contract-number")).toHaveText(firstNumber);
  const next = page.getByTestId("next-term");
  await expect(next).toHaveAttribute("data-starts", earlyStarts);
  await expect(next).toContainText(
    `Renews as ${earlyNumber} on ${earlyStarts}, until ${earlyEnds}.`,
  );
  await expect(page.getByTestId("contract-next-term")).toContainText(earlyNumber);
  // The list of contracts finds it by the day its next term begins, under the number
  // that is in force.
  const withNext = `number:eq:${firstNumber} next_starts_on:eq:${earlyStarts}`;
  await page.goto(`./contracts?filter=${encodeURIComponent(withNext)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 contract");
  await expect(
    page.getByTestId("grid-contracts").getByRole("link", { name: firstNumber, exact: true }),
  ).toBeVisible();
  // It was entered too early: the next term is withdrawn, and the contract is as it was.
  await openContract(page, firstNumber);
  await page
    .getByTestId("next-term")
    .getByRole("button", { name: "Withdraw the next term" })
    .click();
  await page.getByRole("button", { name: "Withdraw", exact: true }).click();
  await expect(
    page.getByText(
      `The next term was withdrawn: ${firstNumber} keeps its present number and period.`,
    ),
  ).toBeVisible();
  await expect(page.getByTestId("next-term")).toHaveCount(0);
  await expect(page.getByTestId("contract-number")).toHaveText(firstNumber);

  // The renewal itself, in force at once: the new number and the new period are one
  // change of the one record.
  await renew.getByRole("button", { name: "Renew", exact: true }).click();
  await form.getByLabel("New number").fill(renewedNumber);
  await form.getByLabel("New period: starts on").fill(renewedStarts);
  await form.getByLabel("New period: ends on").fill(renewedEnds);
  await form.getByLabel("Purchase reference").fill(`RITM-${upper}`);
  await form.getByRole("button", { name: "Renew for 2 items" }).click();
  await expect(
    page.getByText(new RegExp(`^Renewed as ${renewedNumber}, .*2 items follow`)),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: renewedNumber })).toBeVisible();
  await expect(page.getByTestId("contract-number")).toHaveText(renewedNumber);
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "override");
  await expect(inForce(page, "ends_on")).toContainText(renewedEnds);
  // The term it had before is its history.
  const term = page.getByTestId("contract-terms").locator(`tr[data-term="${firstNumber}"]`);
  await expect(term).toBeVisible();
  await expect(term).toContainText(account.username);
  // The coverage followed: the days in force are those of the new period.
  await expect(gridRow(page, coverage, covered).locator('[col-id="effective.ends_on"]')).toHaveText(
    renewedEnds,
  );
  // The one that was ended on a day of its own stays ended.
  await expect(gridRow(page, coverage, bare).locator('[col-id="effective.ends_on"]')).toHaveText(
    lastDay,
  );

  // An item in scope shows the new number and the new period at once, and its own
  // history holds no change: nothing was written to it.
  await openItem(page, covered);
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "true");
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);
  await expect(page.getByTestId("item-contract-count")).toHaveAttribute("data-count", "1");
  const itemCoverage = page.getByTestId("item-coverage");
  await expect(itemCoverage.locator("tbody tr")).toHaveCount(1);
  await expect(itemCoverage.locator(`tr[data-contract="${renewedNumber}"]`)).toHaveAttribute(
    "data-in-force",
    "true",
  );
  await expect(region(page, "History").locator('tbody[data-action="update"]')).toHaveCount(0);

  // The switch whose coverage was ended is under the contract no longer, and says so.
  await openItem(page, bare);
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "false");
  await expect(
    page.getByTestId("item-coverage").locator(`tr[data-contract="${renewedNumber}"]`),
  ).toHaveAttribute("data-in-force", "false");

  await expectClean(page, seen);
});

test("S29, S30: cover on an archived item, an item with no cover, and the end of support next year", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The switch in the other region leaves service and is archived. Its coverage is
  // ended on the day it leaves, which is its last day: the contract runs on for two
  // years and covers the switch no longer than today. The coverage is marked as one the
  // vendor still counts until it has been told.
  await openItem(page, archived);
  await move(page, "Pending-Removal", "Decommissioned");
  await move(page, "Released", "Decommissioned");
  await move(page, "Archived", "Decommissioned");
  const ended = page.getByTestId("item-coverage").locator(`tr[data-contract="${renewedNumber}"]`);
  await expect(ended).toHaveAttribute("data-left-service", "true");
  await expect(ended.getByTestId("left-service")).toBeVisible();
  const until = page.getByTestId("item-covered-until");
  await expect(until).toHaveText(/^\d{4}-\d{2}-\d{2}$/);
  const lastDay = ((await until.textContent()) ?? "").trim();
  // The day is today as the server has it: the browser's day, or the one beside it
  // where the two are in different time zones.
  const near = [-1, 0, 1].map((days) =>
    new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10),
  );
  expect(near).toContain(lastDay);
  expect(lastDay < renewedEnds).toBe(true);
  await expect(ended).toContainText(lastDay);

  // The coverage report, of this file's switches: two are in service, one of them with
  // no cover, and one is out of service under a contract that still runs.
  await page.goto(`./reports/coverage?filter=${encodeURIComponent(own)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Coverage" })).toBeVisible();
  await expect(page.getByTestId("total-in-service")).toHaveText("2");
  await expect(page.getByTestId("total-covered")).toHaveText("1");
  await expect(page.getByTestId("total-uncovered")).toHaveText("1");
  await expect(page.getByTestId("total-out-of-service")).toHaveText("1");
  await expect(page.getByTestId("count-uncovered")).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("count-out_of_service")).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("count-expiring")).toHaveAttribute("data-count", "0");
  // No switch of this file is under two contracts, or under one whose renewal is late.
  await expect(page.getByTestId("count-overlapping")).toHaveAttribute("data-count", "0");
  await expect(page.getByTestId("count-renewal_pending")).toHaveAttribute("data-count", "0");

  // S30: the counts come first, and no list is read until one is opened (P-133). The list
  // of what is in service with no cover, opened, is a grid.
  await expect(page.getByTestId("no-list-open")).toBeVisible();
  await expect(page.getByTestId("section-heading")).toHaveCount(0);
  await page
    .locator('.section-card[data-section="uncovered"]')
    .getByRole("button", { name: "Show these items" })
    .click();
  await expect(page.getByTestId("section-heading")).toHaveText("In service with no cover");
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(
    page.getByTestId("grid-coverage-uncovered").getByRole("link", { name: bare, exact: true }),
  ).toBeVisible();

  // S29: the archived switch is listed as out of service and still counted, under the
  // contract that still runs, with the day its coverage ended.
  await page
    .locator('.section-card[data-section="out_of_service"]')
    .getByRole("button", { name: "Show these items" })
    .click();
  await expect(page.getByTestId("section-heading")).toHaveText("Out of service, and still counted");
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  const listed = gridRow(page, "grid-coverage-out_of_service", archived);
  await expect(listed.getByRole("link", { name: archived, exact: true })).toBeVisible();
  await expect(listed.locator('[col-id="out_of_service_contract.number"]')).toHaveText(
    renewedNumber,
  );
  await expect(listed.locator('[col-id="covered_until"]')).toHaveText(lastDay);
  await expect(listed.locator('[col-id="lifecycle_state"]')).toHaveText("Archived");
  // An archived item is shown greyed.
  await expect(listed).toHaveClass(/row-dim/);

  // The count leads to the same rows in the item grid, with archived items included.
  await page.getByTestId("grid-link-out_of_service").click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByLabel("Include archived")).toBeChecked();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(
    page.getByTestId("grid-items").getByRole("link", { name: archived, exact: true }),
  ).toBeVisible();
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();

  // The summary by contract: the covered switch in the row of the contract, the other
  // in the row of what no contract covers.
  await page.goto(`./reports?${new URLSearchParams({ filter: own, by: "contract" }).toString()}`);
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: renewedNumber }).getByRole("link")).toBeVisible();
  await expect(rows.filter({ hasText: "Under no contract" })).toHaveCount(1);

  // S30: the last day of support of the model is next year, so the two switches in the
  // default view approach it. The archived one is left out until it is asked for.
  await page.goto(`./reports/end-of-life?filter=${encodeURIComponent(own)}`);
  await expect(page.getByRole("heading", { level: 1, name: "End of life" })).toBeVisible();
  const ldos = page.getByTestId("eol-dates").locator('tr[data-date="ldos"]');
  await expect(ldos).toHaveAttribute("data-chosen", "true");
  await expect(ldos.getByTestId("approaching-items")).toHaveText("2");
  await expect(ldos.getByTestId("past-items")).toHaveText("0");
  // They fall in one fiscal year.
  const years = page.getByTestId("eol-years").locator("tbody tr");
  await expect(years).toHaveCount(1);
  await expect(years.locator("td.number").first()).toHaveText("2");
  await expect(page.getByTestId("count-approaching")).toHaveAttribute("data-count", "2");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const approaching = page.getByTestId("grid-end-of-life-approaching");
  await expect(approaching.getByRole("link", { name: covered, exact: true })).toBeVisible();
  await expect(approaching.getByRole("link", { name: bare, exact: true })).toBeVisible();
  await expect(
    gridRow(page, "grid-end-of-life-approaching", covered).locator('[col-id="effective.ldos"]'),
  ).toHaveText(`${year + 1}-06-30`);
  await page.getByLabel("Include archived").check();
  await expect(ldos.getByTestId("approaching-items")).toHaveText("3");
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");

  // D-141: once the vendor has been told that the archived switch left, a person says
  // so on the item, from the list of the report. The mark is cleared, and the coverage
  // stays ended on the day it ended.
  await page.goto(
    `./reports/coverage?${new URLSearchParams({ filter: own, section: "out_of_service" }).toString()}`,
  );
  await gridRow(page, "grid-coverage-out_of_service", archived)
    .getByRole("link", { name: archived, exact: true })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: archived })).toBeVisible();
  const told = page.getByTestId("item-coverage").locator(`tr[data-contract="${renewedNumber}"]`);
  await expect(told).toHaveAttribute("data-left-service", "true");
  await told
    .getByRole("button", { name: `The vendor has been told, for ${renewedNumber}` })
    .click();
  await expect(
    page.getByText(`${vendor} has been told that ${archived} left service.`),
  ).toBeVisible();
  await expect(told).toHaveAttribute("data-left-service", "false");
  await expect(told.getByTestId("left-service")).toHaveCount(0);
  await expect(told).toContainText(lastDay);

  await expectClean(page, seen);
});
